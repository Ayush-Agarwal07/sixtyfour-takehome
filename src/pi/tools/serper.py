"""Serper web search. One batched POST per call."""
from __future__ import annotations

import os

from ..deps import Tool, ToolUnavailable, traced


class Serper(Tool):
    name = "serper.search"

    @traced("serper.search", provider="serper", timeout=15)
    async def search(self, q: str, num: int = 10) -> list[dict]:
        key = os.getenv("SERPER_API_KEY")
        if not key:
            raise ToolUnavailable("SERPER_API_KEY")
        r = await self.deps.http.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": q, "num": num},
        )
        r.raise_for_status()
        organic = r.json().get("organic", [])
        return [{"url": o["link"], "title": o.get("title", ""), "snippet": o.get("snippet", "")}
                for o in organic if o.get("link")]
