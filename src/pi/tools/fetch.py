"""Fetch a page → readable text. httpx + trafilatura.

ponytail: no Firecrawl fallback in the slice (add in Stage 2 when a JS page needs
it). Unfetchable hosts (LinkedIn/X/…) are skipped — SERP snippets already cover
them, and a fetch just wastes a round trip on a login wall.
"""
from __future__ import annotations

from urllib.parse import urlsplit

import trafilatura

from ..constants import UNFETCHABLE_HOSTS
from ..deps import Tool, ToolUnavailable, traced


class Fetch(Tool):
    name = "fetch"

    @traced("fetch", provider="fetch", timeout=8)
    async def get(self, url: str) -> dict:
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        if any(host == h or host.endswith("." + h) for h in UNFETCHABLE_HOSTS):
            raise ToolUnavailable(f"unfetchable host: {host}")
        r = await self.deps.http.get(url, follow_redirects=True)
        r.raise_for_status()
        html = r.text
        text = trafilatura.extract(html) or ""
        return {"url": url, "html": html, "text": text}
