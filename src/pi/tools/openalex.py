"""OpenAlex — scholarly author search and works, for academic co-authorship pivots."""
from __future__ import annotations

from ..constants import OPENALEX_MAILTO
from ..deps import Tool, traced

_BASE = "https://api.openalex.org"
_TTL = 7 * 86400
_TOKEN_MIN = 5


def _tokens(s: str) -> set[str]:
    return {w.lower() for w in s.replace(",", " ").split() if len(w) >= _TOKEN_MIN}


class OpenAlex(Tool):
    @traced("openalex.author", provider="fetch", timeout=15)
    async def author(self, name: str, hints: list[str]) -> dict | None:
        key = f"author|{name}|{','.join(hints)}"

        async def _fetch():
            r = await self.deps.http.get(
                f"{_BASE}/authors",
                params={"search": name, "per-page": 8, "mailto": OPENALEX_MAILTO},
            )
            r.raise_for_status()
            results = r.json().get("results") or []
            hint_tokens: set[str] = set()
            for h in hints:
                hint_tokens |= _tokens(h)

            for a in results:
                insts = [i.get("display_name", "") for i in (a.get("last_known_institutions") or [])
                         if i.get("display_name")]
                insts += [(aff.get("institution") or {}).get("display_name", "")
                          for aff in (a.get("affiliations") or [])
                          if (aff.get("institution") or {}).get("display_name")]
                inst_tokens: set[str] = set()
                for inst in insts:
                    inst_tokens |= _tokens(inst)
                if inst_tokens & hint_tokens:
                    return {
                        "id": a.get("id"),
                        "display_name": a.get("display_name"),
                        "institutions": insts,
                        "works_count": a.get("works_count"),
                        "orcid": (a.get("ids") or {}).get("orcid"),
                    }
            return None

        return await self.cached("openalex", key, _TTL, _fetch)

    @traced("openalex.works", provider="fetch", timeout=15)
    async def works(self, author_id: str, n: int = 5) -> list[dict]:
        key = f"works|{author_id}|{n}"

        async def _fetch() -> list[dict]:
            r = await self.deps.http.get(
                f"{_BASE}/works",
                params={
                    "filter": f"author.id:{author_id}",
                    "sort": "publication_date:desc",
                    "per-page": n,
                    "mailto": OPENALEX_MAILTO,
                },
            )
            r.raise_for_status()
            results = r.json().get("results") or []
            out = []
            for w in results:
                doi = w.get("doi")
                loc = w.get("primary_location") or {}
                source = loc.get("source") or {}
                coauthors = [
                    (au.get("author") or {}).get("display_name")
                    for au in (w.get("authorships") or [])
                    if (au.get("author") or {}).get("display_name")
                ][:6]
                out.append({
                    "title": w.get("title"),
                    "year": w.get("publication_year"),
                    "doi": doi,
                    "venue": source.get("display_name"),
                    "coauthors": coauthors,
                    "url": doi or w.get("id"),
                })
            return out

        return await self.cached("openalex", key, _TTL, _fetch)
