"""RESOLVE enumeration — ≤ENUMERATION_MAX_QUERIES searches, issued concurrently,
deduped by URL. Query set depends on the regime."""
from __future__ import annotations

import asyncio
import re

from .. import constants


def _primary_name(seed) -> str:
    return seed.names[0].form if seed.names else ""


def build_queries(seed) -> list[str]:
    name = _primary_name(seed)
    org = seed.orgs[0] if seed.orgs else ""
    domain = seed.org_domains.get(org) or (org if "." in org else "")
    label = domain.split(".")[0] if domain else org
    title = seed.titles[0] if seed.titles else ""
    q: list[str] = []
    if seed.regime == "HARD_ID_EMAIL":
        email = seed.hard_ids.get("email", "")
        q += [f'"{email}"', f'"{name}" {label}', f'site:linkedin.com/in "{name}" {label}',
              f'site:github.com "{name}"']
    elif seed.regime == "HARD_ID_URL":
        url = next(iter(seed.hard_ids.values()))
        q += [url, f'"{name}"' if name else url]
    else:
        q += [f'"{name}" {org}'.strip(), f'site:linkedin.com/in "{name}" {org}'.strip(),
              f'site:github.com "{name}"']
        if domain:
            q.append(f'"{name}" site:{domain}')
        elif title:
            q.append(f'"{name}" "{title}"')
        # nickname variants are used by the matcher, not as queries: the `nicknames`
        # table maps non-English names badly ("Ali" → "Almena") and each query costs quota.
    seen, out = set(), []
    for x in q:
        x = re.sub(r"\s+", " ", x).strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out[:constants.ENUMERATION_MAX_QUERIES]


async def enumerate_candidates(seed, deps) -> list[dict]:
    queries = build_queries(seed)

    async def one(q: str) -> list[dict]:
        try:
            return await deps.serper.search(q, num=10)
        except Exception:  # noqa: BLE001 — a failed query is a smaller result set, not a crash
            return []

    batches = await asyncio.gather(*(one(q) for q in queries))
    results, seen = [], set()
    for batch in batches:
        for r in batch:
            if r["url"] not in seen:
                seen.add(r["url"])
                results.append(r)
    return results
