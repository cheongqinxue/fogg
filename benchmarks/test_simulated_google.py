"""Reference benchmarks with fixed mock Google latency (not for overhead regression)."""

from __future__ import annotations

import asyncio

import pytest

from benchmarks.harness import GmapsBenchmarkHarness
from benchmarks.scenarios import SIMULATED_GOOGLE_SCENARIOS, Scenario

pytestmark = [pytest.mark.benchmark, pytest.mark.simulated_google]


@pytest.mark.parametrize(
    "benchmark_scenario",
    SIMULATED_GOOGLE_SCENARIOS,
    ids=[scenario.name for scenario in SIMULATED_GOOGLE_SCENARIOS],
)
def test_places_search_with_simulated_google_latency(
    benchmark: object,
    benchmark_scenario: Scenario,
    benchmark_event_loop: asyncio.AbstractEventLoop,
) -> None:
    """Shows total time when mock HTTP sleeps (compare to ``overhead`` group separately)."""
    harness = GmapsBenchmarkHarness(benchmark_scenario)
    benchmark_event_loop.run_until_complete(harness.setup())

    def target() -> None:
        benchmark_event_loop.run_until_complete(harness.invoke_once())

    benchmark.pedantic(
        target,
        rounds=5,
        iterations=1,
        warmup_rounds=1,
    )
    benchmark_event_loop.run_until_complete(harness.teardown())
