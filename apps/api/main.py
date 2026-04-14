from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import releases, pipelines, rules, reports, health, webhooks, uploads

app = FastAPI(
    title="RopQA API",
    description="Release Ops QA Autopilot — backend API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public routes
app.include_router(health.router, tags=["health"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])

# Org-scoped protected routes (all require a valid Clerk JWT with an active org)
app.include_router(releases.router, prefix="/releases", tags=["releases"])
app.include_router(pipelines.router, prefix="/pipelines", tags=["pipelines"])
app.include_router(rules.router, prefix="/rules", tags=["rules"])
app.include_router(reports.router, prefix="/reports", tags=["reports"])
app.include_router(uploads.router, prefix="/uploads", tags=["uploads"])


@app.on_event("startup")
async def on_startup() -> None:
    pass
