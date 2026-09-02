"""Company domain resolution — one Serper search, pick the likely official domain.

ponytail: no homepage fetch, no LinkedIn slug/headcount lookup (stage-2-resolve.md
defers those and Regime′ says headcount never gates anyway). One search + a
slug-match heuristic over the organic results is enough to tell NAME_STRONG from
NAME_WEAK.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

from ..deps import Tool, ToolUnavailable, traced

# ponytail: small fixed aggregator list per the task spec, not a general public-
# suffix/aggregator database.
_AGGREGATORS = {
    "linkedin.com", "crunchbase.com", "wikipedia.org", "facebook.com",
    "twitter.com", "x.com", "bloomberg.com",
}
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _NON_ALNUM.sub("", s.lower())


def _registrable_root(host: str) -> str:
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else host


class Company(Tool):
    name = "company.resolve"

    @traced("company.resolve", provider="serper", timeout=15)
    async def resolve(self, name: str) -> dict | None:
        key = os.getenv("SERPER_API_KEY")
        if not key:
            raise ToolUnavailable("SERPER_API_KEY")

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
            root = _registrable_root(urlparse(link).netloc)
            if root in _AGGREGATORS or root in roots:
                continue
            roots.append(root)

        if not roots:
            return None

        # Prefer a root whose domain label matches a slug of the company name;
        # fall back to the first (highest-ranked) non-aggregator result.
        for root in roots:
            label = _slug(root.rsplit(".", 1)[0])
            if label and (label in target or target in label):
                return {"name": name, "domain": root, "aliases": [x for x in roots if x != root]}

        return {"name": name, "domain": roots[0], "aliases": roots[1:]}
