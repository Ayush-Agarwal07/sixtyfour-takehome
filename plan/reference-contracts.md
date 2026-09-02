# Reference — contracts

The data shapes, vocabulary, routing, and infra everything else builds against.
**Stage 0 implements this file.** Stages 1–5 build against it and must not
change a contract without updating this file first.

---

## 1. Phase contracts

Every phase is `async def phase(state, deps) -> state`, writes the casefile on
return, and never reaches outside `deps`.

```python
understand(input: str, deps) -> Seed
resolve(seed: Seed, deps)      -> Resolution   # {status, confirmed_cid|None, candidates[], links[], budget}
expand(resolution, deps)       -> Findings     # {graph, claims[], slots, conflicts[], stop_reason}
synthesize(findings, deps)     -> Output
```

`run.py` owns budget, stop conditions, phase transitions, trace, casefile.
`Deps(http, llm, cache, trace, sqlite=None, semaphores)` is constructor-injected
into each phase (test seam).

---

## 2. Core types (`src/pi/types.py`, Pydantic only)

```python
Regime = Literal["HARD_ID_URL","HARD_ID_EMAIL","NAME_STRONG",
                 "DEFINITE_DESC","NAME_WEAK","BARE_NAME"]
Status = Literal["confirmed","confirmed_contested","ambiguous","abstained","failed"]

class Temporal(BaseModel):
    start: date | None = None
    end: date | None = None
    end_state: Literal["ongoing","unknown","ended"] = "unknown"
    precision: Literal["year","month","day"] = "year"
    context_date: date | None = None

class Confidence(BaseModel):
    score: float          # sigmoid(logodds)
    logodds: float
    terms: list[Term]     # {factor: str, weight: float}

class Evidence(BaseModel):
    evidence_id: str
    candidate_id: str     # written AT WRITE TIME — the isolation invariant
    url: str              # original (cited) URL
    snippet: str
    retrieved_at: datetime
    source_class: str     # see §3
    extraction_method: str

class Claim(BaseModel):
    id: str
    predicate: str        # closed vocab, §4
    value: str            # canonicalized
    value_raw: str
    temporal: Temporal
    confidence: Confidence
    attachment_confidence: float
    identity_link: str    # §5
    evidence: list[Evidence]

class Seed(BaseModel):
    input: str
    regime: Regime
    names: list[Variant]  # {form, origin: "parsed"|"discovered", evidence_id?, weight}
    hard_ids: dict        # email / url / phone / domain / handle
    orgs: list[str]; titles: list[str]; schools: list[str]; locations: list[str]
    tense: dict           # predicate -> "current"|"former"
    role_description: str | None

class AttrObservation(BaseModel):     # Types′ — carries the source so scoring can weight by tier
    value: str
    source_class: str
    source_tier: float                # anchor tier for this source (§3)
    url: str
    snippet: str

class Candidate(BaseModel):
    cid: str
    urls: list[str]
    handles: dict
    attrs: dict[str, list[AttrObservation]]   # predicate -> observations; each carries its source tier.
                                              # A plain `dict` cannot express source-weighted scoring — do not flatten.
    score: Confidence     # identity log-odds
    rejected_reason: str | None = None

class Link(BaseModel):          # identity links (C19 — replaces the identity graph)
    from_url: str; to_url: str
    mechanism: str              # "reciprocal"|"anchored_one_way"|"one_way"
    section: str                # "prose"|"sidebar"|"nav"

# Graph (findings):
class GraphNode(BaseModel):
    id: str; type: Literal["person","company","account","product","domain","event"]
    label: str; depth: int
    attachment_confidence: float; parent_edge_id: str | None
class GraphEdge(BaseModel):
    id: str; src: str; dst: str
    type: Literal["employment","ownership","authorship","affiliation","derivation","relationship"]
    mechanism: str; evidence_ids: list[str]

class FrontierItem(BaseModel):     # Frontier′ — plain list item; the planner ranks
    id: str
    action: str          # search|fetch|github|github_emails|gravatar|wayback|exa_contents|verify
    args: dict
    origin: Literal["link","slot_template","planner","reinforce"]
    open_slot: str | None            # which open slot this would serve
    relevance: float                 # cheap on-target filter + pre-sort key, NOT a cost/score
    why: str

class Slot(BaseModel):
    name: str; target: int; current: int; barren_fetches: int; closed: bool
```

