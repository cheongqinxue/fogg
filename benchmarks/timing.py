"""Timing runner for gmaps benchmarks (no subprocess, no Google HTTP)."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter

from benchmarks.harness import GmapsBenchmarkHarness
from benchmarks.scenarios import (
    FAILURE_SCENARIOS,
    OVERHEAD_SCENARIOS,
    SIMULATED_GOOGLE_SCENARIOS,
    Scenario,
)


@dataclass(frozen=True, slots=True)
class TimingResult:
    """Aggregated latency for one scenario."""

    scenario: str
    group: str
    rounds: int
    mean_us: float
    median_us: float
    stdev_us: float
    min_us: float
    max_us: float


async def _measure_scenario(
    scenario: Scenario,
    *,
    rounds: int,
    warmup: int,
) -> TimingResult:
    harness = GmapsBenchmarkHarness(scenario)
    await harness.setup()
    for _ in range(warmup):
        await harness.invoke_once_allowing_expected_failure()
    samples: list[float] = []
    for _ in range(rounds):
        start = perf_counter()
        await harness.invoke_once_allowing_expected_failure()
        samples.append(perf_counter() - start)
    await harness.teardown()
    seconds_to_us = 1_000_000.0
    return TimingResult(
        scenario=scenario.name,
        group=scenario.group,
        rounds=rounds,
        mean_us=statistics.mean(samples) * seconds_to_us,
        median_us=statistics.median(samples) * seconds_to_us,
        stdev_us=statistics.stdev(samples) * seconds_to_us if len(samples) > 1 else 0.0,
        min_us=min(samples) * seconds_to_us,
        max_us=max(samples) * seconds_to_us,
    )


async def run_scenarios(
    scenarios: tuple[Scenario, ...],
    *,
    rounds: int,
    warmup: int,
) -> list[TimingResult]:
    """Time each scenario sequentially."""
    results: list[TimingResult] = []
    for scenario in scenarios:
        results.append(await _measure_scenario(scenario, rounds=rounds, warmup=warmup))
    return results


def _format_table(results: list[TimingResult]) -> str:
    header = f"{'scenario':<34} {'group':<18} {'median_us':>12} {'mean_us':>12} {'stdev_us':>12}"
    lines = [header, "-" * len(header)]
    for row in results:
        lines.append(
            f"{row.scenario:<34} {row.group:<18} {row.median_us:12.1f} {row.mean_us:12.1f} {row.stdev_us:12.1f}"
        )
    return "\n".join(lines)


def _select_scenarios(
    *,
    include_failure_path: bool,
    include_simulated_google: bool,
) -> tuple[Scenario, ...]:
    selected: list[Scenario] = list(OVERHEAD_SCENARIOS)
    if include_simulated_google:
        selected.extend(SIMULATED_GOOGLE_SCENARIOS)
    if include_failure_path:
        selected.extend(FAILURE_SCENARIOS)
    return tuple(selected)


def run_cli(argv: list[str] | None = None) -> int:
    """CLI entry: print table and optionally write JSON."""
    parser = argparse.ArgumentParser(
        description="Benchmark FOGG gmaps client overhead (mocked Google HTTP).",
    )
    parser.add_argument("--rounds", type=int, default=80, help="Timed iterations per scenario.")
    parser.add_argument("--warmup", type=int, default=15, help="Warmup iterations (not recorded).")
    parser.add_argument(
        "--include-simulated-google",
        action="store_true",
        help="Include 200 ms mock Google latency (reference, not overhead regression).",
    )
    parser.add_argument(
        "--include-failure-path",
        action="store_true",
        help="Include retry-exhaustion scenario.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write results JSON for before/after compares.",
    )
    args = parser.parse_args(argv)
    scenarios = _select_scenarios(
        include_failure_path=args.include_failure_path,
        include_simulated_google=args.include_simulated_google,
    )
    results = asyncio.run(
        run_scenarios(scenarios, rounds=args.rounds, warmup=args.warmup),
    )
    print(_format_table(results))
    if args.json_out is not None:
        payload = [asdict(row) for row in results]
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_out}")
    return 0
