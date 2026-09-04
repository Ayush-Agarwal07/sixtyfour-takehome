# Scaling

This build is deliberately D1: filesystem state, no DB, one process (`plan/design-decisions.md`).
Three places that decision stops holding, and the seam already in the code to fix each.

## At 100 concurrent runs

`api/app.py` caps *running* jobs at `constants.MAX_RUNNING_JOBS` (3) behind an
`asyncio.Semaphore` and queues the rest in an in-process `jobs: dict` and
`queued: set` — both live in one Python process's memory. 100 submissions to
one process queue fine (the semaphore just makes 97 of them wait); 100
submissions spread across N replicas do not, because `jobs`/`queued`/`daily`
are per-process: `GET /investigate/<job_id>` 404s on any replica that didn't
happen to run that job, and the daily cap becomes N× the configured value
since each replica counts its own. `constants.SEMAPHORES` (serper 5, exa 3,
openrouter 8, fetch 10) are the same problem one layer down — per-process caps
meant to protect one shared OpenRouter/Serper key blow through the real
provider rate limit the moment there's more than one process. The fix is the
standard one: move the semaphores to a shared token bucket (Redis) so the
*provider* limit is enforced globally, replace the in-memory `jobs`/`queued`
dicts with a real queue (Redis/SQS) and stateless workers pulling from it, and
give each tenant its own API key mapped to its own quota — and, ideally, its
own upstream provider key — so one heavy caller can't starve the rest. The
local `.cache/` diskcache should move to something shared (Redis or an
object-store-backed cache) for the same reason: N processes with N cold caches
both pay for the same page twice and fight over local disk locks.

## At 10k stored entities

Nothing here is starting from zero: claim ids, evidence ids, and graph node
ids are already content-derived (`sha256(predicate + value + url)`,
`f"person:{cid}"`, `f"company:{value}"`), so two runs that hit the same
LinkedIn page produce the *same* claim id today — the dedup key already
exists, it's just never checked across runs, because each run's `Casefile`
lives alone in `runs/<job_id>/casefile.json`. The first move is mechanical:
put casefiles in a document store (Postgres/Mongo) instead of one JSON file
per directory, so 10k people are queryable by name/domain/handle instead of
only by job id. The second is structural: promote `Candidate.identity_keys`
(`linkedin:slug`, `github:user`, `site:domain`) from a per-run clustering key
into the primary key of a persistent entity table, so `expand/graph.py`'s
per-job `Graph` becomes one subgraph merged into a standing entity graph
instead of thrown away when the run ends — that's what makes "this
relationship node in job B is the same person confirmed in job A" a lookup
instead of a re-investigation. Third, `constants.CACHE_TTL_S` already encodes
a staleness policy per source class for raw HTTP responses (6h code_host, 30d
press, 7d personal/company sites); the same policy should govern when a
*stored claim* is old enough to justify a scheduled re-crawl, keyed off the
claim's `RECENCY_DECAY` predicate class rather than just the page cache
expiring silently underneath it.

## When the same person is investigated twice

Today a second run on Andrew Goering starts RESOLVE from an empty candidate
list — no read of the first run's confirmed identity. With the entity table
from the section above, an exact `identity_key` match (same email, same
profile URL) should let RESOLVE skip enumeration and clustering entirely and
feed the prior run's confirmed candidate straight into `frontier.seed()`,
spending its budget only on reconfirming the identity still holds (one fetch
+ gate check) rather than rediscovering it from scratch. The same lookup
enables cross-run corroboration that doesn't exist yet: `score_claim`'s
`n_independent` currently counts only sources *within* one run's evidence
list; a claim reproduced by a second, independent run is exactly the
corroboration `constants.CORROBORATION_SECOND` was built to reward, and
`merge_claims`'s soft-conflict logic already does the hard part of comparing
two current-employer/title claims — extending that comparison across time
(newer `context_date` disagrees with the last run's) turns a plain conflict
into a "this changed since last time" finding, which is a better answer than
either abstaining or silently overwriting. Finally, the resume design: this
build cuts mid-run resume (C9) on purpose, but the infrastructure for it is
already half-built — `write_casefile` is atomic (`os.replace`) and fires at
every phase boundary and after every EXPAND batch, so the state to resume
from is already on disk when a process dies. What's missing is (a) a status
distinct from the generic `status = "failed"` that `api/app.py:
_mark_incomplete_failed` stamps on every non-`done` casefile at startup — call
it `failed_restart` so a caller can tell "the process died mid-run" from "the
pipeline concluded, abstained" — and (b) an actual restart path: re-enter
`investigate()` at the casefile's recorded `phase` with its `seed`/
`resolution` pre-loaded instead of at `understand`, relying on the existing
HTTP/LLM cache to make replayed calls nearly free rather than inventing a new
checkpoint format.

The two discovery pivots added since (`tools/usernames.py`, `github.py:code_search`)
are exactly this same opportunity in miniature: a confirmed `username_probe`
hit or a `github_code` hit is a stable identity key — as durable as the
`linkedin:slug`/`github:user` keys already named above — but today it is only
cached per-request (namespaces `usernames`/`github` in the local `.cache/`
diskcache), not written into any cross-run table. Once the entity table
exists, a confirmed handle or a code-search match that resolved to this
person should be written there the same way, so a second run recognizes "this
GitHub login is them" from the table instead of re-probing 15 platforms and
re-running GitHub code search from zero.
