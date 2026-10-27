"""pytest-benchmark fixtures for gmaps overhead suite."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session")
def benchmark_event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Dedicated event loop for sync-style benchmark tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
