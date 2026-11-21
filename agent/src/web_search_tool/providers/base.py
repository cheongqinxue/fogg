"""Shared provider contracts and response normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str

    def as_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class SearchProvider(Protocol):
    name: str

    async def search(
        self, query: str, max_results: int, region: str, timelimit: str | None
    ) -> list[SearchResult]: ...

    async def extract(self, url: str) -> str: ...


def results_from_items(
    items: Any, *, url_key: str, snippet_keys: tuple[str, ...]
) -> list[SearchResult]:
    if not isinstance(items, list):
        return []
    results: list[SearchResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get(url_key)
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        snippet = next(
            (item.get(key) for key in snippet_keys if isinstance(item.get(key), str)), ""
        )
        if not snippet:
            snippet = next(
                (
                    " ".join(part for part in item.get(key, []) if isinstance(part, str))
                    for key in snippet_keys
                    if isinstance(item.get(key), list)
                ),
                "",
            )
        results.append(
            SearchResult(
                title=item.get("title") if isinstance(item.get("title"), str) else "",
                url=url,
                snippet=snippet,
            )
        )
    return results
