"""Per-user tool preferences and encrypted provider credentials in Postgres."""

from __future__ import annotations

from backend.database import get_pool, get_pool_if_initialized

from utils.kms import decrypt_secret, encrypt_secret
from utils.settings import get_settings


async def get_tool_active_overrides(account_id: str) -> dict[str, bool]:
    """Return explicitly saved active states; absent rows use caller defaults."""
    pool = get_pool_if_initialized()
    if pool is None:
        return {}
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT tool_name, active FROM agent_user_tool_preferences WHERE account_id = %s",
            (account_id,),
        )
        rows = await cursor.fetchall()
    return {row["tool_name"]: bool(row["active"]) for row in rows}


async def set_tool_active(account_id: str, tool_name: str, active: bool) -> None:
    """Set a user's active preference for a tool."""
    async with get_pool().connection() as conn:
        await conn.execute(
            """INSERT INTO agent_user_tool_preferences (account_id, tool_name, active)
               VALUES (%s, %s, %s)
               ON CONFLICT (account_id, tool_name) DO UPDATE
               SET active = EXCLUDED.active, updated_at = NOW()""",
            (account_id, tool_name, active),
        )
        await conn.commit()


async def get_saved_providers(account_id: str) -> set[str]:
    """Return provider names with encrypted credentials saved for a user."""
    pool = get_pool_if_initialized()
    if pool is None:
        return set()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT provider FROM agent_user_provider_credentials WHERE account_id = %s",
            (account_id,),
        )
        rows = await cursor.fetchall()
    return {row["provider"] for row in rows}


async def save_provider_credential(account_id: str, provider: str, api_key: str) -> None:
    """Encrypt and idempotently replace a provider key for this user."""
    await save_provider_credentials(account_id, {provider: api_key})


async def save_provider_credentials(account_id: str, credentials: dict[str, str]) -> None:
    """Encrypt then atomically replace one or more provider keys for this user."""
    ciphertexts = {
        provider: await encrypt_secret(
            api_key,
            account_id,
            "provider_api_key",
            {"provider": provider},
        )
        for provider, api_key in credentials.items()
    }
    async with get_pool().connection() as conn:
        try:
            for provider, ciphertext in ciphertexts.items():
                await conn.execute(
                    """INSERT INTO agent_user_provider_credentials (account_id, provider, ciphertext)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (account_id, provider) DO UPDATE
                       SET ciphertext = EXCLUDED.ciphertext, legacy_encryption_owner = NULL, updated_at = NOW()""",
                    (account_id, provider, ciphertext),
                )
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


async def get_provider_credential(account_id: str, provider: str) -> str | None:
    """Decrypt one user's provider key just in time for an API call."""
    pool = get_pool_if_initialized()
    if pool is None:
        return None
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """SELECT ciphertext, legacy_encryption_owner FROM agent_user_provider_credentials
               WHERE account_id = %s AND provider = %s""",
            (account_id, provider),
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return await decrypt_secret(
        row["ciphertext"],
        row["legacy_encryption_owner"] or account_id,
        "provider_api_key",
        {"provider": provider},
    )


async def get_user_api_key(account_id: str | None, provider: str) -> str | None:
    """Resolve an account's key, or the deployment key for a standalone caller."""
    if account_id is not None:
        credential = await get_provider_credential(account_id, provider)
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
