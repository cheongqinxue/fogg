from __future__ import annotations

import pytest
from fastapi import HTTPException

import api.auth as api_auth
from utils.identity import IdentityProviderUnavailable


@pytest.mark.asyncio
async def test_authenticated_uid_uses_verified_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[str | None] = []

    async def verify(token: str | None) -> str:
        received.append(token)
        return "identity-platform-uid"

    monkeypatch.setattr(api_auth, "verify_identity_token", verify)

    uid = await api_auth.authenticated_uid("Bearer signed-token")

    assert uid == "identity-platform-uid"
    assert received == ["signed-token"]


@pytest.mark.asyncio
async def test_authenticated_uid_rejects_invalid_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def verify(_token: str | None) -> None:
        return None

    monkeypatch.setattr(api_auth, "verify_identity_token", verify)

    with pytest.raises(HTTPException) as error:
        await api_auth.authenticated_uid("Bearer invalid")

    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_authenticated_uid_maps_identity_outage_to_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def verify(_token: str | None) -> None:
        raise IdentityProviderUnavailable("provider unavailable")

    monkeypatch.setattr(api_auth, "verify_identity_token", verify)

    with pytest.raises(HTTPException) as error:
        await api_auth.authenticated_uid("Bearer signed-token")

    assert error.value.status_code == 503


def test_path_uid_must_match_verified_identity() -> None:
    assert api_auth.require_path_uid("verified-uid", "verified-uid") == "verified-uid"

    with pytest.raises(HTTPException) as error:
        api_auth.require_path_uid("someone-elses-uid", "verified-uid")

    assert error.value.status_code == 403


def test_path_uid_rejects_empty_user_id() -> None:
    with pytest.raises(HTTPException) as error:
        api_auth.require_path_uid("  ", "verified-uid")

    assert error.value.status_code == 400
