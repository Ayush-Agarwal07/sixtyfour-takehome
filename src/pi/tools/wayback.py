"""Wayback Machine — recover an archived snapshot of a URL (e.g. a team page
after someone left). No LLM, no auth."""
from __future__ import annotations

import trafilatura

from ..deps import Tool, traced


class Wayback(Tool):
    @traced("wayback.snapshot", provider="fetch", timeout=15)
    async def snapshot(self, url: str, year: int | None = None) -> dict | None:
        ck = f"{url}|{year}"

        async def _fetch():
            params = {"url": url}
            if year is not None:
                params["timestamp"] = f"{year}0101"
            r = await self.deps.http.get("https://archive.org/wayback/available", params=params)
            r.raise_for_status()
            closest = (r.json().get("archived_snapshots") or {}).get("closest")
            if not closest or not closest.get("available"):
                return None
            r2 = await self.deps.http.get(closest["url"], follow_redirects=True)
            r2.raise_for_status()
            html = r2.text
            text = trafilatura.extract(html) or ""
            return {
                "url": url,
                "snapshot_url": closest["url"],
                "timestamp": closest["timestamp"][:8],
                "html": html,
                "text": text,
                "via": "wayback",
            }

        return await self.cached("wayback", ck, None, _fetch, cache_none=False)
