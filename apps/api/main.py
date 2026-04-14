from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import releases, pipelines, rules, reports, health

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

app.include_router(health.router, tags=["health"])
app.include_router(releases.router, prefix="/releases", tags=["releases"])
app.include_router(pipelines.router, prefix="/pipelines", tags=["pipelines"])
app.include_router(rules.router, prefix="/rules", tags=["rules"])
app.include_router(reports.router, prefix="/reports", tags=["reports"])


@app.on_event("startup")
async def on_startup() -> None:
    # DB initialization happens via Alembic migrations
    pass
