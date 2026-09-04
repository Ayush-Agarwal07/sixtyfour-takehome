"""Username probe — check whether a handle exists across OSINT-relevant platforms."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from urllib.parse import urlsplit

from ..constants import PROBE_PLATFORMS, PROBE_TIMEOUT_S
from ..deps import Tool, traced

_HEADERS = {
    "User-Agent": "people-research-agent/0.1 (osint research)",
    "Accept": "application/json, text/html",
}
_HUMAN_URL = {
    "github": "https://github.com/{h}",
    "gitlab": "https://gitlab.com/{h}",
    "reddit": "https://www.reddit.com/user/{h}",
    "hackernews": "https://news.ycombinator.com/user?id={h}",
    "keybase": "https://keybase.io/{h}",
    "devto": "https://dev.to/{h}",
}
_TTL = 7 * 86400


def _epoch_to_date(ts: object) -> str | None:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).date().isoformat()  # type: ignore[arg-type]
    except (TypeError, ValueError, OSError):
        return None


class Usernames(Tool):
    @traced("usernames.probe", provider="fetch", timeout=25)
    async def probe(self, handle: str) -> list[dict]:
        key = handle.lower()

        async def _fetch() -> list[dict]:
            results = await asyncio.gather(
                *(self._probe_one(platform, tmpl, rule, handle)
                  for platform, (tmpl, rule) in PROBE_PLATFORMS.items()),
                return_exceptions=True,
            )
            return [r for r in results if isinstance(r, dict)]

        return await self.cached("usernames", key, _TTL, _fetch)

    async def _probe_one(self, platform: str, tmpl: str, rule: str, handle: str) -> dict | None:
        try:
            return await asyncio.wait_for(self._check(platform, tmpl, rule, handle), PROBE_TIMEOUT_S)
        except Exception:  # noqa: BLE001 — any failure means "unknown", not a hit
            return None

    async def _check(self, platform: str, tmpl: str, rule: str, handle: str) -> dict | None:
        url = tmpl.format(h=handle)
        r = await self.deps.http.get(url, headers=_HEADERS, follow_redirects=True)
        if r.status_code in (403, 429) or r.status_code >= 500:
            return None

        created: str | None = None
        body: object | None = None   # the already-fetched JSON, for platforms whose hit is data not a page (fix-round F3)
        if rule == "404":
            if r.status_code != 200:
                return None
            expected_path = urlsplit(url).path.lower()
            final_path = urlsplit(str(r.url)).path.lower()
            if final_path != expected_path:
                return None
            if platform == "github":
                data = r.json()
                body = data
                created = (data.get("created_at") or "")[:10] or None
            elif platform == "devto":
                created = r.json().get("joined_at")
        elif rule == "json_list":
            if r.status_code != 200:
                return None
            data = r.json()
            if not isinstance(data, list) or not data:
                return None
        elif rule == "json_nonnull":
            if r.status_code != 200:
                return None
            data = r.json()
            if not data:
                return None
            if platform == "hackernews" and isinstance(data, dict):
                body = data
                created = _epoch_to_date(data.get("created"))
        elif rule == "reddit":
            if r.status_code != 200:
                return None
            data = r.json() or {}
            info = data.get("data") or {}
            if not info.get("name"):
                return None
            body = data
            created = _epoch_to_date(info.get("created_utc"))
        elif rule == "keybase":
            if r.status_code != 200:
                return None
            data = r.json() or {}
            them = data.get("them") or []
            if not them or them[0] is None:
                return None
            body = data
        else:
            return None

        human = _HUMAN_URL.get(platform)
        return {"platform": platform, "url": human.format(h=handle) if human else url,
                "created": created, "body": body}
