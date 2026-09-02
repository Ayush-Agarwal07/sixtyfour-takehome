"""Fetch a page → readable text + html. httpx + trafilatura. Cached by normalized
URL with a TTL by source class. Unfetchable hosts raise ToolUnavailable (use Exa)."""
from __future__ import annotations

import trafilatura

from ..deps import Tool, ToolUnavailable, traced
from ..sources import classify, is_unfetchable


class Fetch(Tool):
    name = "fetch"

    @traced("fetch", provider="fetch", timeout=10)
    async def get(self, url: str) -> dict:
        if is_unfetchable(url):
            raise ToolUnavailable(f"unfetchable host: {url}")
        cache = self.deps.cache
        if cache is not None:
            hit = cache.get_http(url)
            if hit is not None:
                self._last_cache_hit = True
                return hit
        r = await self.deps.http.get(url, follow_redirects=True)
        r.raise_for_status()
        html = r.text
        text = trafilatura.extract(html) or ""
        out = {"url": url, "final_url": str(r.url), "html": html, "text": text, "via": "httpx"}
        if cache is not None:
            cache.set_http(url, out, classify(url))
        return out
