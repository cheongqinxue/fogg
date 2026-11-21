"""Identity token verification for API requests.

Local development uses a fixed, fictional UID. Production verifies Identity
Platform ID tokens with Google's Firebase Admin SDK.
"""

from __future__ import annotations

import asyncio
from threading import Lock
from typing import Any

from utils.settings import get_settings

LOCAL_IDENTITY_UID = "fogg-local-user"

_firebase_app: Any | None = None
_firebase_app_lock = Lock()


class IdentityConfigurationError(RuntimeError):
    """Identity verification is misconfigured for the selected environment."""


class IdentityProviderUnavailable(RuntimeError):
    """The configured identity provider could not verify the token."""


def _identity_backend() -> str:
    settings = get_settings()
    backend = settings.identity_backend
    if settings.fogg_env == "prod" and backend == "local":
        raise IdentityConfigurationError(
            "Local identity verification cannot be used when FOGG_ENV=prod"
        )
    return backend


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


def _verify_google_identity_token(token: str) -> str | None:
    project_id = get_settings().identity_project_id.strip()
    if not project_id:
        raise IdentityConfigurationError(
            "IDENTITY_PROJECT_ID is required when IDENTITY_BACKEND=google"
        )

    try:
        from firebase_admin import auth
    except Exception as exc:
        raise IdentityProviderUnavailable("Firebase Admin SDK is unavailable") from exc

    try:
        app = _get_firebase_app(project_id)
        decoded_token = auth.verify_id_token(token, app=app, check_revoked=False)
    except auth.InvalidIdTokenError:
        return None
    except IdentityConfigurationError:
        raise
    except Exception as exc:
        raise IdentityProviderUnavailable("Identity Platform token verification failed") from exc

    uid = decoded_token.get("uid")
    return uid if isinstance(uid, str) and uid else None


async def verify_identity_token(token: str | None) -> str | None:
    """Return the verified user's Identity Platform UID, or ``None`` if invalid.

    In local mode, the same fictional UID is returned for every request; the
    token is ignored. In Google mode, ``token`` is the raw bearer token after
    the ``Bearer `` prefix has been removed. Invalid or expired tokens return
    ``None``. Configuration and provider failures raise distinct exceptions so
    callers can distinguish an unauthorized request from an unavailable verifier.

    Google token verification uses the synchronous Firebase Admin SDK in a
    worker thread so this function remains safe to await from FastAPI handlers.
    """
    if _identity_backend() == "local":
        return LOCAL_IDENTITY_UID

    if not token or not token.strip():
        return None

    return await asyncio.to_thread(_verify_google_identity_token, token.strip())
