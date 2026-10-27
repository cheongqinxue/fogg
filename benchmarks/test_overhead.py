"""Regression benchmarks for local gmaps overhead (zero simulated Google latency)."""

from __future__ import annotations

import asyncio

import pytest

from benchmarks.harness import GmapsBenchmarkHarness
from benchmarks.scenarios import OVERHEAD_SCENARIOS, Scenario

pytestmark = pytest.mark.benchmark


@pytest.mark.parametrize(
    "benchmark_scenario",
    OVERHEAD_SCENARIOS,
    ids=[scenario.name for scenario in OVERHEAD_SCENARIOS],
)
def test_places_search_overhead(
    benchmark: object,
    benchmark_scenario: Scenario,
    benchmark_event_loop: asyncio.AbstractEventLoop,
) -> None:
    """End-to-end ``PlacesTextSearchRequest.call()`` without real Google latency."""
    harness = GmapsBenchmarkHarness(benchmark_scenario)
    benchmark_event_loop.run_until_complete(harness.setup())

    def target() -> None:
        benchmark_event_loop.run_until_complete(harness.invoke_once())

    benchmark.pedantic(
        target,
        rounds=8,
        iterations=1,
        warmup_rounds=2,
    )
    benchmark_event_loop.run_until_complete(harness.teardown())
