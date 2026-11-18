"""Argument-matched simulated tool responses for development."""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Mapping
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel

from master_agt.simulations import SCENARIOS

# All tools that can contact Google must always be intercepted in development,
# even when no fixture currently exists for them.
SIMULATED_TOOL_NAMES = frozenset(
    {
        "places_text_search",
        "places_search_nearby",
        "places_get",
        "routes_compute",
        "routes_compute_matrix",
    }
)


class SimulationError(Exception):
    """No registered simulation matches the tool arguments."""


def _distance_km(lat: float, lng: float, center: Mapping[str, float]) -> float:
    lat1, lat2 = math.radians(center["latitude"]), math.radians(lat)
    dlat, dlng = lat2 - lat1, math.radians(lng - center["longitude"])
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(min(1.0, value)))


def _matches(actual: Any, expected: Any) -> bool:
    if isinstance(actual, BaseModel):
        actual = actual.model_dump()
    if isinstance(expected, re.Pattern):
        return isinstance(actual, str) and expected.search(actual) is not None
    if isinstance(expected, Mapping):
        if "any_of" in expected:
            return any(_matches(actual, choice) for choice in expected["any_of"])
        if "any_regex" in expected:
            return isinstance(actual, list) and any(
                _matches(item, expected["any_regex"]) for item in actual
            )
        if "range" in expected:
            lower, upper = expected["range"]
            return isinstance(actual, (int, float)) and lower <= actual <= upper
        if not isinstance(actual, Mapping):
            return False
        for key, value in expected.items():
            if key == "center_within_km":
                if not isinstance(actual.get("latitude"), (int, float)) or not isinstance(
                    actual.get("longitude"), (int, float)
                ):
                    return False
                if _distance_km(actual["latitude"], actual["longitude"], value) > value["distance"]:
                    return False
            elif key not in actual or not _matches(actual[key], value):
                return False
        return True
    return actual == expected


def _location_mismatch(actual: Any, expected: Any) -> str | None:
    """Explain an out-of-range center only when the other conditions match."""
    if isinstance(actual, BaseModel):
        actual = actual.model_dump()
    if not isinstance(actual, Mapping) or not isinstance(expected, Mapping):
        return None
    other = {key: value for key, value in expected.items() if key != "center_within_km"}
    if "center_within_km" in expected and _matches(actual, other):
        center = expected["center_within_km"]
        if isinstance(actual.get("latitude"), (int, float)) and isinstance(
            actual.get("longitude"), (int, float)
        ):
            distance = _distance_km(actual["latitude"], actual["longitude"], center)
            if distance > center["distance"]:
                return (
                    f"Search center is {distance:.1f} km from the simulated center "
                    f"({center['latitude']}, {center['longitude']}); "
                    f"maximum is {center['distance']} km. Correct the location and try again."
                )
    for key, value in other.items():
        if key in actual:
            # Report a nested mismatch only if every other expected argument matches.
            peers = {k: v for k, v in other.items() if k != key}
            if _matches(actual, peers):
                detail = _location_mismatch(actual[key], value)
                if detail:
                    return detail
    return None


def simulated_tools(
    tools: list[BaseTool],
    scenarios: Mapping[str, Any] | None = None,
    *,
    delay_seconds: float = 1.0,
) -> list[BaseTool]:
    """Replace external tools while retaining their schemas and validation."""
    if delay_seconds < 0:
        raise ValueError("Simulation delay cannot be negative")
    registry = SCENARIOS if scenarios is None else scenarios
    copies = []
    for original in tools:
        if original.name not in SIMULATED_TOOL_NAMES:
            copies.append(original)
            continue

        def make_coroutine(name: str):
            async def invoke(**kwargs: Any) -> str:
                await asyncio.sleep(delay_seconds)
                location_errors = []
                for scenario in registry.values():
                    for case in scenario.get(name, []):
                        if _matches(kwargs, case["expected"]):
                            result = case["response"]
                            return (
                                result
                                if isinstance(result, str)
                                else json.dumps(result, ensure_ascii=False)
                            )
                        detail = _location_mismatch(kwargs, case["expected"])
                        if detail:
                            location_errors.append(detail)
                if location_errors:
                    raise SimulationError(location_errors[0])
                raise SimulationError(f"No simulation matches {name} with the supplied arguments")

            return invoke

        copies.append(
            original.model_copy(update={"coroutine": make_coroutine(original.name), "func": None})
        )
    return copies
