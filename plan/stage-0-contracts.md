# Stage 0 — Contracts + plumbing

**Owner:** you, sequential. **~2h.** **Prereqs:** none.
**Builds against:** [reference-contracts.md](reference-contracts.md).

The spine everything else is built on. Define the **full** types now (Pydantic is
cheap) even though Stages 1–3 implement behavior shallow-first. Nothing here
touches the network or an LLM.

## Scope

In:
- Package skeleton + tooling.
- `types.py` — every model in [reference-contracts.md](reference-contracts.md) §2, plus all trace event models and the Output envelope.
- `constants.py` — every weight/cap/timeout/tier/model slug from the reference docs, each with a comment naming its derivation (judgment / census / reasoned / standard).
- `deps.py` — `Deps` dataclass + `Tool` base with the `@traced` decorator, semaphore, timeout.
- `trace/` — event models, JSONL writer (append + fsync), reasoning sidecar writer, `render.py` (JSONL → `trace.md`).
- `store/` — `casefile.py` (atomic write via temp + `os.replace`), `cache.py` (diskcache wrappers, `PI_NO_CACHE`/`PI_OFFLINE`), `urlnorm.py` (+ its unit test).
- `llm/prompts/*.md` skeletons with declared input/output schemas (bodies rough; Stage 1–3 tune them).

Out: any tool that hits the network, any phase logic, any scoring math.

## Modules & files

```
pyproject.toml  README.md  .env.example  .gitignore (runs/, .cache/, .env)
src/pi/
  __init__.py  constants.py  types.py  deps.py
  trace/{events.py, writer.py, render.py}
  store/{casefile.py, cache.py, urlnorm.py}
  llm/prompts/{parse,match,extract,disconfirm,gate,planner,synth,role_resolve}.md
tests/{test_types.py, test_urlnorm.py, test_trace_render.py}
```

## Tasks

1. `pyproject.toml` with deps (anthropic/openai client, instructor, tenacity,
   httpx, trafilatura, selectolax, extruct, fastapi, uvicorn, sse-starlette,
   pydantic, aiofiles, python-dotenv, diskcache, orjson, nameparser, unidecode,
   nicknames, rapidfuzz, tldextract, dateparser, pytest, pytest-asyncio, respx,
   pandas). No LangChain/LlamaIndex/LangGraph. Playwright/VLM excluded.
2. `types.py` — copy [reference-contracts.md](reference-contracts.md) §2 verbatim into Pydantic. Add every trace event model (§7) as a discriminated union on `event_type`. Add the `Output` envelope (§6) and a `Casefile` model.
3. `constants.py` — identity term weights, claim tiers, extraction rungs, regime caps + priors, budget/stop numbers, semaphores, timeouts, cache TTLs, tracking params, model slugs (leave slug values as `TODO_VERIFY` strings; Stage 1 fills real ones). Each with a one-line derivation comment.
4. `deps.py` — `Deps` dataclass; `Tool` base class exposing `async run()`, wrapped by `@traced` that emits a `tool_call` event (name, args, latency, ok/error) and enforces the tool's semaphore + timeout.
5. `trace/writer.py` — append-only JSONL, one event per line via orjson; `write_reasoning(event_id, text)` → `reasoning/{event_id}.txt`.
6. `trace/render.py` — read `trace.jsonl` → `trace.md`: sections per phase transition; a decision block for each `gate_decision` / `planner_decision` / `disconfirmation` (show reasoning excerpt + chosen-vs-not); a final tool table (name, args-summary, latency_ms, cost_usd, cache_hit).
7. `store/casefile.py` — `write(casefile)` atomic; `read(job_id)`.
8. `store/urlnorm.py` — the normalization from [reference-contracts.md](reference-contracts.md) §9; blocklist not allowlist.
9. `store/cache.py` — http + llm caches; env switches.
10. Prompt skeletons — each `.md` states its input fields and its exact output JSON schema at the top as a comment block.

## Tests (must exist and pass)

- `test_types.py` — every model instantiates from a minimal fixture; `Output` round-trips through `.model_dump_json()` and back; the trace union discriminates correctly.
- `test_urlnorm.py` — tracking params stripped; `www.`/fragment/trailing-slash removed; unknown param **kept**; `http`→`https`; two equivalent URLs normalize equal.
- `test_trace_render.py` — a hand-built `trace.jsonl` with one of every event type renders to non-empty markdown containing each phase name and each decision block.

## Checkpoints (binary) — ✅ ALL GREEN

- [x] `python -c "import pi"` succeeds; `pytest tests/` green (12 passed).
- [x] Every model in [reference-contracts.md](reference-contracts.md) §2 + every trace event + `Output` instantiates from a fixture (`test_types.py`); `Output` round-trips JSON.
- [x] `constants.py` imports standalone; gate log-odds threshold computes to 1.735.
- [x] A script writing one of **every** (18) trace event type produces `trace.jsonl`, and `render.py` turns it into a readable `trace.md` with decision blocks (disconfirmation/gate/planner) and a calls table.
- [x] Casefile write is atomic (`os.replace`; no leftover `.tmp`; overwrite keeps a valid file).
- [x] `urlnorm` unit test green, including the "keep unknown param" case.
- [x] All 8 prompt `.md` files exist with an input/output schema comment block.

## Degrade / cut behavior

Nothing here is cuttable — it is the contract. If time is tight, the render.py
polish (tool table formatting) is the only thing that can be rougher.
