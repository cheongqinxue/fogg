"""Per-user tool preferences and encrypted provider credentials in Postgres."""

from __future__ import annotations

from contextlib import suppress

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from utils.kms import decrypt_secret, encrypt_secret
from utils.settings import get_settings

_POOL: AsyncConnectionPool | None = None

_SCHEMA_STATEMENTS = (
    """
CREATE TABLE IF NOT EXISTS agent_user_tool_preferences (
    uid TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    active BOOLEAN NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (uid, tool_name)
);
""",
    """
CREATE TABLE IF NOT EXISTS agent_user_provider_credentials (
    uid TEXT NOT NULL,
    provider TEXT NOT NULL,
    ciphertext TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (uid, provider)
);
""",
)


async def init_user_tool_config_store() -> None:
    """Create the user tool configuration tables during API startup."""
    global _POOL
    if _POOL is not None:
        return
    pool = AsyncConnectionPool(
        conninfo=get_settings().database_url,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"row_factory": dict_row},
    )
    await pool.open()
    try:
        async with pool.connection() as conn:
            for statement in _SCHEMA_STATEMENTS:
                await conn.execute(statement)
            await conn.commit()
    except BaseException:
        with suppress(Exception):
            await pool.close()
        raise
    _POOL = pool


async def shutdown_user_tool_config_store() -> None:
    """Close the user tool configuration pool during API shutdown."""
    global _POOL
    pool, _POOL = _POOL, None
    if pool is not None:
        await pool.close()


def _pool() -> AsyncConnectionPool:
    if _POOL is None:
        raise RuntimeError("User tool configuration store is not initialized")
    return _POOL


async def get_tool_active_overrides(uid: str) -> dict[str, bool]:
    """Return explicitly saved active states; absent rows use caller defaults."""
    if _POOL is None:
        return {}
    async with _pool().connection() as conn:
        cursor = await conn.execute(
            "SELECT tool_name, active FROM agent_user_tool_preferences WHERE uid = %s",
            (uid,),
        )
        rows = await cursor.fetchall()
    return {row["tool_name"]: bool(row["active"]) for row in rows}


async def set_tool_active(uid: str, tool_name: str, active: bool) -> None:
    """Set a user's active preference for a tool."""
    async with _pool().connection() as conn:
        await conn.execute(
            """INSERT INTO agent_user_tool_preferences (uid, tool_name, active)
               VALUES (%s, %s, %s)
               ON CONFLICT (uid, tool_name) DO UPDATE
               SET active = EXCLUDED.active, updated_at = NOW()""",
            (uid, tool_name, active),
        )
        await conn.commit()


async def get_saved_providers(uid: str) -> set[str]:
    """Return provider names with encrypted credentials saved for a user."""
    if _POOL is None:
        return set()
    async with _pool().connection() as conn:
        cursor = await conn.execute(
            "SELECT provider FROM agent_user_provider_credentials WHERE uid = %s",
            (uid,),
        )
        rows = await cursor.fetchall()
    return {row["provider"] for row in rows}


async def save_provider_credential(uid: str, provider: str, api_key: str) -> None:
    """Encrypt and idempotently replace a provider key for this user."""
    await save_provider_credentials(uid, {provider: api_key})


async def save_provider_credentials(uid: str, credentials: dict[str, str]) -> None:
    """Encrypt then atomically replace one or more provider keys for this user."""
    ciphertexts = {
        provider: await encrypt_secret(
            api_key,
            uid,
            "provider_api_key",
            {"provider": provider},
        )
        for provider, api_key in credentials.items()
    }
    async with _pool().connection() as conn:
        try:
            for provider, ciphertext in ciphertexts.items():
                await conn.execute(
                    """INSERT INTO agent_user_provider_credentials (uid, provider, ciphertext)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (uid, provider) DO UPDATE
                       SET ciphertext = EXCLUDED.ciphertext, updated_at = NOW()""",
                    (uid, provider, ciphertext),
                )
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


async def get_provider_credential(uid: str, provider: str) -> str | None:
    """Decrypt one user's provider key just in time for an API call."""
    if _POOL is None:
        return None
    async with _pool().connection() as conn:
        cursor = await conn.execute(
            """SELECT ciphertext FROM agent_user_provider_credentials
               WHERE uid = %s AND provider = %s""",
            (uid, provider),
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return await decrypt_secret(
        row["ciphertext"],
        uid,
        "provider_api_key",
        {"provider": provider},
    )


async def get_user_api_key(uid: str, provider: str) -> str | None:
    """Resolve a user's key, preferring encrypted BYOK storage over env fallback."""
    if _POOL is not None:
        credential = await get_provider_credential(uid, provider)
        if credential:
            return credential
    settings = get_settings()
    setting_name = {
        "google_maps": "google_maps_api_key",
        "tavily": "tavily_api_key",
        "exa": "exa_api_key",
        "firecrawl": "firecrawl_api_key",
    }.get(provider)
    if setting_name is None:
        raise ValueError(f"Unknown credential provider: {provider}")
    value = getattr(settings, setting_name).strip()
    return value or None


def reset_user_tool_config_store_for_tests() -> None:
    """Drop the global pool reference for isolated tests."""
    global _POOL
    _POOL = None
