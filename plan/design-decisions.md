# Design decisions & changelog

Three layers, newest last: the original locked decisions (D), the red-team
changes made against the spec (C), and the deltas confirmed in review (′).
**Object to any row before building; the code assumes all of these.**

---

## Layer 1 — Locked decisions (D1–D12)

| # | Decision | Rationale |
|---|---|---|
| D1 | Take-home scope, filesystem state, no DB (one exception: none — SQLite yield priors were cut) | Persistence is +40–60% effort for zero graded benefit. Seam in SCALING.md. |
| D2 | RESOLVE on a flat candidate list; EXPAND on a graph. **No merges after the gate.** | Merging is the hard part of resolution and dangerous on a mutable graph. |
| D3 | Identity links separate from the findings graph | "same person as" and "led to" are different relations. |
| D4 | Multi-entity findings graph (person → company → product) | Chains are where non-obvious findings live. |
| D5 | Floats from deterministic log-odds; terms printed | Ordinally meaningful and auditable. Not frequency-calibrated — stated. |
| D6 | Task-tiered model routing, all via OpenRouter | Single auth path. |
| D7 | Constants module for values; derivation table in DESIGN.md | Clean code, honest docs. |
| D8 | Light eval (~6 targets × runs), no calibration table | Time trade; method documented, data out of scope. |
| D9 | Source-class independence rule, not content hashing | Crude but captures most value, no tuning. |
| D10 | Batched concurrency | Legible trace, no stale-topology problem. |
| D11 | Budget unit = network round trip | Physical, correlates with latency. |
| D12 | Gate: math first, model can veto but not override | False confirm is the worst outcome. |

---

## Layer 2 — Red-team changes from the spec (C1–C24)

Each row is a deliberate divergence from the consolidated spec. The "Why" is the
failure it prevents.

