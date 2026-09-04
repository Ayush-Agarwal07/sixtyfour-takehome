# People Research Agent

Give it a freeform description of a person — an email, a profile URL, a name
and a company, or just a role ("the CTO of Ariglad") — and it returns a
confirmed identity plus a structured profile where every fact carries its
source URL, the exact text span it came from, and a deterministic confidence
score. It is built to refuse rather than guess: `ambiguous` and `abstained`
are correct, typed answers, not failures — a confidently wrong person is the
only real failure mode.

## Setup

Requires Python 3.11+.

```bash
uv sync --extra dev          # or: pip install -e ".[dev]"
cp .env.example .env
```

| Key | Required | Used for |
|---|---|---|
| `OPENROUTER_API_KEY` | yes | every LLM call (T1–T5), all routed through OpenRouter |
| `SERPER_API_KEY` | yes | web search — RESOLVE cannot enumerate candidates without it |
| `EXA_API_KEY` | no | reads LinkedIn/X/Crunchbase (the "unfetchable" hosts); without it those profiles are skipped, not crashed on |
| `GITHUB_PAT` | no | raises GitHub's unauthenticated 60 req/h cap and enables the `github_code` pivot's code search (which raises `ToolUnavailable` without it); profile/repo/commit-email reads work without it |

`FIRECRAWL_API_KEY` exists in `.env.example` but nothing calls it yet — leave
it blank. A missing required key makes that one tool raise `ToolUnavailable`;
the run degrades and returns a typed status, it never crashes.

## Run

```bash
pi investigate "andrew.goering@ramp.com"
```

(or, without an editable install on `sys.path`: `PYTHONPATH=src python -m pi.cli investigate "<target>"`)

Each run writes to `runs/<target>-<n>/`, where `<target>` is a slug of the
person and `<n>` counts runs of that same target: `runs/henry-wang-1`,
`runs/henry-wang-2`. The directory name is also the `job_id` the API returns.
The slug comes from the raw input, before the model parses it — an email or
profile URL gives the derived name, anything else gives the first comma segment
with request phrasing stripped ("do deep research on the CTO of Ariglad" →
`cto-of-ariglad-1`).

| File | Content |
|---|---|
| `output.json` | the profile envelope — the deliverable (see **Output shape** below) |
| `report.md` | the same findings as a readable dossier: profile tables with per-fact confidence and sources, timeline, a mermaid graph, rejected candidates |
| `trace.md` | human-readable trace: candidate scores, the gate math, disconfirmation, every tool/LLM call |
| `trace.jsonl` | one event per line: every tool call with its arguments, latency, and cache hit; every LLM call with model, tier, tokens, cost, latency, and a pointer to its reasoning sidecar; every planner choice against the formula's ranking; every same-person test; gate math; stop reason with numbers. `trace.md` is rendered from it |
| `reasoning/*.txt` | the model's reasoning for each gate/disconfirmation/planner call |
| `casefile.json` | full internal state, written atomically at every phase boundary and EXPAND batch |

`PI_NO_CACHE=1 pi investigate "..."` bypasses the HTTP/LLM disk cache (use this
to see real variance run-to-run). `pi render runs/<dir>` re-renders
`trace.md` after a code change without re-running the pipeline. `pi report
runs/<dir>` re-renders `report.md` the same way — every run writes one
automatically, and any past run can be re-rendered from its `output.json`.

## Run the API

```bash
PYTHONPATH=src uvicorn pi.api.app:app --port 8080
```

Start a job:

```bash
curl -s -X POST localhost:8080/investigate -H 'content-type: application/json' -d '{"target": "andrew.goering@ramp.com"}'
```

Poll it, tail the trace, or stream it live:

```bash
curl -s localhost:8080/investigate/<job_id>
curl -s localhost:8080/investigate/<job_id>/trace
curl -s -N localhost:8080/investigate/<job_id>/stream
curl -s localhost:8080/health
```

Set `PI_API_KEY` to require an `X-API-Key` header matching it on every route except `/health`.

## Output shape

Trimmed to ~40 lines from a real, confirmed run
(`examples/2_cto_ariglad/output.json`, input `"do deep research on the CTO of
Ariglad"`). Cut for space: the other
name-variant spellings on `seed`, the rest of `profile.employment`, the full
narrated `summary`, `timeline`, `identity_resolution`, and `graph` — none of
it is redacted, all of it is public data the pipeline found on the open web.

