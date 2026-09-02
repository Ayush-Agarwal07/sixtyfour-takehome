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

## Checkpoints (binary) — re-audited 2026-09-02

Audit found two earlier runs (`runs/01822fb4688e`, `runs/5d2837983dcf`) that CONFIRMED
a Technical Solutions Engineer at Epic Systems as "sarah chen, product designer,
ex-figma" at P=0.964. Root causes fixed: substring anchor matching with no
`contradicts` path → T4 categorical matcher (`resolve/match.py`); LinkedIn text
tiered 2.0 → one classifier (`pi/sources.py`); 98-row census bucketing Chen/Wang as
uncommon → full 2010 table; fetch-order-dependent uniqueness → snippet-level only;
surname-based cluster merging → identity keys + verified links (`resolve/links.py`);
canned "disconfirmation" → executed T1 call on math pass (`resolve/disconfirm.py`).

Rule for every checkpoint below: a target ends **confirmed on the right person OR
ambiguous/abstained**. Never confirmed on the wrong person. Do not change weights
to make a target confirm; weight changes must keep `test_identity_table` green
and be recorded in DESIGN.md.

- [x] `test_identity_table` (incl. the Epic-Systems regression row), `test_match`,
  `test_cluster`, `test_links`, `test_sources`, `test_census`, `test_regime`,
  `test_gate_order`, `test_traced_args`, `test_llm_client` green.
- [x] The 4 PDF inputs run with the fixed pipeline (2026-09-02):
  `andrew.goering@ramp.com` → confirmed (`runs/3f07d4e7846a`, P=0.987, $0.016);
  `Henry wang, sixtyfour ai` → confirmed via self-published links henrywa.ng → GitHub/LinkedIn
  (`runs/ebbf8e8db714`, P=0.973, 3 namesakes rejected with reasons, $0.026);
  `sarah chen, product designer, ex-figma` → ambiguous with per-candidate reasons and specific
  disambiguation inputs (`runs/6c0ed8c8c30f`, top P=0.495, $0.020);
  `CTO of Ariglad` → role resolved to Ali Avci, LinkedIn confirmed, GitHub namesake rejected
  (`runs/1cd743907433`, P=0.937, $0.028).
- [ ] 2 additional verifiable common-name targets → correct or abstain.
- [x] Trace shows a T1 disconfirmation with an executed action (search or fetch),
  a `candidate_score` block with terms, and every tool call with its arguments.
- [ ] Every tool degrades to `ToolUnavailable` when its key is missing.
- [ ] Gate never runs more than `GATE_MAX_CYCLES` evidence cycles.

## Degrade / cut behavior

Never cut: gate with margin, disconfirmation **execution**, evidence keyed by cid.
Cuttable under pressure: role_resolve Wayback branch (fall back to current team
page only); Gravatar pre-step; Exa neural query (keep site: queries).
