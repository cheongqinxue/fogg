"""Verify FOGG sessions and exchange Google sign-in tokens."""

from __future__ import annotations

import asyncio
from threading import Lock
from typing import Any

from backend.accounts import Session, get_session_account_id, login_external_account
from psycopg import Error as PostgresError
from psycopg_pool import PoolTimeout

from utils.settings import get_settings

LOCAL_ACCOUNT_ID = "00000000-0000-4000-8000-000000000001"

_firebase_app: Any | None = None
_firebase_app_lock = Lock()


class IdentityConfigurationError(RuntimeError):
    """Identity verification is misconfigured for the selected environment."""


class IdentityProviderUnavailable(RuntimeError):
    """The configured identity provider could not verify the token."""


def _identity_backend() -> str:
    settings = get_settings()
    backend = settings.identity_backend
    if settings.fogg_env == "prod" and backend != "google":
        raise IdentityConfigurationError("Production requires IDENTITY_BACKEND=google")
    return backend


def password_sign_in_enabled() -> bool:
    settings = get_settings()
    return settings.fogg_env != "prod" and settings.identity_backend == "password"


def google_sign_in_enabled() -> bool:
    return get_settings().identity_backend == "google"


def session_endpoints_enabled() -> bool:
    return get_settings().identity_backend != "local"


def _get_firebase_app(project_id: str) -> Any:
    """Get or initialize the Firebase Admin SDK app for Identity Platform."""
    global _firebase_app
    with _firebase_app_lock:
        if _firebase_app is not None:
            if _firebase_app.project_id != project_id:
                raise IdentityConfigurationError(
                    "Firebase Admin SDK is already initialized for a different project"
                )
            return _firebase_app

        import firebase_admin

        try:
            app = firebase_admin.get_app()
        except ValueError:
            app = firebase_admin.initialize_app(options={"projectId": project_id})

        if app.project_id != project_id:
            raise IdentityConfigurationError(
                "Firebase Admin SDK project does not match IDENTITY_PROJECT_ID"
            )
        _firebase_app = app
        return app


def _verify_google_identity_token(token: str, project_id: str) -> str | None:
    try:
        from firebase_admin import auth
    except Exception as exc:
        raise IdentityProviderUnavailable("Firebase Admin SDK is unavailable") from exc

    try:
        app = _get_firebase_app(project_id)
        decoded_token = auth.verify_id_token(token, app=app, check_revoked=True)
    except (auth.InvalidIdTokenError, auth.UserDisabledError, auth.UserNotFoundError):
        return None
    except IdentityConfigurationError:
        raise
    except Exception as exc:
        raise IdentityProviderUnavailable("Identity Platform token verification failed") from exc

    firebase = decoded_token.get("firebase")
    if not isinstance(firebase, dict) or firebase.get("sign_in_provider") != "google.com":
        return None
    if firebase.get("tenant"):
        return None
    subject = decoded_token.get("uid")
    return subject if isinstance(subject, str) and subject else None


async def verify_identity_token(token: str | None) -> str | None:
    """Resolve an API bearer token against FOGG's session store."""
    backend = _identity_backend()
    if backend == "local":
        return LOCAL_ACCOUNT_ID

    if not token or not token.strip():
        return None

    try:
        return await get_session_account_id(token.strip())
    except (PostgresError, PoolTimeout) as exc:
        raise IdentityProviderUnavailable("Session verification is unavailable") from exc


async def exchange_google_token(token: str) -> Session | None:
    """Verify a Google sign-in and issue an ordinary FOGG session."""
    if not token:
        return None
    project_id = get_settings().identity_project_id.strip()
    if not project_id:
        raise IdentityConfigurationError(
            "IDENTITY_PROJECT_ID is required when IDENTITY_BACKEND=google"
        )
    subject = await asyncio.to_thread(_verify_google_identity_token, token, project_id)
    if subject is None:
        return None
    try:
        return await login_external_account(f"https://securetoken.google.com/{project_id}", subject)
    except (PostgresError, PoolTimeout) as exc:
        raise IdentityProviderUnavailable("Account lookup is unavailable") from exc
