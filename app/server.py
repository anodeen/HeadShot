#!/usr/bin/env python3
"""Minimal API + static server for HeadShot MVP.

Run:
  python3 app/server.py
Then open:
  http://127.0.0.1:4173/app/
"""

from __future__ import annotations

import json
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
            amount_cents INTEGER NOT NULL,
            payment_status TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    try:
        conn.execute("ALTER TABLE orders ADD COLUMN team_size INTEGER NOT NULL DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
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

    team_multiplier = max(team_size, 1)
    gross = base_price * team_multiplier
    discounted = int(gross * 0.9)
    return discounted


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
            self._send_json(
                {
                    "inputRetentionDays": INPUT_TTL_DAYS,
                    "outputRetentionDays": OUTPUT_TTL_DAYS,
                    "message": "Users can delete jobs and orders immediately from dashboard.",
                }
            )
            return

        if path == "/api/packages":
            self._send_json({"packages": PACKAGES})
            return

        if path == "/api/branding-previews":
            self._send_json({"previews": BRANDING_PRESETS})
            return

        if path == "/api/orders":
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT id, plan, team_size, amount_cents, payment_status, created_at FROM orders ORDER BY id DESC LIMIT 20"
                ).fetchall()
            self._send_json(
                {
                    "orders": [
                        {
                            "id": row["id"],
                            "plan": row["plan"],
                            "teamSize": row["team_size"],
                            "amountCents": row["amount_cents"],
                            "paymentStatus": row["payment_status"],
                            "createdAt": row["created_at"],
                        }
                        for row in rows
                    ]
                }
            )
            return

        if path == "/api/jobs":
            with get_db() as conn:
                rows = conn.execute(
                    """
                    SELECT id, order_id, plan, style, background, outfit, upload_count, created_at
                    FROM jobs ORDER BY id DESC LIMIT 20
                    """
                ).fetchall()
            jobs = []
            for row in rows:
                status, seconds_remaining = status_for_job(row["created_at"])
                jobs.append(
                    {
                        "id": row["id"],
                        "orderId": row["order_id"],
                        "plan": row["plan"],
                        "style": row["style"],
                        "background": row["background"],
                        "outfit": row["outfit"],
                        "uploadCount": row["upload_count"],
                        "status": status,
                        "secondsRemaining": seconds_remaining,
                    }
                )
            self._send_json({"jobs": jobs})
            return

        if path.startswith("/api/jobs/"):
            try:
                job_id = int(path.split("/")[-1])
            except ValueError:
                self._send_json({"error": "Invalid job id."}, HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                row = conn.execute(
                    """
                    SELECT id, order_id, plan, style, background, outfit, upload_count, created_at
                    FROM jobs WHERE id = ?
                    """,
                    (job_id,),
                ).fetchone()

            if row is None:
                self._send_json({"error": "Job not found."}, HTTPStatus.NOT_FOUND)
                return

            status, seconds_remaining = status_for_job(row["created_at"])
            self._send_json(
                {
                    "id": row["id"],
                    "orderId": row["order_id"],
                    "plan": row["plan"],
                    "style": row["style"],
                    "background": row["background"],
                    "outfit": row["outfit"],
                    "uploadCount": row["upload_count"],
                    "status": status,
                    "secondsRemaining": seconds_remaining,
                }
            )
            return

        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path

        if path == "/api/orders":
            payload = parse_json_body(self)
            if payload is None:
                self._send_json({"error": "Invalid JSON payload."}, HTTPStatus.BAD_REQUEST)
                return

            plan = payload.get("plan")
            if plan not in PACKAGES:
                self._send_json({"error": "Unknown package."}, HTTPStatus.BAD_REQUEST)
                return

            team_size_raw = payload.get("teamSize", 1)
            try:
                team_size = int(team_size_raw)
            except (TypeError, ValueError):
                self._send_json({"error": "teamSize must be a number."}, HTTPStatus.BAD_REQUEST)
                return

            if team_size < 1 or team_size > MAX_TEAM_SIZE:
                self._send_json(
                    {"error": f"teamSize must be between 1 and {MAX_TEAM_SIZE}."},
                    HTTPStatus.BAD_REQUEST,
                )
                return

            amount_cents = calculate_order_amount(plan, team_size)
            now = int(time.time())
            with get_db() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO orders (plan, team_size, amount_cents, payment_status, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (plan, team_size, amount_cents, "paid", now),
                )
                conn.commit()
                order_id = cur.lastrowid

            self._send_json(
                {
                    "id": order_id,
                    "plan": plan,
                    "teamSize": team_size,
                    "amountCents": amount_cents,
                    "paymentStatus": "paid",
                    "message": "Payment successful. Order created.",
                },
                HTTPStatus.CREATED,
            )
            return

        if path == "/api/jobs":
            payload = parse_json_body(self)
            if payload is None:
                self._send_json({"error": "Invalid JSON payload."}, HTTPStatus.BAD_REQUEST)
                return

            required = ["orderId", "plan", "style", "background", "outfit", "uploadCount"]
            missing = [key for key in required if key not in payload]
            if missing:
                self._send_json({"error": f"Missing required fields: {', '.join(missing)}"}, HTTPStatus.BAD_REQUEST)
                return

            plan = payload["plan"]
            if plan not in PACKAGES:
                self._send_json({"error": "Unknown package."}, HTTPStatus.BAD_REQUEST)
                return

            try:
                order_id = int(payload["orderId"])
                upload_count = int(payload["uploadCount"])
            except (TypeError, ValueError):
                self._send_json({"error": "orderId and uploadCount must be numbers."}, HTTPStatus.BAD_REQUEST)
                return

            if upload_count < 8:
                self._send_json({"error": "At least 8 uploads are required."}, HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                order = conn.execute(
                    "SELECT id, plan, payment_status FROM orders WHERE id = ?", (order_id,)
                ).fetchone()

                if order is None:
                    self._send_json({"error": "Order not found."}, HTTPStatus.BAD_REQUEST)
                    return
                if order["payment_status"] != "paid":
                    self._send_json({"error": "Order is not paid."}, HTTPStatus.BAD_REQUEST)
                    return
                if order["plan"] != plan:
                    self._send_json({"error": "Order plan does not match selected plan."}, HTTPStatus.BAD_REQUEST)
                    return

                now = int(time.time())
                cur = conn.execute(
                    """
                    INSERT INTO jobs (order_id, plan, style, background, outfit, upload_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (order_id, plan, payload["style"], payload["background"], payload["outfit"], upload_count, now),
                )
                conn.commit()
                job_id = cur.lastrowid

            self._send_json(
                {
                    "id": job_id,
                    "orderId": order_id,
                    "status": "queued",
                    "secondsRemaining": 8,
                    "message": "Generation job accepted.",
                },
                HTTPStatus.CREATED,
            )
            return

        self._send_json({"error": "Route not found."}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path

        if path.startswith("/api/jobs/"):
            try:
                job_id = int(path.split("/")[-1])
            except ValueError:
                self._send_json({"error": "Invalid job id."}, HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                cur = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                conn.commit()

            if cur.rowcount == 0:
                self._send_json({"error": "Job not found."}, HTTPStatus.NOT_FOUND)
                return

            self._send_json({"ok": True, "deleted": "job", "id": job_id})
            return

        if path.startswith("/api/orders/"):
            try:
                order_id = int(path.split("/")[-1])
            except ValueError:
                self._send_json({"error": "Invalid order id."}, HTTPStatus.BAD_REQUEST)
                return

            with get_db() as conn:
                conn.execute("DELETE FROM jobs WHERE order_id = ?", (order_id,))
                cur = conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
                conn.commit()

            if cur.rowcount == 0:
                self._send_json({"error": "Order not found."}, HTTPStatus.NOT_FOUND)
                return

            self._send_json({"ok": True, "deleted": "order", "id": order_id})
            return

        self._send_json({"error": "Route not found."}, HTTPStatus.NOT_FOUND)


def run() -> None:
    server = ThreadingHTTPServer((HOST, PORT), HeadShotHandler)
    print(f"HeadShot server running on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
