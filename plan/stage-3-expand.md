# Stage 3 — Deepen EXPAND + Findings Quality

**Owner:** parallel agents (2). **~5h — this is where slack goes.** **Prereqs:**
Stage 2 green (can start against a stubbed confirmed candidate).
**Builds against:** [reference-contracts.md](reference-contracts.md), [reference-confidence-scoring.md](reference-confidence-scoring.md).

EXPAND is where **Findings Quality** (co-top-weighted) and the **agentic loop**
(the planner) live. RESOLVE is already strong; spend extra time here.

## Scope

Build the findings graph rooted at the confirmed person. **No merging occurs
here.** The planner is the visible agentic decision; the wow-sources are the
"how did it find that" payoff.

### Workstream A — graph + frontier + planner (the agentic loop)

```
expand/{graph.py, frontier.py, planner.py, slots.py, expander.py}
```

- `graph.py` — nodes/edges per [reference-contracts.md](reference-contracts.md) §2; content-derived IDs; every edge carries `mechanism`; root-to-node path **is** the provenance chain.
- `frontier.py` (Frontier′) — builds a **plain list**, no multiplicative score, no cost/class_prior/yield_prior tables, no SQLite. Each item = `{action, args, open_slot, relevance, why}`. `relevance` is a **cheap on-target filter, not a ranking model**: Case A (SERP) = normalized count of matched confirmed-candidate anchors; Case B (link on a fetched page) = `parent_attachment × section_mult` (prose 1.0 / sidebar 0.6 / nav·footer 0.2). Drop items below `FRONTIER_RELEVANCE_FLOOR` so the planner isn't flooded with junk. A one-line pre-sort (open-slot match, then relevance) orders the list **only to populate `formula_top` for the trace contrast**. The planner does the real ranking.
- `planner.py` (C4) — the **decider**. T1-class, reasoning on. Input: slot table, pre-sorted frontier top-12 `{action, open_slot, relevance, why}`, graph summary ≤40 nodes, last batch's new claims (one line each), open conflicts, budget. Output: `{picks[≤4], new_actions[≤2]{tool,args,hypothesis,slot}, close_slots[], distrust[claim_id], stop, reasoning}`; total executed ≤4. Emit `planner_decision{formula_top (the cheap pre-sort), chosen, reasoning}` — the sort-vs-chosen contrast still shows strategy.
- Reinforce (C7) — any node with `descendants ≥3 ∧ attachment <0.6` generates a `verify(node)` item ranked first, surfaced to the planner; **forced** if the planner skips it twice. Fallback: reserve 20% of EXPAND calls.
- `slots.py` — coverage slots: `identity_anchors(≥1 hard key) · current_role(1, corroborated) · employment_history(≥3) · education(≥1) · contact(≥1 verified) · public_output · social_graph · notable_artifacts`. Close at target or after 3 barren fetches aimed at it. Static domain_class → slots table.
- `expander.py` — the batch loop (k=4): refresh frontier → planner → execute in parallel under semaphores/timeouts → extraction → assembly → update slots/yield/budget → check S1–S3. `EXPAND_cap = min(40, 60 − resolve_spent)` (Budget′). Planner latency counted against wall clock.

### Workstream B — extraction + assembly + Findings Quality

```
expand/extract/{ladder.py, jsonld.py, github_parse.py, linkedin_snippet.py, prose_llm.py}
score/{claim_score.py, temporal.py, canonical.py, conflicts.py}
expand/assemble.py
```

- Extraction ladder (C20): JSON-LD/OpenGraph (`extruct`) → GitHub API parse → LinkedIn SERP snippet parser → prose LLM. **Skip the model entirely when a structured rung produced the fields.** Extractor returns **tuples** `(predicate, value_raw, span, extraction_rung, context_date)` + `(url, anchor_text, section)` for links — a pure function of `(page_text, target_context)`, testable with a fixture.
- `prose_llm.py` — window ±1.5k chars around each name-variant occurrence, cap 6k (C14). **Span check:** every prose span must be a substring of the page (or rapidfuzz partial ≥0.9) or it is **dropped**. This is the primary anti-fabrication guard.
- `assemble.py` — tuples → `Claim`s: canonicalize value ([reference-contracts.md](reference-contracts.md) §4), parse `Temporal` ([reference-confidence-scoring.md](reference-confidence-scoring.md)), attach provenance, set `identity_link` (incl. `graph_path:{hops}` from a hard-key node), score confidence. **Other-person rule:** facts about non-target people → unresolved `person` nodes, **relationship claims only** (name as written + relationship edge + evidence), never their bio/employment/contact. The claim is about the **target** (`target --co_founder_with--> Jane`), stays inside the isolation invariant. Their name + company domain becomes a **planner-visible pivot query**.

### Findings Quality highlights (spend the slack here)

- **commit-email → employer (Findings′, never-cut):** historical commit authored from `@company.com` → `resolve_company(domain)` → `employment` claim, mechanism `"authored commits from company email domain, {year}"`. Tag in `specialization_payoff`.
- **Wayback team pages:** recover roles deleted when someone left.
- **Gravatar pivot:** `md5(email)` → profile → accounts.
- Waste controls: domain early-stop (3 fetches, no new claims); depth cap 2 (exception to 3 for reciprocal verification); **orchestrator sees claims (~100 tokens each), never raw page text** — the primary cost control.

### C6′ — downstream identity conflicts

On an EXPAND page contradicting the confirmed identity on an **immutable**
predicate: quarantine the subtree (`attachment_confidence = 0`), list in
`conflicts`, set `identity_contested = true`. ≥2 independent → `status:
confirmed_contested`. **Never abort to `abstained`.**

## Tests

- `test_extract_span_check.py` — a fixture page; a tuple whose span isn't in the text (partial <0.9) is dropped.
- `test_isolation.py` — evidence keyed to a `cid ≠ confirmed_cid` never appears in any output claim.
- `test_temporal.py`, `test_claim_spread.py` — see [reference-confidence-scoring.md](reference-confidence-scoring.md).
- `test_frontier.py` — Case B section multipliers applied; a reinforce item ranks first when its trigger holds.

## Checkpoints (binary)

- [ ] On a stubbed confirmed candidate, **coverage slots fill** and close correctly; budget respected (`EXPAND_cap = min(40, 60−resolve_spent)`).
- [ ] Trace contains **≥1 planner-injected `new_actions` query** and **≥1 `verify`/reinforce action**, with `planner_decision` showing formula-top vs chosen.
- [ ] `test_isolation` green: **no** evidence for a non-confirmed cid ever enters output claims.
- [ ] `test_extract_span_check` green: unverifiable prose spans dropped.
- [ ] **≥1 `specialization_payoff` claim** produced on a real run (ideally the commit-email→employer inference).
- [ ] `test_claim_spread` produces 0.96 / 0.85 / **0.12** (sub-0.3 reachable).
- [ ] A C6′ scenario (injected immutable-predicate conflict) → subtree quarantined + `identity_contested`, **status stays confirmed/confirmed_contested**, never abstained.
- [ ] Orchestrator context stays flat across batches (it receives claim summaries, not raw page text) — spot-check the planner prompt payload.

## Degrade / cut behavior

Never cut: planner `picks`, verify/reinforce, commit-email→employer, span check,
`identity_link`, isolation. Cut order under pressure: planner `new_actions` (keep
`picks`) → Wayback/Gravatar → LinkedIn snippet parser (fall back to prose LLM).
