"""Agent-facing web search and extraction tools with configurable provider fallback."""

from __future__ import annotations

import logging
from typing import Literal
from urllib.parse import urlsplit

import httpx
from langchain_core.tools import tool
from pydantic import Field, HttpUrl
from utils.request_context import require_request_account_id
from utils.settings import get_settings
from utils.tools import PrioritizedToolInput, capture_tool_io, serialize_tool_output
from utils.user_tool_config import get_user_api_key

from web_search_tool.cache import get_web_search_cache, web_search_cache_enabled
from web_search_tool.providers.base import SearchProvider
from web_search_tool.providers.exa import ExaProvider
from web_search_tool.providers.firecrawl import FirecrawlProvider
from web_search_tool.providers.tavily import TavilyProvider

logger = logging.getLogger(__name__)


class WebSearchInput(PrioritizedToolInput):
    query: str = Field(min_length=1, max_length=500, description="Web search query.")
    region: str = Field(
        default="us-en", max_length=10, description="Search region, e.g. us-en or sg-en."
    )
    timelimit: Literal["d", "w", "m", "y"] | None = Field(
        default=None, description="Optional result age filter: day, week, month, or year."
    )
    max_results: int = Field(
        default=5, ge=1, le=10, description="Maximum search results to return."
    )


class WebExtractInput(PrioritizedToolInput):
    url: HttpUrl = Field(description="Public page URL to fetch and extract as Markdown.")


_MAX_EXTRACT_CHARS = 20_000
_PROVIDER_CLASSES = {
    "tavily": TavilyProvider,
    "exa": ExaProvider,
    "firecrawl": FirecrawlProvider,
}


def _provider_order() -> list[str]:
    return [name for name in get_settings().web_search_providers if name in _PROVIDER_CLASSES]


async def _configured_providers() -> list[SearchProvider]:
    account_id = require_request_account_id()
    providers: list[SearchProvider] = []
    for name in _provider_order():
        api_key = await get_user_api_key(account_id, name)
        if api_key:
            providers.append(_PROVIDER_CLASSES[name](api_key))
    return providers


def _public_http_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def _cache_key(operation: str, value: dict[str, object]) -> tuple[object, ...]:
    return (operation, tuple(sorted(value.items())), tuple(_provider_order()))


@tool(args_schema=WebSearchInput)
@capture_tool_io
async def web_search(
    query: str,
    region: str = "us-en",
    timelimit: Literal["d", "w", "m", "y"] | None = None,
    max_results: int = 5,
) -> str:
    """Search the web with configured providers and return sourced results."""
    providers = await _configured_providers()
    if not providers:
        return "Web search is not configured: set at least one provider API key."

    cache = get_web_search_cache() if web_search_cache_enabled() else None
    cache_key = _cache_key(
        "search",
        {
            "query": query.strip(),
            "region": region,
            "timelimit": timelimit,
            "max_results": max_results,
        },
    )
    if cache is not None:
        cached = await cache.alookup(cache_key)
        if cached is not None:
            return serialize_tool_output(cached)

    failures: list[str] = []
    for provider in providers:
        try:
            results = await provider.search(query, max_results, region, timelimit)
            if results:
                response = {
                    "provider": provider.name,
                    "results": [item.as_dict() for item in results],
                }
                if cache is not None:
                    await cache.aupdate(cache_key, response)
                return serialize_tool_output(response)
            failures.append(f"{provider.name}: no results")
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            logger.warning("Web search provider %s failed: %s", provider.name, exc)
            failures.append(f"{provider.name}: request failed")

    return "Web search found no results from configured providers (" + "; ".join(failures) + ")."


@tool(args_schema=WebExtractInput)
@capture_tool_io
async def web_extract(url: str) -> str:
    """Fetch a public page and extract its readable content as Markdown."""
    url = str(url)
    if not _public_http_url(url):
        return "Web extraction requires a public HTTP or HTTPS URL."
    providers = await _configured_providers()
    if not providers:
        return "Web extraction is not configured: set at least one provider API key."

    cache = get_web_search_cache() if web_search_cache_enabled() else None
    cache_key = _cache_key("extract", {"url": url})
    if cache is not None:
        cached = await cache.alookup(cache_key)
        if cached is not None:
            return serialize_tool_output(cached)

    for provider in providers:
        try:
            content = await provider.extract(url)
            response = {
                "provider": provider.name,
                "url": url,
                "content": content[:_MAX_EXTRACT_CHARS],
            }
            if cache is not None:
                await cache.aupdate(cache_key, response)
            return serialize_tool_output(response)
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            logger.warning("Web extraction provider %s failed: %s", provider.name, exc)

    return "Web content extraction failed across the configured providers."
