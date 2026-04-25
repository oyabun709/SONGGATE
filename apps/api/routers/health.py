from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text

router = APIRouter()


@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/db")
async def health_db():
    """Diagnostic endpoint — tests DB connectivity and returns exact error if broken."""
    from database import engine
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1 AS ok"))
            row = result.fetchone()
            # Check if core tables exist
            tables_result = await conn.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
            ))
            tables = [r[0] for r in tables_result.fetchall()]
            return {
                "db": "ok",
                "ping": row[0],
                "tables": tables,
                "table_count": len(tables),
            }
    except Exception as exc:
        return {
            "db": "error",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }
