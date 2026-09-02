"""Phase 1 UNDERSTAND.

`parse_input` — Stage 1 slice, unchanged: hard-ID regex only (email / profile
URL), bare-name fallthrough, no network, no LLM.

`understand` — Stage 2: the full path. Hard IDs still short-circuit (fast path,
no LLM/network); everything else goes through the T5 parse + company resolution
+ regime classification.

one-line run.py change needed (owned by someone else, not made here):
    cf.seed = parse_input(text)          ->  cf.seed = await understand(text, deps, llm)
and, alongside the other tool construction in investigate():
    deps.company = Company(deps)
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

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LINKEDIN = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w%-]+", re.I)
GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w-]+", re.I)
XURL = re.compile(r"(?:https?://)?(?:www\.)?(?:x|twitter)\.com/[A-Za-z0-9_]+", re.I)

_PARSE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "llm" / "prompts" / "parse.md"


def parse_input(text: str) -> Seed:
    text = text.strip()

    m = EMAIL.search(text)
    if m:
        email = m.group(0)
        d = derive_from_email(email)
        names = []
        for h in d.hypotheses:
            first = h.first or (f"{h.first_initial}." if h.first_initial else None)
            form = " ".join(x for x in (first, h.last) if x).title()
            if form:
                names.append(Variant(form=form, weight=h.confidence))
        return Seed(input=text, regime="HARD_ID_EMAIL", names=names,
                    hard_ids={"email": email}, orgs=[d.domain])

    for rx, key in ((LINKEDIN, "linkedin"), (GITHUB, "github"), (XURL, "x")):
        m = rx.search(text)
        if m:
            return Seed(input=text, regime="HARD_ID_URL",
                        hard_ids={key: _https(m.group(0))})

    # ponytail: name/org/title parse is Stage 2 (T5). Fall through as a bare name.
    return Seed(input=text, regime="BARE_NAME", names=[Variant(form=text)])


def _https(u: str) -> str:
    return u if u.startswith("http") else "https://" + u


# ─────────────────────────────── Stage 2 ──────────────────────────────────
class ParseModel(BaseModel):
    """T5 structured-output contract (see llm/prompts/parse.md)."""
    names: list[str] = Field(default_factory=list)
    orgs: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    schools: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    role_description: Optional[str] = None
    tense: dict[str, str] = Field(default_factory=dict)


def _variants_for(name: str) -> list[Variant]:
    # ponytail: variants.py is Worker A's module and may not exist yet. Degrade
    # to a single as-given Variant rather than fail the whole parse.
    try:
        from .variants import generate_variants
    except ImportError:
        return [Variant(form=name)]
    return generate_variants(name) or [Variant(form=name)]


async def understand(text: str, deps, llm) -> Seed:
    """Full UNDERSTAND path: hard-ID fast path, else T5 parse + company
    resolution + regime classification.

    one-line run.py change needed (owned by someone else, not made here):
        cf.seed = parse_input(text)     ->   cf.seed = await understand(text, deps, llm)
    and, alongside the other tool construction in investigate():
        deps.company = Company(deps)
    """
    seed = parse_input(text)
    if seed.regime.startswith("HARD_ID"):
        return seed  # fast path — no LLM, no network

    prompt = _PARSE_PROMPT_PATH.read_text() + f"\n\nInput: {text}"
    parsed = llm.complete("T5", prompt, ParseModel, phase="understand")

    org = parsed.orgs[0] if parsed.orgs else None
    company_resolved = False
    org_is_huge = regime_mod.is_huge_org(org) if org else False
    if org:
        try:
            resolved = await deps.company.resolve(org)
        except ToolUnavailable:
            resolved = None
        company_resolved = bool(resolved and resolved.get("domain"))

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
        names.extend(_variants_for(n))

    return Seed(
        input=text,
        regime=regime,
        names=names,
        hard_ids=seed.hard_ids,
        orgs=parsed.orgs,
        titles=parsed.titles,
        schools=parsed.schools,
        locations=parsed.locations,
        tense=parsed.tense,
        role_description=parsed.role_description,
    )
