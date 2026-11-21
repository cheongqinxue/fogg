"""Resolve authenticated API identity from the request's bearer token."""

from __future__ import annotations

from fastapi import Header, HTTPException, status
from utils.identity import (
    IdentityConfigurationError,
    IdentityProviderUnavailable,
    verify_identity_token,
)


def parse_bearer_token(authorization: str | None) -> str | None:
    """Read the token from the Authorization header when supplied."""
    if authorization is not None:
        scheme, separator, credentials = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not credentials.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization must use a bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return credentials.strip()
    return None


async def authenticated_account_id(authorization: str | None = Header(default=None)) -> str:
    """Return the verified ID for the current request."""
    token = parse_bearer_token(authorization)
    try:
        account_id = await verify_identity_token(token)
    except (IdentityConfigurationError, IdentityProviderUnavailable) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity verification is unavailable",
        ) from exc

    if account_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return account_id


def require_path_account_id(path_account_id: str, verified_account_id: str) -> str:
    """Ensure the legacy user path agrees with the UID verified from the token."""
    cleaned = path_account_id.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="account_id required")
    if cleaned != verified_account_id:
        raise HTTPException(status_code=403, detail="account_id does not match authenticated user")
    return verified_account_id
