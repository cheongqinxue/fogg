from __future__ import annotations

import base64
import os
from types import SimpleNamespace

import pytest
from utils import kms


@pytest.fixture
def local_kms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOGG_ENV", "test")
    monkeypatch.setenv("KMS_BACKEND", "local")
    monkeypatch.setenv("KMS_LOCAL_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode("ascii"))


@pytest.mark.asyncio
async def test_local_kms_round_trips_secret_with_context(local_kms: None) -> None:
    context = {"provider": "tavily", "credential_version": "3"}
    encrypted = await kms.encrypt_secret("provider-api-key", "workspace-1", "web-search", context)

    assert encrypted != "provider-api-key"
    assert (
        await kms.decrypt_secret(encrypted, "workspace-1", "web-search", context)
        == "provider-api-key"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("account_id", "group", "context"),
    [
        ("workspace-2", "web-search", {"provider": "tavily"}),
        ("workspace-1", "maps", {"provider": "tavily"}),
        ("workspace-1", "web-search", {"provider": "exa"}),
    ],
)
async def test_local_kms_rejects_mismatched_context(
    local_kms: None,
    account_id: str,
    group: str,
    context: dict[str, str],
) -> None:
    encrypted = await kms.encrypt_secret(
        "provider-api-key",
        "workspace-1",
        "web-search",
        {"provider": "tavily"},
    )

    with pytest.raises(kms.KMSDecryptionError):
        await kms.decrypt_secret(encrypted, account_id, group, context)


@pytest.mark.asyncio
async def test_local_kms_rejects_tampered_ciphertext(local_kms: None) -> None:
    encrypted = await kms.encrypt_secret("provider-api-key", "user-1", "web-search")
    tampered = encrypted[:-1] + ("A" if encrypted[-1] != "A" else "B")

    with pytest.raises((kms.KMSCiphertextError, kms.KMSDecryptionError)):
        await kms.decrypt_secret(tampered, "user-1", "web-search")


@pytest.mark.asyncio
async def test_local_kms_requires_a_configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOGG_ENV", "dev")
    monkeypatch.setenv("KMS_BACKEND", "local")
    # A developer .env file may have a local key configured; whitespace overrides it
    # while still representing an unset key after settings normalization.
    monkeypatch.setenv("KMS_LOCAL_ENCRYPTION_KEY", " ")

    with pytest.raises(kms.KMSConfigurationError):
        await kms.encrypt_secret("provider-api-key", "user-1", "web-search")


@pytest.mark.asyncio
async def test_local_kms_is_not_allowed_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOGG_ENV", "prod")
    monkeypatch.setenv("KMS_BACKEND", "local")

    with pytest.raises(kms.KMSConfigurationError):
        await kms.encrypt_secret("provider-api-key", "user-1", "web-search")


@pytest.mark.asyncio
async def test_google_kms_backend_uses_configured_key_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "prod")
    monkeypatch.setenv("KMS_BACKEND", "google")
    monkeypatch.setenv("KMS_KEY_NAME", "projects/p/locations/global/keyRings/r/cryptoKeys/k")

    class FakeKMSClient:
        request: dict[str, object] | None = None

        async def encrypt(self, *, request: dict[str, object]) -> SimpleNamespace:
            self.request = request
            return SimpleNamespace(ciphertext=b"google-encrypted")

        async def decrypt(self, *, request: dict[str, object]) -> SimpleNamespace:
            self.request = request
            return SimpleNamespace(plaintext=b"provider-api-key")

    fake_client = FakeKMSClient()
    monkeypatch.setattr(kms, "_get_google_client", lambda: fake_client)
    context = {"provider": "exa"}

    encrypted = await kms.encrypt_secret("provider-api-key", "tenant-1", "web-search", context)
    assert fake_client.request is not None
    assert fake_client.request["name"] == os.environ["KMS_KEY_NAME"]
    assert fake_client.request["additional_authenticated_data"]

    decrypted = await kms.decrypt_secret(encrypted, "tenant-1", "web-search", context)
    assert decrypted == "provider-api-key"
    assert fake_client.request is not None
    assert fake_client.request["name"] == os.environ["KMS_KEY_NAME"]


@pytest.mark.asyncio
async def test_kms_context_rejects_reserved_fields(local_kms: None) -> None:
    with pytest.raises(ValueError, match="reserved"):
        await kms.encrypt_secret(
            "provider-api-key",
            "user-1",
            "web-search",
            {"uid": "different-user"},
        )
