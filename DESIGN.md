# Design

Every number below is copied verbatim from `src/pi/constants.py`, the single
source of truth. The **Derivation** column is the tag `constants.py` carries on
that line: `(judgment)` subjective engineering call, `(census)` US 2010 Census
surname table, `(reasoned)` derived from call structure, `(standard)` common
practice, `(verified)` checked against a live API. Where a row also carries a
red-team id (C1, A2, Regime′, …) that id is `plan/design-decisions.md`'s tag for
the divergence that produced it.

Everything here is deterministic. No float in a `Confidence.terms` list is ever
model-emitted — the model chooses *categories* (`exact_match`, `CONFIRM`, a
frontier pick); this file's tables turn each category into a fixed weight. A
reader who has this file does not need `identity_score.py` or `claim_score.py`
open to predict a run's arithmetic.

---

## 1. Identity log-odds terms

| Term | Weight | Derivation |
|---|---|---|
| prior — NAME_STRONG / NAME_WEAK / DEFINITE_DESC / BARE_NAME | −1.5 | (judgment) `LOGODDS_PRIOR` |
| prior — HARD_ID_URL / HARD_ID_EMAIL | 0 | (judgment) `HARD_ID_PRIOR` |
| hard key: seed URL resolves to this candidate | +3.5 | (judgment) |
| hard key: seed email on a fetched page of this candidate | +3.5 | (judgment) |
| hard key: Gravatar match for seed email | +3.0 | (judgment) |
| hard key: GitHub commit-email hit | +3.0 | (judgment) |
| hard key: verified reciprocal link | +3.0 | (judgment) |
| anchored one-way link (fetched official/self-pub page → unfetchable profile) | +1.5 | (judgment, C21) |
| uniqueness — sole candidate ≥ `UNIQUENESS_MIN_ANCHOR` (1.2) on **enumeration-time (snippet) evidence only** | +0.8 | (judgment, A2/Unique′) |
| dominant cluster — BARE_NAME/NAME_WEAK only, exactly one candidate cluster exists, it carries ≥8 attached sources, and those sources are ≥60% of all enumeration results | +2.0 | (judgment, A5) |
| name mismatch (matcher: differently-named person) | −2.0 | (judgment) |
| contradicts on a fetched official/self-pub page | −(tier × 0.6) | (judgment) `CONTRADICT_PAGE_MULT` |
| contradicts on a snippet | −0.5 | (judgment) `CONTRADICT_SNIPPET` |

`Confidence.score = sigmoid(Σ terms)`. Anchor-match rows (below) are added on top.

## 2. Anchor tiers and attribute factors

Anchor weight per attribute = `max over sources(source_tier × attr_factor × T4_category_mult)`, plus a corroboration bonus when ≥2 independent sources back the same attribute.

| Source class (identity tier) | Weight | Derivation |
|---|---|---|
| company_site / government_registry / academic | 2.5 | (judgment) |
| personal_site / code_host | 2.0 | (judgment) |
| professional_network / social | 1.2 | (judgment) |
| press | 1.0 | (judgment) |
| unknown | 0.8 | (judgment) |
| aggregator | 0.5 | (judgment) |
| seed | 0.0 | (judgment) |

| Attribute factor | Weight | Derivation |
|---|---|---|
| employer | 1.0 | (judgment) |
| education | 0.7 | (judgment) |
| title | 0.5 | (judgment) |
| location | 0.4 | (judgment) |

| Corroboration | Value | Derivation |
|---|---|---|
| per extra independent source, per anchor | +0.3 | (judgment) `CORROBORATION_PER_SOURCE` |
| cap | +0.6 | (judgment) `CORROBORATION_CAP` |

Independence key: `(source_class, registrable_domain)`; all aggregators collapse to one key regardless of domain.

