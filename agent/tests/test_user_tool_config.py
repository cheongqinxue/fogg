from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

import utils.user_tool_config as user_tool_config


class _Cursor:
    async def fetchone(self):
        return {"ciphertext": "encrypted-value"}

    async def fetchall(self):
        return []


class _Connection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self.commits = 0

    async def execute(self, query: str, params: tuple = ()) -> _Cursor:
        self.executed.append((query, params))
        return _Cursor()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        raise AssertionError("unexpected rollback")


class _Pool:
    def __init__(self) -> None:
        self.conn = _Connection()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_Connection]:
        yield self.conn


@pytest.mark.asyncio
async def test_provider_credentials_are_encrypted_before_idempotent_upsert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _Pool()
    monkeypatch.setattr(user_tool_config, "_POOL", pool)
    encrypted_plaintexts: list[tuple[str, str, str, dict[str, str]]] = []

    async def encrypt(plaintext: str, uid: str, group: str, context: dict[str, str]) -> str:
        encrypted_plaintexts.append((plaintext, uid, group, context))
        return "ciphertext-only"

    monkeypatch.setattr(user_tool_config, "encrypt_secret", encrypt)

    await user_tool_config.save_provider_credentials(
        "uid-1", {"tavily": "replacement-key", "exa": "exa-key"}
    )

    assert encrypted_plaintexts == [
        ("replacement-key", "uid-1", "provider_api_key", {"provider": "tavily"}),
        ("exa-key", "uid-1", "provider_api_key", {"provider": "exa"}),
    ]
    writes = pool.conn.executed
    assert len(writes) == 2
    assert all("ON CONFLICT (uid, provider) DO UPDATE" in query for query, _ in writes)
    assert all("replacement-key" not in repr(params) for _, params in writes)
    assert all(params[2] == "ciphertext-only" for _, params in writes)
    assert pool.conn.commits == 1


@pytest.mark.asyncio
async def test_user_api_key_is_decrypted_just_in_time_with_bound_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _Pool()
    monkeypatch.setattr(user_tool_config, "_POOL", pool)
    decrypt_contexts: list[tuple[str, str, str, dict[str, str]]] = []

    async def decrypt(ciphertext: str, uid: str, group: str, context: dict[str, str]) -> str:
        decrypt_contexts.append((ciphertext, uid, group, context))
        return "plaintext-api-key"

    monkeypatch.setattr(user_tool_config, "decrypt_secret", decrypt)

    key = await user_tool_config.get_user_api_key("uid-2", "google_maps")

    assert key == "plaintext-api-key"
    assert decrypt_contexts == [
        ("encrypted-value", "uid-2", "provider_api_key", {"provider": "google_maps"})
    ]
