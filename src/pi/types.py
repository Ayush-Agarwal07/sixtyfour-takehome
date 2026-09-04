"""Core domain models. Pydantic only — no behavior.

Mirrors plan/reference-contracts.md §2. Every downstream module builds against
these; do not change a shape without updating that reference file first.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Regime = Literal[
    "HARD_ID_URL", "HARD_ID_EMAIL", "NAME_STRONG",
    "DEFINITE_DESC", "NAME_WEAK", "BARE_NAME",
]
Status = Literal["confirmed", "ambiguous", "abstained", "failed"]

NodeType = Literal["person", "company", "account", "product", "domain", "event"]
EdgeType = Literal[
    "employment", "ownership", "authorship", "affiliation", "derivation", "relationship",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────── confidence / temporal ───────────────────────
class Term(BaseModel):
    factor: str
    weight: float


class Confidence(BaseModel):
    score: float                       # sigmoid(logodds)
    logodds: float
    terms: list[Term] = Field(default_factory=list)


class Temporal(BaseModel):
    start: Optional[date] = None
    end: Optional[date] = None
    end_state: Literal["ongoing", "unknown", "ended"] = "unknown"
    precision: Literal["year", "month", "day"] = "year"
    context_date: Optional[date] = None


# ─────────────────────────── evidence / claims ───────────────────────────
class Evidence(BaseModel):
    evidence_id: str
    candidate_id: str                  # written AT WRITE TIME — the isolation invariant
    url: str                           # original (cited) URL
    snippet: str
    retrieved_at: datetime = Field(default_factory=_utcnow)
    source_class: str
    extraction_method: str


class Claim(BaseModel):
    id: str
    predicate: str                     # closed vocab (reference-contracts §4)
    value: str                         # canonicalized
    value_raw: str
    temporal: Temporal = Field(default_factory=Temporal)
    confidence: Confidence
    attachment_confidence: float = 1.0
    identity_link: str                 # reference-contracts §5
    evidence: list[Evidence] = Field(default_factory=list)


# ─────────────────────────────── understand ──────────────────────────────
class Variant(BaseModel):
    form: str
    kind: Literal["as_given", "diacritic_stripped", "initials", "order_swap", "nickname"] = "as_given"
    weight: float = 0.0


class Seed(BaseModel):
    input: str
    regime: Regime
    names: list[Variant] = Field(default_factory=list)
    hard_ids: dict[str, str] = Field(default_factory=dict)   # email/url/phone/domain/handle
    orgs: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    schools: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    tense: dict[str, str] = Field(default_factory=dict)      # org (lowercase) -> current|former
    role_description: Optional[str] = None
    org_domains: dict[str, str] = Field(default_factory=dict) # org -> registrable domain (resolve_company)
    original_regime: Optional[Regime] = None                  # set when DEFINITE_DESC is rewritten

    @property
    def anchor_domains(self) -> set[str]:
        return set(self.org_domains.values()) | {o.lower() for o in self.orgs if "." in o}


# ──────────────────────────────── resolve ────────────────────────────────
class AttrObservation(BaseModel):
    """Types′ — an attribute value AND the source it came from, so identity
    scoring can weight by tier. A plain dict cannot express this; do not flatten.
    """
    value: str
    source_class: str
    source_tier: float                 # identity tier for this source (constants.IDENTITY_TIER)
    url: str
    snippet: str
    category: Literal["exact_match", "matches_former", "partial"] = "exact_match"
    kind: Literal["snippet", "page"] = "snippet"


class SourceText(BaseModel):
    """Evidence text attached to a candidate: a SERP snippet or a fetched page excerpt."""
    url: str
    kind: Literal["snippet", "page"] = "snippet"
    source_class: str = "unknown"
    tier: float = 0.8
    text: str = ""


class Candidate(BaseModel):
    cid: str
    urls: list[str] = Field(default_factory=list)             # identity-bearing pages of this person only
    handles: dict[str, str] = Field(default_factory=dict)     # platform -> handle
    identity_keys: list[str] = Field(default_factory=list)    # "linkedin:slug", "github:user", "site:domain"
    sources: list[SourceText] = Field(default_factory=list)   # evidence texts (snippets + fetched pages)
    attrs: dict[str, list[AttrObservation]] = Field(default_factory=dict)  # predicate -> matched observations
    negatives: list[Term] = Field(default_factory=list)       # contradictions etc. (matcher output)
    score: Confidence
    reciprocal: bool = False           # a verified mutual link merged into this candidate (§4.7)
    anchored_one_way: bool = False     # fetched official/self-pub page links this candidate's unfetchable profile
    hard_key: Optional[str] = None     # constants.IDENTITY_HARD_KEYS key
    name_form: str = "exact"
    merged_from: list[str] = Field(default_factory=list)
    rejected_reason: Optional[str] = None


class Link(BaseModel):                 # identity links (C19 — replaces the identity graph)
    from_url: str
    to_url: str
    mechanism: Literal["reciprocal", "anchored_one_way", "one_way", "co_citation"]
    section: Literal["prose", "sidebar", "nav", "footer"] = "prose"


class Resolution(BaseModel):
    status: Status
    confirmed_cid: Optional[str] = None
    candidates: list[Candidate] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    how_confirmed: str = ""
    what_would_disambiguate: list[str] = Field(default_factory=list)
    reason: str = ""                   # for abstained/ambiguous/failed


# ─────────────────────────── graph / frontier ────────────────────────────
class GraphNode(BaseModel):
    id: str
    type: NodeType
    label: str
    depth: int = 0
    attachment_confidence: float = 1.0


class GraphEdge(BaseModel):
    id: str
    src: str
    dst: str
    type: EdgeType
    mechanism: str
    evidence_ids: list[str] = Field(default_factory=list)


class FrontierItem(BaseModel):
    # Frontier′: a plain list item. No cost/score — the planner ranks. `relevance`
    # is only a cheap on-target filter + pre-sort key (constants.SECTION_MULT).
    id: str
    action: str        # search|fetch|github|github_emails|gravatar|wayback|exa_contents|verify
    args: dict[str, Any] = Field(default_factory=dict)
    origin: Literal["link", "slot_template", "planner", "reinforce"]
    open_slot: Optional[str] = None
    relevance: float = 0.0
    why: str = ""


class Slot(BaseModel):
    name: str
    target: int
    current: int = 0
    barren_fetches: int = 0
    closed: bool = False


class Conflict(BaseModel):
    kind: Literal["soft", "hard", "identity"]
    predicate: str
    values: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    severity: float = 0.0
    note: Optional[str] = None


class Findings(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    slots: list[Slot] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    stop_reason: Optional[str] = None


# ──────────────────────────────── output ─────────────────────────────────
class SummarySentence(BaseModel):
    text: str
    claim_ids: list[str] = Field(default_factory=list)   # ≥1 or the sentence is dropped


class Profile(BaseModel):
    current_role: Optional[Claim] = None
    employment: list[Claim] = Field(default_factory=list)
    education: list[Claim] = Field(default_factory=list)
    location: Optional[Claim] = None
    contact: list[Claim] = Field(default_factory=list)
    accounts: list[Claim] = Field(default_factory=list)
    public_output: list[Claim] = Field(default_factory=list)
    relationships: list[Claim] = Field(default_factory=list)
    notable: list[Claim] = Field(default_factory=list)


class Identity(BaseModel):
    confidence: Confidence
    cid: Optional[str] = None
    hard_keys: list[str] = Field(default_factory=list)
    how_confirmed: str = ""
    public_figure: bool = False
    footprint_since: Optional[str] = None   # earliest timeline year, e.g. "2013"
    accounts_found: int = 0                 # distinct handle claim values, confidence >= 0.5


class CandidateResolutionView(BaseModel):
    cid: str
    score: float
    terms: list[Term] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)


class RejectedView(BaseModel):
    cid: str
    reason: str


class IdentityResolution(BaseModel):
    candidates: list[CandidateResolutionView] = Field(default_factory=list)
    rejected: list[RejectedView] = Field(default_factory=list)
    what_would_disambiguate: list[str] = Field(default_factory=list)


class Graph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class TimelineEntry(BaseModel):
    date: str          # "YYYY" or "YYYY-MM" from the claim's temporal precision
    text: str          # "{predicate}: {value_raw}" (+ " (ended {YYYY})" when ended)
    claim_id: str
    url: str           # first evidence url


class RunMetadata(BaseModel):
    job_id: str
    budget: dict[str, Any] = Field(default_factory=dict)   # tool_calls, llm_calls, usd, seconds
    stop_reason: Optional[str] = None
    models: dict[str, Any] = Field(default_factory=dict)
    timings: dict[str, Any] = Field(default_factory=dict)


class Output(BaseModel):
    status: Status
    input: str
    seed: Optional[Seed] = None
    regime: Optional[Regime] = None
    identity: Optional[Identity] = None
    summary: list[SummarySentence] = Field(default_factory=list)
    profile: Profile = Field(default_factory=Profile)
    # attachment_confidence < ATTACH_PROFILE: real claims about a possibly different person
    unverified: list[Claim] = Field(default_factory=list)
    graph: Graph = Field(default_factory=Graph)
    conflicts: list[Conflict] = Field(default_factory=list)
    negative_findings: list[dict[str, Any]] = Field(default_factory=list)
    identity_resolution: IdentityResolution = Field(default_factory=IdentityResolution)
    specialization_payoff: list[str] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    run_metadata: Optional[RunMetadata] = None


# ─────────────────────────────── casefile ────────────────────────────────
class Casefile(BaseModel):
    """The durable, atomically-written state of one run."""
    job_id: str
    input: str
    status: Status = "failed"
    phase: Literal["understand", "resolve", "expand", "synthesize", "done"] = "understand"
    seed: Optional[Seed] = None
    resolution: Optional[Resolution] = None
    findings: Optional[Findings] = None
    output: Optional[Output] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
