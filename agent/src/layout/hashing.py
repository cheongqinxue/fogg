"""Canonical layout JSON hashing (matches the browser client's layout hash)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    return value


def layout_document_hash(document: dict[str, Any]) -> str:
    """Return SHA-256 hex of canonical JSON for a layout document.

    Args:
        document: Layout document dict (schema v1).

    Returns:
        Lowercase hex digest.
    """
    canonical = _canonicalize(document)
    payload = json.dumps(canonical, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
