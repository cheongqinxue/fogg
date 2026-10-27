"""Quota read model for a single SKU."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuotaBalance:
    """Local free-tier usage and remaining balance for one SKU."""

    used: int
    balance: int
