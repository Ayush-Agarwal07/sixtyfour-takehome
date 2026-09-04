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
_ORG_SUFFIXES = ("ai", "hq", "app", "labs", "io", "co", "inc", "tech")


def _slug(s: str) -> str:
    return _NON_ALNUM.sub("", s.lower())


class Company(Tool):
    @traced("company.resolve", provider="serper", timeout=15)
    async def resolve(self, name: str) -> dict | None:
        key = os.getenv("SERPER_API_KEY")
        if not key:
            raise ToolUnavailable("SERPER_API_KEY")
        ck = name.strip().lower()

        async def _fetch() -> dict:
            r = await self.deps.http.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
                json={"q": f"{name} official website", "num": 10},
            )
            r.raise_for_status()
            organic = r.json().get("organic", [])

            target = _slug(name)
            name_l = name.strip().lower()
            entries: list[tuple[str, str]] = []  # (root, "title snippet" lowercased), one per unique root
            seen: set[str] = set()
            for o in organic:
                link = o.get("link")
                if not link:
                    continue
                if classify(link) in ("aggregator", "social", "professional_network", "press", "code_host"):
                    continue
                root = registrable_domain(urlparse(link).netloc)
                if not root or root in seen:
                    continue
                seen.add(root)
                entries.append((root, f"{o.get('title', '')} {o.get('snippet', '')}".lower()))

            roots = [r for r, _ in entries]
            result = None
            if entries:
                chosen = next((r for r, _ in entries if _slug(r.rsplit(".", 1)[0]) == target), None)
                if chosen is None:
                    for r, _ in entries:
                        label = _slug(r.rsplit(".", 1)[0])
                        if any(label == target + s or target == label + s for s in _ORG_SUFFIXES):
                            chosen = r
                            break
                if chosen is None:
                    for r, blob in entries:
                        label = _slug(r.rsplit(".", 1)[0])
                        if label and target in label and name_l in blob:
                            chosen = r
                            break
                if chosen is None:
                    chosen = roots[0]
                result = {"name": name, "domain": chosen, "aliases": [x for x in roots if x != chosen]}
            return result or {}

        result = await self.cached("company", ck, CACHE_TTL_S["search"], _fetch)
        return result or None
