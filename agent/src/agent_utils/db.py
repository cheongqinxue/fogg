"""Shared Postgres connection URL for agent services."""

from __future__ import annotations

import os


def _default_database_url() -> str:
    user = os.environ.get("POSTGRES_USER", "fogg")
    password = os.environ.get("POSTGRES_PASSWORD", "fogg")
    db = os.environ.get("POSTGRES_DB", "fogg")
    host = os.environ.get("AGENT_DATABASE_HOST", "127.0.0.1")
    port = os.environ.get("COMPOSE_PORT_POSTGRES", "15432")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def database_url() -> str:
    """Resolve Postgres URL (same rules as LangGraph checkpoints)."""
    return (
        os.environ.get("AGENT_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or _default_database_url()
    )