Content-derived IDs (no per-run UUIDs): root by `cid`; company by registrable
domain; account by canonical URL; unresolved person by
`person:unresolved:{slug}:{context_hash}`; claim/evidence/edge by
`sha256(canonical fields)[:16]`.

---

## 3. Source classes & tiers

Classes (9): `code_host · professional_network · social · personal_site ·
company_site · academic · government_registry · press · aggregator`.

Identity anchor tier weights (used in [reference-identity-scoring.md](reference-identity-scoring.md)):
`official_org 2.5 · self_published 2.0 · professional_network_snippet 1.2 ·
press 1.0 · aggregator 0.5`.

Claim source tiers (used in [reference-confidence-scoring.md](reference-confidence-scoring.md)):
`official_org +2.5 · self_published +2.2 · reputable_secondary +1.4 ·
syndicated_aggregator +0.2 (never sole support)`. (Breach and model-inference
tiers removed — see C13.)

Unfetchable set (never spend a fetch; SERP snippet + Exa contents only):
`{linkedin, x/twitter, facebook, instagram, crunchbase, threads}`.

---

## 4. Closed predicate vocabulary (C23)

`employer · title · employment(org,title,temporal) · education(school,degree,temporal)
· location · email · phone · website · handle(platform) · repo · publication ·
talk · award · funding_event · board_or_advisor · founded · relationship(kind) ·
other(tag)`. `other` never fills a coverage slot.

**Canonicalization (before corroboration):** employer → registrable domain via
`resolve_company` cache; school → lowercase, strip "university of"/"the"; title →
lowercase, strip seniority noise; handle → lowercase; dates → `Temporal`.
Corroboration keys on `(predicate, canonical_value)`.

---

## 5. `identity_link` values (highest-leverage field)

Answers *is this source about the target?* — not *did the source say this?*

- `hard_key:{type}` — page is a hard-key page (confirmed GitHub profile, official team page, seed URL)
- `anchor_match:{attrs}` — SERP-matched on named attributes
- `graph_path:{hops}` — reached via a link chain from a hard-key node
- `inferred` — **only** allowed inside `inferences[]`, never on a `Claim`

---

## 6. Output envelope

```
status: confirmed | confirmed_contested | ambiguous | abstained | failed
input, seed, regime
identity: {confidence, cid, hard_keys[], how_confirmed, public_figure, identity_contested}
summary: [{text, claim_ids[]}]          # every sentence cites ≥1 claim or is dropped
profile: {current_role, employment[], education[], location, contact[], accounts[],
          public_output[], relationships[], notable[]}   # each entry is a Claim
graph: {nodes[], edges[]}
conflicts[], negative_findings[], inferences[]
identity_resolution: {candidates[{cid, score, terms[], urls[]}],
                      rejected[{cid, reason}], what_would_disambiguate[]}
specialization_payoff: [claim_ids whose sole source was github_emails|wayback|gravatar|reciprocal|commit_email]
run_metadata: {job_id, budget{tool_calls, llm_calls, usd, seconds}, stop_reason, models{}, timings{}}
```

---

## 7. Trace events (JSONL, one per line; `@traced` on every tool)

`tool_call · llm_call{model,tier,prompt_ref,response_ref,usage,cost_usd,latency_ms,cache_hit,reasoning_ref}
· phase_transition · candidate_score · merge · rejection · variant_discovered ·
role_resolution · disconfirmation{hypothesis,actions,result} · gate_test ·
gate_decision · frontier_update · planner_decision{formula_top,chosen,reasoning} ·
reinforce · slot_update · conflict_detected · budget_update · stop`

Each event has a fixed Pydantic model + optional `note: str`. Reasoning tokens →
sidecar `reasoning/{event_id}.txt`, referenced by `reasoning_ref`. Non-reasoning
tiers carry a mandatory `reasoning` string in their structured output, stored in
the same sidecar. `trace/render.py` turns JSONL → `trace.md` (per phase, per
decision, tool table with latencies).

---

## 8. Model routing (OpenRouter; slugs/prices verified in Stage 1, in `constants.py`)

