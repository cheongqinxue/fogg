"""Postgres persistence for per-user layout documents."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.database import get_pool

from layout.hashing import layout_document_hash
from layout.models import LayoutDocument, LayoutHead

logger = logging.getLogger(__name__)


class UserLayoutRow:
    """In-memory view of one user layout row."""

    def __init__(
        self, account_id: str, revision: int, layout_hash: str, layout: dict[str, Any]
    ) -> None:
        self.account_id = account_id
        self.revision = revision
        self.layout_hash = layout_hash
        self.layout = layout


async def get_user_layout(account_id: str) -> UserLayoutRow | None:
    """Load layout row or ``None`` if missing."""
    pool = get_pool()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT account_id, revision, layout_hash, layout
            FROM agent_user_layout
            WHERE account_id = %s
            """,
            (account_id,),
        )
        record = await cursor.fetchone()
    if record is None:
        return None
    layout = record["layout"]
    if isinstance(layout, str):
        layout = json.loads(layout)
    return UserLayoutRow(
        account_id=record["account_id"],
        revision=int(record["revision"]),
        layout_hash=record["layout_hash"],
        layout=layout,
    )


async def upsert_user_layout(
    account_id: str,
    revision: int,
    layout: dict[str, Any],
) -> UserLayoutRow:
    """Insert or replace layout document and revision."""
    layout_hash = layout_document_hash(layout)
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO agent_user_layout (account_id, revision, layout_hash, layout, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (account_id) DO UPDATE SET
                revision = EXCLUDED.revision,
                layout_hash = EXCLUDED.layout_hash,
                layout = EXCLUDED.layout,
                updated_at = NOW()
            """,
            (account_id, revision, layout_hash, json.dumps(layout)),
        )
        await conn.commit()
    return UserLayoutRow(account_id, revision, layout_hash, layout)


async def get_or_create_user_layout(account_id: str) -> UserLayoutRow:
    """Return existing row or seed defaults at revision 0."""
    row = await get_user_layout(account_id)
    if row is not None:
        return row
    layout = LayoutDocument.default_singapore().to_storage_dict()
    return await upsert_user_layout(account_id, 0, layout)


async def get_layout_head(account_id: str) -> LayoutHead | None:
    """Return revision and hash only."""
    row = await get_user_layout(account_id)
    if row is None:
        return None
    return LayoutHead(revision=row.revision, layout_hash=row.layout_hash)


async def delete_user_layout(account_id: str) -> int:
    """Remove one row from ``agent_user_layout``.

    Returns:
        Number of rows deleted (0 or 1).
    """
    pool = get_pool()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "DELETE FROM agent_user_layout WHERE account_id = %s",
            (account_id,),
        )
        await conn.commit()
    return cursor.rowcount or 0


async def truncate_all_user_layouts() -> int:
    """Remove every layout row (dev nuclear reset).

    Returns:
        Number of rows deleted before truncate (approximate via COUNT when possible).
    """
    pool = get_pool()
    async with pool.connection() as conn:
        count_cursor = await conn.execute("SELECT COUNT(*) AS n FROM agent_user_layout")
        row = await count_cursor.fetchone()
        removed = int(row["n"]) if row else 0
        await conn.execute("TRUNCATE TABLE agent_user_layout")
        await conn.commit()
    return removed
