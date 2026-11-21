"""Assemble functionality module tools into the master agent toolbox."""

from gmaps.tools import (
    places_get,
    places_search_nearby,
    places_text_search,
    routes_compute,
    routes_compute_matrix,
)
from langchain_core.tools import tool
from layout.tools import map_set_viewport
from pydantic import Field
from utils.settings import AppSettings, get_settings
from utils.tools import PrioritizedToolInput, capture_tool_io
from utils.user_tool_config import get_saved_providers, get_tool_active_overrides
from web_search_tool.tools import web_extract, web_search

TOOL_CREDENTIAL_PROVIDERS = {
    name: ("google_maps",)
    for name in (
        "places_text_search",
        "places_search_nearby",
        "places_get",
        "routes_compute",
        "routes_compute_matrix",
    )
} | {name: ("tavily", "exa", "firecrawl") for name in ("web_search", "web_extract")}

LIMITED_CONCURRENCY_TOOL_NAMES = frozenset(
    {"places_text_search", "places_search_nearby", "web_search"}
)

_WEB_PROVIDER_SETTINGS = {
    "tavily": "tavily_api_key",
    "exa": "exa_api_key",
    "firecrawl": "firecrawl_api_key",
}


class EchoDestinationInput(PrioritizedToolInput):
    name: str = Field(description="Destination label used only to verify the tool loop is working.")


@tool(args_schema=EchoDestinationInput)
@capture_tool_io
def echo_destination(name: str) -> str:
    """Connectivity test only; this does not search for or save a destination."""
    return f"Noted destination: {name.strip()}"


def get_tools():
    """Return tools contributed by the enabled functionality modules."""
    return [
        places_text_search,
        places_search_nearby,
        places_get,
        routes_compute,
        routes_compute_matrix,
        map_set_viewport,
        echo_destination,
        web_search,
        web_extract,
    ]


def _environment_providers(settings: AppSettings) -> set[str]:
    return {
        provider
        for provider in settings.web_search_providers
        if provider in _WEB_PROVIDER_SETTINGS
        and getattr(settings, _WEB_PROVIDER_SETTINGS[provider]).strip()
    } | ({"google_maps"} if settings.google_maps_api_key.strip() else set())


async def get_user_tool_configuration(account_id: str, *, settings: AppSettings | None = None):
    """Return per-user readiness and activation for every registered tool."""
    settings = settings or get_settings()
    tools = get_tools()
    saved = await get_saved_providers(account_id)
    overrides = await get_tool_active_overrides(account_id)
    environment = _environment_providers(settings)
    enabled_providers = set(settings.web_search_providers) | {"google_maps"}
    configured = (environment | saved) & enabled_providers

    result = []
    for registered_tool in tools:
        providers = TOOL_CREDENTIAL_PROVIDERS.get(registered_tool.name, ())
        ready = not providers or bool(configured.intersection(providers))
        default_active = not providers or bool(environment.intersection(providers))
        active = overrides.get(registered_tool.name, default_active) and ready
        result.append(
            {
                "tool": registered_tool,
                "name": registered_tool.name,
                "description": registered_tool.description or "",
                "providers": providers,
                "configured_providers": configured.intersection(providers),
                "ready": ready,
                "active": active,
            }
        )
    return result


async def get_active_tools(account_id: str | None, *, tools=None):
    """Select tools for an account or restrict a standalone graph to unscoped tools."""
    source = get_tools() if tools is None else tools
    if account_id is None:
        account_tools = {*TOOL_CREDENTIAL_PROVIDERS, map_set_viewport.name}
        return [tool for tool in source if tool.name not in account_tools]

    configurations = await get_user_tool_configuration(account_id)
    known_names = {item["name"] for item in configurations}
    active_names = {item["name"] for item in configurations if item["active"]}
    return [tool for tool in source if tool.name not in known_names or tool.name in active_names]