| Tier | Tasks | Model class | Notes |
|---|---|---|---|
| T1 | identity gate, disconfirmation, planner | Sonnet-class **with reasoning**, same-tier secondary | fires ~2 (gate/disconfirm) + per-batch (planner); do not economize |
| T2 | synthesis, conflict narration | Sonnet-class | long-context coherence, no embellishment |
| T3 | page → claims extraction | Gemini-Flash-class (cheap, schema-reliable) | 60–70% of spend; truncate + window before |
| T4 | attribute-match categorical (batched) | Gemini-Flash-class | one call per ≤10 candidates |
| T5 | input parse, role_resolve | Gemini-Flash-class | one call/run |

Structured output via `instructor` `create_with_completion` (keeps raw response
for reasoning/usage). Retries: 3 validation / 2 rate-limit / 0 refusal. Cost from
OpenRouter response headers, never estimated. **Failure policy:** extraction
failure non-fatal (zero claims, continue); T1 gate failure → secondary model,
then ABSTAIN (never a weaker fallback); synthesis retries then fails.

---

## 9. Concurrency & infra

Process-wide semaphores: `Serper 5 · Exa 3 · Firecrawl 2 · OpenRouter 8 ·
generic fetch 10`. Timeouts: `fetch 8s · Firecrawl 20s · Wayback 15s · LLM 60s`.
Concurrency (Concurrency′): max **3 concurrent *running* jobs** (a job
semaphore); further submissions are accepted (`202`) and **queue**; `429` only
when in-flight (running + queued) exceeds `MAX_INFLIGHT` (env, default 10). So
"submit 5 → all complete, ≤3 running at once" and "429 past the ceiling" are both
true and non-contradictory.

Cache: `diskcache` at `.cache/http/` keyed by normalized URL (scheme+host
lowercased, force https, strip `www.`, drop fragment, drop `TRACKING_PARAMS`,
sort remaining, strip trailing slash), TTL by class (structured API 6h ·
official/self-published 7d · press 30d · aggregator 1d · Wayback/EDGAR ∞).
`.cache/llm/` keyed `(model, sha256(prompt+schema))`, no TTL. `PI_NO_CACHE=1`
disables both (honest variance runs); `PI_OFFLINE=1` makes misses raise (replay).
Store under normalized key, **cite the original URL** in evidence.

`TRACKING_PARAMS = {utm_source,utm_medium,utm_campaign,utm_term,utm_content,
fbclid,gclid,msclkid,mc_cid,mc_eid,ref,source,_ga}`.

Workspace: `runs/{job_id}/` → `casefile.json` (atomic: temp + `os.replace`),
`trace.jsonl`, `evidence/`, `candidates/{cid}/`, `reasoning/`.

---

## 10. Budget & stop conditions (single source of truth)

- Budget unit = **tool round trip** (search query, fetch, API call). LLM calls
  tracked by count and `$` separately.
- Regime caps (RESOLVE): HARD_ID 12 · NAME_STRONG 20 · DEFINITE_DESC 24 ·
  NAME_WEAK 30 · BARE_NAME 10.
- **Counting (Budget-count′):** enumeration is **one** Serper batch (+ ≤1 Exa) =
  ≤2 round trips, *not* 8; `resolve_company` runs first = 1.
  `resolve_budget = min(4 + 2·n_candidates, cap)` is computed **after**
  enumeration reveals `n_candidates`, and counts **all** RESOLVE round trips
  inclusive (canonicalization + enumeration + verification). The base 4 pays for
  `resolve_company` + enumeration; the `+2n` pays for the k=2 verification
  fetches, reciprocal checks, and disconfirmation actions. Exceeding the cap
  escalates it and logs the reason.
- `EXPAND_cap = min(40, 60 − resolve_spent)` (Budget′).
- Stops: **S1** all slots closed · **S2** confirmed claims/tool-call < 0.25 over
  trailing 8, only after ≥16 EXPAND calls · **S3** 40 EXPAND / 60 total / 180s
  soft / 300s hard / $0.75 hard, $0.50 soft (stop expanding, spend rest on
  synthesis) · **S4** gate unmet after resolve cap. Log which fired, with numbers.
