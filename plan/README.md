# People Research Agent — Build Plan (index)

This directory is the implementation contract for the Sixtyfour take-home. Each
file is one part of the build; every part ends in **binary checkpoints** (a gate
you either pass or you don't — no "mostly done"). Do not start a stage until the
previous stage's checkpoints are all green.

## The one-paragraph brief

Freeform natural-language target in → structured, provenance-carrying JSON
profile out, driven by a real-time research agent. Graded most on **Agentic
Behavior** and **Findings Quality**, then Specialization, Trace Quality,
Performance, Reliability. Deliverables: runnable repo + README, `examples/` with
3 runs (input, output JSON, trace), bonus hosted API.

## Architecture spine (unchanged across all stages)

```
INPUT
  → UNDERSTAND   (no network → Seed + regime)
  → RESOLVE      (flat candidate list + identity links, scoring only)
  ═══ IDENTITY GATE ═══   math first; model may veto a pass, never override a fail
  → EXPAND       (findings graph rooted at the confirmed person, planner-driven)
  → SYNTHESIZE   (profile JSON + graph JSON + trace)
```

The gate is the spine. Nothing in EXPAND revisits identity; nothing in RESOLVE
enriches. Evidence is filed under a `candidate_id` **at write time**; synthesis
only ever reads the confirmed candidate's evidence.

## Core principle of this plan: build vertically, then deepen

The build is **not** breadth-first (all tools, then all scoring, then all
phases). It is a thin **vertical slice** through every phase on the easiest
input, then depth added to the same modules. The slice is **not throwaway** —
you implement the real files shallow-first and deepen them in place. If time
runs out you degrade to "shallower but running," never "half-wired."

## Build sequence

| Stage | File | Owner | ~h | One-line gate |
|---|---|---|---|---|
| 0 | [stage-0-contracts.md](stage-0-contracts.md) | you (seq) | 2 | `import pi`; every model instantiates; fake run renders `trace.md` |
| 1 | [stage-1-vertical-slice.md](stage-1-vertical-slice.md) | you (seq) | 3 | `pi investigate "andrew.goering@ramp.com"` → valid output + trace, one real run |
| 2 | [stage-2-resolve.md](stage-2-resolve.md) | parallel | 4 | 4 PDF + 2 common-name targets → correct or abstain, **zero confident wrong** |
| 3 | [stage-3-expand.md](stage-3-expand.md) | parallel | 5 | coverage fills; ≥1 planner query + ≥1 verify in trace; isolation holds; ≥1 specialization payoff |
| 4 | [stage-4-synthesis-api.md](stage-4-synthesis-api.md) | 1 agent | 2 | envelope validates; 6 edge inputs typed, no 500; 5 concurrent |
| 5 | [stage-5-examples-eval-docs.md](stage-5-examples-eval-docs.md) | you | 3–4 | fresh clone + `.env` → run in <5 min; 3 examples committed |
| 6 | [stage-6-stretch.md](stage-6-stretch.md) | if time | — | SSE / deploy / replay / famous-person / academic |

Estimates are optimistic. Stage 3 is where reality bites; the Stage 1 slice is
the hedge that guarantees a runnable artifact regardless.

## Reference docs (shared; read before the stages that cite them)

- [design-decisions.md](design-decisions.md) — every decision and every change from the spec, with the reason. Object to any row before building.
- [reference-contracts.md](reference-contracts.md) — types, closed predicate vocabulary, output envelope, trace events, model routing, concurrency, cache. Stage 0 implements this.
- [reference-identity-scoring.md](reference-identity-scoring.md) — the log-odds identity table + worked rows that become test fixtures. Stages 1–2.
- [reference-confidence-scoring.md](reference-confidence-scoring.md) — per-claim log-odds confidence, spread check, temporal rules. Stages 1, 3.

## Cut order (cut top-first if time compresses)

SSE → hosted deploy → replay mode → OpenAlex/ORCID/Wikidata → 6-target eval down
to 3×1 → SCALING.md to a README section → Wayback/Gravatar → planner
`new_actions` (keep `picks`).

**Never cut:** gate with margin · evidence keyed by cid · disconfirmation
execution · planner `picks` · verify/reinforce · commit-email→employer
inference · span verification · `identity_link` on every claim · trace renderer.

## The four things that carry the weight

1. Identity gate with margin ([reference-identity-scoring.md](reference-identity-scoring.md), Stage 2)
2. Evidence keyed by `candidate_id` at write time (Stages 1, 3)
3. Reciprocal-link / anchored-one-way verification (Stage 2)
4. `identity_link` on every claim (Stages 1, 3)

## Checkpoint discipline

- Each stage file has a `## Checkpoints` section with a checkbox list.
- A checkpoint is **binary and observable** — a test that passes, a command that
  produces a named artifact, a trace event that appears. "Looks done" is not a
  checkpoint.
- If a checkpoint can't be made green, either fix it or explicitly log it as a
  documented cut in [design-decisions.md](design-decisions.md). Never silently skip.
