"""Company domain resolution — one Serper search, pick the likely official domain.
Cached. Returns {name, domain, aliases} or None."""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

from ..constants import CACHE_TTL_S
from ..deps import Tool, ToolUnavailable, traced
from ..sources import classify, registrable_domain

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _NON_ALNUM.sub("", s.lower())


class Company(Tool):
    name = "company.resolve"

    @traced("company.resolve", provider="serper", timeout=15)
    async def resolve(self, name: str) -> dict | None:
        key = os.getenv("SERPER_API_KEY")
        if not key:
            raise ToolUnavailable("SERPER_API_KEY")
        cache = self.deps.cache
        ck = name.strip().lower()
        if cache is not None:
            hit = cache.get("company", ck)
            if hit is not None:
                self._last_cache_hit = True
                return hit or None

        r = await self.deps.http.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f"{name} official website", "num": 10},
        )
        r.raise_for_status()
        organic = r.json().get("organic", [])

        target = _slug(name)
        roots: list[str] = []
        for o in organic:
            link = o.get("link")
            if not link:
                continue
            if classify(link) in ("aggregator", "social", "professional_network", "press", "code_host"):
                continue
            root = registrable_domain(urlparse(link).netloc)
            if root and root not in roots:
                roots.append(root)

        result = None
        if roots:
            for root in roots:
                label = _slug(root.rsplit(".", 1)[0])
                if label and (label in target or target in label):
                    result = {"name": name, "domain": root, "aliases": [x for x in roots if x != root]}
                    break
            if result is None:
                result = {"name": name, "domain": roots[0], "aliases": roots[1:]}
        if cache is not None:
            cache.set("company", ck, result or {}, CACHE_TTL_S["search"])
        return result
