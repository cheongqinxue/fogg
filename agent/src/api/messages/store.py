"""Persistent, UI-facing conversation transcript storage."""

from __future__ import annotations

import base64
import binascii
import logging
from datetime import UTC, datetime
from typing import Any

from backend.database import get_pool

logger = logging.getLogger(__name__)
PAGE_SIZE = 50
_BACKFILL_KEY = 0x464F4747
_BACKFILL_NAME = "langgraph_checkpoint_transcript_v1"


async def append_message(account_id: str, role: str, text: str) -> dict:
    """Append a user or assistant message and return its persisted fields."""
    async with get_pool().connection() as conn:
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, %s))",
            (account_id, _BACKFILL_KEY),
        )
        cursor = await conn.execute(
            """INSERT INTO agent_chat_messages (account_id, role, text)
               VALUES (%s, %s, %s)
               RETURNING id, role, text, created_at""",
            (account_id, role, text),
        )
        row = await cursor.fetchone()
        await conn.commit()
    return row


def _message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            part if isinstance(part, str) else part["text"]
            for part in content
            if isinstance(part, str)
            or (isinstance(part, dict) and isinstance(part.get("text"), str))
        ).strip()
    return str(content).strip() if content is not None else ""


def _ui_message(message: Any) -> tuple[str, str] | None:
    """Convert only user-facing checkpoint messages to transcript records."""
    kind = (getattr(message, "additional_kwargs", None) or {}).get("kind")
    if kind in {"client_context", "user_action"}:
        return None
    message_type = getattr(message, "type", None)
    if message_type == "human":
        return ("user", _message_text(message))
    if message_type == "ai" and not getattr(message, "tool_calls", None):
        return ("assistant", _message_text(message))
    return None


def _checkpoint_time(snapshot: Any) -> datetime:
    timestamp = snapshot.checkpoint.get("ts")
    if isinstance(timestamp, str):
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
    return datetime.now(UTC)


def _message_key(message: Any) -> tuple[str, str | None, str]:
    return (
        str(getattr(message, "type", type(message).__name__)),
        getattr(message, "id", None),
        _message_text(message),
    )


def _legacy_rows(snapshots: list[Any]) -> list[tuple[str, str, datetime]]:
    """Rebuild message order and approximate per-message checkpoint timestamps."""
    if not snapshots:
        return []
    latest_messages = list(
        snapshots[0].checkpoint.get("channel_values", {}).get("messages") or [],
    )
    assigned_times: list[datetime | None] = [None] * len(latest_messages)
    newer_messages = latest_messages
    newer_time = _checkpoint_time(snapshots[0])

    for older_snapshot in snapshots[1:]:
        older_messages = list(
            older_snapshot.checkpoint.get("channel_values", {}).get("messages") or [],
        )
        older_keys = [_message_key(message) for message in older_messages]
        newer_keys = [_message_key(message) for message in newer_messages]
        common_prefix = 0
        while (
            common_prefix < len(older_keys)
            and common_prefix < len(newer_keys)
            and older_keys[common_prefix] == newer_keys[common_prefix]
        ):
            common_prefix += 1
        for index in range(common_prefix, min(len(newer_messages), len(assigned_times))):
            if assigned_times[index] is None:
                assigned_times[index] = newer_time
        newer_messages = older_messages
        newer_time = _checkpoint_time(older_snapshot)

    for index in range(min(len(newer_messages), len(assigned_times))):
        if assigned_times[index] is None:
            assigned_times[index] = newer_time

    fallback_time = _checkpoint_time(snapshots[-1])
    rows: list[tuple[str, str, datetime]] = []
    for index, message in enumerate(latest_messages):
        ui_message = _ui_message(message)
        if ui_message is None or not ui_message[1]:
            continue
        rows.append((*ui_message, assigned_times[index] or fallback_time))
    return rows


