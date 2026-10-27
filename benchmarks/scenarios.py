"""Benchmark scenario definitions (no real Google HTTP)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BenchmarkGroup = Literal["overhead", "simulated_google", "failure_path"]

# Reference latency only — not used for overhead regression tracking.
DEFAULT_SIMULATED_GOOGLE_LATENCY_SEC = 0.2


@dataclass(frozen=True, slots=True)
class Scenario:
    """One measurable configuration of the gmaps client stack.

    Attributes:
        name: Stable identifier for pyperf / pytest-benchmark.
        group: ``overhead`` scenarios use zero simulated Google latency.
            ``simulated_google`` adds fixed network delay in the mock transport.
            ``failure_path`` measures retry behavior (not steady-state).
        simulated_google_latency_sec: Sleep in the mock HTTP layer before 200 OK.
        cache_enabled: ``GMAPS_CACHE_ENABLED``.
        quota_enabled: ``GMAPS_QUOTA_TRACKING``.
        warm_cache: Prime Redis cache once before timed iterations (cache hit path).
        clear_cache_before_each: Delete cache keys before each iteration (cache miss path).
    """

    name: str
    group: BenchmarkGroup
    simulated_google_latency_sec: float = 0.0
    cache_enabled: bool = False
    quota_enabled: bool = False
    warm_cache: bool = False
    clear_cache_before_each: bool = False


OVERHEAD_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="client_minimal",
        group="overhead",
        cache_enabled=False,
        quota_enabled=False,
    ),
    Scenario(
        name="client_cache_miss",
        group="overhead",
        cache_enabled=True,
        quota_enabled=False,
        clear_cache_before_each=True,
    ),
    Scenario(
        name="client_cache_hit",
        group="overhead",
        cache_enabled=True,
        quota_enabled=False,
        warm_cache=True,
    ),
    Scenario(
        name="client_quota_record",
        group="overhead",
        cache_enabled=False,
        quota_enabled=True,
    ),
    Scenario(
        name="client_full_stack_cache_miss",
        group="overhead",
        cache_enabled=True,
        quota_enabled=True,
        clear_cache_before_each=True,
    ),
    Scenario(
        name="client_full_stack_cache_hit",
        group="overhead",
        cache_enabled=True,
        quota_enabled=True,
        warm_cache=True,
    ),
)

SIMULATED_GOOGLE_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="client_with_simulated_google_latency",
        group="simulated_google",
        simulated_google_latency_sec=DEFAULT_SIMULATED_GOOGLE_LATENCY_SEC,
        cache_enabled=False,
        quota_enabled=False,
    ),
    Scenario(
        name="client_simulated_google_cache_hit",
        group="simulated_google",
        simulated_google_latency_sec=DEFAULT_SIMULATED_GOOGLE_LATENCY_SEC,
        cache_enabled=True,
        quota_enabled=False,
        warm_cache=True,
    ),
)

FAILURE_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="transport_retry_exhausted",
        group="failure_path",
        cache_enabled=False,
        quota_enabled=False,
    ),
)

ALL_SCENARIOS: tuple[Scenario, ...] = (
    *OVERHEAD_SCENARIOS,
    *SIMULATED_GOOGLE_SCENARIOS,
    *FAILURE_SCENARIOS,
)
