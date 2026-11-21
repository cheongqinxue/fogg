"""Per-request context for tools invoked from HTTP handlers."""

from __future__ import annotations

from contextvars import ContextVar

request_account_id: ContextVar[str] = ContextVar("request_account_id")


def require_request_account_id() -> str:
    """Return the request account or fail before accessing account data."""
    account_id = request_account_id.get(None)
    if not account_id:
        raise RuntimeError("An account is required for this operation.")
    return account_id
