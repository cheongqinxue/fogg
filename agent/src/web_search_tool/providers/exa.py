"""Exa Search and Contents API adapter."""

from __future__ import annotations

import httpx
from utils.settings import get_settings

from web_search_tool.providers.base import SearchResult, results_from_items


class ExaProvider:
    name = "exa"
    base_url = "https://api.exa.ai"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @classmethod
    def from_environment(cls) -> ExaProvider | None:
        key = get_settings().exa_api_key.strip()
        return cls(key) if key else None

    async def _post(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
            response = await client.post(
                f"{self.base_url}{path}",
                json=payload,
                headers={"x-api-key": self.api_key, "Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise TypeError("Exa returned an unexpected response.")
        return data

    async def search(
        self, query: str, max_results: int, region: str, timelimit: str | None
    ) -> list[SearchResult]:
        del region, timelimit  # Exa does not expose equivalent parameters on Search.
        data = await self._post(
            "/search", {"query": query, "type": "auto", "numResults": max_results}
        )
        return results_from_items(
            data.get("results"), url_key="url", snippet_keys=("text", "highlights")
        )

    async def extract(self, url: str) -> str:
        data = await self._post("/contents", {"urls": [url], "text": {"maxCharacters": 20000}})
        results = data.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            content = results[0].get("text")
            if isinstance(content, str):
                return content
        raise ValueError("Exa returned no extracted content.")
