"""Gravatar profile lookup — maps an email's md5 hash to a public profile, if any."""
from __future__ import annotations

import hashlib

from ..deps import Tool, traced

_TTL = 7 * 86400


class Gravatar(Tool):
    @traced("gravatar.profile", provider="fetch", timeout=10)
    async def profile(self, email: str) -> dict | None:
        h = hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()

        async def _fetch():
            r = await self.deps.http.get(
                f"https://gravatar.com/{h}.json",
                headers={"User-Agent": "people-research-agent/0.1"},
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            entries = r.json().get("entry") or []
            if not entries:
                return None
            e = entries[0]
            return {
                "display_name": e.get("displayName", ""),
                "about": e.get("aboutMe", ""),
                "urls": [u["value"] for u in e.get("urls", [])],
                "accounts": [
                    {"url": a.get("url", ""), "service": a.get("shortname") or a.get("service") or ""}
                    for a in e.get("accounts", [])
                ],
            }

        return await self.cached("gravatar", h, _TTL, _fetch)
