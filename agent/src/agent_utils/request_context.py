"""Per-request context for tools invoked from HTTP handlers."""

from __future__ import annotations

from contextvars import ContextVar

request_user_id: ContextVar[str] = ContextVar("request_user_id", default="default")
