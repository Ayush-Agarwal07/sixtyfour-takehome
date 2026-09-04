"""Serper web search. Cached 24h per (query, num). One HTTP call per query,
issued concurrently by callers under the provider semaphore."""
from __future__ import annotations

import os

from ..constants import CACHE_TTL_S
from ..deps import Tool, ToolUnavailable, traced


class Serper(Tool):
    @traced("serper.search", provider="serper", timeout=15)
    async def search(self, q: str, num: int = 10) -> list[dict]:
        key = os.getenv("SERPER_API_KEY")
        if not key:
            raise ToolUnavailable("SERPER_API_KEY")
        ck = f"{q}\x00{num}"

        async def _fetch() -> list[dict]:
            r = await self.deps.http.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
                json={"q": q, "num": num},
            )
            r.raise_for_status()
            organic = r.json().get("organic", [])
            return [{"url": o["link"], "title": o.get("title", ""), "snippet": o.get("snippet", ""), "query": q}
                    for o in organic if o.get("link")]

        return await self.cached("search", ck, CACHE_TTL_S["search"], _fetch)
