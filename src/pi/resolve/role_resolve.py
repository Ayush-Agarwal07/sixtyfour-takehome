"""DEFINITE_DESC → NAME_STRONG. "the CTO of Ariglad" has no name: read the
company's own site and the SERP, ask T5 for the current holder, rewrite the seed.
Competing holders → ambiguous. A wrong name is worse than none."""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ..trace.events import RoleResolution
from ..types import Seed, Variant
from ..understand.variants import generate_variants

_PROMPT = (Path(__file__).resolve().parent.parent / "llm" / "prompts" / "role_resolve.md").read_text()


_EXEC_TOKENS = ("cto", "ceo", "cfo", "coo", "founder", "chief", "president")
_ROLE_NOISE = re.compile(r"^(the|a|an)\s+|\s+(of|at)\s+.*$", re.I)


def _clean_role(role: str, company: str) -> str:
    """'the CTO of Ariglad' → 'CTO'."""
    r = _ROLE_NOISE.sub("", role.strip())
    if company and company.lower() in r.lower():
        r = re.sub(re.escape(company), "", r, flags=re.I).strip()
    return r or role


class RoleHolder(BaseModel):
    name: Optional[str] = None
    is_current: Optional[bool] = None
    sources: list[int] = Field(default_factory=list)
    competing: list[str] = Field(default_factory=list)
    reasoning: str = ""


async def role_resolve(seed: Seed, deps, llm, read_page) -> tuple[Seed, RoleHolder, list[dict]]:
    """Returns (rewritten seed, holder, cited SERP results). The cited results are
    fed to enumeration as forced results: T5 already judged that they name the
    holder, so the surname relevance floor must not drop them ("Ali A." on LinkedIn)."""
    company = seed.orgs[0] if seed.orgs else ""
    role = _clean_role(seed.titles[0] if seed.titles else (seed.role_description or ""), company)
    domain = seed.org_domains.get(company, "")
    sources: list[tuple[str, str]] = []
    serp: dict[str, dict] = {}

    if domain:
        for path in ("", "/about", "/team"):
            try:
                page = await read_page(f"https://{domain}{path}", deps)
            except Exception:  # noqa: BLE001
                page = None
            if page and page.get("text"):
                sources.append((f"https://{domain}{path}", page["text"][:2500]))
                if role.lower() in page["text"].lower():
                    break
    queries = [f'"{company}" {role}', f'site:linkedin.com/in "{company}" {role}']
    if any(t in role.lower() for t in _EXEC_TOKENS):
        queries.append(f'"{company}" founders OR "co-founder"')
    for q in queries:
        try:
            for r in await deps.serper.search(q, num=8):
                sources.append((r["url"], f"{r.get('title', '')} — {r.get('snippet', '')}"))
                serp[r["url"]] = r
        except Exception:  # noqa: BLE001
            pass

    shown = sources[:14]
    numbered = "\n".join(f"[{i}] {u}\n{t}" for i, (u, t) in enumerate(shown, 1))
    prompt = f"Role: {role}\nCompany: {company}\n\nSources:\n{numbered}"
    holder = await llm.complete("T5", prompt, RoleHolder, phase="resolve", system=_PROMPT)

    if deps.trace:
        eid = uuid.uuid4().hex[:16]
        deps.trace.write_reasoning(eid, holder.reasoning)
        deps.trace.emit(RoleResolution(event_id=eid, phase="resolve", company=company,
                                       resolved_holder=holder.name, method="official site + serp → T5",
                                       note=(f"competing: {holder.competing}; " if holder.competing else "")
                                            + holder.reasoning[:200]))

    cited = [dict(serp[shown[i - 1][0]], force=True) for i in holder.sources
             if 1 <= i <= len(shown) and shown[i - 1][0] in serp]
    if not holder.name or holder.competing:
        return seed, holder, cited
    new = seed.model_copy(update={
        "names": generate_variants(holder.name) or [Variant(form=holder.name)],
        "regime": "NAME_STRONG" if domain else "NAME_WEAK",
        "titles": [role] if role else seed.titles,
        "role_description": None,
        "original_regime": "DEFINITE_DESC",
        "tense": {**seed.tense, company.lower(): "former" if holder.is_current is False else "current"},
    })
    return new, holder, cited
