"""Shared pytest hooks for the ``tests/`` suite."""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark collected tests as ``unit`` unless they opt into another tier."""
    other_tiers = frozenset({"integration", "benchmark", "simulated_google"})
    for item in items:
        if other_tiers.intersection(item.keywords):
            continue
        if "unit" not in item.keywords:
            item.add_marker(pytest.mark.unit)
