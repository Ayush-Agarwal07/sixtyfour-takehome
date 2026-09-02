"""Exa contents — reads a URL's text from Exa's index. The legitimate way to read
LinkedIn/X experience text (build-time check #1: confirmed). Cached by URL."""
from __future__ import annotations

import os

from ..deps import Tool, ToolUnavailable, traced
from ..sources import classify


class Exa(Tool):
    name = "exa.contents"

    @traced("exa.contents", provider="exa", timeout=30)
    async def contents(self, url: str) -> dict:
        key = os.getenv("EXA_API_KEY")
        if not key:
            raise ToolUnavailable("EXA_API_KEY")
        cache = self.deps.cache
        if cache is not None:
            hit = cache.get_http("exa:" + url)
            if hit is not None:
                self._last_cache_hit = True
                return hit
        r = await self.deps.http.post(
            "https://api.exa.ai/contents",
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json={"ids": [url], "text": True},
        )
        r.raise_for_status()
        res = r.json().get("results", [])
        if not res or not res[0].get("text"):
            raise ToolUnavailable(f"exa: no contents for {url}")
        out = {"url": url, "html": "", "text": res[0]["text"], "via": "exa"}
        if cache is not None:
            cache.set_http("exa:" + url, out, classify(url))
        return out
