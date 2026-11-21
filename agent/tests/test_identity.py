from __future__ import annotations

from datetime import UTC, datetime

import pytest
from backend.accounts import Session
from firebase_admin import auth
from utils import identity


@pytest.mark.asyncio
async def test_local_identity_returns_fixed_uid_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "dev")
    monkeypatch.setenv("IDENTITY_BACKEND", "local")

    assert await identity.verify_identity_token(None) == identity.LOCAL_ACCOUNT_ID


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
async def test_google_identity_returns_verified_account_id_without_network_in_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "prod")
    monkeypatch.setenv("IDENTITY_BACKEND", "google")
    monkeypatch.setattr(
        identity,
        "_verify_google_identity_token",
        lambda _token, _project_id: "identity-platform-uid-123",
    )

    monkeypatch.setenv("IDENTITY_PROJECT_ID", "example-project")

    session = Session("internal-account-id", "session-token", datetime.now(UTC))

    async def login(issuer: str, subject: str) -> Session:
        assert issuer == "https://securetoken.google.com/example-project"
        assert subject == "identity-platform-uid-123"
        return session

    monkeypatch.setattr(identity, "login_external_account", login)
    assert await identity.exchange_google_token("signed-token") == session


@pytest.mark.asyncio
async def test_google_identity_returns_none_for_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "prod")
    monkeypatch.setenv("IDENTITY_BACKEND", "google")
    monkeypatch.setattr(identity, "_verify_google_identity_token", lambda _token, _project_id: None)

    monkeypatch.setenv("IDENTITY_PROJECT_ID", "example-project")
    assert await identity.exchange_google_token("invalid-token") is None


@pytest.mark.asyncio
async def test_google_identity_requires_project_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "prod")
    monkeypatch.setenv("IDENTITY_BACKEND", "google")
    monkeypatch.delenv("IDENTITY_PROJECT_ID", raising=False)

    with pytest.raises(identity.IdentityConfigurationError):
        await identity.exchange_google_token("signed-token")


@pytest.mark.asyncio
async def test_google_identity_reports_provider_outage_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "prod")
    monkeypatch.setenv("IDENTITY_BACKEND", "google")

    monkeypatch.setenv("IDENTITY_PROJECT_ID", "example-project")

    def unavailable(_token: str, _project_id: str) -> str | None:
        raise identity.IdentityProviderUnavailable("verification unavailable")

    monkeypatch.setattr(identity, "_verify_google_identity_token", unavailable)

    with pytest.raises(identity.IdentityProviderUnavailable):
        await identity.exchange_google_token("signed-token")


@pytest.mark.parametrize(
    ("firebase", "expected"),
    [
        ({"sign_in_provider": "google.com"}, "verified-user"),
        ({"sign_in_provider": "password"}, None),
        ({"sign_in_provider": "google.com", "tenant": "unconfigured"}, None),
    ],
)
def test_google_exchange_verifier_checks_revocation_and_provider(
    monkeypatch: pytest.MonkeyPatch, firebase: dict[str, str], expected: str | None
) -> None:
    configured_app = object()

    def verify(token: str, *, app: object, check_revoked: bool) -> dict:
        assert app is configured_app
        assert token == "signed-token"
        assert check_revoked
        return {"uid": "verified-user", "firebase": firebase}

    monkeypatch.setattr(identity, "_get_firebase_app", lambda _project_id: configured_app)
    monkeypatch.setattr(auth, "verify_id_token", verify)
    assert identity._verify_google_identity_token("signed-token", "example-project") == expected
