"""Phase 1 UNDERSTAND.

`parse_input` — hard-ID regex only (email / profile URL), no network, no LLM.
`understand`  — full path: hard IDs short-circuit; everything else goes through
the T5 parse, company resolution (domain stored on the seed), and regime
classification.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ..deps import ToolUnavailable
from ..types import Seed, Variant
from .email_derive import derive_from_email
from . import regime as regime_mod
from .variants import generate_variants

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LINKEDIN = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w%-]+", re.I)
GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w-]+", re.I)
XURL = re.compile(r"(?:https?://)?(?:www\.)?(?:x|twitter)\.com/[A-Za-z0-9_]+", re.I)

_PROMPT = (Path(__file__).resolve().parent.parent / "llm" / "prompts" / "parse.md").read_text()


def _https(u: str) -> str:
    return u if u.startswith("http") else "https://" + u


def parse_input(text: str) -> Seed:
    text = text.strip()

    m = EMAIL.search(text)
    if m:
        email = m.group(0)
        d = derive_from_email(email)
        names: list[Variant] = []
        for h in d.hypotheses:
            first = h.first or (f"{h.first_initial}." if h.first_initial else None)
            form = " ".join(x for x in (first, h.last) if x).title()
            if form:
                names.append(Variant(form=form, weight=h.confidence))
        return Seed(input=text, regime="HARD_ID_EMAIL", names=names,
                    hard_ids={"email": email}, orgs=[d.domain], org_domains={d.domain: d.domain},
                    tense={d.domain: "current"})

    for rx, key in ((LINKEDIN, "linkedin"), (GITHUB, "github"), (XURL, "x")):
        m = rx.search(text)
        if m:
            url = _https(m.group(0))
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            words = [w for w in re.split(r"[-_.]+", slug) if w and not w.isdigit()]
            names = [Variant(form=" ".join(words).title())] if words else []
            return Seed(input=text, regime="HARD_ID_URL", hard_ids={key: url}, names=names)

    return Seed(input=text, regime="BARE_NAME", names=[Variant(form=text)] if text else [])


class ParseModel(BaseModel):
    """T5 structured-output contract (see llm/prompts/parse.md)."""
    names: list[str] = Field(default_factory=list)
    orgs: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    schools: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    role_description: Optional[str] = None
    tense: dict[str, str] = Field(default_factory=dict)
    reasoning: str = ""


def _clean_tense(tense: dict[str, str], orgs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    lower = {o.lower(): o.lower() for o in orgs}
    for k, v in (tense or {}).items():
        v = "former" if str(v).lower().startswith("form") or "ex" == str(v).lower() else "current"
        key = k.lower().strip()
        if key in lower:
            out[key] = v
        elif len(orgs) == 1:
            out[orgs[0].lower()] = v
    for o in orgs:
        out.setdefault(o.lower(), "current")
    return out


async def understand(text: str, deps, llm) -> Seed:
    seed = parse_input(text)
    if seed.regime.startswith("HARD_ID"):
        return seed
    if not text.strip():
        return Seed(input=text, regime="BARE_NAME", names=[])

    parsed = await llm.complete("T5", f"Input: {text}", ParseModel, phase="understand", system=_PROMPT)

    org = parsed.orgs[0] if parsed.orgs else None
    org_domains: dict[str, str] = {}
    company_resolved = False
    org_is_huge = regime_mod.is_huge_org(org) if org else False
    for o in parsed.orgs[:2]:
        try:
            resolved = await deps.company.resolve(o)
        except (ToolUnavailable, Exception):  # noqa: BLE001 — degrade, never crash
            resolved = None
        if resolved and resolved.get("domain"):
            org_domains[o] = resolved["domain"]
    company_resolved = bool(org and org in org_domains)

    name = parsed.names[0] if parsed.names else None
    title = parsed.titles[0] if parsed.titles else None
    regime = regime_mod.classify(
        name=name, org=org, title=title,
        role_description=parsed.role_description,
        hard_ids=seed.hard_ids,
        company_resolved=company_resolved,
        org_is_huge=org_is_huge,
    )

    names: list[Variant] = []
    for n in parsed.names:
        names.extend(generate_variants(n) or [Variant(form=n)])

    return Seed(
        input=text, regime=regime, names=names, hard_ids=seed.hard_ids,
        orgs=parsed.orgs, titles=parsed.titles, schools=parsed.schools,
        locations=parsed.locations, tense=_clean_tense(parsed.tense, parsed.orgs),
        role_description=parsed.role_description, org_domains=org_domains,
    )