| # | Spec said | Plan does | Why |
|---|---|---|---|
| C1 | Flat identity weights; prior −1.5 for all regimes | Anchor matches weighted by source tier; HARD_ID prior 0; seed URL/email/Gravatar/commit-email are +3.0–3.5 hard keys; +0.8 uniqueness | Spec weights top out "Henry Wang" at 0.71 and a bare LinkedIn URL at 0.73 — both under the 0.85 gate. |
| C2 | Name table conflated rarity and form (nickname +0.8 > exact common +0.2) | Split: rarity (rare +2.0 / uncommon +1.0 / common +0.2 / unknown +0.5) + form penalty (exact 0 / swap −0.2 / nickname −0.4 / initials −0.9) | Spec ranked "Hank Wang" above "Henry Wang". |
| C3 | Tense contradiction −1.5 on any evidence | Only on fetched pages with a context date; 0 on SERP snippets; new T4 category `matches_former` | Stale LinkedIn snippets say "at Figma" → spec scores the true ex-Figma person at 0.17. |
| C4 | Frontier formula picks every EXPAND fetch | Planner call (T1-class) chooses ≤4 actions from top-12 formula-ranked frontier; may add ≤2 hypothesis queries, pick verify, close slots, distrust claims. Formula-top vs chosen logged | Top-weighted criterion requires the LLM to drive research. Formula generates; model chooses. |
| C5 | Disconfirmation answers "what would falsify?" as text | Returns ≤2 executable tool calls; they run; candidates rescored; then gate. `next_evidence` on CONTINUE is likewise executable | Otherwise the call is decoration. Cheapest visibly-agentic decision in RESOLVE. |
| C6 | Identity conflict −3.0 → route back to RESOLVE | **Superseded by C6′ below.** | Route-back violates D2 and §4.10. |
| C7 | Reinforce fires automatically on descendants ≥3 ∧ attachment <0.6 | Same condition generates a `verify` frontier item ranked first, surfaced to the planner; forced if planner skips it twice | Keeps the behavior, makes it a visible model choice, keeps the guarantee. |
| C8 | Display claim × attachment × identity | Identity shown once at top; per-claim shows claim_confidence and attachment_confidence separately | Multiplying identity into every claim caps the profile at the identity number and reads under-confident. |
| C9 | Kill mid-run, restart, continues | Cut. Casefile written atomically at every phase + every EXPAND batch; on restart, running jobs → `failed_restart`, partial served. Resume design in SCALING.md | Resumable in-flight batches ≈ 1.5 days for a property no grader tests. |
| C10 | Budget = any round trip; full fan-out; caps 6/15/20/30/30 | Budget = tool round trips only. Enumeration ≤8 (one Serper batch), counted. Caps: HARD_ID 12 · NAME_STRONG 20 · DEFINITE_DESC 24 · NAME_WEAK 30 · BARE_NAME 10. EXPAND cap 40. S3 = 60 tool calls / 180s soft / 300s hard / $0.75 | Spec's fan-out (18–30 searches) exceeded its own caps before scoring began. |
| C11 | BARE_NAME cap 30, expect ABSTAIN | One enumeration pass; census-common surname ∧ ≥3 clusters → `ambiguous` with a disambiguation table immediately | 30 calls to abstain is waste; a candidate table is a better answer. |
| C12 | Hard temporal conflict = two ongoing overlapping >60d | Only two ongoing **full-time employment** claims; founder+advisor / exec+board are soft. Identity conflict = contradiction on an **immutable** predicate only (hard-key mismatch, birth year, degree year) | Concurrent roles are normal; spec would flag them hard. |
| C13 | "Model inference −0.5" source tier | Removed. Every claim needs a page span. Synthesis inferences go in a separate unscored `inferences[]` | Claims without spans are the fabrication path. |
| C14 | Truncate page to 6k tokens | Window ±1.5k chars around each name-variant occurrence, cap 6k; prose-LLM spans must be substring-verified (or rapidfuzz partial ≥0.9) or dropped | Head-truncation loses the target on team pages; span check is the strongest anti-fabrication guard. |
| C15 | T1 failure → ABSTAIN, no fallback | Same-tier secondary model first, then ABSTAIN | An OpenRouter blip on one model shouldn't abstain a well-resolved run. |
| C16 | Temperature 0 everywhere | Temp 0 on T2–T5; T1 uses a reasoning-capable model with reasoning on, no temperature param | Reasoning models reject temperature; reasoning tokens are a stated trace requirement. |
| C17 | Same handle across platforms → same bucket | Handle merge only when handle is rare (≥6 chars, not a bare first name/common word); else separate; reciprocal verification is the merge mechanism | `jsmith` on GitHub and X are different people often enough to blend profiles. |
| C18 | Tier-separated lanes | Single k=4 batch, per-tool timeouts, slow fetches deferred to Firecrawl next batch | Lanes are complexity for marginal throughput at this scale. |
| C19 | Identity graph as separate graph structure | A `links[]` table on the casefile (from_url, to_url, mechanism, section); reciprocal check is a query over it | Same concept, a tenth of the code. |
| C20 | Ladder incl. HTML table, Crunchbase, faculty, VLM | JSON-LD/OpenGraph → GitHub API → LinkedIn SERP snippet parser → prose LLM | Crunchbase unfetchable; the rest low yield for the time. |
| C21 | (not in spec) | Unfetchable set {linkedin, x/twitter, facebook, instagram, crunchbase, threads}: never spend a fetch; SERP snippet + Exa contents only. Fetched official/self-published page → unfetchable profile = `anchored_one_way` +1.5 | Reciprocal links unreachable for the platforms most people have; honest substitute. |
| C22 | (not in spec) | Hosted API requires `X-API-Key`; per-job hard $0.75; daily job cap env var. **Concurrency superseded by Concurrency′ below.** | Otherwise the $100 key is public. |
| C23 | (not in spec) | Closed predicate vocabulary and value canonicalization before corroboration | Corroboration and slots are undefined without them. |
| C24 | (not in spec) | `abstained`/`ambiguous` return the same envelope with `identity_resolution.candidates[]` and `what_would_disambiguate[]` | ABSTAIN must still be a useful, typed answer. |

---

## Layer 3 — Confirmed deltas from review (′)

These supersede or extend the rows above.

