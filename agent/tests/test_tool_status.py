from __future__ import annotations

import api.routes.tool_status as status_module
import pytest
from api.app import app
from api.routes.tool_status import (
    CredentialUpdateRequest,
    ToolActiveRequest,
    ToolStatus,
    ToolStatusResponse,
    build_tool_status,
    update_tool_active_state,
    update_tool_credentials,
)
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from utils.settings import AppSettings


async def _saved_providers(_uid: str) -> set[str]:
    return set()


async def _active_overrides(_uid: str) -> dict[str, bool]:
    return {}


def _status_map(response):
    return {tool.name: tool for tool in response.tools}


def _use_empty_user_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("master.tools.get_saved_providers", _saved_providers)
    monkeypatch.setattr("master.tools.get_tool_active_overrides", _active_overrides)


@pytest.mark.asyncio
async def test_tool_status_lists_all_tools_and_reports_missing_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_empty_user_config(monkeypatch)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("EXA_API_KEY", "")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "")
    settings = AppSettings(_env_file=None)

    response = await build_tool_status("test-user", settings)
    statuses = _status_map(response)

    assert response.api_server == "ready"
    assert set(statuses) == {
        "places_text_search",
        "places_search_nearby",
        "places_get",
        "routes_compute",
        "routes_compute_matrix",
        "map_set_viewport",
        "echo_destination",
        "web_search",
        "web_extract",
    }
    assert all(
        statuses[name].status == "needs_configuration" and statuses[name].active is False
        for name in (
            "places_text_search",
            "places_search_nearby",
            "places_get",
            "routes_compute",
            "routes_compute_matrix",
            "web_search",
            "web_extract",
        )
    )
    assert statuses["places_text_search"].description
    assert statuses["places_text_search"].credentials[0].provider == "google_maps"
    assert statuses["map_set_viewport"].status == "ready"
    assert statuses["map_set_viewport"].active is True


@pytest.mark.asyncio
async def test_environment_keys_make_tools_ready_and_active_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_empty_user_config(monkeypatch)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "maps-key")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")
    monkeypatch.setenv("WEB_SEARCH_PROVIDER_ORDER", "tavily,exa,firecrawl")
    settings = AppSettings(_env_file=None)

    statuses = _status_map(await build_tool_status("test-user", settings))

    assert statuses["places_text_search"].status == "ready"
    assert statuses["places_text_search"].active is True
    assert statuses["routes_compute_matrix"].status == "ready"
    assert statuses["web_search"].status == "ready"
    assert statuses["web_extract"].status == "ready"


@pytest.mark.asyncio
async def test_user_saved_key_makes_tool_ready_but_not_active_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def saved(_uid: str) -> set[str]:
        return {"google_maps"}

    monkeypatch.setattr("master.tools.get_saved_providers", saved)
    monkeypatch.setattr("master.tools.get_tool_active_overrides", _active_overrides)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "")
    settings = AppSettings(_env_file=None)

    maps_tool = _status_map(await build_tool_status("test-user", settings))["places_get"]

    assert maps_tool.status == "ready"
    assert maps_tool.active is False
    assert maps_tool.credentials[0].configured is True


@pytest.mark.asyncio
async def test_provider_keys_outside_configured_order_do_not_make_web_tools_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_empty_user_config(monkeypatch)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "firecrawl-key")
    monkeypatch.setenv("WEB_SEARCH_PROVIDER_ORDER", "tavily,exa")
    settings = AppSettings(_env_file=None)

    statuses = _status_map(await build_tool_status("test-user", settings))

    assert statuses["web_search"].status == "needs_configuration"
    assert statuses["web_extract"].status == "needs_configuration"


@pytest.mark.asyncio
async def test_cannot_enable_tool_before_credentials_are_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def not_ready(_uid: str) -> ToolStatusResponse:
        return ToolStatusResponse(
            tools=[
                ToolStatus(
                    name="places_get",
                    description="Fetch place details.",
                    active=False,
                    status="needs_configuration",
                )
            ]
        )

    monkeypatch.setattr(status_module, "build_tool_status", not_ready)

    with pytest.raises(HTTPException) as error:
        await update_tool_active_state("places_get", ToolActiveRequest(active=True), "test-user")

    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_credential_save_replaces_per_provider_without_returning_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[tuple[str, str, str]] = []

    async def save(account_id: str, credentials: dict[str, str]) -> None:
        saved.extend((account_id, provider, key) for provider, key in credentials.items())

    monkeypatch.setattr(status_module, "save_provider_credentials", save)
    request = CredentialUpdateRequest(credentials={"tavily": SecretStr("new-secret")})

    response = await update_tool_credentials(request, "test-user")

    assert saved == [("test-user", "tavily", "new-secret")]
    assert response.updated == ["tavily"]
    assert "new-secret" not in response.model_dump_json()


@pytest.mark.asyncio
async def test_tool_status_endpoint_needs_no_external_service_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IDENTITY_BACKEND", "local")
    _use_empty_user_config(monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/v1/tools/status")

    assert response.status_code == 200
    assert response.json()["api_server"] == "ready"
    assert response.json()["tools"]
