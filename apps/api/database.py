from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings

# asyncpg uses connect_args for SSL rather than URL params.
# statement_cache_size=0 is required for Neon's pgbouncer pooler, which runs
# in transaction mode and does not support prepared statements.
_connect_args: dict = {"statement_cache_size": 0}
if settings.database_url_requires_ssl:
    _connect_args["ssl"] = True

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args=_connect_args,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