| # | Change | Supersedes | Detail |
|---|---|---|---|
| **C6′** | Downstream identity conflicts → **quarantine + flag, never abort** | C6, C9's abort path | On an EXPAND page contradicting the confirmed identity on an immutable predicate: set the subtree `attachment_confidence = 0`, list in `conflicts`, set `identity_contested = true`. ≥2 independent identity conflicts → `status: confirmed_contested` (a distinct status), **not** `abstained`. A passed gate is never un-confirmed by weak downstream links. |
| **Regime′** | Drop the headcount≤5k test from "strong org" | C10 regime rule | Resolvable company domain → NAME_STRONG by default. Downgrade to NAME_WEAK only for a small **known-huge stoplist** (FAANG-tier: google, meta, amazon, apple, microsoft, netflix, etc.) or an unresolvable org (logged). Removes dependency on flaky headcount extraction; correct for all 4 canonical inputs. |
| **Findings′** | Wire commit-email → employer inference | extends C20/high-yield | Historical commit authored from `@company.com` → `resolve_company(domain)` → emit `employment` claim, mechanism `"authored commits from company email domain, {year}"`. Tag in `specialization_payoff`. This is the single best "how did it find that." Never-cut. |
| **Gate-loop′** | Cap RESOLVE gate cycles at 2 | extends C5/gate | disconfirm→rescore→gate→CONTINUE→execute→rescore→gate at most twice, then force a decision. Prevents thrash at the budget edge. |
| **Budget′** | `EXPAND_cap = min(40, 60 − resolve_spent)`, enforced in `run.py`; planner latency counted against wall clock | extends C10 | The 60-total actually binds even for NAME_WEAK (resolve 30 + expand 40 = 70 > 60). Planner is a T1 call between batches — it eats wall clock, not the tool-call budget; budget it explicitly. |
| **DESIGN′** | Document the `+0.8 uniqueness` term's trivial satisfaction in single-candidate HARD_ID runs | extends C1 | In DESIGN.md, state that with one candidate the uniqueness term is trivially true and contributes +0.8 without disambiguation work — part of why HARD_ID confirms fast. Keeps the arithmetic honest. |
| **Example′** | (optional) add `4_sarah_chen` example showing `ambiguous` + disambiguation table | extends deliverables | Showcases the margin gate and a correct *refusal* — a differentiator. Only if Stage 5 has slack. |
| **Cluster′** | Clustering merges **only** on identity-bearing co-occurrence (same URL / rare handle / email / personal domain); **never** on a shared attribute token | fixes spec §4.3 | A "shared rare token" that is an employer/school blends two same-name people at one org and pre-empts the gate — the one actively-wrong rule. |
| **Unique′** | Uniqueness (+0.8) fires when this candidate is the only one with any ≥prof-tier anchor, **or** the only one with ≥2 anchor matches, **or** the only one with an official_org match | fixes C1 | Old wording denied the +0.8 that the `andrew.goering` and `jsmith` worked rows use; new wording keeps every worked row and still gives the two Sarah Chens none. |
| **Budget-count′** | Enumeration = 1 Serper batch (+≤1 Exa) ≤2 round trips; `resolve_budget = min(4+2n, cap)` computed **after** enumeration, counting all RESOLVE round trips inclusive | clarifies C10 | Removes the "budget smaller than the enumeration it must pay for" circularity. |
| **Concurrency′** | Max 3 concurrent **running** jobs (semaphore); submissions queue (`202`); `429` only beyond `MAX_INFLIGHT` (default 10) | fixes C22 | "5 complete" and "429 beyond 3" contradicted; running-cap + queue + high 429 ceiling reconciles both. |
| **Types′** | `Candidate.attrs: dict[str, list[AttrObservation]]`, each observation carrying `source_class` + `source_tier` + `url` + `snippet` | fixes types | A plain `attrs: dict` cannot carry per-source tiers, so the source-weighted identity scoring you approved was unimplementable from the types. |
| **Frontier′** | EXPAND frontier is a plain relevance-sorted list; the **planner ranks**. Dropped the multiplicative `p×slot×prior/cost` formula, the `class_prior`/`yield_prior`/cost tables, and `λ`. Kept a cheap on-target filter (anchor/section) + a one-line pre-sort for the trace contrast | simplifies §5.2 / Stage 3 (ponytail) | Two stacked ranking systems for one decision; the formula was the least-agentic part and needed calibration nobody has time for. No deliverable changes; net-positive on Agentic Behavior. |

---

## Build-time checks — resolved in Stage 1

1. **Exa `contents` on LinkedIn → ✅ YES.** Returns the full profile as clean
   structured text (headline, location, a real Experience section with roles +
   dates + company metadata; ~16k chars). This is the read path for the
   `professional_network` class in RESOLVE and EXPAND — wired via `tools/exa.py`,
   used whenever a candidate URL is on an unfetchable host.
2. **`resolve_company` → deferred to Stage 2.** The HARD_ID_EMAIL slice gets the
   employer domain straight from the email, so the slice never needed it. Build it
   with the NAME_STRONG path (regime classification) in Stage 2.
3. **Model slug → `openai/gpt-4o-mini`** for the whole slice (`constants._SLICE_MODEL`).
   Verified live: json_object structured output works via OpenRouter; ~$0.0003/run.
   Stage 2 splits T1 onto a reasoning model.
