"""Firecrawl Search and Scrape API adapter."""

from __future__ import annotations

import httpx
from utils.settings import get_settings

from web_search_tool.providers.base import SearchResult, results_from_items


class FirecrawlProvider:
    name = "firecrawl"
    base_url = "https://api.firecrawl.dev/v2"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @classmethod
    def from_environment(cls) -> FirecrawlProvider | None:
        key = get_settings().firecrawl_api_key.strip()
        return cls(key) if key else None

    async def _post(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=40, trust_env=False) as client:
            response = await client.post(
                f"{self.base_url}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise TypeError("Firecrawl returned an unexpected response.")
        return data

    async def search(
        self, query: str, max_results: int, region: str, timelimit: str | None
    ) -> list[SearchResult]:
        del region, timelimit  # Firecrawl Search does not expose a stable common equivalent.
        data = await self._post(
            "/search", {"query": query, "limit": max_results, "sources": ["web"]}
        )
        payload = data.get("data")
        items = payload.get("web") if isinstance(payload, dict) else payload
        return results_from_items(items, url_key="url", snippet_keys=("description", "markdown"))

    async def extract(self, url: str) -> str:
        data = await self._post("/scrape", {"url": url, "formats": ["markdown"]})
        payload = data.get("data")
        if isinstance(payload, dict) and isinstance(payload.get("markdown"), str):
            return payload["markdown"]
        raise ValueError("Firecrawl returned no extracted content.")
