"""LangGraph Postgres checkpointer for durable thread state."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from agent_utils.db import database_url as _database_url

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
        conninfo=_database_url(),
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
        saver = AsyncPostgresSaver(pool)
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
