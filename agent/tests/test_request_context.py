"""Account context is explicit and isolated across concurrent calls."""

import asyncio

import pytest
from gmaps.tools import places_get
from layout.tools import map_set_viewport
from master.tools import get_active_tools
from utils.request_context import request_account_id, require_request_account_id
from web_search_tool.tools import web_search


@pytest.mark.asyncio
async def test_account_context_isolated_across_tasks_and_workers() -> None:
    first_ready = asyncio.Event()
    second_ready = asyncio.Event()

    async def call(account_id: str, ready: asyncio.Event, other_ready: asyncio.Event) -> str:
        token = request_account_id.set(account_id)
        try:
            ready.set()
            await other_ready.wait()
            return await asyncio.to_thread(require_request_account_id)
        finally:
            request_account_id.reset(token)

    assert await asyncio.gather(
        call("first-account", first_ready, second_ready),
        call("second-account", second_ready, first_ready),
    ) == ["first-account", "second-account"]
    with pytest.raises(LookupError):
        request_account_id.get()


@pytest.mark.asyncio
async def test_missing_account_disables_scoped_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unexpected(*_args, **_kwargs):
        pytest.fail("An account-scoped operation ran without an account.")

    monkeypatch.setattr("master.tools.get_user_tool_configuration", unexpected)
    monkeypatch.setattr("gmaps.tools.PlacesGetRequest.call", unexpected)
    monkeypatch.setattr("layout.tools.execute_map_set_viewport_tool", unexpected)
    monkeypatch.setattr("web_search_tool.tools.get_user_api_key", unexpected)

    tools = await get_active_tools(None)
    assert [tool.name for tool in tools] == ["echo_destination"]
    for tool, payload in (
        (places_get, {"place_id": "example", "priority": 1}),
        (map_set_viewport, {"lat": 1, "lng": 2, "priority": 1}),
        (web_search, {"query": "example", "priority": 1}),
    ):
        with pytest.raises(RuntimeError, match="An account is required"):
            await tool.ainvoke(payload)
