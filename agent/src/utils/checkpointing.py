"""LangGraph Postgres checkpointer for durable thread state."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING
from uuid import UUID

from backend.database import get_pool_if_initialized

from utils.settings import get_settings

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from psycopg_pool import AsyncConnectionPool

_CHECKPOINTER: BaseCheckpointSaver | None = None
_CHECKPOINTER_POOL: AsyncConnectionPool | None = None


def get_checkpointer() -> BaseCheckpointSaver:
    """Return the active Postgres checkpointer (set by ``init_checkpointer`` at startup).

    Returns:
        BaseCheckpointSaver for the compiled ReAct graph.
    """
    if _CHECKPOINTER is None:
        msg = "Checkpointer not initialized — FastAPI lifespan must call init_checkpointer() first."
        raise RuntimeError(msg)
    return _CHECKPOINTER


async def init_checkpointer() -> BaseCheckpointSaver:
    """Open a reconnecting async pool and initialize the saver at app startup."""
    global _CHECKPOINTER, _CHECKPOINTER_POOL
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(
        conninfo=get_settings().database_url,
        min_size=1,
        max_size=10,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        check=AsyncConnectionPool.check_connection,
        open=False,
    )
    try:
        await pool.open(wait=True)
        saver = AsyncPostgresSaver(pool)  # ty: ignore[invalid-argument-type]
        await saver.setup()
    except BaseException:
        # Preserve the initialization error if cleanup itself fails.
        with suppress(Exception):
            await pool.close()
        raise
    _CHECKPOINTER_POOL = pool
    _CHECKPOINTER = saver
    return saver


async def shutdown_checkpointer() -> None:
    """Close checkpointer connections (app shutdown)."""
    global _CHECKPOINTER, _CHECKPOINTER_POOL
    pool = _CHECKPOINTER_POOL
    _CHECKPOINTER = None
    _CHECKPOINTER_POOL = None
    if pool is not None:
        await pool.close()


async def clear_all_checkpoint_threads() -> None:
    """Clear all checkpoint data for the development reset endpoint."""
    if _CHECKPOINTER_POOL is None:
        raise RuntimeError("Checkpointer not initialized.")
    async with _CHECKPOINTER_POOL.connection() as conn:
        await conn.execute("TRUNCATE TABLE checkpoint_writes, checkpoint_blobs, checkpoints")


async def checkpoint_thread_id(account_id: str) -> str:
    """Resolve checkpoint IDs retained from before accounts owned chat state."""
    pool = get_pool_if_initialized()
    try:
        key = UUID(account_id)
    except ValueError:
        return account_id
    if pool is None:
        return account_id
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT legacy_subject FROM users WHERE account_id = %s", (key,)
        )
        row = await cursor.fetchone()
    return (row["legacy_subject"] if row else None) or account_id
