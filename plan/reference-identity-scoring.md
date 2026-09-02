# Reference — identity scoring (the solved table)

Deterministic log-odds. `P = sigmoid(logodds)`. Gate: **P(top) ≥ 0.85**
(logodds ≥ 1.735) **AND** **P(top) − P(runner_up) ≥ 0.30**. Math first; T1 may
veto a pass (→ ABSTAIN/CONTINUE), never override a fail.

The worked rows at the bottom are **test fixtures** — `tests/test_identity_table.py`
asserts each. If a code change moves any row across the gate, the test fails.

---

## Term table

| Term | Weight |
|---|---|
| prior (NAME_STRONG / NAME_WEAK / DEFINITE_DESC / BARE_NAME) | −1.5 |
| prior (HARD_ID_URL / HARD_ID_EMAIL) | 0 |
| seed URL resolves to this candidate | +3.5 |
| seed email displayed on a fetched page of this candidate | +3.5 |
| Gravatar profile for seed email with matching name | +3.0 |
| GitHub commit-email / user-search hit for seed email | +3.0 |
| verified reciprocal link (both ends fetched) | +3.0 |
| anchored one-way link (fetched official/self-pub page → this candidate's unfetchable profile) | +1.5 |
| plain one-way link | +0.5 |
| anchor match = `tier × attr` (per anchor: max over sources, +0.3 per extra independent source, cap +0.6) | see below |
| uniqueness (Unique′): this candidate is the **only** one with any anchor match at ≥ professional_network tier, **or** the only one with ≥2 anchor matches, **or** the only one with an official_org-tier match | +0.8 |
| surname rarity (US Census /100k): rare <10 / uncommon 10–100 / common >100 / not found | +2.0 / +1.0 / +0.2 / +0.5 |
| name form: exact or diacritic-stripped / order swap / nickname / initials | 0 / −0.2 / −0.4 / −0.9 |
| anchor contradicts on fetched official/self-pub page / on snippet | −(tier × 0.6) / −0.5 |
| tense contradiction (fetched page with context date only) | −1.5 |
| hard timeline conflict (two full-time ongoing, overlap >60d, fetched pages) | −2.5 |
| geographic impossibility | −2.0 |

**Anchor tiers:** official_org 2.5 · self_published 2.0 · professional_network_snippet 1.2 · press 1.0 · aggregator 0.5.
**Attribute factors:** employer 1.0 · title 0.5 · education 0.7 · location 0.4.
**T4 categories:** exact_match ×1.0 · matches_former ×1.0 (when seed tense is past) · partial ×0.5 · unrelated 0 · contradicts (→ negative rows above).

Attribute matching is **one batched T4 call** per ≤10 candidates, constrained to
`{exact_match, partial, unrelated, contradicts, matches_former}` → fixed weight.
Never a free-form number. Validate the returned candidate IDs against the batch.

Score all candidates on **free SERP snippets before any fetch**. Fetch order is
by **expected discrimination** (personal domains first — full history + outbound
links = reciprocal evidence in one fetch), k=2.

---

## Regime → prior & caps

| Regime | Signal | Prior | Cap |
|---|---|---|---|
| HARD_ID_URL | profile URL in input | 0 | 12 |
| HARD_ID_EMAIL | email in input | 0 | 12 |
| NAME_STRONG | name + resolvable company (not on huge-stoplist) | −1.5 | 20 |
| DEFINITE_DESC | role description, no name → resolve org, find holder → becomes NAME_STRONG | −1.5 | 24 |
| NAME_WEAK | name + weak/generic/unresolvable anchor | −1.5 | 30 |
| BARE_NAME | name alone | −1.5 | 10 (expect ambiguous) |

Regime′: resolvable company domain → NAME_STRONG by default; NAME_WEAK only for
the known-huge stoplist or unresolvable org (logged).

---

## Worked rows → test fixtures

| Input | Evidence terms | Sum → P | Result |
|---|---|---|---|
| Henry Wang, sixtyfour ai | team page +2.5, title +1.25, LinkedIn snippet corrob +0.3, team→LinkedIn anchored +1.5, unique +0.8, common +0.2, prior −1.5 | 5.05 → **0.994** | confirm |
| same, no team page, LinkedIn snippet only | employer +1.2, title +0.6, unique +0.8, common +0.2, prior −1.5 | 1.3 → **0.79** | CONTINUE; one press/GitHub-bio source pushes it over |
| wrong Henry Wang (other employer, aggregator) | common +0.2, snippet contradict −0.5, prior −1.5 | −1.8 → **0.14** | rejected |
| andrew.goering@ramp.com | prior 0, rare +2.0, snippet employer +1.2, unique +0.8 | 4.0 → **0.98** | confirm |
| jsmith@ramp.com | prior 0, common +0.2, initials −0.9, employer +1.2, unique +0.8 | 1.3 → **0.79** | CONTINUE; commit-email hit +3.0 confirms |
| linkedin.com/in/… as input | prior 0, seed URL +3.5 | 3.5 → **0.97** | confirm unless a hard key contradicts |
| sarah chen, ex-figma — two Figma Sarah Chens | each: employer +1.2, title +0.6, common +0.2, prior −1.5 | 0.5 → **0.62**, margin 0 | fetch top-2 by discrimination |
| …after portfolio fetch on the real one: "previously Figma" +2.0, title +1.0, corrob +0.3, reciprocal GitHub +3.0 | vs other 0.62 | 5.0 → **0.993**, margin 0.37 | confirm |
| …neither has a fetchable portfolio | — | — | ambiguous + disambiguation table |

Note (DESIGN′): in single-candidate HARD_ID runs the uniqueness term is trivially
true and adds +0.8 without doing disambiguation work — part of why HARD_ID
confirms fast. State this in DESIGN.md.

---

## Gate decision matrix (order: math first)

| Math | Model | Result |
|---|---|---|
| pass | CONFIRM | confirm |
| pass | ABSTAIN | abstain, log disagreement |
| pass | CONTINUE | continue (execute `next_evidence` while budget remains; **max 2 gate cycles**, Gate-loop′) |
| fail | — | no model call; continue if budget, else abstain |

**T1 gate prompt contains:** seed; top-3 candidates only with logodds,
`factor:weight` terms, URLs with source_class, attributes each paired with its
evidence snippet, verified reciprocal links with mechanism, conflicts with
severity; calls spent vs budget.
**Excludes:** raw page text, candidates 4+, link structure, coverage slots,
EXPAND state.
**Required instruction:** abstention is correct under genuine ambiguity; a
confident wrong ID is worse than an abstention; CONTINUE requires naming specific
obtainable evidence.

```json
{"decision":"CONFIRM|ABSTAIN|CONTINUE","cid":"c3","reasoning":"...",
 "rejected":[{"cid":"c1","reason":"..."}],"next_evidence":"..."}
```
