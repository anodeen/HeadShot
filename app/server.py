#!/usr/bin/env python3
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HOST = "0.0.0.0"
PORT = 4173
DB_PATH = Path(__file__).resolve().parent / "headshot.db"
BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_TTL_DAYS = 7
OUTPUT_TTL_DAYS = 30
MAX_TEAM_SIZE = 50

PACKAGES = {
    "basic": {"name": "Basic", "headshotCount": 40, "priceCents": 2900, "delivery": "2–3 hr"},
    "professional": {"name": "Professional", "headshotCount": 100, "priceCents": 4900, "delivery": "1–2 hr"},
    "executive": {"name": "Executive", "headshotCount": 200, "priceCents": 7900, "delivery": "Priority"},
}

BRANDING_PRESETS = [
    {"id": "linkedin", "label": "LinkedIn profile", "width": 400, "height": 400},
    {"id": "email", "label": "Email signature", "width": 320, "height": 320},
    {"id": "team", "label": "Team page card", "width": 800, "height": 600},
]


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan TEXT NOT NULL,
            team_size INTEGER NOT NULL DEFAULT 1,
            rerun_credits INTEGER NOT NULL DEFAULT 1,
            amount_cents INTEGER NOT NULL,
            payment_status TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    for sql in [
        "ALTER TABLE orders ADD COLUMN team_size INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE orders ADD COLUMN rerun_credits INTEGER NOT NULL DEFAULT 1",
    ]:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            source_job_id INTEGER,
            plan TEXT NOT NULL,
            style TEXT NOT NULL,
            background TEXT NOT NULL,
            outfit TEXT NOT NULL,
            upload_count INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders (id)
        )
        """
    )
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN source_job_id INTEGER")
    except sqlite3.OperationalError:
        pass

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS generated_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            variant TEXT NOT NULL,
            download_token TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            order_id INTEGER,
            message TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )

    conn.commit()
    return conn


def parse_json_body(handler: SimpleHTTPRequestHandler) -> dict | None:
    content_length = int(handler.headers.get("Content-Length", "0"))
    if content_length <= 0:
        return None
    raw = handler.rfile.read(content_length)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def status_for_job(created_at: int) -> tuple[str, int]:
    elapsed = int(time.time()) - created_at
    if elapsed < 8:
        return "queued", max(8 - elapsed, 0)
    if elapsed < 25:
        return "processing", max(25 - elapsed, 0)
    return "completed", 0


def calculate_order_amount(plan: str, team_size: int) -> int:
    base_price = PACKAGES[plan]["priceCents"]
    if team_size <= 1:
        return base_price
    return int(base_price * max(team_size, 1) * 0.9)


def create_assets(conn: sqlite3.Connection, job_id: int) -> None:
    now = int(time.time())
    for variant in ["portrait-a", "portrait-b", "portrait-c", "linkedin-crop"]:
        token = secrets.token_urlsafe(10)
        conn.execute(
            "INSERT INTO generated_assets (job_id, variant, download_token, created_at) VALUES (?, ?, ?, ?)",
            (job_id, variant, token, now),
        )


def create_notification(conn: sqlite3.Connection, level: str, message: str) -> None:
    conn.execute(
        "INSERT INTO notifications (level, message, created_at) VALUES (?, ?, ?)",
        (level, message, int(time.time())),
    )


class HeadShotHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def _send_json(self, payload: dict, code: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path == "/api/health":
            self._send_json({"ok": True})
            return
        if path == "/api/privacy":
            self._send_json({"inputRetentionDays": INPUT_TTL_DAYS, "outputRetentionDays": OUTPUT_TTL_DAYS})
            return
        if path == "/api/packages":
            self._send_json({"packages": PACKAGES})
            return
        if path == "/api/branding-previews":
            self._send_json({"previews": BRANDING_PRESETS})
            return

        if path == "/api/notifications":
            with get_db() as conn:
                rows = conn.execute("SELECT id, level, message, created_at FROM notifications ORDER BY id DESC LIMIT 20").fetchall()
            self._send_json({"notifications": [dict(row) for row in rows]})
            return

        if path == "/api/metrics":
            with get_db() as conn:
                orders = conn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
                jobs = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
                completed = conn.execute("SELECT COUNT(*) c FROM jobs WHERE ? - created_at >= 25", (int(time.time()),)).fetchone()["c"]
                tickets = conn.execute("SELECT COUNT(*) c FROM support_tickets").fetchone()["c"]
            self._send_json({"orders": orders, "jobs": jobs, "completedJobs": completed, "supportTickets": tickets})
            return

        if path == "/api/orders":
            with get_db() as conn:
                rows = conn.execute("SELECT id, plan, team_size, rerun_credits, amount_cents, payment_status, created_at FROM orders ORDER BY id DESC LIMIT 20").fetchall()
            self._send_json({"orders": [{"id": r["id"], "plan": r["plan"], "teamSize": r["team_size"], "rerunCredits": r["rerun_credits"], "amountCents": r["amount_cents"], "paymentStatus": r["payment_status"], "createdAt": r["created_at"]} for r in rows]})
            return

        if path == "/api/jobs":
            with get_db() as conn:
                rows = conn.execute("SELECT id, order_id, source_job_id, plan, style, background, outfit, upload_count, created_at FROM jobs ORDER BY id DESC LIMIT 20").fetchall()
            jobs = []
            for r in rows:
                status, sec = status_for_job(r["created_at"])
                jobs.append({"id": r["id"], "orderId": r["order_id"], "sourceJobId": r["source_job_id"], "plan": r["plan"], "style": r["style"], "background": r["background"], "outfit": r["outfit"], "uploadCount": r["upload_count"], "status": status, "secondsRemaining": sec})
            self._send_json({"jobs": jobs})
            return

        if path.startswith("/api/jobs/") and path.endswith("/assets"):
            try:
                job_id = int(path.split("/")[3])
            except ValueError:
                self._send_json({"error": "Invalid job id."}, HTTPStatus.BAD_REQUEST)
                return
            with get_db() as conn:
                job = conn.execute("SELECT id, created_at FROM jobs WHERE id = ?", (job_id,)).fetchone()
                if job is None:
                    self._send_json({"error": "Job not found."}, HTTPStatus.NOT_FOUND)
                    return
                status, _ = status_for_job(job["created_at"])
                if status != "completed":
                    self._send_json({"error": "Assets are available after completion."}, HTTPStatus.BAD_REQUEST)
                    return
                rows = conn.execute("SELECT variant, download_token FROM generated_assets WHERE job_id = ?", (job_id,)).fetchall()
            assets = [{"variant": r["variant"], "downloadUrl": f"/api/download/{r['download_token']}"} for r in rows]
            self._send_json({"assets": assets})
            return

        if path.startswith("/api/download/"):
            token = path.split("/")[-1]
            with get_db() as conn:
                row = conn.execute("SELECT variant FROM generated_assets WHERE download_token = ?", (token,)).fetchone()
            if row is None:
                self._send_json({"error": "Asset not found."}, HTTPStatus.NOT_FOUND)
                return
            self._send_json({"ok": True, "message": f"Mock download for {row['variant']}"})
            return

        if path.startswith("/api/jobs/"):
            try:
                job_id = int(path.split("/")[-1])
            except ValueError:
                self._send_json({"error": "Invalid job id."}, HTTPStatus.BAD_REQUEST)
                return
            with get_db() as conn:
                r = conn.execute("SELECT id, order_id, source_job_id, plan, style, background, outfit, upload_count, created_at FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if r is None:
                self._send_json({"error": "Job not found."}, HTTPStatus.NOT_FOUND)
                return
            status, sec = status_for_job(r["created_at"])
            self._send_json({"id": r["id"], "orderId": r["order_id"], "sourceJobId": r["source_job_id"], "plan": r["plan"], "style": r["style"], "background": r["background"], "outfit": r["outfit"], "uploadCount": r["upload_count"], "status": status, "secondsRemaining": sec})
            return

        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        payload = parse_json_body(self)

        if path == "/api/orders":
            if payload is None:
                self._send_json({"error": "Invalid JSON payload."}, HTTPStatus.BAD_REQUEST); return
            plan = payload.get("plan")
            if plan not in PACKAGES:
                self._send_json({"error": "Unknown package."}, HTTPStatus.BAD_REQUEST); return
            try:
                team_size = int(payload.get("teamSize", 1))
            except (TypeError, ValueError):
                self._send_json({"error": "teamSize must be a number."}, HTTPStatus.BAD_REQUEST); return
            if not 1 <= team_size <= MAX_TEAM_SIZE:
                self._send_json({"error": f"teamSize must be between 1 and {MAX_TEAM_SIZE}."}, HTTPStatus.BAD_REQUEST); return

            with get_db() as conn:
                amount = calculate_order_amount(plan, team_size)
                cur = conn.execute("INSERT INTO orders (plan, team_size, rerun_credits, amount_cents, payment_status, created_at) VALUES (?, ?, 1, ?, 'paid', ?)", (plan, team_size, amount, int(time.time())))
                create_notification(conn, "info", f"Order #{cur.lastrowid} created for {plan}.")
                conn.commit()
                oid = cur.lastrowid
            self._send_json({"id": oid, "plan": plan, "teamSize": team_size, "amountCents": amount, "paymentStatus": "paid", "rerunCredits": 1}, HTTPStatus.CREATED)
            return

        if path == "/api/jobs":
            if payload is None:
                self._send_json({"error": "Invalid JSON payload."}, HTTPStatus.BAD_REQUEST); return
            required = ["orderId", "plan", "style", "background", "outfit", "uploadCount"]
            if any(k not in payload for k in required):
                self._send_json({"error": "Missing required fields."}, HTTPStatus.BAD_REQUEST); return
            try:
                order_id = int(payload["orderId"]); upload_count = int(payload["uploadCount"])
            except (TypeError, ValueError):
                self._send_json({"error": "orderId and uploadCount must be numbers."}, HTTPStatus.BAD_REQUEST); return
            if upload_count < 8:
                self._send_json({"error": "At least 8 uploads are required."}, HTTPStatus.BAD_REQUEST); return

            with get_db() as conn:
                order = conn.execute("SELECT id, plan, payment_status FROM orders WHERE id = ?", (order_id,)).fetchone()
                if order is None or order["payment_status"] != "paid" or order["plan"] != payload["plan"]:
                    self._send_json({"error": "Invalid paid order for selected plan."}, HTTPStatus.BAD_REQUEST); return
                cur = conn.execute("INSERT INTO jobs (order_id, source_job_id, plan, style, background, outfit, upload_count, created_at) VALUES (?, NULL, ?, ?, ?, ?, ?, ?)", (order_id, payload["plan"], payload["style"], payload["background"], payload["outfit"], upload_count, int(time.time())))
                create_assets(conn, cur.lastrowid)
                create_notification(conn, "info", f"Job #{cur.lastrowid} queued.")
                conn.commit()
                jid = cur.lastrowid
            self._send_json({"id": jid, "orderId": order_id, "status": "queued", "secondsRemaining": 8}, HTTPStatus.CREATED)
            return

        if path == "/api/rerun":
            if payload is None:
                self._send_json({"error": "Invalid JSON payload."}, HTTPStatus.BAD_REQUEST); return
            try:
                source_job = int(payload.get("jobId"))
            except (TypeError, ValueError):
                self._send_json({"error": "jobId is required."}, HTTPStatus.BAD_REQUEST); return
            with get_db() as conn:
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (source_job,)).fetchone()
                if row is None:
                    self._send_json({"error": "Job not found."}, HTTPStatus.NOT_FOUND); return
                order = conn.execute("SELECT rerun_credits FROM orders WHERE id = ?", (row["order_id"],)).fetchone()
                if order is None or order["rerun_credits"] <= 0:
                    self._send_json({"error": "No rerun credits available."}, HTTPStatus.BAD_REQUEST); return
                conn.execute("UPDATE orders SET rerun_credits = rerun_credits - 1 WHERE id = ?", (row["order_id"],))
                cur = conn.execute("INSERT INTO jobs (order_id, source_job_id, plan, style, background, outfit, upload_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (row["order_id"], row["id"], row["plan"], row["style"], row["background"], row["outfit"], row["upload_count"], int(time.time())))
                create_assets(conn, cur.lastrowid)
                create_notification(conn, "warning", f"Rerun started from job #{source_job} -> #{cur.lastrowid}.")
                conn.commit()
                new_id = cur.lastrowid
            self._send_json({"id": new_id, "sourceJobId": source_job, "status": "queued", "secondsRemaining": 8}, HTTPStatus.CREATED)
            return

        if path == "/api/support":
            if payload is None:
                self._send_json({"error": "Invalid JSON payload."}, HTTPStatus.BAD_REQUEST); return
            email = str(payload.get("email", "")).strip(); message = str(payload.get("message", "")).strip()
            if not email or not message:
                self._send_json({"error": "email and message are required."}, HTTPStatus.BAD_REQUEST); return
            order_id = payload.get("orderId")
            try:
                norm = int(order_id) if order_id not in (None, "") else None
            except (TypeError, ValueError):
                self._send_json({"error": "orderId must be numeric if provided."}, HTTPStatus.BAD_REQUEST); return
            with get_db() as conn:
                cur = conn.execute("INSERT INTO support_tickets (email, order_id, message, created_at) VALUES (?, ?, ?, ?)", (email, norm, message, int(time.time())))
                create_notification(conn, "warning", f"Support ticket #{cur.lastrowid} opened.")
                conn.commit()
            self._send_json({"id": cur.lastrowid, "message": "Support request received."}, HTTPStatus.CREATED)
            return

        self._send_json({"error": "Route not found."}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/jobs/"):
            try: job_id = int(path.split("/")[-1])
            except ValueError:
                self._send_json({"error": "Invalid job id."}, HTTPStatus.BAD_REQUEST); return
            with get_db() as conn:
                conn.execute("DELETE FROM generated_assets WHERE job_id = ?", (job_id,))
                cur = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                create_notification(conn, "info", f"Job #{job_id} deleted.")
                conn.commit()
            if cur.rowcount == 0:
                self._send_json({"error": "Job not found."}, HTTPStatus.NOT_FOUND); return
            self._send_json({"ok": True, "deleted": "job", "id": job_id}); return

        if path.startswith("/api/orders/"):
            try: order_id = int(path.split("/")[-1])
            except ValueError:
                self._send_json({"error": "Invalid order id."}, HTTPStatus.BAD_REQUEST); return
            with get_db() as conn:
                job_rows = conn.execute("SELECT id FROM jobs WHERE order_id = ?", (order_id,)).fetchall()
                for row in job_rows:
                    conn.execute("DELETE FROM generated_assets WHERE job_id = ?", (row["id"],))
                conn.execute("DELETE FROM jobs WHERE order_id = ?", (order_id,))
                cur = conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
                create_notification(conn, "info", f"Order #{order_id} deleted.")
                conn.commit()
            if cur.rowcount == 0:
                self._send_json({"error": "Order not found."}, HTTPStatus.NOT_FOUND); return
            self._send_json({"ok": True, "deleted": "order", "id": order_id}); return

        self._send_json({"error": "Route not found."}, HTTPStatus.NOT_FOUND)


def run() -> None:
    server = ThreadingHTTPServer((HOST, PORT), HeadShotHandler)
    print(f"HeadShot server running on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