```json
{
  "status": "confirmed",
  "input": "do deep research on the CTO of Ariglad",
  "regime": "DEFINITE_DESC",
  "identity": {
    "confidence": {
      "score": 0.976, "logodds": 3.7,
      "terms": [
        {"factor": "prior", "weight": -1.5},
        {"factor": "anchor:employer:professional_network", "weight": 1.2},
        {"factor": "corroboration:employer:3src", "weight": 0.6},
        {"factor": "anchor:title:professional_network", "weight": 0.6},
        {"factor": "surname:rare", "weight": 2.0},
        {"factor": "uniqueness", "weight": 0.8}
      ]
    },
    "cid": "c2",
    "how_confirmed": "math P=0.976 margin=0.57 [...]; T1 CONFIRM",
    "footprint_since": "2013",
    "accounts_found": 3
  },
  "profile": {
    "current_role": {
      "predicate": "title", "value_raw": "CTO and Co-Founder",
      "temporal": {"start": "2020-05-01", "end_state": "ongoing"},
      "confidence": {
        "score": 0.332, "logodds": -0.7,
        "terms": [
          {"factor": "prior", "weight": -1.5},
          {"factor": "source_tier:professional_network", "weight": 1.4},
          {"factor": "conflict:soft", "weight": -0.3}
        ]
      },
      "evidence": [{"url": "https://ca.linkedin.com/in/aiavci",
                    "snippet": "CTO and Co-Founder - [ariglad](...)",
                    "source_class": "professional_network"}]
    }
  },
  "conflicts": [
    {"kind": "soft", "predicate": "title",
     "values": ["cto & cofounder", "cto and cofounder"], "severity": -0.3}
  ],
  "negative_findings": [{"predicate": "coverage", "sought": "public output (repos, publications, talks)",
                         "found": 0, "target": 3, "status": "not_found"}],
  "run_metadata": {
    "job_id": "75a83420c341",
    "budget": {"tool_calls": 27, "llm_calls": 17, "usd": 0.098, "seconds": 96.8},
    "stop_reason": "S2"
  }
}
```

`identity.footprint_since` is the earliest year in `timeline` (`null` if
empty); `identity.accounts_found` counts distinct `handle` claim values with
confidence ≥0.5. `timeline` (trimmed above) is a flat, deduped, date-sorted
list of `{date, text, claim_id, url}` built from every dated claim, capped at 40.
`unverified` (omitted above — empty on this run) holds real `Claim`s whose
source failed the same-person test below `ATTACH_PROFILE`: possibly a
different person of the same name, never merged into `profile`/`timeline`.

## Provenance per claim

Every claim answers two questions separately. *Did the source say this?* is
`evidence[]`: the cited URL, the verbatim snippet, `extraction_method` (json_ld,
site_parser, prose_llm, github_emails, gravatar, wayback, username_probe,
github_code, openalex, link) and `retrieved_at` — when this run recorded the
evidence (a cached page or Wayback snapshot keeps its own date in the URL or
snippet). *Is this source about the
target?* is `identity_link` (`hard_key:*`, `anchor_match:<categories>`,
`graph_path:<hops>`) plus `attachment_confidence`, the same-person test score
of the page it came from. Graph edges carry `mechanism`, the tool and host that
produced them. `report.md` renders all of this as one line per fact.

## How identity is decided

- Candidates come only from identity-bearing URLs found while enumerating the
  web — a LinkedIn `/in/…`, a GitHub user page, an X handle, a personal-site
  root. Press, company, aggregator, and academic pages are never a clustering
  key; they are floating evidence, attached to a candidate only once a fetched
  page actually links them.
- Every candidate gets a deterministic log-odds sum (regime prior + anchor
  matches weighted by source tier and attribute + surname rarity + name-form
  penalty + hard keys like a resolved seed URL or a verified reciprocal link).
  The sigmoid of that sum must clear **both** halves of the gate — top
  `P ≥ 0.85` **and** top `P` − runner-up `P ≥ 0.30` — before anything confirms.
- The math decides first, always. A T1 model may **veto** a passing gate
  (→ abstained/ambiguous) or ask for one more named piece of evidence
  (CONTINUE, at most 2 cycles); it can never override a failing gate into a
  confirm.
- Before a passing gate is trusted, executed disconfirmation runs: T1 writes a
  hypothesis for how the leading candidate could be the wrong person and up to
  2 real, executable tool calls that would show it. The calls actually run,
  the candidate is rescored on the result, and only then is the gate — and T1 —
  asked again.

## How findings are scored

