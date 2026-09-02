# Stage 1 — Vertical slice on the easiest input

**Owner:** you, sequential. **~3h.** **Prereqs:** Stage 0 green.
**Builds against:** all reference docs (subset only).

The point: **prove the whole pipe connects** on the easiest input before building
the hard machinery. This is **not throwaway** — you implement the real modules
shallow, and Stages 2–3 deepen the same files. If everything after this stage
slips, you still have a runnable agent and a readable trace.

Target input: `andrew.goering@ramp.com` (HARD_ID_EMAIL — no name parse ambiguity,
prior 0, a clean confirm path).

## Scope — shallow implementations of the real modules

| Phase | Shallow version built now | Deferred to Stage 2/3 |
|---|---|---|
| understand | email regex, `email_derive` (name + employer from domain), regime = HARD_ID_EMAIL | T5 parse, variants, other regimes, tense |
| resolve | 1–2 searches, trivial cluster, identity_score subset (prior 0, surname rarity, employer snippet, unique), gate math + **one real T1 confirm** | full §3 table, disconfirm, reciprocal, role_resolve, k=2 ordering |
| expand | **no planner** — one k=4 batch off links + 2 slot templates; ladder = JSON-LD + span-checked prose LLM; assemble claims with `identity_link` | planner, frontier formula, full ladder, wow-sources, reinforce |
| synthesize | programmatic profile from claims; minimal/no T2 summary | T2 summary, conflicts, inferences, specialization_payoff |

## Also in this stage: resolve the two load-bearing build-time checks

These change downstream design, so answer them **here**, not in Stage 3:

1. **Exa `contents` on a LinkedIn profile URL** — does it return usable
   *experience* text? Record yes/no in [design-decisions.md](design-decisions.md) build-time checks. If no,
   the `employment_history ≥3` slot falls back to GitHub / personal sites /
   press / Wayback in Stage 3 — note it now.
2. **`resolve_company`** returns a domain + aliases for `ramp.com` / `sixtyfour` /
   `ariglad`. Confirm the shape.
3. Fill real **OpenRouter slugs + prices** into `constants.py` (replace the
   `TODO_VERIFY` placeholders) and confirm one T1 and one T3 call actually return.

## Modules touched (real files, shallow)

```
understand/{parse.py (email path only), email_derive.py, regime.py, census.py}
resolve/{enumerate.py, cluster.py, identity_score.py (subset), gate.py (math + T1)}
tools/{serper.py, exa.py, fetch.py, company.py}
expand/{expander.py (one batch), extract/{jsonld.py, prose_llm.py}, assemble.py}
synth/{synthesize.py (programmatic), output.py}
run.py  cli.py
```

`email_derive` patterns: `first.last`, `first_last`, `first-last`, `flast`,
`firstl`, `f.last`, `first`, digit-strip → name hypotheses with a pattern
confidence; domain → employer via `resolve_company`.

## Tests

- `test_email_derive.py` — `andrew.goering@ramp.com` → first=andrew, last=goering, employer=ramp.com; `jsmith@ramp.com` → initials form.
- `test_slice_smoke.py` — with recorded fixtures (respx + cached LLM), `run("andrew.goering@ramp.com")` returns a valid `Output` with `status=confirmed`, ≥1 claim, ≥1 evidence, and a non-empty `trace.jsonl`.
- `test_extract_span_check.py` (seed here, expand in Stage 3) — a prose-LLM tuple whose span is **not** a substring of the page (and rapidfuzz partial <0.9) is **dropped**.

## Checkpoints (binary) — ✅ core met (2 deliberate deferrals)

- [x] `pi investigate "andrew.goering@ramp.com"` (live) → `output.json` validates, `status=confirmed`, real claims (title, employer ×2 sources, location).
- [x] `trace.md` readable end to end: phase transitions, tool calls with latency, gate math + decision with reasoning, explicit `Stop` reason.
- [x] Every `Evidence` carries `candidate_id == confirmed_cid` (isolation holds).
- [x] Probe #1 (Exa LinkedIn contents) = YES, wired; #3 model slug verified live. (Probe #2 `resolve_company` **deferred** — email path doesn't need it, see design-decisions.)
- [x] `test_email_derive`, `test_extract_span_check` green (20 tests). `test_slice_smoke` **deferred** to Stage 2 (respx fixtures land with the tool tests; the live run is the smoke test for now).
- [x] One real T1 gate call returned valid structured JSON; reasoning in `reasoning/{event_id}.txt`, rendered in the trace (now served from cache).

## Degrade / cut behavior

This stage is the floor. If Stages 2–5 all slip, this — plus README + one example
— is a shippable submission. Do not leave Stage 1 until every checkpoint is green.
