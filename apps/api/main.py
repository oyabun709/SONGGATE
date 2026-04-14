from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from config import settings
from routers import releases, pipelines, rules, reports, health, webhooks, uploads, scans
from routers import public_api, billing

app = FastAPI(
    title="RopQA API",
    description=(
        "**RopQA** — Release Ops QA Autopilot\n\n"
        "Automated release-readiness scanning for music distributors and labels.\n\n"
        "## Authentication\n\n"
        "The public API (`/api/v1/`) uses **API key authentication**.\n\n"
        "1. Create a key via `POST /api/v1/keys` (requires a one-time Clerk session token)\n"
        "2. Pass the key as a Bearer token on all subsequent requests:\n"
        "   ```\n"
        "   Authorization: Bearer ropqa_sk_…\n"
        "   ```\n\n"
        "## Scan lifecycle\n\n"
        "`queued` → `running` → `complete` | `failed`\n\n"
        "Poll `GET /api/v1/scans/{id}` until status is terminal.\n\n"
        "## Readiness score\n\n"
        "| Grade | Score |\n"
        "|-------|-------|\n"
        "| PASS  | ≥ 80  |\n"
        "| WARN  | ≥ 60  |\n"
        "| FAIL  | < 60  |"
    ),
    version="1.0.0",
    contact={
        "name": "RopQA Engineering",
        "email": "engineering@ropqa.io",
    },
    license_info={
        "name": "Proprietary",
    },
)

_CORS_ORIGINS = [
    "http://localhost:3000",
    settings.frontend_url,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(o for o in _CORS_ORIGINS if o)),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Health / webhooks (no auth) ───────────────────────────────────────────────
app.include_router(health.router, tags=["health"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])

# ── Internal routes (Clerk JWT) ───────────────────────────────────────────────
app.include_router(releases.router, prefix="/releases", tags=["releases"])
app.include_router(pipelines.router, prefix="/pipelines", tags=["pipelines"])
app.include_router(rules.router, prefix="/rules", tags=["rules"])
app.include_router(reports.router, prefix="/reports", tags=["reports"])
app.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
app.include_router(scans.router, tags=["scans"])

# ── Billing (Clerk JWT) ───────────────────────────────────────────────────────
app.include_router(billing.router, tags=["billing"])

# ── Public API v1 (API key auth) ──────────────────────────────────────────────
app.include_router(public_api.router, tags=["Public API v1"])


@app.on_event("startup")
async def on_startup() -> None:
    pass
