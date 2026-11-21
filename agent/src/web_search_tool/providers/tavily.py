"""Tavily Search and Extract API adapter."""

from __future__ import annotations

import httpx
from utils.settings import get_settings

from web_search_tool.providers.base import SearchResult, results_from_items


class TavilyProvider:
    name = "tavily"
    base_url = "https://api.tavily.com"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @classmethod
    def from_environment(cls) -> TavilyProvider | None:
        key = get_settings().tavily_api_key.strip()
        return cls(key) if key else None

    async def _post(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
            response = await client.post(
                f"{self.base_url}{path}",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise TypeError("Tavily returned an unexpected response.")
        return data

    async def search(
        self, query: str, max_results: int, region: str, timelimit: str | None
    ) -> list[SearchResult]:
        payload = {
            "query": query,
            "topic": "general",
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        country_codes = {
            "au": "australia",
            "ca": "canada",
            "cn": "china",
            "de": "germany",
            "fr": "france",
            "gb": "united kingdom",
            "jp": "japan",
            "kr": "south korea",
            "sg": "singapore",
            "us": "united states",
        }
        country_code = region.split("-", maxsplit=1)[0].lower()
        if country := country_codes.get(country_code):
            payload["country"] = country
        if timelimit:
            payload["time_range"] = timelimit
        data = await self._post("/search", payload)
        return results_from_items(data.get("results"), url_key="url", snippet_keys=("content",))

    async def extract(self, url: str) -> str:
        data = await self._post(
            "/extract",
            {"urls": [url], "extract_depth": "basic", "format": "markdown"},
        )
        results = data.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            content = results[0].get("raw_content") or results[0].get("content")
            if isinstance(content, str):
                return content
        raise ValueError("Tavily returned no extracted content.")
