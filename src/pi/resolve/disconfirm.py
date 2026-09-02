"""Executed disconfirmation (C5): T1 names how the match could be wrong and the
tool calls that would show it; the calls run; the candidate is re-matched."""
from __future__ import annotations

import uuid
from pathlib import Path

from pydantic import BaseModel, Field

from .. import constants
from ..sources import classify, identity_tier
from ..trace.events import Disconfirmation
from ..types import Candidate, SourceText
from .gate import _cand_block

_PROMPT = (Path(__file__).resolve().parent.parent / "llm" / "prompts" / "disconfirm.md").read_text()


class DisconfirmPlan(BaseModel):
    hypothesis: str = ""
    actions: list[dict] = Field(default_factory=list)
    expected_if_wrong: str = ""
    reasoning: str = ""


def _name_tokens(seed) -> set[str]:
    toks: set[str] = set()
    for v in seed.names[:3]:
        toks |= {t for t in v.form.lower().replace(".", "").split() if len(t) >= 3}
    return toks


async def run_actions(actions: list[dict], top: Candidate, seed, deps, read_page, *, anchor_domains: set[str],
                      on_page=None) -> list[str]:
    """Execute ≤DISCONFIRM_MAX_ACTIONS search/fetch actions, attaching results to `top`
    as evidence. Returns one summary line per action."""
    names = [v.form for v in seed.names]
    toks = _name_tokens(seed)
    summary: list[str] = []
    for a in actions[:constants.DISCONFIRM_MAX_ACTIONS]:
        tool, args = (a.get("tool") or "").lower(), a.get("args") or {}
        try:
            if tool == "search" and args.get("q"):
                rs = await deps.serper.search(args["q"], num=8)
                n = 0
                for r in rs:
                    blob = f"{r.get('title', '')} — {r.get('snippet', '')}"
                    if toks and not any(t in blob.lower() for t in toks):
                        continue
                    cls = classify(r["url"], anchor_domains=anchor_domains, names=names)
                    top.sources.append(SourceText(url=r["url"], kind="snippet", source_class=cls,
                                                  tier=identity_tier(cls), text=blob[:600]))
                    n += 1
                summary.append(f"search {args['q']!r}: {len(rs)} results, {n} about the name")
            elif tool == "fetch" and args.get("url"):
                page = await read_page(args["url"], deps)
                if page and page.get("text"):
                    cls = classify(args["url"], anchor_domains=anchor_domains, names=names)
                    top.sources.append(SourceText(url=args["url"], kind="page", source_class=cls,
                                                  tier=identity_tier(cls), text=page["text"][:3000]))
                    if on_page is not None:
                        on_page(page, top if args["url"] in top.urls else None)
                    summary.append(f"fetch {args['url']}: {len(page['text'])} chars")
                else:
                    summary.append(f"fetch {args['url']}: no text")
            else:
                summary.append(f"skipped unknown action {a}")
        except Exception as e:  # noqa: BLE001
            summary.append(f"{tool} failed: {type(e).__name__}")
    return summary


async def disconfirm(seed, top: Candidate, runner: Candidate | None, deps, llm, read_page, *,
                     spent: int, budget: int, anchor_domains: set[str], on_page=None) -> DisconfirmPlan:
    prompt = "\n".join([
        f"Seed input: {seed.input}",
        f"Seed anchors: orgs={seed.orgs} titles={seed.titles} tense={seed.tense} hard_ids={seed.hard_ids}",
        f"Tool calls left: {max(0, budget - spent)}", "",
        "TOP CANDIDATE", _cand_block(top), "",
        ("RUNNER-UP\n" + _cand_block(runner)) if runner else "RUNNER-UP: none",
    ])
    plan = await llm.complete("T1", prompt, DisconfirmPlan, phase="resolve", system=_PROMPT)
    results = await run_actions(plan.actions, top, seed, deps, read_page, anchor_domains=anchor_domains, on_page=on_page) \
        if spent < budget else ["budget exhausted: no actions run"]
    if deps.trace:
        eid = uuid.uuid4().hex[:16]
        deps.trace.write_reasoning(eid, plan.reasoning)
        deps.trace.emit(Disconfirmation(event_id=eid, phase="resolve", hypothesis=plan.hypothesis,
                                        actions=plan.actions[:constants.DISCONFIRM_MAX_ACTIONS],
                                        result="; ".join(results) or "no actions",
                                        note=f"expected if wrong: {plan.expected_if_wrong[:200]}"))
    return plan
