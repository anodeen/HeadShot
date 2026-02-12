# HeadShot

Starter MVP web app for an AI-powered professional headshot generator platform.

## Current build

A functional prototype is available in `app/` with:

- guided selfie uploads with basic client-side quality feedback,
- style/background/outfit selectors,
- package selection (Basic/Professional/Executive),
- package catalog API (`/api/packages`),
- order/payment simulation API (`/api/orders`),
- generation job submission + polling (`/api/jobs`),
- recent orders and recent jobs dashboard lists,
- responsive layout for desktop/mobile.

## Run locally

From repo root:

```bash
python3 app/server.py
```

Then open:

- `http://localhost:4173/app/`

## Product planning docs

- `docs/prd-analysis.md` — implementation-oriented PRD walkthrough and phased scope guidance.
