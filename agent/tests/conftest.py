"""Shared pytest hooks for the ``agent/tests/`` suite."""

from __future__ import annotations

import pytest
from collections.abc import Iterator

from utils.settings import reset_settings_for_tests


@pytest.fixture(autouse=True)
def clear_cached_settings() -> Iterator[None]:
    """Isolate environment-backed configuration between tests."""
    reset_settings_for_tests()
    yield
    reset_settings_for_tests()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark collected tests as ``unit`` unless they opt into another tier."""
    other_tiers = frozenset({"integration", "benchmark", "simulated_google"})
    for item in items:
        if other_tiers.intersection(item.keywords):
            continue
        if "unit" not in item.keywords:
            item.add_marker(pytest.mark.unit)
