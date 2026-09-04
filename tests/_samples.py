"""One of every trace event, shared by test_types and test_trace_render."""
from __future__ import annotations

from pi.trace.events import (
    BaseEvent, BudgetUpdate, CandidateScore, ConflictDetected, Disconfirmation,
    FrontierUpdate, GateDecision, GateTest, LLMCall, Merge, PhaseTransition,
    PlannerDecision, Reinforce, Rejection, RoleResolution, SlotUpdate, Stop,
    ToolCall,
)
from pi.types import Term

GATE_REASONING_EVENT_ID = "evt_gate_0001"
PLANNER_REASONING_EVENT_ID = "evt_plan_0001"


def all_sample_events() -> list[BaseEvent]:
    return [
        PhaseTransition(event_id="e01", from_phase="understand", to_phase="resolve"),
        ToolCall(event_id="e02", tool="serper.search", args={"q": "henry wang sixtyfour"},
                 latency_ms=120.0, ok=True, cache_hit=False),
        LLMCall(event_id="e03", model="gemini-flash", tier="T5", cost_usd=0.0004,
                latency_ms=800.0, usage={"in": 300, "out": 60}),
        CandidateScore(event_id="e04", cid="c1", logodds=5.05, score=0.994,
                       terms=[Term(factor="anchor:employer", weight=2.5),
                              Term(factor="prior", weight=-1.5)]),
        Merge(event_id="e05", from_cid="c9", to_cid="c1", reason="verified reciprocal link"),
        Rejection(event_id="e06", cid="c2", reason="employer contradicts on official page"),
        RoleResolution(event_id="e08", company="ariglad", resolved_holder="Jane Roe",
                       method="team page + linkedin serp"),
        Disconfirmation(event_id="e09", hypothesis="could be a different Henry Wang",
                        actions=[{"tool": "fetch", "args": {"url": "https://hwang.dev"}}],
                        result="personal site confirms Sixtyfour"),
        GateTest(event_id="e10", p_top=0.994, p_runner_up=0.14, margin=0.854, math_pass=True),
        GateDecision(event_id=GATE_REASONING_EVENT_ID, decision="CONFIRM", cid="c1",
                     reasoning_ref=f"reasoning/{GATE_REASONING_EVENT_ID}.txt",
                     rejected=[{"cid": "c2", "reason": "wrong employer"}]),
        FrontierUpdate(event_id="e12", added=6,
                       top=[{"id": "f1", "action": "fetch", "score": 3.2}]),
        PlannerDecision(event_id=PLANNER_REASONING_EVENT_ID,
                        formula_top=[{"id": "f1", "action": "fetch"},
                                     {"id": "f2", "action": "search"}],
                        chosen=[{"id": "f1", "action": "fetch"}],
                        new_actions=[{"tool": "search", "args": {"q": "henry wang jane roe"},
                                      "hypothesis": "joint press", "slot": "social_graph"}],
                        reasoning_ref=f"reasoning/{PLANNER_REASONING_EVENT_ID}.txt"),
        Reinforce(event_id="e14", node_id="company:acme.com", descendants=4, attachment=0.42),
        SlotUpdate(event_id="e15", slot="employment_history", current=3, target=3, closed=True),
        ConflictDetected(event_id="e16", kind="soft", predicate="title",
                         values=["Head of Design", "Design Lead"], severity=-0.3),
        BudgetUpdate(event_id="e17", tool_calls=22, llm_calls=6, usd=0.31, seconds=94.0),
        Stop(event_id="e18", stop_reason="S1", numbers={"slots_closed": 8}),
    ]
