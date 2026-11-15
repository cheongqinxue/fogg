"""Load repository environment files before the agent reads configuration."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def load_repo_dotenv() -> None:
    """Load ``.env`` at repo root and optional ``agent/.env`` (does not override existing env)."""
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env", override=False)
    load_dotenv(_REPO_ROOT / "agent" / ".env", override=False)
