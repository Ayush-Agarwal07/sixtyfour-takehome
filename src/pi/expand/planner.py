"""EXPAND planner (C4) — an LLM call that picks from the ranked frontier and may
inject its own actions. The frontier's pre-sort is a formula; this is the decider.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from pydantic import BaseModel, Field

from .. import constants
from ..trace.events import PlannerDecision
from ..types import Claim, Conflict, FrontierItem

_PROMPT = (Path(__file__).resolve().parent.parent / "llm" / "prompts" / "planner.md").read_text()
_VALID_TOOLS = {"search", "fetch", "github", "gravatar", "wayback", "verify"}
_ARG_ALIASES = {"query": "q", "search_query": "q", "handle": "login", "username": "login",
                "link": "url", "href": "url", "mail": "email"}


class PlannerOut(BaseModel):
    picks: list[str] = Field(default_factory=list)
    new_actions: list[dict] = Field(default_factory=list)
    close_slots: list[str] = Field(default_factory=list)
    stop: bool = False
    reasoning: str = ""


def _slots_table(slots) -> str:
    return "\n".join(f"{s.name} {s.current}/{s.target} {'closed' if s.closed else 'open'}"
                     for s in slots.slots.values())


def _frontier_lines(ranked: list[tuple[FrontierItem, float]]) -> str:
    return "\n".join(f"{item.id} | {item.action} {item.args} | {item.origin} | {score:.3f} | {item.why}"
                     for item, score in ranked) or "none"


def _claim_lines(claims: list[Claim], limit: int = 15) -> str:
    return "\n".join(f"{c.predicate}={c.value} ({c.confidence.score:.2f})" for c in claims[:limit]) or "none"


def _conflict_lines(conflicts: list[Conflict]) -> str:
    return "\n".join(f"{c.kind} {c.predicate}: {c.values}" for c in conflicts) or "none"


def _normalize_args(args: dict) -> dict:
    """The model spells argument keys inconsistently (`query` for `q`, etc.) — canonicalize
    before it becomes a frontier key or a tool call."""
    return {_ARG_ALIASES.get(k, k): v for k, v in (args or {}).items()}


def _register_new_actions(shaped: list[dict], frontier) -> list[dict]:
    """Normalize args, drop anything already done or already pending this run (by
    frontier key), and register survivors on the frontier so they get a real,
    deduped id — feeding them into the normal frontier bookkeeping instead of a
    parallel ad-hoc path that could re-suggest the same action forever."""
    kept: list[dict] = []
    for a in shaped:
        tool = a["tool"]
        args = _normalize_args(a.get("args"))
        key = frontier.key(tool, args)
        if key in frontier.done or key in frontier.items:
            continue
        frontier.add(FrontierItem(id=key, action=tool, args=args, origin="planner",
                                  open_slot=a.get("slot"), relevance=0.8, why=a.get("hypothesis", "")))
        kept.append({**a, "args": args})
    return kept


def _validate(out: PlannerOut, ranked_ids: set[str], frontier) -> PlannerOut:
    """picks ⊆ ranked ids, ≤ PLANNER_MAX_PICKS; new_actions well-formed, ≤ PLANNER_MAX_NEW,
    deduped against the frontier; total ≤ PLANNER_MAX_PICKS with new_actions trimmed first."""
    picks = [p for p in out.picks if p in ranked_ids][: constants.PLANNER_MAX_PICKS]
    shaped = [a for a in out.new_actions[: constants.PLANNER_MAX_NEW]
             if isinstance(a, dict) and a.get("tool") in _VALID_TOOLS and isinstance(a.get("args"), dict)]
    new_actions = _register_new_actions(shaped, frontier)
    room = max(0, constants.PLANNER_MAX_PICKS - len(picks))
    new_actions = new_actions[:room]
    return out.model_copy(update={"picks": picks, "new_actions": new_actions})


async def plan(*, ranked: list[tuple[FrontierItem, float]], slots, graph, last_claims: list[Claim],
               conflicts: list[Conflict], budget: dict, llm, deps, frontier,
               pivots: list[FrontierItem] | None = None) -> PlannerOut:
    ranked_ids = {item.id for item, _ in ranked}
    prompt = "\n\n".join([
        "SLOTS\n" + _slots_table(slots),
        "FRONTIER\n" + _frontier_lines(ranked),
        "GRAPH\n" + "\n".join(f"{n['id']} {n['type']} {n['label']} {n['attachment']:.2f}"
                              for n in graph.summary()),
        "NEW CLAIMS LAST BATCH\n" + _claim_lines(last_claims),
        "OPEN CONFLICTS\n" + _conflict_lines(conflicts),
        f"BUDGET\ntool_calls_left={budget.get('tool_calls_left')}",  # calls only: usd/seconds vary per run and would break replay
    ])

    note = None
    try:
        # T2, not T1: same model, no reasoning tokens — the planner doesn't need a
        # reasoning-on call every batch, and it was most of EXPAND's LLM cost.
        out = await llm.complete("T2", prompt, PlannerOut, phase="expand", system=_PROMPT)
        out = _validate(out, ranked_ids, frontier)
    except Exception as e:  # noqa: BLE001 — a formula-order fallback, never a crash
        note = f"planner failed: {type(e).__name__}: {e}"
        out = PlannerOut(picks=[item.id for item, _ in ranked[: constants.PLANNER_MAX_PICKS]],
                         reasoning=f"{note}; formula order used")

    if deps is not None and deps.trace is not None:
        eid = uuid.uuid4().hex[:16]
        ref = deps.trace.write_reasoning(eid, out.reasoning)
        item_by_id = {item.id: item for item, _ in ranked}
        # forced pivots (username_probe/gravatar/github_code/openalex) never touch the
        # ranked frontier (F1) — surfaced here only so the trace shows what actually ran.
        chosen_view = [{"id": it.id, "action": it.action, "args": it.args, "origin": "pivot"}
                      for it in (pivots or [])]
        chosen_view += [{"id": pid, "action": item_by_id[pid].action, "args": item_by_id[pid].args}
                       for pid in out.picks if pid in item_by_id]
        formula_top = [{"id": item.id, "action": item.action, "args": item.args} for item, _ in ranked[:4]]
        deps.trace.emit(PlannerDecision(event_id=eid, phase="expand", note=note, formula_top=formula_top,
                                        chosen=chosen_view, new_actions=out.new_actions, reasoning_ref=ref))
    return out
