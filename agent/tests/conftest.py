"""Shared pytest hooks for the ``agent/tests/`` suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from utils.request_context import request_account_id
from utils.settings import reset_settings_for_tests


@pytest.fixture(autouse=True)
def clear_cached_settings() -> Iterator[None]:
    """Isolate environment-backed configuration between tests."""
    reset_settings_for_tests()
    yield
    reset_settings_for_tests()


@pytest.fixture
def account_context() -> Iterator[str]:
    """Supply an explicit account for tests that call tools without HTTP."""
    account_id = "test-account"
    token = request_account_id.set(account_id)
    try:
        yield account_id
    finally:
        request_account_id.reset(token)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark collected tests as ``unit`` unless they opt into another tier."""
    other_tiers = frozenset({"integration", "benchmark", "simulated_google"})
    for item in items:
        if other_tiers.intersection(item.keywords):
            continue
        if "unit" not in item.keywords:
            item.add_marker(pytest.mark.unit)
