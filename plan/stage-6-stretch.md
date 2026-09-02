# Stage 6 — Stretch (only if Stages 0–5 all green)

**Owner:** you / spare agents. **Time-boxed, opportunistic.** **Prereqs:** every
Stage 0–5 checkpoint green. **Do not** start any of these while a Stage 5
checkpoint is red — Findings/Trace quality outrank all of it.

These are ordered by value. Each is independent; do them in order, stop when time
runs out.

## 6.1 — SSE streaming

`GET /investigate/{id}/stream` (sse-starlette) tails the trace queue so a reviewer
watches decisions live. Low risk (read-only over existing trace).
**Checkpoint:** a `curl` to the stream endpoint emits events as a run progresses.

## 6.2 — Hosted API (the deliverable bonus)

Deploy the FastAPI app to Fly.io (or Render) with a volume for `runs/` + `.cache/`.
Keep it light — **no Playwright** (Firecrawl covers JS). Enforce `X-API-Key`,
3-job cap, per-job `$0.75`, daily job cap (C22) so the $100 key isn't public.
**Checkpoint:** a public `POST /investigate` from another machine returns a
`job_id`; `GET` returns the output; key required.

## 6.3 — Replay mode

`PI_OFFLINE=1` makes cache misses raise, so an eval run executes entirely against
the content cache with the network off. This is the honest answer to "better or
just different" — isolates code changes from web drift.
**Checkpoint:** `PI_OFFLINE=1 python eval/run_eval.py` completes with zero network
calls and reproduces cached-run identities.

## 6.4 — Famous-person path (Wikidata)

A `wikidata` tool for the "famous person" edge case: a public figure resolves
fast via a structured authority instead of burning the enumeration budget.
**Checkpoint:** a famous-name input confirms via Wikidata in ≤3 tool calls.

## 6.5 — Academic class (OpenAlex / ORCID)

For `academic`-class targets, add OpenAlex/ORCID tools → publication list,
co-authors, affiliations. High value only for researcher targets.
**Checkpoint:** a researcher input produces ≥3 `publication` claims sourced to
OpenAlex/ORCID.

## Cut order reminder

If you are in Stage 6 and time is short, prefer **6.2 (hosted API)** and **6.3
(replay)** — they map directly to a listed bonus and to discussion topic #4. SSE,
Wikidata, and academic tools are polish.

## What to explicitly **not** build (discussion answers, not code)

Per §17 of the spec and discussion prep — mention these in the follow-up, do not
implement:

- Cross-run entity accumulation (content-derived IDs already enable it for ~zero cost).
- Second-degree resolution (profiling the target's connections).
- Temporal monitoring (re-crawl over days, slow channels like FOIA, human escalation) vs point-in-time snapshot.
- Frequency calibration (~200 hand-labeled claims; isotonic on raw log-odds; ECE/Brier). Method documented in DESIGN.md, data out of scope.
- Reinforce-vs-expand common-unit normalization (expected confidence gain per second) — the principled version; current trigger condition is the shippable one.
