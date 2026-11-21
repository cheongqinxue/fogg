"""Resolve authenticated API identity from the request's bearer token."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from utils.identity import (
    IdentityConfigurationError,
    IdentityProviderUnavailable,
    verify_identity_token,
)


async def authenticated_uid(authorization: str | None = Header(default=None)) -> str:
    """Return the verified UID; local identity mode permits requests without a token."""
    token: str | None = None
    if authorization is not None:
        scheme, separator, credentials = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not credentials.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization must use a bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = credentials.strip()

    try:
        uid = await verify_identity_token(token)
    except (IdentityConfigurationError, IdentityProviderUnavailable) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity verification is unavailable",
        ) from exc

    if uid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return uid


def require_path_uid(path_uid: str, verified_uid: str) -> str:
    """Ensure the legacy user path agrees with the UID verified from the token."""
    cleaned = path_uid.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="user_id required")
    if cleaned != verified_uid:
        raise HTTPException(status_code=403, detail="user_id does not match authenticated user")
    return verified_uid