async def backfill_checkpoint_transcripts(checkpointer: Any) -> int:
    """One-time, idempotent import of old checkpointed UI chat history.

    Checkpoint timestamps provide the closest available timestamp for legacy
    messages; LangGraph did not store a timestamp on each message.
    """
    pool = get_pool()
    migrated_count = 0
    async with pool.connection() as conn:
        await conn.execute("SELECT pg_advisory_lock(%s)", (_BACKFILL_KEY,))
        await conn.commit()
        try:
            cursor = await conn.execute(
                "SELECT 1 FROM agent_chat_migrations WHERE migration_key = %s",
                (_BACKFILL_NAME,),
            )
            if await cursor.fetchone():
                return 0
            await conn.commit()

            async with checkpointer.conn.connection() as checkpoint_conn:
                cursor = await checkpoint_conn.execute(
                    "SELECT DISTINCT thread_id FROM checkpoints WHERE checkpoint_ns = '' ORDER BY thread_id",
                )
                thread_ids = [row["thread_id"] for row in await cursor.fetchall()]

            for thread_id in thread_ids:
                cursor = await conn.execute(
                    """
                    SELECT account_id::text AS account_id FROM users
                    WHERE legacy_subject = %s OR account_id::text = %s
                    ORDER BY (legacy_subject = %s) DESC NULLS LAST LIMIT 1
                    """,
                    (thread_id, thread_id, thread_id),
                )
                account = await cursor.fetchone()
                if account is None:
                    await conn.commit()
                    continue
                account_id = account["account_id"]
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, %s))",
                    (account_id, _BACKFILL_KEY),
                )
                cursor = await conn.execute(
                    "SELECT 1 FROM agent_chat_migrated_users WHERE account_id = %s",
                    (account_id,),
                )
                if await cursor.fetchone():
                    await conn.commit()
                    continue
                cursor = await conn.execute(
                    "SELECT EXISTS (SELECT 1 FROM agent_chat_messages WHERE account_id = %s) AS present",
                    (account_id,),
                )
                if not (await cursor.fetchone())["present"]:
                    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
                    snapshots = [snapshot async for snapshot in checkpointer.alist(config)]
                    rows = _legacy_rows(snapshots)
                    if rows:
                        async with conn.cursor() as insert_cursor:
                            await insert_cursor.executemany(
                                """INSERT INTO agent_chat_messages (account_id, role, text, created_at)
                                   VALUES (%s, %s, %s, %s)""",
                                [
                                    (account_id, role, text, timestamp)
                                    for role, text, timestamp in rows
                                ],
                            )
                        migrated_count += len(rows)
                await conn.execute(
                    "INSERT INTO agent_chat_migrated_users (account_id) VALUES (%s) ON CONFLICT DO NOTHING",
                    (account_id,),
                )
                await conn.commit()

            await conn.execute(
                "INSERT INTO agent_chat_migrations (migration_key) VALUES (%s) ON CONFLICT DO NOTHING",
                (_BACKFILL_NAME,),
            )
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (_BACKFILL_KEY,))
            await conn.commit()
    logger.info("Migrated %d legacy messages from LangGraph checkpoints", migrated_count)
    return migrated_count


async def list_messages(account_id: str, before_id: int | None = None) -> tuple[list[dict], bool]:
    """Load the newest page, or the page immediately older than ``before_id``."""
    async with get_pool().connection() as conn:
        if before_id is None:
            cursor = await conn.execute(
                """SELECT id, role, text, created_at FROM agent_chat_messages
                   WHERE account_id = %s ORDER BY id DESC LIMIT %s""",
                (account_id, PAGE_SIZE + 1),
            )
        else:
            cursor = await conn.execute(
                """SELECT id, role, text, created_at FROM agent_chat_messages
                   WHERE account_id = %s AND id < %s ORDER BY id DESC LIMIT %s""",
                (account_id, before_id, PAGE_SIZE + 1),
            )
        rows = await cursor.fetchall()
    has_more = len(rows) > PAGE_SIZE
    return list(reversed(rows[:PAGE_SIZE])), has_more


async def delete_user_messages(account_id: str) -> int:
    """Delete transcript rows for one user without touching its layout."""
    async with get_pool().connection() as conn:
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, %s))",
            (account_id, _BACKFILL_KEY),
        )
        cursor = await conn.execute(
            "DELETE FROM agent_chat_messages WHERE account_id = %s", (account_id,)
        )
        await conn.commit()
    return cursor.rowcount or 0


async def truncate_messages() -> int:
    """Delete all transcript rows (development reset)."""
    async with get_pool().connection() as conn:
        cursor = await conn.execute("SELECT COUNT(*) AS n FROM agent_chat_messages")
        row = await cursor.fetchone()
        count = int(row["n"])
        await conn.execute("TRUNCATE TABLE agent_chat_messages RESTART IDENTITY")
        await conn.commit()
    return count


def encode_cursor(message_id: int) -> str:
    """Encode the oldest row ID as a compact opaque page cursor."""
    return base64.urlsafe_b64encode(str(message_id).encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> int:
    """Decode a cursor; reject malformed or nonpositive IDs."""
    try:
        message_id = int(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("Invalid message cursor") from exc
    if message_id <= 0:
        raise ValueError("Invalid message cursor")
    return message_id
