"""Fixed Pydantic model per trace event type + a discriminated union.

plan/reference-contracts.md §7. Every event carries event_id, ts, an optional
free-text note, and a discriminator `event_type`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field, TypeAdapter

from ..types import Term


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BaseEvent(BaseModel):
    event_id: str
    ts: datetime = Field(default_factory=_utcnow)
    phase: Optional[str] = None
    note: Optional[str] = None


class ToolCall(BaseEvent):
    event_type: Literal["tool_call"] = "tool_call"
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0
    ok: bool = True
    error: Optional[str] = None
    cache_hit: bool = False


class LLMCall(BaseEvent):
    event_type: Literal["llm_call"] = "llm_call"
    model: str
    tier: str
    prompt_ref: Optional[str] = None
    response_ref: Optional[str] = None
    usage: dict[str, Any] = Field(default_factory=dict)
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    cache_hit: bool = False
    reasoning_ref: Optional[str] = None


class PhaseTransition(BaseEvent):
    event_type: Literal["phase_transition"] = "phase_transition"
    from_phase: str
    to_phase: str


class CandidateScore(BaseEvent):
    event_type: Literal["candidate_score"] = "candidate_score"
    cid: str
    logodds: float
    score: float
    terms: list[Term] = Field(default_factory=list)


class Merge(BaseEvent):
    event_type: Literal["merge"] = "merge"
    from_cid: str
    to_cid: str
    reason: str


class Rejection(BaseEvent):
    event_type: Literal["rejection"] = "rejection"
    cid: str
    reason: str


class VariantDiscovered(BaseEvent):
    event_type: Literal["variant_discovered"] = "variant_discovered"
    form: str
    origin: str
    evidence_id: Optional[str] = None


class RoleResolution(BaseEvent):
    event_type: Literal["role_resolution"] = "role_resolution"
    company: str
    resolved_holder: Optional[str] = None
    method: str = ""


class Disconfirmation(BaseEvent):
    event_type: Literal["disconfirmation"] = "disconfirmation"
    hypothesis: str
    actions: list[dict[str, Any]] = Field(default_factory=list)
    result: str = ""


class GateTest(BaseEvent):
    event_type: Literal["gate_test"] = "gate_test"
    p_top: float
    p_runner_up: float
    margin: float
    math_pass: bool


class GateDecision(BaseEvent):
    event_type: Literal["gate_decision"] = "gate_decision"
    decision: str                       # CONFIRM|ABSTAIN|CONTINUE
    cid: Optional[str] = None
    reasoning_ref: Optional[str] = None
    rejected: list[dict[str, Any]] = Field(default_factory=list)
    next_evidence: Optional[str] = None


class FrontierUpdate(BaseEvent):
    event_type: Literal["frontier_update"] = "frontier_update"
    added: int = 0
    top: list[dict[str, Any]] = Field(default_factory=list)


class PlannerDecision(BaseEvent):
    event_type: Literal["planner_decision"] = "planner_decision"
    formula_top: list[dict[str, Any]] = Field(default_factory=list)
    chosen: list[dict[str, Any]] = Field(default_factory=list)
    new_actions: list[dict[str, Any]] = Field(default_factory=list)
    reasoning_ref: Optional[str] = None


class Reinforce(BaseEvent):
    event_type: Literal["reinforce"] = "reinforce"
    node_id: str
    descendants: int
    attachment: float


class SlotUpdate(BaseEvent):
    event_type: Literal["slot_update"] = "slot_update"
    slot: str
    current: int
    target: int
    closed: bool


class ConflictDetected(BaseEvent):
    event_type: Literal["conflict_detected"] = "conflict_detected"
    kind: str                           # soft|hard|identity
    predicate: str
    values: list[str] = Field(default_factory=list)
    severity: float = 0.0


class BudgetUpdate(BaseEvent):
    event_type: Literal["budget_update"] = "budget_update"
    tool_calls: int = 0
    llm_calls: int = 0
    usd: float = 0.0
    seconds: float = 0.0


class Stop(BaseEvent):
    event_type: Literal["stop"] = "stop"
    stop_reason: str                    # S1|S2|S3|S4
    numbers: dict[str, Any] = Field(default_factory=dict)


Event = Annotated[
    Union[
        ToolCall, LLMCall, PhaseTransition, CandidateScore, Merge, Rejection,
        VariantDiscovered, RoleResolution, Disconfirmation, GateTest, GateDecision,
        FrontierUpdate, PlannerDecision, Reinforce, SlotUpdate, ConflictDetected,
        BudgetUpdate, Stop,
    ],
    Field(discriminator="event_type"),
]

EVENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(Event)

ALL_EVENT_TYPES = (
    ToolCall, LLMCall, PhaseTransition, CandidateScore, Merge, Rejection,
    VariantDiscovered, RoleResolution, Disconfirmation, GateTest, GateDecision,
    FrontierUpdate, PlannerDecision, Reinforce, SlotUpdate, ConflictDetected,
    BudgetUpdate, Stop,
)


def parse_event(data: dict[str, Any]) -> BaseEvent:
    """Round-trip a serialized event back into its concrete model."""
    return EVENT_ADAPTER.validate_python(data)