Every claim's confidence is `prior (−1.5) + source tier + extraction rung +
corroboration + recency − conflict`, shipped as named terms on the claim
(`confidence.terms`) — never a single opaque float. Source tier is
predicate-aware and runs 2.5 (company/government/academic site) down to 0.2
(aggregator — never sole support for a claim). Extraction rung is 1.0 for
JSON-LD down to 0 for prose-LLM extraction, which must additionally pass a
substring (or ≥90% rapidfuzz) span check against the actual page text or the
tuple is dropped before it ever becomes a claim. Corroboration adds +1.2 for a
second independent source (`(source_class, registrable_domain)` as the
independence key) with 0.6× decay per source after that. Recency subtracts per
year for mutable predicates — 0 for immutable facts, up to −0.5/yr for contact
info — and any mutable claim with no context date at all takes a flat −0.3.

**Confidence is ordinally calibrated, not frequency-calibrated: a 0.9 is more reliable than a 0.6; it does not mean 90% correct.**

Confidence is about the *claim*; attachment is about the *source* — a deterministic
same-person test (`expand/anchors.py`, DESIGN.md §13) scores name presence (or the
person's own email/personal domain stated in the page), matched anchor categories,
and owned/linked bonuses into four bands: below 0.5 the source contributes nothing;
[0.5, 0.8) lands in `output.unverified`, never the profile; [0.8, 0.9) is a normal
profile claim; ≥0.9 is trusted enough to grow the anchor set.

### Pivots

Four EXPAND actions are forced into every batch ahead of the planner's own
picks, not ranked by relevance: `username_probe` (the candidate's own +
discovered handles, filtered for rarity, checked against 15 platforms),
`gravatar` (discovered emails), `github_code` (the person's name, then a
discovered corporate email — the candidate's own repos are excluded), and
`openalex` (seed schools or a discovered education/publication/academic
employer claim, gated on an institution match, not name alone). A
`username_probe` hit is scored by the same-person test above, like any other
new source — not a fixed confirmed/unverified pair.

## Edge-case behaviour

All rows below except the last are real, live runs — the run id is the receipt.

| Input class | Example | Typed status | Why |
|---|---|---|---|
| Empty | `""` | `abstained` | `understand()` short-circuits an empty string to a nameless `BARE_NAME` seed before any network call; RESOLVE's first check returns `abstained` with "no person name … in the input". (`runs/00c2920cb3e4`) |
| Gibberish | `"asdfgh qwerty zxcvb"` | `abstained` | T5 extracts no name from nonsense text; the empty name list hits the same guard as empty input. (`runs/18d0e822235e`) |
| Common bare name | `"John Smith"` | `ambiguous` | A `BARE_NAME` + census-`common` surname + ≥3 identity clusters + a failed gate is forced straight to `ambiguous` with the full candidate table (`resolver.py`'s common-bare-name branch), regardless of how weak any individual candidate scores — a live run found 5 "John Smith" clusters, each at P≈0.21, and returned `ambiguous` with `how_confirmed: "common bare name with several distinct people"`. (`runs/df7d09eec6ac`) (a title, school, or location makes it NAME_WEAK and it gets a full resolve pass) |
| Famous name, no anchor | `"Elon Musk"` | `ambiguous` (usually) | A bare name carries no employer/title for `seed_anchors()` to test against, so fame alone earns only the regime prior + surname rarity — nowhere near the 0.85 gate. "Musk" is census-`rare`, not `common`, so this misses the common-bare-name branch above and falls to the general rule: `ambiguous` when ≥2 candidate clusters each clear a 0.3 plausibility floor. A live run found 5 clusters at P≈0.62 each and returned `ambiguous`. The dominant-cluster public-figure bonus (`identity_score.compute_dominant`) only fires when enumeration collapses to **exactly one** candidate holding ≥8 sources that are ≥60% of all results — real, but rarer than fame alone would suggest, since a well-known name usually fragments into several distinct clusters instead. (`runs/5e8d99d4d94b`) |
| Non-Latin script | `"王小明, 阿里巴巴"` | `abstained` (evidence-dependent) | `unidecode` supplies a Latin search variant (`Wang Xiao Ming`); the untransliterated surname correctly falls back to the census `not_found` bucket (neutral +1.0) rather than misfiring as `rare` — but a single non-anchor-matched candidate still can't clear the gate alone. (`runs/7058af2ce184`) |
| No web presence | a real but unindexed person | `abstained` | Enumeration returns zero identity-bearing URLs; `cluster()` yields no candidates and no usable floating evidence, and RESOLVE returns "no pages about '\<name\>' matched the enumeration queries" — no EXPAND budget is spent chasing nothing. |

## Cost and time

Five canonical inputs, one run each, straight from `run_metadata.budget` in `examples/*/output.json`:

| Input | Example | Status | Tool calls | LLM calls | USD | Seconds | Stop reason |
|---|---|---|---|---|---|---|---|
| `andrew.goering@ramp.com` | `examples/3_andrew_goering` (`andrew-goering-11`) | confirmed | 17 | 13 | $0.049 | 63.6s | S_frontier_empty |
| `Henry wang, sixtyfour ai` | `examples/1_henry_wang` (`henry-wang-32`) | confirmed | 38 | 40 | $0.213 | 155.4s | S2 |
| `sarah chen, product designer, ex-figma` | `examples/4_sarah_chen_refusal` (`sarah-chen-8`) | abstained | 9 | 14 | $0.066 | 95.8s | no_expand:abstained |
| `do deep research on the CTO of Ariglad` | `examples/2_cto_ariglad` (`cto-of-ariglad-13`) | confirmed | 33 | 24 | $0.112 | 146.6s | S2 |
| `Saarth Shah, Sixtyfour` | `examples/5_saarth_shah` (`saarth-shah-4`) | confirmed | 35 | 28 | $0.174 | 118.2s | S2 |
| **mean** | — | — | 26.4 | 23.8 | **$0.123** | **115.9s** | — |

Example 5 is the subject of Sixtyfour's own public reference report; see DESIGN.md for what we find and do not find.

Live runs vary between invocations (real search results, real model sampling)
— these are one draw each, not an average over repeats; see **Eval and replay**
below for a harness that repeats N times per target.

The cheapest run (Andrew Goering, HARD_ID_EMAIL) is cheap because uniqueness is
trivially satisfied with one candidate (see DESIGN.md); Sarah Chen still costs
real money to *abstain* — RESOLVE spends its evidence-cycle budget genuinely
trying to separate plausible candidates before giving up rather than guessing.

## Eval and replay

```bash
python eval/run_eval.py --runs 2 --no-cache          # live, sequential, one target at a time
PI_OFFLINE=1 pi investigate "Henry wang, sixtyfour ai"  # replay a cached run, network off
python check_run.py runs/<id>                          # invariant check on one run
```

`run_eval.py` runs each target in `eval/targets.json` through the real pipeline
and prints one row per run — `input | run | status | top_P | claims | tool_calls
| usd | seconds | ok` — then a summary line with the identity-correct rate and
mean cost/time. `ok` compares the status against the target's expected status
(or list of acceptable statuses). `--no-cache` disables the disk cache so every
run pays full cost and shows real variance.

`PI_OFFLINE=1` is replay mode: a cache miss raises instead of hitting the
network, so a run can only use what a prior cached run stored. Because the
budget counts every tool call (cache hits included, reported as `cache_hits`),
the planner sees only calls left, and set-derived prompt content is sorted, a
replay reproduces the original run's tool calls, budget, and claims under an
all-cache replay; the exact interleaving of parallel actions is not pinned.
That isolates a code change from web drift: same inputs, different output
means the code changed the behaviour.

`check_run.py` re-checks one run's `output.json` against the invariants that
must always hold: every claim has evidence and an `identity_link`, every
evidence record belongs to the confirmed candidate, the budget is sane.

**Repeated runs (2026-09-03, `--runs 2 --no-cache`, 6 targets):** identity
correct or refused 12/12, confident-wrong 0. The four real targets confirmed
the same person both times at the same identity confidence; claim counts varied
with the web (Henry Wang 23 vs 19, Ariglad 18 vs 17). Mean $0.083 and 93 s per
run including the two edge inputs. Replay reproduced a cached Henry Wang run
exactly: 29 claims, 41 tool calls both times, $0.00 offline.

## Layout

```
src/pi/
  run.py         orchestrator — understand → resolve → gate → expand → synthesize; casefile writes; trace + report render on exit
  cli.py         `pi investigate | render | report`
  report.py      output.json → report.md, the readable dossier
  api/           FastAPI: POST/GET /investigate, trace, SSE stream, /health
  constants.py   every weight, cap, tier, model slug — DESIGN.md is derived from this file
  types.py       every Pydantic model in the pipeline
  sources.py     URL → source class → tier, the one classifier used everywhere
  understand/    parse.py regime.py variants.py census.py email_derive.py — text → Seed + regime
  resolve/       enumerate.py cluster.py match.py identity_score.py links.py disconfirm.py gate.py role_resolve.py resolver.py — RESOLVE + the identity gate
  expand/        frontier.py planner.py anchors.py extract.py assemble.py slots.py graph.py expander.py — the agentic EXPAND loop and the same-person test
  synth/         synthesize.py — programmatic profile + cited T2 summary
  score/         claim_score.py canonical.py temporal.py — claim confidence, value canonicalization, date parsing
  tools/         serper.py exa.py fetch.py github.py gravatar.py wayback.py usernames.py openalex.py company.py — each @traced
  llm/           client.py + prompts/*.md — the OpenRouter client, cache, cost, reasoning sidecar
  trace/         events.py writer.py render.py — every decision, traced
  store/         casefile.py cache.py urlnorm.py — atomic casefile, HTTP/LLM disk cache
tests/           unit tests — feed the scorers by hand, do not run the live pipeline
eval/            targets.json + run_eval.py — the live eval harness
plan/            the build contract — design-decisions.md and the reference-*.md docs
```
