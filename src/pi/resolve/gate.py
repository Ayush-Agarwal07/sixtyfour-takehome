"""The identity gate: math first; T1 may veto a pass, never override a fail (D12)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .. import constants
from ..sources import host_of
from ..types import Candidate, Link

_PROMPT = (Path(__file__).resolve().parent.parent / "llm" / "prompts" / "gate.md").read_text()


class GateVerdict(BaseModel):
    decision: Literal["CONFIRM", "ABSTAIN", "CONTINUE"] = "ABSTAIN"
    cid: Optional[str] = None
    reasoning: str = ""
    rejected: list[dict] = Field(default_factory=list)
    next_evidence: Optional[str] = None
    what_would_disambiguate: list[str] = Field(default_factory=list)


def gate_decision(math_pass: bool, model_decision: str) -> str:
    """math first; the model may veto a pass, never override a fail."""
    if not math_pass:
        return "continue"
    return {"CONFIRM": "confirm", "ABSTAIN": "abstain"}.get(model_decision.upper(), "continue")


def math_pass(p_top: float, p_run: float) -> bool:
    return p_top >= constants.GATE_P_THRESHOLD and (p_top - p_run) >= constants.GATE_MARGIN


def _cand_block(c: Candidate) -> str:
    lines = [f"Candidate {c.cid}: P={c.score.score:.3f} logodds={c.score.logodds:+.2f}",
             "  terms: " + ", ".join(f"{t.factor}={t.weight:+.2f}" for t in c.score.terms)]
    lines.append("  urls: " + ", ".join(f"{u} [{host_of(u)}]" for u in c.urls[:4]))
    for attr, obs in c.attrs.items():
        for o in obs[:2]:
            lines.append(f"  {attr} = {o.value} ({o.category}, {o.source_class}, {o.kind}) — \"{o.snippet[:200]}\"")
    for n in c.negatives:
        lines.append(f"  NEGATIVE {n.factor} {n.weight:+.2f}")
    if c.merged_from:
        lines.append(f"  merged from: {', '.join(c.merged_from)}")
    return "\n".join(lines)


def build_gate_prompt(seed, ranked: list[Candidate], links: list[Link], spent: int, budget: int) -> str:
    parts = [f"Seed input: {seed.input}",
             f"Seed name variants: {', '.join(v.form for v in seed.names[:4])}",
             f"Seed anchors: orgs={seed.orgs} titles={seed.titles} schools={seed.schools} "
             f"locations={seed.locations} tense={seed.tense} hard_ids={seed.hard_ids}",
             f"Tool calls spent {spent} of {budget}.", ""]
    for c in ranked[:constants.GATE_PROMPT_CANDIDATES]:
        parts.append(_cand_block(c))
        parts.append("")
    if links:
        parts.append("Verified links: " + "; ".join(f"{l.from_url} → {l.to_url} ({l.mechanism})" for l in links[:8]))
    return "\n".join(parts)


async def t1_gate(seed, ranked: list[Candidate], links: list[Link], llm, *, spent: int, budget: int) -> GateVerdict:
    prompt = build_gate_prompt(seed, ranked, links, spent, budget)
    verdict = await llm.complete("T1", prompt, GateVerdict, phase="resolve", system=_PROMPT)
    if verdict.cid is None and ranked:
        verdict.cid = ranked[0].cid
    return verdict


_DISAMBIG_SYSTEM = _PROMPT + """

ADDENDUM — the math did NOT pass. You must not confirm. Set decision to "ABSTAIN".
For every candidate shown, put a one-line description of who the evidence says they are
into `rejected` (cid + reason). Fill `what_would_disambiguate` with the specific inputs
(employer, city, school, a URL) that would separate these particular people."""


async def t1_disambiguate(seed, ranked: list[Candidate], links: list[Link], llm, *, spent: int, budget: int) -> GateVerdict:
    prompt = build_gate_prompt(seed, ranked, links, spent, budget)
    v = await llm.complete("T1", prompt, GateVerdict, phase="resolve", system=_DISAMBIG_SYSTEM)
    v.decision = "ABSTAIN"
    return v
