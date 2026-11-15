"""Development simulations match multiple scenarios without reaching real APIs."""

import json
import re

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from graph.simulation import SimulationError, simulated_tools
from graph.tools import get_tools


def test_original_schemas_and_local_tools_are_preserved():
    original = get_tools()
    patched = simulated_tools(original, delay_seconds=0)
    assert [tool.args for tool in patched] == [tool.args for tool in original]
    assert next(t for t in patched if t.name == "map_set_viewport") is next(
        t for t in original if t.name == "map_set_viewport"
    )


@pytest.mark.asyncio
async def test_registered_scenarios_match_regex_ranges_and_locations():
    scenarios = {
        "first": {
            "places_text_search": [
                {
                    "expected": {
                        "text_query": re.compile("ski", re.I),
                        "area": {
                            "center_within_km": {
                                "latitude": 36.6513,
                                "longitude": 138.181,
                                "distance": 20,
                            }
                        },
                    },
                    "response": {"places": [{"id": "first"}]},
                }
            ]
        },
        "second": {
            "places_text_search": [
                {
                    "expected": {
                        "text_query": re.compile("coffee", re.I),
                        "min_rating": {"range": [4, 5]},
                    },
                    "response": {"places": [{"id": "second"}]},
                }
            ]
        },
    }
    tools = simulated_tools(get_tools(), scenarios, delay_seconds=0)
    search = next(t for t in tools if t.name == "places_text_search")
    area = {"latitude": 36.65, "longitude": 138.18, "radius_meters": 1000, "mode": "restrict"}
    first = json.loads(await search.ainvoke({"text_query": "SKI resorts", "area": area}))
    second = json.loads(await search.ainvoke({"text_query": "Coffee", "min_rating": 4.5}))
    assert first["places"][0]["id"] == "first"
    assert second["places"][0]["id"] == "second"
    with pytest.raises(SimulationError, match="maximum is 20 km"):
        await search.ainvoke({"text_query": "ski", "area": {**area, "latitude": 35.0}})
    place = next(t for t in tools if t.name == "places_get")
    with pytest.raises(SimulationError, match="No simulation matches"):
        await place.ainvoke({"place_id": "anything"})


@pytest.mark.asyncio
async def test_nearby_reports_distance_from_scenario_center():
    nearby = next(
        t for t in simulated_tools(get_tools(), delay_seconds=0) if t.name == "places_search_nearby"
    )
    args = {
        "latitude": 36.2197,
        "longitude": 137.3625,
        "radius_meters": 5000,
        "included_types": ["ski_resort"],
    }
    places = json.loads(await nearby.ainvoke(args))["places"]
    assert len(places) == 3
    assert len({place["id"] for place in places}) == 3
    assert all("rating" not in place for place in places)
    with pytest.raises(SimulationError, match=r"maximum is 100 km"):
        await nearby.ainvoke({**args, "latitude": 34.0})


@pytest.mark.asyncio
async def test_nagano_text_search_includes_three_distinct_locations():
    search = next(
        t for t in simulated_tools(get_tools(), delay_seconds=0) if t.name == "places_text_search"
    )
    result = json.loads(await search.ainvoke({"text_query": "ski resorts Nagano"}))
    places = result["places"]
    assert len(places) == 3
    assert len({place["id"] for place in places}) == 3
    assert all(
        "latitude" in place["location"] and "longitude" in place["location"] for place in places
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("index", range(3))
async def test_simulated_airport_routes_match_destination(index):
    from graph.simulations import TEXT_SEARCH_SKI_RESORTS

    route = next(
        t for t in simulated_tools(get_tools(), delay_seconds=0) if t.name == "routes_compute"
    )
    place = TEXT_SEARCH_SKI_RESORTS[index]
    result = json.loads(
        await route.ainvoke(
            {
                "origin": {"address": "Matsumoto Airport"},
                "destination": {"place_id": place["id"]},
            }
        )
    )
    path = result["routes"][0]
    assert path["distanceMeters"] > 0
    assert path["duration"].endswith("s")
    assert path["polyline"]["encodedPolyline"]
    leg = path["legs"][0]
    assert leg["startLocation"]["latLng"]["latitude"] == 36.16667
    assert leg["endLocation"]["latLng"] == place["location"]
    assert leg["steps"][0]["polyline"] == path["polyline"]
    assert leg["steps"][0]["navigationInstruction"]["instructions"]
    with pytest.raises(SimulationError, match="No simulation matches"):
        await route.ainvoke(
            {"origin": {"address": "Tokyo Airport"}, "destination": {"place_id": place["id"]}}
        )


@pytest.mark.asyncio
async def test_simulated_airport_route_accepts_coordinates():
    route = next(
        t for t in simulated_tools(get_tools(), delay_seconds=0) if t.name == "routes_compute"
    )
    result = json.loads(
        await route.ainvoke(
            {
                "origin": {"latitude": 36.16667, "longitude": 137.92278},
                "destination": {"latitude": 36.698, "longitude": 137.839},
            }
        )
    )
    assert result["routes"][0]["polyline"]["encodedPolyline"] == "uxv{Ek`yhYywfBrjO"


@pytest.mark.asyncio
async def test_airport_search_result_can_be_used_as_route_origin():
    tools = simulated_tools(get_tools(), delay_seconds=0)
    search = next(tool for tool in tools if tool.name == "places_text_search")
    route = next(tool for tool in tools if tool.name == "routes_compute")
    airport = json.loads(await search.ainvoke({"text_query": "Matsumoto Airport"}))["places"][0]
    assert airport["id"] == "sim-matsumoto-airport"
    result = json.loads(
        await route.ainvoke(
            {
                "origin": {"place_id": airport["id"]},
                "destination": {"place_id": "sim-nagano-ski-3"},
            }
        )
    )
    assert result["routes"][0]["polyline"]["encodedPolyline"]


@pytest.mark.asyncio
async def test_simulated_calls_apply_async_delay_on_success_and_failure(monkeypatch):
    from graph import simulation

    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(simulation.asyncio, "sleep", fake_sleep)
    tools = simulated_tools(get_tools())
    search = next(t for t in tools if t.name == "places_text_search")
    await search.ainvoke({"text_query": "ski resorts Nagano"})
    with pytest.raises(SimulationError):
        await search.ainvoke({"text_query": "something unknown"})
    assert delays == [1.0, 1.0]


@pytest.mark.asyncio
async def test_dev_graph_uses_simulated_tool(monkeypatch):
    from graph import agent
    from gmaps.settings import reset_usage_store_for_tests

    class Model:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            self.tools = tools
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "places_text_search",
                            "args": {"text_query": "ski resorts Nagano"},
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ],
                )
            assert any(isinstance(m, ToolMessage) and "sim-nagano" in m.content for m in messages)
            return AIMessage(content="Here are resorts.")

    monkeypatch.setenv("FOGG_ENV", "dev")
    reset_usage_store_for_tests()
    try:
        graph = agent.build_graph(model=Model(), checkpointer=InMemorySaver())
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="ski resorts Nagano")]},
            {"configurable": {"thread_id": "sim-test"}},
        )
        assert result["messages"][-1].content == "Here are resorts."
    finally:
        reset_usage_store_for_tests()
