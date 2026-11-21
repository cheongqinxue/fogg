from __future__ import annotations

import api.auth as api_auth
import pytest
from fastapi import HTTPException
from utils.identity import IdentityProviderUnavailable


@pytest.mark.asyncio
async def test_authenticated_account_id_uses_verified_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[str | None] = []

    async def verify(token: str | None) -> str:
        received.append(token)
        return "identity-platform-user"

    monkeypatch.setattr(api_auth, "verify_identity_token", verify)

    account_id = await api_auth.authenticated_account_id("Bearer signed-token")

    assert account_id == "identity-platform-user"
    assert received == ["signed-token"]


@pytest.mark.asyncio
async def test_authenticated_account_id_rejects_invalid_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def verify(_token: str | None) -> None:
        return None

    monkeypatch.setattr(api_auth, "verify_identity_token", verify)

    with pytest.raises(HTTPException) as error:
        await api_auth.authenticated_account_id("Bearer invalid")

    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_authenticated_account_id_maps_identity_outage_to_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def verify(_token: str | None) -> None:
        raise IdentityProviderUnavailable("provider unavailable")

    monkeypatch.setattr(api_auth, "verify_identity_token", verify)

    with pytest.raises(HTTPException) as error:
        await api_auth.authenticated_account_id("Bearer signed-token")

    assert error.value.status_code == 503


def test_path_user_id_must_match_verified_identity() -> None:
    assert api_auth.require_path_account_id("verified-user", "verified-user") == "verified-user"

    with pytest.raises(HTTPException) as error:
        api_auth.require_path_account_id("someone-else", "verified-user")

    assert error.value.status_code == 403


def test_path_user_id_rejects_empty_user_id() -> None:
    with pytest.raises(HTTPException) as error:
        api_auth.require_path_account_id("  ", "verified-user")

    assert error.value.status_code == 400
