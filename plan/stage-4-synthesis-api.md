# Stage 4 — Synthesis + API + edge cases

**Owner:** 1 agent. **~2h.** **Prereqs:** Stage 3 green (or Stage 1 slice if
compressed). **Builds against:** [reference-contracts.md](reference-contracts.md) §6.

Turn findings into the output envelope, wrap it in a durable API, and prove it
never 500s.

## Scope

### Workstream A — synthesis

```
synth/{synthesize.py, output.py}
```

- `profile` assembled **programmatically** from claims (deterministic — no model invents structure).
- T2 writes `summary[]` sentences, **each citing ≥1 `claim_id`**; any sentence with no citation is **dropped**. Long-context coherence, no embellishment.
- `conflicts[]` — both values, both sources, unresolved.
- `negative_findings[]` — seed assertions sought and **not** confirmed. (Seed is not knowledge; unconfirmed seed content lands here, never as a claim.)
- `identity_resolution` — candidates with scores + terms + URLs, `rejected[]` with reasons, `what_would_disambiguate[]`.
- `specialization_payoff[]` — claim_ids whose sole source was github_emails / wayback / gravatar / reciprocal / commit_email.
- `inferences[]` — synthesis inferences, **unscored**, `identity_link:inferred`, never mixed into `claims`.
- Conflicts and negative findings make the output **more** trustworthy; a clean profile with no gaps reads as a system that doesn't check.

### Workstream B — API + CLI

```
api/{app.py, jobs.py}   cli.py
```

- `POST /investigate` → `202 {job_id}`; `GET /investigate/{id}` → `200` (or `404`); `GET /investigate/{id}/trace`; `GET /health`.
- FastAPI, in-process asyncio pool, **filesystem as durability layer** (no Celery). Casefile is source of truth; on restart, running jobs → `failed_restart`, partial served (C9).
- `X-API-Key` required when set (C22); max **3 concurrent *running* jobs** (job semaphore); submissions beyond queue (`202`); `429` only when in-flight > `MAX_INFLIGHT` (env, default 10) (Concurrency′); per-job hard `$0.75`; daily job cap via env var; `422` for unparseable input.
- Idempotency: every call is a new run, new `job_id` (reviewers test variance directly).
- `cli.py` — `investigate | render | eval`.

### Edge cases — typed JSON, never 500

empty string · gibberish · famous person · no web presence · public-figure name
collision · non-Latin script. Each returns a valid envelope with an appropriate
`status` (`abstained` / `ambiguous` / `failed` / `confirmed`).

## Tests

- `test_api_edge_cases.py` — the six edge inputs each return a typed envelope, **no 500**, correct-ish status.
- `test_synth_citation.py` — a summary sentence with no `claim_id` is dropped; no unconfirmed-evidence claim reaches the output.
- `test_concurrency.py` — 5 concurrent `POST`s all complete with **≤3 running at once** (verifiable via timing/trace); submissions beyond `MAX_INFLIGHT` return `429`.

## Checkpoints (binary)

- [ ] Output validates against the `Output` envelope for a real run.
- [ ] **No unconfirmed evidence in output** — every claim's evidence is under `confirmed_cid`; `test_synth_citation` green.
- [ ] Six edge inputs → typed statuses, **zero 500s** (`test_api_edge_cases` green).
- [ ] 5 concurrent submissions all complete with **≤3 running at once**; submissions beyond `MAX_INFLIGHT` → `429` (`test_concurrency` green).
- [ ] `X-API-Key` enforced when set; `422` on unparseable input; `/health` returns ok.
- [ ] `abstained`/`ambiguous` runs still return `identity_resolution.candidates[]` + `what_would_disambiguate[]` (C24).

## Degrade / cut behavior

Cuttable: `X-API-Key` + rate limiting (keep for hosted, skip for local-only);
`inferences[]` (fold into nothing rather than fabricate). Never cut: programmatic
profile assembly, citation-drop rule, isolation in synthesis.
