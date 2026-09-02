"""Exa contents — reads a URL's text from Exa's index.

The legitimate way to read LinkedIn/X experience: httpx hits a login wall, but
Exa's index returns the profile as clean structured text (probe #1, confirmed).
"""
from __future__ import annotations

import os

from ..deps import Tool, ToolUnavailable, traced


class Exa(Tool):
    name = "exa.contents"

    @traced("exa.contents", provider="exa", timeout=30)
    async def contents(self, url: str) -> dict:
        key = os.getenv("EXA_API_KEY")
        if not key:
            raise ToolUnavailable("EXA_API_KEY")
        r = await self.deps.http.post(
            "https://api.exa.ai/contents",
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json={"ids": [url], "text": True},
        )
        r.raise_for_status()
        res = r.json().get("results", [])
        if not res or not res[0].get("text"):
            raise ToolUnavailable(f"exa: no contents for {url}")
        return {"url": url, "html": "", "text": res[0]["text"]}
