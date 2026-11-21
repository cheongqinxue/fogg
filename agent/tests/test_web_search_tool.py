"""Offline contracts for the web-search provider adapters and agent tools."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError
from web_search_tool.tools import web_extract, web_search


@pytest.fixture(autouse=True)
def disable_redis_cache_by_default(monkeypatch):
    """Provider adapter unit tests must not depend on a running Redis service."""
    monkeypatch.setenv("WEB_SEARCH_CACHE_ENABLED", "false")


def _mock_async_client(monkeypatch, handler):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "web_search_tool.providers.tavily.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(
        "web_search_tool.providers.exa.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(
        "web_search_tool.providers.firecrawl.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.asyncio
async def test_search_falls_back_to_next_provider_and_normalizes_results(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDER_ORDER", "tavily,exa,firecrawl")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-test-key")
    monkeypatch.setenv("EXA_API_KEY", "exa-test-key")
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.url.path, request.headers))
        if request.url.host == "api.tavily.com":
            assert request.headers["authorization"] == "Bearer tavily-test-key"
            payload = json.loads(request.content)
            assert payload["country"] == "singapore"
            assert "api_key" not in payload
            return httpx.Response(503, json={"message": "temporarily unavailable"})
        return httpx.Response(
            200,
            json={
                "results": [{"title": "Cafe", "url": "https://example.test", "text": "Local pick"}]
            },
        )

    _mock_async_client(monkeypatch, handler)
    output = await web_search.ainvoke(
        {"query": "supper Busan", "max_results": 3, "region": "sg-en", "priority": 1}
    )
    data = json.loads(output)

    assert data == {
        "provider": "exa",
        "results": [{"title": "Cafe", "url": "https://example.test", "snippet": "Local pick"}],
    }
    assert [call[0] for call in seen] == ["api.tavily.com", "api.exa.ai"]
    assert seen[0][1] == "/search"
    assert seen[1][1] == "/search"
    assert seen[1][2]["x-api-key"] == "exa-test-key"


@pytest.mark.asyncio
async def test_search_stops_after_first_provider_with_results(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDER_ORDER", "tavily,exa")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-test-key")
    monkeypatch.setenv("EXA_API_KEY", "exa-test-key")
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(
            200,
            json={"results": [{"title": "Result", "url": "https://example.test", "content": "ok"}]},
        )

    _mock_async_client(monkeypatch, handler)
    output = await web_search.ainvoke(
        {"query": "query", "region": "sg-en", "timelimit": "w", "priority": 1}
    )
    assert json.loads(output)["provider"] == "tavily"
    assert seen == ["api.tavily.com"]


@pytest.mark.asyncio
async def test_search_without_keys_fails_closed_without_network(monkeypatch):
    for key in ("TAVILY_API_KEY", "EXA_API_KEY", "FIRECRAWL_API_KEY"):
        # Settings also load .env; whitespace overrides any local developer key.
        monkeypatch.setenv(key, " ")
    output = await web_search.ainvoke({"query": "Busan", "priority": 1})
    assert "not configured" in output


@pytest.mark.asyncio
async def test_search_uses_cached_result_without_calling_provider(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_CACHE_ENABLED", "true")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-test-key")

    class CacheStub:
        async def alookup(self, key):
            assert key[0] == "search"
            return {
                "provider": "tavily",
                "results": [{"title": "Cached", "url": "https://example.test", "snippet": "saved"}],
            }

    monkeypatch.setattr("web_search_tool.tools.get_web_search_cache", CacheStub)

    async def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected provider call: {request.url}")

    _mock_async_client(monkeypatch, no_network)
    output = await web_search.ainvoke({"query": "same query", "priority": 1})
    assert json.loads(output)["results"][0]["title"] == "Cached"


@pytest.mark.asyncio
async def test_firecrawl_extract_caps_content_and_rejects_non_http_url(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDER_ORDER", "firecrawl")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "firecrawl-test-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.firecrawl.dev/v2/scrape"
        assert request.headers["authorization"] == "Bearer firecrawl-test-key"
        return httpx.Response(200, json={"success": True, "data": {"markdown": "x" * 21_000}})

    _mock_async_client(monkeypatch, handler)
    output = await web_extract.ainvoke({"url": "https://example.test", "priority": 1})
    assert len(json.loads(output)["content"]) == 20_000
    with pytest.raises(ValidationError):
        await web_extract.ainvoke({"url": "file:///etc/passwd", "priority": 1})


def test_search_schema_keeps_provider_selection_internal_and_bounds_results():
    assert "provider" not in web_search.args_schema.model_fields
    with pytest.raises(ValidationError):
        web_search.args_schema.model_validate({"query": "x", "max_results": 100, "priority": 1})
