"""Postgres persistence for per-thread layout documents."""

from __future__ import annotations

import json
import logging
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from utils.settings import get_settings
from layout.hashing import layout_document_hash
from layout.models import LayoutDocument, LayoutHead

logger = logging.getLogger(__name__)

_POOL: AsyncConnectionPool | None = None

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_thread_layout (
    thread_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL,
    layout_hash TEXT NOT NULL,
    layout JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_MIGRATE_DOCUMENT_COLUMN = """
DO $$
BEGIN
    ALTER TABLE agent_thread_layout RENAME COLUMN document TO layout;
EXCEPTION
    WHEN undefined_column THEN NULL;
END $$;
"""


async def init_layout_store() -> None:
    """Create the layout table and open the connection pool."""
    global _POOL
    if _POOL is not None:
        return
    _POOL = AsyncConnectionPool(
        conninfo=get_settings().database_url,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"row_factory": dict_row},
    )
    await _POOL.open()
    async with _POOL.connection() as conn:
        await conn.execute(_SCHEMA_SQL)
        await conn.execute(_MIGRATE_DOCUMENT_COLUMN)
        await conn.commit()
    logger.info("Layout store initialized")


async def shutdown_layout_store() -> None:
    """Close the layout connection pool."""
    global _POOL
    if _POOL is None:
        return
    await _POOL.close()
    _POOL = None


def _require_pool() -> AsyncConnectionPool:
    if _POOL is None:
        msg = "Layout store not initialized — call init_layout_store() first."
        raise RuntimeError(msg)
    return _POOL


class ThreadLayoutRow:
    """In-memory view of one thread layout row."""

    def __init__(
        self, thread_id: str, revision: int, layout_hash: str, layout: dict[str, Any]
    ) -> None:
        self.thread_id = thread_id
        self.revision = revision
        self.layout_hash = layout_hash
        self.layout = layout


async def get_thread_layout(thread_id: str) -> ThreadLayoutRow | None:
    """Load layout row or ``None`` if missing."""
    pool = _require_pool()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT thread_id, revision, layout_hash, layout
            FROM agent_thread_layout
            WHERE thread_id = %s
            """,
            (thread_id,),
        )
        record = await cursor.fetchone()
    if record is None:
        return None
    layout = record["layout"]
    if isinstance(layout, str):
        layout = json.loads(layout)
    return ThreadLayoutRow(
        thread_id=record["thread_id"],
        revision=int(record["revision"]),
        layout_hash=record["layout_hash"],
        layout=layout,
    )


async def upsert_thread_layout(
    thread_id: str,
    revision: int,
    layout: dict[str, Any],
) -> ThreadLayoutRow:
    """Insert or replace layout document and revision."""
    layout_hash = layout_document_hash(layout)
    pool = _require_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO agent_thread_layout (thread_id, revision, layout_hash, layout, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (thread_id) DO UPDATE SET
                revision = EXCLUDED.revision,
                layout_hash = EXCLUDED.layout_hash,
                layout = EXCLUDED.layout,
                updated_at = NOW()
            """,
            (thread_id, revision, layout_hash, json.dumps(layout)),
        )
        await conn.commit()
    return ThreadLayoutRow(thread_id, revision, layout_hash, layout)


async def get_or_create_thread_layout(thread_id: str) -> ThreadLayoutRow:
    """Return existing row or seed defaults at revision 0."""
    row = await get_thread_layout(thread_id)
    if row is not None:
        return row
    layout = LayoutDocument.default_singapore().to_storage_dict()
    return await upsert_thread_layout(thread_id, 0, layout)


async def get_layout_head(thread_id: str) -> LayoutHead | None:
    """Return revision and hash only."""
    row = await get_thread_layout(thread_id)
    if row is None:
        return None
    return LayoutHead(revision=row.revision, layout_hash=row.layout_hash)


async def delete_thread_layout(thread_id: str) -> int:
    """Remove one row from ``agent_thread_layout``.

    Returns:
        Number of rows deleted (0 or 1).
    """
    pool = _require_pool()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "DELETE FROM agent_thread_layout WHERE thread_id = %s",
            (thread_id,),
        )
        await conn.commit()
    return cursor.rowcount or 0


async def truncate_all_thread_layouts() -> int:
    """Remove every layout row (dev nuclear reset).

    Returns:
        Number of rows deleted before truncate (approximate via COUNT when possible).
    """
    pool = _require_pool()
    async with pool.connection() as conn:
        count_cursor = await conn.execute("SELECT COUNT(*) AS n FROM agent_thread_layout")
        row = await count_cursor.fetchone()
        removed = int(row["n"]) if row else 0
        await conn.execute("TRUNCATE TABLE agent_thread_layout")
        await conn.commit()
    return removed
