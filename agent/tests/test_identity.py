from __future__ import annotations

import pytest

from utils import identity


@pytest.mark.asyncio
async def test_local_identity_returns_fixed_uid_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "dev")
    monkeypatch.setenv("IDENTITY_BACKEND", "local")

    assert await identity.verify_identity_token(None) == identity.LOCAL_IDENTITY_UID


@pytest.mark.asyncio
async def test_local_identity_rejects_production_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "prod")
    monkeypatch.setenv("IDENTITY_BACKEND", "local")

    with pytest.raises(identity.IdentityConfigurationError):
        await identity.verify_identity_token(None)


@pytest.mark.asyncio
async def test_google_identity_returns_none_for_missing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "prod")
    monkeypatch.setenv("IDENTITY_BACKEND", "google")

    assert await identity.verify_identity_token(" ") is None


@pytest.mark.asyncio
async def test_google_identity_returns_verified_uid_without_network_in_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "prod")
    monkeypatch.setenv("IDENTITY_BACKEND", "google")
    monkeypatch.setattr(
        identity,
        "_verify_google_identity_token",
        lambda token: "identity-platform-uid-123",
    )

    assert await identity.verify_identity_token(" signed-token ") == "identity-platform-uid-123"


@pytest.mark.asyncio
async def test_google_identity_returns_none_for_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "prod")
    monkeypatch.setenv("IDENTITY_BACKEND", "google")
    monkeypatch.setattr(identity, "_verify_google_identity_token", lambda _token: None)

    assert await identity.verify_identity_token("invalid-token") is None


@pytest.mark.asyncio
async def test_google_identity_requires_project_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "prod")
    monkeypatch.setenv("IDENTITY_BACKEND", "google")
    monkeypatch.delenv("IDENTITY_PROJECT_ID", raising=False)

    with pytest.raises(identity.IdentityConfigurationError):
        await identity.verify_identity_token("signed-token")


@pytest.mark.asyncio
async def test_google_identity_reports_provider_outage_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "prod")
    monkeypatch.setenv("IDENTITY_BACKEND", "google")

    def unavailable(_token: str) -> str | None:
        raise identity.IdentityProviderUnavailable("verification unavailable")

    monkeypatch.setattr(identity, "_verify_google_identity_token", unavailable)

    with pytest.raises(identity.IdentityProviderUnavailable):
        await identity.verify_identity_token("signed-token")
