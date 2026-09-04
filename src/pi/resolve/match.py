"""T4 batched attribute matching — the only place a model judges anchors.

Constrained categories → fixed weights (never a model float). Produces the
candidate's matched observations (with the tier of the citing source) AND its
negatives (`contradicts`, name mismatch). Recomputed from scratch per call so a
later fetch can revise an earlier snippet-level judgement.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .. import constants
from ..sources import host_of
from ..types import AttrObservation, Candidate, Term

_PROMPT = (Path(__file__).resolve().parent.parent / "llm" / "prompts" / "match.md").read_text()
_PAGE_CLASSES = {"company_site", "personal_site", "code_host", "professional_network", "academic", "government_registry"}
_MAX_SOURCES = 6  # sources[:_MAX_SOURCES] is what the model is shown; citations bind to that prefix


class AttrCat(BaseModel):
    category: Literal["exact_match", "matches_former", "partial", "unrelated", "contradicts"] = "unrelated"
    sources: list[int] = Field(default_factory=list)


class MatchRow(BaseModel):
    cid: str
    name: Literal["exact", "variant", "mismatch"] = "exact"
    employer: Optional[AttrCat] = None
    title: Optional[AttrCat] = None
    education: Optional[AttrCat] = None
    location: Optional[AttrCat] = None


class MatchBatch(BaseModel):
    results: list[MatchRow] = Field(default_factory=list)
    reasoning: str = ""


def seed_anchors(seed) -> dict[str, str]:
    a: dict[str, str] = {}
    if seed.orgs:
        a["employer"] = seed.orgs[0]
    if seed.titles:
        a["title"] = seed.titles[0]
    if seed.schools:
        a["education"] = seed.schools[0]
    if seed.locations:
        a["location"] = seed.locations[0]
    return a


def _seed_block(seed, anchors: dict[str, str]) -> str:
    lines = [f"Seed input: {seed.input}", f"Seed name and variants: {', '.join(v.form for v in seed.names[:4])}"]
    for k, v in anchors.items():
        tense = seed.tense.get(v.lower(), "current") if k == "employer" else "current"
        lines.append(f"Seed {k}: {v} (tense: {tense})")
    return "\n".join(lines)


def _cand_block(c: Candidate) -> str:
    lines = [f"Candidate {c.cid} — urls: {', '.join(c.urls[:3]) or '(none)'}"]
    for i, s in enumerate(c.sources[:_MAX_SOURCES], 1):
        lines.append(f"  [{i}] ({s.kind}, {s.source_class}, {host_of(s.url)}) {s.text[:900]}")
    return "\n".join(lines)


def _apply(c: Candidate, row: MatchRow, anchors: dict[str, str], seed) -> None:
    c.attrs = {}
    c.negatives = []
    if row.name == "mismatch":
        c.negatives.append(Term(factor="name_mismatch", weight=constants.NAME_MISMATCH))
    elif row.name == "variant":
        c.name_form = "nickname"
    else:
        c.name_form = "exact"
    shown = c.sources[:_MAX_SOURCES]
    n_shown = len(shown)
    for attr, anchor in anchors.items():
        cat: AttrCat | None = getattr(row, attr, None)
        if not cat:
            continue
        idxs = [i for i in cat.sources if 1 <= i <= n_shown][:_MAX_SOURCES]
        category = cat.category
        if category == "matches_former" and seed.tense.get(anchor.lower(), "current") != "former":
            category = "partial"
        if category in constants.T4_CATEGORY_MULT and constants.T4_CATEGORY_MULT[category] > 0:
            for i in idxs:
                s = shown[i - 1]
                c.attrs.setdefault(attr, []).append(AttrObservation(
                    value=anchor, source_class=s.source_class, source_tier=s.tier, url=s.url,
                    snippet=s.text[:200], category=category, kind=s.kind))
        elif category == "contradicts":
            worst = 0.0
            for i in idxs:
                s = shown[i - 1]
                w = -(s.tier * constants.CONTRADICT_PAGE_MULT) if (s.kind == "page" and s.source_class in _PAGE_CLASSES) \
                    else constants.CONTRADICT_SNIPPET
                worst = min(worst, w)
            if not idxs:
                worst = constants.CONTRADICT_SNIPPET
            c.negatives.append(Term(factor=f"contradicts:{attr}", weight=round(worst, 3)))


async def match_candidates(seed, cands: list[Candidate], llm, *, only: set[str] | None = None) -> None:
    anchors = seed_anchors(seed)
    targets = [c for c in cands if (only is None or c.cid in only) and c.sources]
    if not anchors or not targets:
        return
    head = _seed_block(seed, anchors)
    for i in range(0, len(targets), 10):
        batch = targets[i:i + 10]
        prompt = head + "\n\n" + "\n\n".join(_cand_block(c) for c in batch)
        out = await llm.complete("T4", prompt, MatchBatch, phase="resolve", system=_PROMPT)
        rows = {r.cid: r for r in out.results if r.cid in {c.cid for c in batch}}
        for c in batch:
            row = rows.get(c.cid)
            if row is None:
                c.attrs, c.negatives = {}, []
                continue
            _apply(c, row, anchors, seed)
