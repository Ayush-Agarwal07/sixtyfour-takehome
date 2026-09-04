"""GitHub REST API — profile, repos, commit emails. Unauthenticated calls work
(60 req/h); a GITHUB_PAT raises the rate limit but is never required."""
from __future__ import annotations

import os
from urllib.parse import quote

from ..constants import CACHE_TTL_S
from ..deps import Tool, ToolUnavailable, traced

_BASE = "https://api.github.com"


class GitHub(Tool):
    def _headers(self) -> dict:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        pat = os.getenv("GITHUB_PAT")
        if pat:
            headers["Authorization"] = f"Bearer {pat}"
        return headers

    async def _get(self, path: str):
        async def _fetch():
            r = await self.deps.http.get(f"{_BASE}{path}", headers=self._headers())
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()

        return await self.cached("github", path, CACHE_TTL_S["code_host"], _fetch)

    @traced("github.profile", provider="fetch", timeout=10)
    async def profile(self, login: str) -> dict | None:
        data = await self._get(f"/users/{login}")
        if not data:
            return None
        return {k: data.get(k) for k in (
            "login", "name", "bio", "company", "blog", "location",
            "email", "twitter_username", "html_url", "public_repos", "created_at",
        )}

    @traced("github.repos", provider="fetch", timeout=10)
    async def repos(self, login: str, n: int = 5) -> list[dict]:
        data = await self._get(f"/users/{login}/repos?sort=pushed&per_page={n}&type=owner")
        if not data:
            return []
        return [
            {k: r.get(k) for k in ("full_name", "html_url", "description", "pushed_at", "language")}
            for r in data if not r.get("fork")
        ]

    @traced("github.commit_emails", provider="fetch", timeout=15)
    async def commit_emails(self, full_name: str, login: str) -> list[dict]:
        data = await self._get(f"/repos/{full_name}/commits?author={login}&per_page=50")
        if not data:
            return []
        agg: dict[str, dict] = {}
        for c in data:
            author = (c.get("commit") or {}).get("author") or {}
            email = author.get("email") or ""
            date = author.get("date") or ""
            if not email or email.endswith("noreply.github.com"):
                continue
            day = date[:10]
            entry = agg.get(email)
            if entry is None:
                agg[email] = {"email": email, "name": author.get("name"), "first": day, "last": day, "count": 1}
            else:
                entry["count"] += 1
                if day < entry["first"]:
                    entry["first"] = day
                if day > entry["last"]:
                    entry["last"] = day
        return sorted(agg.values(), key=lambda e: e["count"], reverse=True)

    @traced("github.code_search", provider="fetch", timeout=15)
    async def code_search(self, q: str, n: int = 10) -> list[dict]:
        if not os.getenv("GITHUB_PAT"):
            raise ToolUnavailable("GITHUB_PAT")
        path = f"/search/code?q={quote(q)}&per_page={n}"

        async def _fetch():
            r = await self.deps.http.get(f"{_BASE}{path}", headers=self._headers())
            if r.status_code == 403:
                return None                   # rate-limited: never cache, retry next time
            r.raise_for_status()
            items = r.json().get("items") or []
            out = []
            for item in items:
                full_name = (item.get("repository") or {}).get("full_name", "")
                item_path = item.get("path", "")
                out.append({
                    "repo": full_name,
                    "path": item_path,
                    "html_url": item.get("html_url", ""),
                    "raw_url": f"https://raw.githubusercontent.com/{full_name}/HEAD/{item_path}",
                })
            return out

        result = await self.cached("github", path, CACHE_TTL_S["code_host"], _fetch, cache_none=False)
        return result if result is not None else []
