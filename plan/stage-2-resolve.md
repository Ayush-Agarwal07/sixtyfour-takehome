# Stage 2 — Deepen RESOLVE (identity)

**Owner:** parallel agents (2–3). **~4h.** **Prereqs:** Stage 1 green.
**Builds against:** [reference-identity-scoring.md](reference-identity-scoring.md), [reference-contracts.md](reference-contracts.md).

The hardest, most-graded phase. **Step 5 of the original build order — "the
project."** The bar is absolute: on common-name inputs, be **correct or ABSTAIN,
zero confident wrong.**

## Scope — build the full identity machinery on the working slice

Deepen the shallow `understand/` and `resolve/` from Stage 1 into the complete
phase, plus the tools RESOLVE needs.

### Workstream A — UNDERSTAND (full)

```
understand/{parse.py (T5), variants.py, regime.py, email_derive.py, census.py, tense.py}
data/surnames.csv
```

- `parse.py` — comma-segmentation **before** nameparser; T5 call for name/companies/titles/schools/locations on odd phrasings; hard-ID regex first.
- `variants.py` — as-given, initials, order swap (given-name-last cultures), nickname expansion (`nicknames`), diacritic strip (`unidecode`). **Never** middle names, handles, chosen English names, or any character absent from input. Discovered fuller forms get `origin=discovered` + required `evidence_id`, re-open search only when discriminating.
- `regime.py` — Regime′: resolvable company → NAME_STRONG; known-huge stoplist or unresolvable → NAME_WEAK (logged). DEFINITE_DESC when role description + no name. Email → HARD_ID_EMAIL; profile URL → HARD_ID_URL.
- `census.py` — load `surnames.csv`, rarity bucket (rare/uncommon/common/not-found).
- `tense.py` — tense as a constraint: "ex-figma" → a page saying *currently at Figma* is evidence **against** (feeds `matches_former` / tense contradiction).

### Workstream B — tools RESOLVE needs

```
tools/{serper.py (batch), exa.py (search + contents), fetch.py, github.py, gravatar.py, wayback.py, company.py}
```

- `serper.py` — one batched request for the ≤8 enumeration queries.
- `github.py` — user, repos, `commits?author=` emails, `search/users?q={email}`, `search/commits author-email:`.
- `gravatar.py` — `md5(email)` → profile → linked accounts.
- `wayback.py` — CDX latest snapshot for a URL.
- `company.py` — `resolve_company`: Serper + homepage fetch → domain, aliases, LinkedIn slug (headcount best-effort, **not** gating per Regime′).
- Every tool: missing key → `ToolUnavailable`, never raises; respx fixtures.

### Workstream C — RESOLVE phase (full)

```
resolve/{enumerate.py, cluster.py, identity_score.py, fetch_order.py,
         reciprocal.py, disconfirm.py, gate.py, role_resolve.py, resolver.py}
```

- `enumerate.py` — ≤8 queries (spec templates minus `site:x.com`); variants capped at 3; one Serper batch + Exa neural.
- `cluster.py` (Cluster′) — merge **only** on identity-bearing co-occurrence: same URL, same rare handle (C17: ≥6 chars, not a bare first name/common word), same email, or same personal-site domain. **Never merge on a shared attribute token** (employer / title / school / city) — that is exactly what two same-name people at one company share, so merging there blends their profiles and pre-empts the gate, which is the project. Everything not identity-bearing stays **separate**; identity scoring + reciprocal verification do the rest. `rapidfuzz`. Emits `merge` events. Bucketing, not identity judgment.
- `identity_score.py` — the full [reference-identity-scoring.md](reference-identity-scoring.md) table; one batched T4 attribute-match call per ≤10 candidates (validate returned IDs); anchor tier × attr; uniqueness; surname rarity; name form; contradiction/tense/timeline/geo negatives. Score on SERP snippets before any fetch.
- `fetch_order.py` — order by expected discrimination (personal domains first), k=2.
- `reciprocal.py` — over `links[]`: `verify_reciprocal_link(a,b)` fetches both, tests mutual reference (+3.0); anchored one-way for unfetchable targets (+1.5, C21); merges clusters on a verified pair.
- `disconfirm.py` (C5) — T1: "what would falsify this match?" → returns ≤2 **executable** tool calls; run them; rescore. Also the pure `timeline_conflict_check`.
- `gate.py` — math first ([reference-identity-scoring.md](reference-identity-scoring.md) matrix); T1 veto only; CONTINUE executes `next_evidence` while budget remains; **max 2 gate cycles** (Gate-loop′); T1 failure → secondary model → ABSTAIN (C15).
- `role_resolve.py` (DEFINITE_DESC) — company → official team/about page + Wayback if past tense + LinkedIn SERP → T4 pick current holder → seed rewrite; `role_resolution` event; ≥2 competing official holders → `ambiguous`.
- HARD_ID_EMAIL pre-steps: Gravatar + GitHub email search before general enumeration. BARE_NAME: one pass, census-common ∧ ≥3 clusters → `ambiguous` immediately (C11).
- Evidence written under `candidates/{cid}/` **at write time**.

## Tests

- `test_identity_table.py` — **every** worked row in [reference-identity-scoring.md](reference-identity-scoring.md) asserts its `sum → P → result`.
- `test_variants_no_fabrication.py` — property test: no variant contains a character absent from the input.
- `test_regime.py` — 8 inputs (4 PDF + empty, gibberish, non-Latin, LinkedIn URL) → correct regime.
- `test_cluster.py` — `jsmith` on GitHub vs X stay separate; a rare handle merges; **two same-name candidates sharing only an employer token stay separate** (Cluster′).
- `test_gate_order.py` — model ABSTAIN overrides a math pass; model CONFIRM cannot override a math fail.

## Checkpoints (binary) — core met; DEFINITE_DESC + hardening open

- [x] `test_identity_table` (8 worked rows), `test_variants_no_fabrication`, `test_regime`, `test_cluster`, `test_gate_order` all green (47 total).
- [x] 3 of the 4 PDF inputs: **Henry Wang → confirmed** (right founder), **`andrew.goering@ramp.com` → confirmed** (HARD_ID path), **sarah chen → abstained** (T1 read the real profile, refused the Epic-Systems mismatch). **CTO of Ariglad → NOT built** (DEFINITE_DESC / `role_resolve` is the next increment).
- [x] Trace shows a **disconfirmation fetch executed** and a **runner-up rejected with a reason** (sarah chen run).
- [x] Tools degrade to `ToolUnavailable` when a key is missing (worker-tested for company; pattern shared).
- [x] Gate runs ≤2 cycles (one disconfirm cycle, then decide) — enforced structurally.
- [ ] **Open / hardening:** DEFINITE_DESC role-resolve; T4 batched attribute match (string-match today, mitigated by profile-grounded T1); 2 extra hand-checked common-name targets; recall when the real person isn't in the fetched top-2.

**Key design outcome:** the gate is now math-first → **gpt-4o T1 veto with the candidate's real profile always fetched first**. That combination is what produces correct-or-abstain: eager snippet anchors can pass the math, but the model reading the actual profile catches the mismatch. gpt-4o-mini confabulated here and was not enough.

## Degrade / cut behavior

Never cut: gate with margin, disconfirmation **execution**, evidence keyed by cid.
Cuttable under pressure: role_resolve Wayback branch (fall back to current team
page only); Gravatar pre-step; Exa neural query (keep site: queries).
