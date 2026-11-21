"""Shared async Postgres pool for FOGG application tables."""

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from utils.settings import get_settings

from backend.migrate import migrate_database

_pool: AsyncConnectionPool | None = None


async def init_database() -> None:
    """Prepare the schema and open the application pool."""
    global _pool
    if _pool is not None:
        return

    settings = get_settings()
    await migrate_database(settings.database_url, apply=settings.fogg_env != "prod")
    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=10,
        open=False,
        kwargs={"row_factory": dict_row},
    )
    try:
        await pool.open(wait=True)
    except BaseException:
        await pool.close()
        raise
    _pool = pool


def get_pool() -> AsyncConnectionPool:
    """Return the pool initialized at service startup."""
    if _pool is None:
        raise RuntimeError("FOGG database is not initialized. Call init_database() first.")
    return _pool


async def shutdown_database() -> None:
    """Close the shared application pool."""
    global _pool
    pool, _pool = _pool, None
    if pool is not None:
        await pool.close()


def get_pool_if_initialized() -> AsyncConnectionPool | None:
    """Return the optional pool for callers that support running without storage."""
    return _pool