**T4 category multipliers** (the only place a model judges an anchor — a constrained categorical, never a float): `exact_match` ×1.0 · `matches_former` ×1.0 (only when the seed's tense for that org is `former`) · `partial` ×0.5 · `unrelated` ×0 · `contradicts` → the negative rows in §1, not a multiplier.

## 3. Surname rarity buckets (census)

US 2010 Census surname table, occurrences per 100k people. 162,254 surnames — every one with ≥100 US bearers.

| Bucket | Threshold | Weight | Derivation |
|---|---|---|---|
| rare | per100k < 2.0 (`SURNAME_RARE_MAX`) | +2.0 | (census) |
| uncommon | 2.0 ≤ per100k < 20.0 | +1.0 | (census) |
| common | per100k ≥ 20.0 (`SURNAME_COMMON_MIN`) | +0.2 | (census) |
| not_found | absent from the table | +1.0 | (census) |

## 4. Name forms

| Form | Weight | Derivation |
|---|---|---|
| exact / diacritic-stripped | 0 | (judgment, C2) |
| order swap | −0.2 | (judgment, C2) |
| nickname | −0.4 | (judgment, C2) |
| initials / partial | −0.9 | (judgment, C2) |
| mismatch (different person) | −2.0 | (judgment) |

## 5. The gate

| Constant | Value | Derivation |
|---|---|---|
| `GATE_P_THRESHOLD` | 0.85 | (judgment) |
| `GATE_MARGIN` | 0.30 | (judgment) |
| `GATE_MAX_CYCLES` | 2 | (Gate-loop′) |
| `GATE_PROMPT_CANDIDATES` | 3 | (judgment) — top-3 only shown to T1 |

Pass condition: `P(top) ≥ 0.85 AND P(top) − P(runner_up) ≥ 0.30`. Decision matrix (`resolve/gate.py:gate_decision`) — **math first, always**:

| Math | Model (T1) | Result |
|---|---|---|
| fail | (no call) | continue while budget remains, else abstained/ambiguous |
| pass | CONFIRM | confirmed |
| pass | ABSTAIN | abstained/ambiguous — model vetoed a passing gate |
| pass | CONTINUE | one more disconfirmation cycle, then re-gate (≤2 cycles total) |

## 6. Claim tiers and extraction rungs

| Source class (claim tier) | Weight | Derivation |
|---|---|---|
| company_site / government_registry / academic | 2.5 | (judgment) |
| personal_site / code_host | 2.2 | (judgment) |
| company_site_other / professional_network / social / press | 1.4 | (judgment) |
| seed (user-supplied hard id, e.g. email domain) | 1.5 | (judgment) |
| unknown | 0.8 | (judgment) |
| aggregator | 0.2 | (judgment) — **never sole support** |

| Extraction rung | Weight | Derivation |
|---|---|---|
| json_ld | +1.0 | (judgment) |
| site_parser (GitHub API, Gravatar API) | +0.7 | (judgment) |
| html_table | +0.4 | (judgment) |
| prose_llm | 0.0 | (judgment) — span-checked, but earns no rung bonus |
| none (seed hard id) | 0.0 | (judgment) |

## 7. Corroboration, recency, conflict (claims)

| Constant | Value | Derivation |
|---|---|---|
| corroboration, 2nd independent source | +1.2 | (judgment) `CORROBORATION_SECOND` |
| corroboration decay per source after that | ×0.6 | (judgment) `CORROBORATION_DECAY` |
| recency — immutable | 0/yr | (judgment) |
| recency — current_employer | −0.15/yr | (judgment) |
| recency — current_title / current_location | −0.35/yr | (judgment) |
| recency — contact | −0.5/yr | (judgment) |
| no context date on a mutable predicate | −0.3 | (judgment) `NO_CONTEXT_DATE_PENALTY` |
| conflict — soft | −0.3 | (judgment) |
| conflict — hard / identity | −1.5 / −3.0 defined, never produced: merge emits soft conflicts only (see honesty notes) |
| conflict — identity | −3.0 | (judgment) → quarantine, not abort (C6′) |

Prior for every claim is the same −1.5 (`LOGODDS_PRIOR`) regardless of regime.

## 8. Regimes, priors, caps

| Regime | Trigger | Prior | RESOLVE cap | Derivation |
|---|---|---|---|---|
| HARD_ID_URL | profile URL in input | 0 | 12 | (judgment, C10) |
| HARD_ID_EMAIL | email in input | 0 | 12 | (judgment, C10) |
| NAME_STRONG | name + a resolvable, non-huge company | −1.5 | 20 | (judgment, C10/Regime′) |
| DEFINITE_DESC | definite role + org, no name | −1.5 | 24 | (judgment, C10) |
| NAME_WEAK | name + an org that did not resolve or is on the huge-company stoplist, OR name + only a title/school/location | −1.5 | 30 | (judgment, C10/Regime′) |
| BARE_NAME | name alone | −1.5 | 10 | (judgment, C10) |

`HUGE_COMPANY_STOPLIST` (Regime′, judgment): google, alphabet, meta, facebook, amazon, apple, microsoft, netflix, ibm, oracle, intel, walmart, jpmorgan, accenture — a resolvable domain downgrades NAME_STRONG → NAME_WEAK only for these, never for headcount (the headcount-based rule was dropped as flaky).

`DEFINITE_ROLES` (judgment): ceo/cto/cfo/coo/cmo/cpo/cro/ciso/cio, president, founder, cofounder, chair(person), chief, head, vp, director, managing director, general counsel, principal, partner — plus the regexes `chief \w+ officer` and `(head|vp|director) of`.

## 9. Budget and stops

The budget unit is one tool invocation; cache hits count toward the caps and are reported separately as `cache_hits`. This is the tool cache only — LLM cache hits are free: they count toward neither `llm_calls` nor `usd`.

| Constant | Value | Derivation |
|---|---|---|
| `RESOLVE_BUDGET_BASE` / `RESOLVE_BUDGET_PER_CANDIDATE` | 4 / 2 — `resolve_budget = min(spent + 4 + 2n, cap)` | (reasoned, Budget-count′) |
| `ENUMERATION_MAX_QUERIES` | 5 | (judgment; free-tier keys — plan allows ≤8) |
| `DISCONFIRM_MAX_ACTIONS` | 2 | (judgment, C5) |
| `FETCH_K` | 2 | (judgment) — top-K candidates fetched per RESOLVE evidence cycle |
| `EXPAND_CAP` | 40 | (judgment) — `min(40, S3_TOTAL_TOOL_CALLS − resolve_spent)` (Budget′) |
| `EXPAND_MAX_BATCHES` (S3_batches) | 12 | (round-3) hard cap on planner batches |
| `S3_TOTAL_TOOL_CALLS` | 60 | (judgment, C10) whole-run tool-call ceiling |
| `S3_SOFT_SECONDS` | 180 | (judgment) |
| `S3_SOFT_USD` | 0.50 | (judgment, C22) |
| `FRONTIER_RELEVANCE_FLOOR` | 0.3 | (judgment) |
| `DOMAIN_EARLY_STOP_FETCHES` | 3 | (judgment) — stop fetching a domain that yielded 0 claims after 3 tries |
| `DEPTH_CAP` | 2 | (judgment) — link-following depth from a fetched page |
| `SLOT_BARREN_LIMIT` | 3 | (judgment) — barren fetches before a slot force-closes |

**EXPAND stop reasons, as actually coded in `expand/expander.py`:**

| Code | Condition |
|---|---|
| S1 | `slots.all_closed()` |
| S2 | batch_count > 3 **and** 2 consecutive batches added no new merged claim (literal thresholds, not named constants — ponytail) |
| S3 | soft caps: tool calls ≥ `EXPAND_CAP`, **or** elapsed ≥ `S3_SOFT_SECONDS`, **or** spend ≥ `S3_SOFT_USD` |
| S3_batches | `batch_count ≥ EXPAND_MAX_BATCHES` (12) |
| S5_planner | the T2 planner returns `stop: true`, or two consecutive empty picks |
| S_frontier_empty | the ranked frontier is empty and slots are not all closed |

## 10. Slots

| Slot | Target | Derivation |
|---|---|---|
| identity_anchors | 1 | (judgment, plan B3) |
| current_role | 1 | (judgment) |
| employment_history | 3 | (judgment) |
| education | 1 | (judgment) |
| contact | 1 | (judgment) |
| public_output | 3 | (judgment) |
| social_graph | 3 | (judgment) |
| notable_artifacts | 2 | (judgment) |

`PREDICATE_SLOTS` maps each predicate to the slot(s) it can fill (e.g. `employer`/`employment` → `current_role` + `employment_history`); `CLASS_SLOTS` predicts which slots a source class usually fills, used to guess a frontier item's `open_slot` before it is fetched (e.g. `code_host` → identity_anchors, public_output, contact, employment_history).

## 11. Frontier priors and action costs

| Class prior (expected yield per fetch) | Value | Derivation |
|---|---|---|
| personal_site | 0.9 | (judgment, plan B4) |
| code_host | 0.8 | (judgment) |
| company_site | 0.7 | (judgment) |
| academic | 0.6 | (judgment) |
| professional_network | 0.6 | (judgment) |
| press | 0.5 | (judgment) |
| government_registry / unknown / company_site_other | 0.4 | (judgment) |
| social | 0.3 | (judgment) |
| aggregator | 0.15 | (judgment) |

| Action cost (seconds, USD) | Derivation |
|---|---|
| search: (1.5, 0.002) | (judgment) |
| fetch: (3.0, 0.0) | (judgment) |
| exa_contents: (3.0, 0.005) | (judgment) |
| github / github_emails: (1.0, 0.0) / (1.5, 0.0) | (judgment) |
| gravatar: (0.5, 0.0) | (judgment) |
| wayback: (8.0, 0.0) | (judgment) |
| verify: (6.0, 0.0) | (judgment) |

`COST_LAMBDA = 100.0` ($0.01 ≈ 1s, judgment) folds `$` into the same denominator as seconds. Frontier score = `relevance × slot_gap × class_prior / (est_seconds + COST_LAMBDA × est_usd)`. `FRONTIER_TOP_N = 12` items shown to the planner; `PLANNER_MAX_PICKS = 4`; `PLANNER_MAX_NEW = 2` planner-invented actions per batch; `REINFORCE_FORCE_AFTER_SKIPS = 2` — a reinforce item the planner skips twice is forced into the next batch regardless.

## 12. Model routing

(verified 2026-09-02 against `GET https://openrouter.ai/api/v1/models`)

| Tier | Job | Model | Reasoning | Max tokens |
|---|---|---|---|---|
| T1 | identity gate, disconfirmation | `anthropic/claude-sonnet-5` (→ `anthropic/claude-sonnet-4.6` on failure) | on (`medium` effort) | 1500 |
| T2 | EXPAND planner, synthesis summary | `anthropic/claude-sonnet-5` (→ `anthropic/claude-sonnet-4.6`) | off | 900 |
| T3 | page → claims (prose extraction) | `google/gemini-3.8-flash` | off | 1500 |
| T4 | attribute-match categorical | `google/gemini-3.8-flash` | off | 1200 |
| T5 | input parse, role resolution | `google/gemini-3.8-flash` | off | 600 |

`TEMPERATURE = 0` for T2–T5; T1 sends no temperature (reasoning models reject it). Prices (USD / 1M tokens, verified 2026-09-02): sonnet-5 $2.00 in / $10.00 out; sonnet-4.6 $3.00 / $15.00; gemini-3.8-flash $0.75 / $3.75 — used only when OpenRouter doesn't report `usage.cost` directly. `RETRIES`: validation 3, rate_limit 2, refusal 0 (a refusal is not retried with the same prompt).

---

## 13. Same-person test (attachment)

A source's attachment is computed from what it shares with the confirmed identity — never from
how the page was reached — via a deterministic log-odds test run before its claims attach.

**Anchors.** Seeded once: from the seed, `orgs`/`org_domains`→employer, `schools`→school,
`locations`→location, `hard_ids`; from the candidate, `handles` (site→domain, else handle),
`identity_keys`. Each value yields lowercase phrases: itself, plus — for
employer/school/location only, never a collaborator/handle/email/domain — its first word (≥5
chars, skip generic words) and pre-comma segment, dropped if that names an institution
(university, hospital, etc.). That test also marks a school/location anchor, or such an
employer, weak: +0.6 (`ATTACH_PER_CATEGORY_WEAK`) not +1.2, since namesakes share it; its
phrases inherit weak. Top `ATTACH_CATEGORY_CAP` (3) matches, sorted descending, summed.

| Term | Weight |
|---|---|
| prior | −1.0 |
| name variant present (all tokens), or the person's email/personal domain in the body | +1.5 / no name | −2.0 |
| per distinct matched anchor category, strong (cap 3) | +1.2 |
| per distinct matched anchor category, weak — school/location, or a university/college/institute/school/hospital/health/department-named employer (cap 3) | +0.6 |
| the confirmed candidate's own page (`owned`) | +3.0 |
| reached by a link on an already-trusted page (`linked`) | +2.0 |

Worked arithmetic: name only → 0.5 → **P = 0.622** (middle band); +1 strong anchor category →
1.7 → **P = 0.846** (profile); +1 weak category → 1.1 → **P = 0.750** (still unverified — one
school/location is not enough); +2 weak categories → 1.7 → **P = 0.846** (same as one strong);
no name, 0 categories → −3.0 → **P = 0.047** (skip); owned + name → 3.5 → **P = 0.971**.
A source with no identity signal is capped at 0.75 (`ATTACH_NO_IDENTITY_CAP`) unless owned:
shared anchors and a link never outvote a missing name.

| Band | Range | Meaning |
|---|---|---|
| skip | < 0.5 (`ATTACH_SKIP`) | no extraction call, no claims, no page-link harvest |
| unverified | [0.5, 0.8) | claims are real but land in `Output.unverified[]`, never the profile |
| profile | [0.8, 0.9) (`ATTACH_PROFILE`) | claims count toward the profile, timeline, summary, slots |
| trusted | ≥ 0.9 (`ATTACH_TRUSTED`) | claims grow the anchor set; its own links inherit `ATTACH_LINKED_FROM_TRUSTED` |

**The middle-band T4 check.** A non-owned page in [0.5, 0.8) is re-checked once via
`resolve.match.match_candidates` against seed anchors (falling back to the first raw
employer/school/location phrase). A `contradicts:*` on employer/education/location overrides
the score to `ATTACH_CONTRADICTED` (0.2) — into skip; else the pre-T4 score stands.
`ATTACH_T4_MAX` (6) caps checks per run; a failed call never blocks the page.

**Trusted claims grow the anchor set; middle-band pages get re-scored.** After each batch's
merge, `anchors.grow()` folds every claim at ≥`ATTACH_TRUSTED` into the anchor set. Every
middle-band page (capped at 20/run) is re-scored against the grown set; one that now crosses
`ATTACH_PROFILE` gets its claims promoted in place and drops off the watch list. A
contradiction-skipped page is never re-scored.

**Honesty note:** name + one *strong* anchor category still clears 0.846 — a namesake page
mentioning a specific, non-generic employer passes. It is a raw string match, not semantic:
two different companies sharing a distinctive name both count as strong. Upgrade path: an
org alias/disambiguation table, and running T4 on profile-band pages too.

---

## Four worked identity rows (`tests/test_identity_table.py`)

These are test fixtures — a code change that moves any of them across the gate
fails the suite.

1. **`andrew.goering@ramp.com` confirms** (`test_andrew_goering_email_confirms`). HARD_ID_EMAIL prior is 0. The only anchor is a LinkedIn (professional_network, tier 1.2) employer match at ×1.0 → +1.2. "Goering" is a rare US surname → +2.0. One candidate clears `UNIQUENESS_MIN_ANCHOR` → +0.8. Sum = 4.0 → **P = 0.98**, comfortably past 0.85 with no runner-up: confirmed.
2. **Henry Wang confirms off a team page** (`test_henry_wang_team_page_confirms`). NAME_STRONG prior −1.5. The company's own team page (tier 2.5) backs both employer and title at ×1.0 → +2.5 (employer) with a +0.3 LinkedIn-snippet corroboration bonus, +2.5×0.5=1.25 rounds into the title term. The team page also anchors the candidate's LinkedIn one-way (+1.5, `anchored_one_way`). "Wang" is a common US surname → only +0.2. Sum ≈ 5.05 → **P = 0.994**: confirmed. Drop the team page and keep only the LinkedIn snippet (`test_henry_wang_linkedin_only_continues`) and the sum falls to 1.3 → P = 0.79 — under the gate, so RESOLVE fetches one more source instead of confirming on a snippet alone.
3. **`jsmith@ramp.com` needs more than the email** (`test_jsmith_email_continues`). HARD_ID_EMAIL prior 0, one LinkedIn employer anchor (+1.2), uniqueness (+0.8), but "Smith" is common (+0.2) and the local-part `jsmith` only supports an initials-form name match (−0.9). Sum = 1.3 → P = 0.79, under 0.85: the math fails the gate, so T1 is never even consulted — RESOLVE spends its remaining budget on a GitHub commit-email search; a hit there is a fresh +3.0 hard key that clears the gate on the next cycle.
4. **Two Sarah Chens tie, then one clears with new evidence** (`test_two_figma_sarah_chens_tie_below_gate` → `test_sarah_chen_after_portfolio_confirms_with_margin`). Both candidates start identical: NAME_STRONG prior −1.5, one LinkedIn employer+title anchor each (+1.2, +0.6), common surname (+0.2) → 0.5 logodds, **P = 0.62 for both**, margin 0 — the gate needs *both* P ≥ 0.85 and a ≥0.30 margin, so a perfect tie can never pass no matter how high it climbs together. RESOLVE fetches the top-2 by discrimination; when one owns a personal portfolio site that says "previously Figma" (self-published, tier 2.0, `matches_former` category since the seed's Figma tense is `former`) and a reciprocal GitHub link (+3.0), her sum jumps to ≈5.0 → P = 0.993 while the other candidate is untouched at 0.62 — margin 0.37 clears the gate. If neither candidate has a fetchable personal page, both stay at 0.62/0 margin and the run returns `ambiguous` with a candidate table instead of guessing.

**DESIGN′ note:** in every single-candidate HARD_ID run (rows 1 and 3 above), the uniqueness term is *trivially* true — there is nothing else to be unique against — so it adds +0.8 for free, without any disambiguation work happening. This is a real, honest part of why HARD_ID regimes confirm fast and cheaply; it is not evidence of a stronger identity match than a NAME_STRONG run that had to earn the same +0.8 against real competitors.

---

## RESOLVE flow

1. `DEFINITE_DESC` only: name the role-holder first — fetch the org's own site (`/`, `/about`, `/team`) and a small SERP, ask T5 who holds the role now; competing holders or no confident name → typed `ambiguous`/`abstained` immediately; otherwise rewrite the seed to `NAME_STRONG`/`NAME_WEAK` and continue.
2. If the seed still has no name, abstain typed — a role description or hard id is not enough on its own.
3. Enumerate ≤5 Serper queries built from the regime (email-quote, name+org, `site:linkedin.com/in`, `site:github.com`, name+domain), issued concurrently, deduped by URL.
4. Cluster results by identity-bearing URL (LinkedIn `/in/…`, GitHub user, X handle, personal-site root); merge groups that share one *rare* handle across platforms; everything else (press, company, academic, aggregator pages) is floating evidence, never a clustering key.
5. Zero candidates → seed one from floating evidence, or abstain if there is none; exactly one candidate → all floating evidence attaches to it directly.
6. Run one batched T4 attribute-match call on snippets only, score every candidate's log-odds, and test the gate (`P(top) ≥ 0.85 ∧ margin ≥ 0.30`).
7. `BARE_NAME` + a common surname + ≥3 clusters + a failed gate → typed `ambiguous` immediately with the candidate table (no more budget spent chasing a crowd).
8. While the math fails and budget remains: fetch the anchor org's page once if enumeration found it, then fetch the top-`FETCH_K` (2) candidates by expected discrimination; re-match, re-score, re-test the gate — up to `GATE_MAX_CYCLES` (2) times.
9. Once the math passes: run executed disconfirmation — T1 proposes a falsification hypothesis with ≤2 real tool calls, the calls run, the top candidate is rescored, the gate is retested.
10. T1 reviews the top-3 candidates (veto-only: a passing gate can be vetoed to ABSTAIN/CONTINUE, but a failing gate is never overridden to CONFIRM). CONTINUE executes one more piece of named evidence and retries once; the final `Resolution` carries every candidate, every rejection reason, and — on anything but confirmed — what input would disambiguate it.

## EXPAND loop

1. Seed the frontier from the confirmed candidate's own pages/handles (relevance 0.95), the anchor org's site and its Wayback history, and a handful of template searches (interview/podcast, `"name" "org"`, founder mentions) — each item guesses one open slot.
2. Reinforce: any graph node with ≥3 descendants and attachment confidence <0.6 (`REINFORCE_MIN_DESCENDANTS`/`MAX_ATTACHMENT`) gets a `verify` frontier item; if the planner skips it twice it is forced into the next batch regardless.
3. Rank the frontier by `relevance × slot_gap × class_prior / (seconds + λ·usd)` and hand the planner the top 12 — a cheap pre-sort, not the decision.
4. The T2 planner (no reasoning tokens — this runs every batch) picks ≤4 items from that list, may add ≤2 of its own hypothesis actions, may close slots it judges saturated, or may vote to stop.
5. Run the ≤4 chosen actions concurrently (search / fetch / exa_contents / github+commit-emails / gravatar / wayback / verify). **Before any extraction**, each newly-read source is scored against the identity anchor set by the same-person test (§13); below `ATTACH_SKIP` it contributes nothing — no extraction call, no claims, no page-link harvest.
6. Structured payloads (JSON-LD, GitHub API, Gravatar API) extract with no span check, everything else goes through prose-LLM extraction whose spans must appear verbatim (or ≥90% rapidfuzz) in the source text or the tuple is dropped; every resulting claim carries the attachment score from step 5.
7. Assemble tuples into claims + graph nodes/edges, then split by `ATTACH_PROFILE` and merge each half separately by `(predicate, value)` — a namesake's claims never corroborate a real one — rescoring confidence (source tier + rung + corroboration + recency) and flagging soft conflicts when two *current* employer/title/location claims disagree. Trusted claims (≥`ATTACH_TRUSTED`) grow the anchor set; every middle-band page still on file is re-scored against it.
8. Recompute the 8 coverage slots from the *attached* (≥`ATTACH_PROFILE`) merged claims; a slot closes when its target is met or after 3 barren fetches in a row.
9. Stop on S1 (all slots closed), S2 (2 barren batches back-to-back after batch 3), S3 / S3_batches (tool-call, wall-clock, dollar, or 12-batch ceiling), or S5 (planner votes stop, or two empty picks in a row); otherwise loop back to step 2.

## Discovery pivots (forced, not planner-ranked)

Four EXPAND actions never appear on the ranked frontier at all. `expander.py`'s
`pending_pivots` queue forces up to 2 of them into every batch — ahead of
forced-reinforce items and the planner's own picks, but still inside the same
`PLANNER_MAX_PICKS` (4) per-batch cap — because the relevance × class_prior /
cost formula in §11 would otherwise starve them for many batches behind cheap
high-relevance fetches.

| Action | Triggers | Cost (s, $) | Notes |
|---|---|---|---|
| `username_probe` | the confirmed candidate's own handles (known platform keys only — a bare website is never fed to the prober) at EXPAND start; any `handle` claim discovered mid-run that passes the probe rule: ≥`RARE_HANDLE_MIN_LEN` (6) chars, not in `COMMON_HANDLE_WORDS`, and not one of the person's own name tokens | 4.0, 0 | capped at `PROBE_MAX_HANDLES_PER_RUN` (4) handles probed per run |
| `gravatar` | any discovered `email` claim | 0.5, 0 | one enqueue per distinct email |
| `github_code` | the person's name (quoted) at EXPAND start, if `GITHUB_PAT` is set; the first discovered email whose domain is not a free-mail provider (`_FREE_MAIL_DOMAINS`) | 2.0, 0 | at most 2 enqueues/run; hits whose repo belongs to the candidate's own GitHub login are dropped at execution — the pivot looks for other people's code that mentions them, not their own |
| `openalex` | seed schools present at EXPAND start; a discovered `education`/`publication` claim; a discovered `employer`/`employment` claim whose value contains "lab", "university", or "institute" | 2.0, 0 | once per run; the author search only accepts a candidate whose institution list shares a token with the hint list (seed schools + discovered employer/education/publication values) — a name match alone is not enough |

`username_probe` checks all 15 platforms in `PROBE_PLATFORMS`: github, gitlab,
reddit, hackernews, keybase, devto, huggingface, kaggle, devpost, behance,
dribbble, youtube, producthunt, linktree, academia (`medium` was dropped —
its "404" rule is a soft-404, every handle "hits"). Each hit runs through the
same-person test (§13): JSON platforms (github, reddit, hackernews, keybase)
reuse the body the probe already fetched, everything else gets one page read,
capped at 8 reads per probe call — a hit past that cap scores on its URL alone.

`username_probe`, `github_code`, and `openalex` are all specialization-payoff
methods (`synth/synthesize.py:_PAYOFF_METHODS`), alongside `github_emails`,
`gravatar`, and `wayback` — a claim earned by any of them lands in
`Output.specialization_payoff` regardless of its confidence score.

## Output envelope

Every field on `types.Output`, in order:

| Field | Content |
|---|---|
| `status` | `confirmed` \| `ambiguous` \| `abstained` \| `failed` |
| `input` | the raw text given to the CLI/API |
| `seed` | the parsed `Seed` — names, hard ids, orgs, titles, regime |
| `regime` | the *original* regime shown to the user (pre-DEFINITE_DESC rewrite, if any) |
| `identity` | confidence + terms, confirmed cid, hard keys used, `how_confirmed` prose, `public_figure` (true when the dominant-cluster term fired — `how_confirmed` is prefixed `"public figure: "`) |
| `summary` | T2-written sentences, each required to cite ≥1 real claim id or the sentence is dropped |
| `profile` | the programmatic profile: current_role, employment, education, location, contact, accounts, public_output, relationships, notable — every entry is a `Claim` at attachment ≥ `ATTACH_PROFILE` |
| `unverified` | real claims below `ATTACH_PROFILE` — about a source that scored too low on the same-person test (§13) to trust as the confirmed person; never in `profile`/`timeline`/`summary` |
| `graph` | nodes + edges rooted at the confirmed person |
| `conflicts` | soft conflicts detected during merge (both values ongoing) |
| `negative_findings` | seed-asserted facts never confirmed by a page span (`predicate` = the attribute), plus coverage slots below target at stop (`predicate: coverage`, `found`/`target`) |
| `identity_resolution` | every candidate's score+terms, every rejection reason, what would disambiguate |
| `specialization_payoff` | claim ids that came from a github-commit-email, gravatar, wayback, username-probe, github-code-search, OpenAlex, or reciprocal-link mechanism — the "how did it find that" list |
| `timeline` | dated claims, one line each, earliest first |
| `run_metadata` | job id, budget (tool_calls, llm_calls, usd, seconds, resolve sub-budget), stop_reason, models used, timings |

---

## Honesty notes

- **Uniqueness (+0.8) is trivially satisfied on single-candidate hard-id runs.** With one candidate there is nothing to be unique *against*; the +0.8 fires without any disambiguation work happening (see the worked rows above). It is real arithmetic, not a bug, but it should not be read as evidence of a stronger match than a contested NAME_STRONG run that earned the same +0.8 against real competitors.
- **US Census surname rarity misleads for non-US surnames.** The table is US bearer counts, not global frequency. "Avci" — a common Turkish surname — appears at 0.070 per 100k US residents, which is *below* `SURNAME_RARE_MAX` (2.0), so it scores the `rare` bucket (+2.0) — the same weight as a genuinely rare American surname — purely because few Turkish immigrants happen to be in the US Census sample, not because the name is discriminating. `not_found` (fully absent from the table — the common case for non-Latin-script names never transliterated) scores a neutral +1.0 instead, which is the more honest of the two failure modes.
- **Aggregators are never sole support.** `aggregator` sits at the bottom of both the identity tier table (0.5) and the claim tier table (0.2) by construction — a single aggregator source alone cannot clear either the identity gate or push a claim's confidence meaningfully positive; it can only corroborate a claim already backed by something better.
- **Reinforce/verify rarely fires live.** The mechanism is real (§9, `Graph.reinforce_candidates`), but almost every node `assemble()` creates inherits an attachment from the same-person test (§13) run on the action that found it — usually ≥0.9 for the confirmed candidate's own page (name + `ATTACH_OWNED`) — so the `<0.6` trigger condition is rare in practice on a run whose identity already cleared the gate. It exists for the cases where a claim arrives through a longer, weaker chain (a link found on a link), which is uncommon because most edges are wired directly from the root.
- **Confidence is ordinal, not frequency-calibrated.** A 0.9 claim is more reliable than a 0.6 claim on this scale; it does not mean the claim is correct 90% of the time. No calibration study backs these numbers — they encode a consistent ranking, not a measured probability.
- **A shared username is suggestive, not proof.** A `username_probe` hit is scored by the same-person test (§13) like any other source, not a fixed confirmed/unverified pair: name-on-page alone lands it in the unverified band (0.622); an unclaimed-but-real handle whose page fails even the name check can still score above skip on a matched anchor category, and a page linking to it from an already-trusted source can outscore a name-only hit entirely.
