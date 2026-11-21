"""Adapter from the generic async Redis cache base to LangChain's cache API."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.caches import BaseCache
from langchain_core.outputs import Generation

from utils.cache.redis_cache import AsyncRedisCache


class LangChainRedisCacheAdapter(BaseCache):
    """Expose a generic Redis cache through LangChain's async cache interface.

    ``cache`` must be a cache whose key accepts a ``(prompt, llm_string)`` tuple
    and whose value accepts/returns serialized Generation dictionaries.
    """

    def __init__(self, cache: AsyncRedisCache[list[Generation]]) -> None:
        self._cache = cache

    @staticmethod
    def _key(prompt: str, llm_string: str) -> tuple[str, str]:
        return prompt, llm_string

    def lookup(self, prompt: str, llm_string: str) -> list[Generation] | None:
        raise NotImplementedError("Use alookup with the async Redis cache adapter")

    def update(self, prompt: str, llm_string: str, generations: list[Generation]) -> None:
        raise NotImplementedError("Use aupdate with the async Redis cache adapter")

    def clear(self, **kwargs: Any) -> None:
        raise NotImplementedError("Use aclear with the async Redis cache adapter")

    async def alookup(self, prompt: str, llm_string: str) -> list[Generation] | None:
        return await self._cache.alookup(self._key(prompt, llm_string))

    async def aupdate(self, prompt: str, llm_string: str, generations: list[Generation]) -> None:
        await self._cache.aupdate(self._key(prompt, llm_string), generations)

    async def aclear(self, **kwargs: Any) -> None:
        await self._cache.aclear()


class LangChainGenerationCache(AsyncRedisCache[list[Generation]]):
    """Concrete JSON serialization for LangChain generation cache values."""

    def make_key(self, key: Any) -> str:
        prompt, llm_string = key
        identity = json.dumps([prompt, llm_string], separators=(",", ":"))
        digest = hashlib.sha256(identity.encode()).hexdigest()
        return f"{self.prefix}:{digest}"

    def serialize(self, value: list[Generation]) -> str:
        return json.dumps([item.model_dump() for item in value], separators=(",", ":"))

    def deserialize(self, value: str | bytes) -> list[Generation]:
        return [Generation(**item) for item in json.loads(value)]
