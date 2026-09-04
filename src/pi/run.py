"""Orchestrator: understand → resolve → gate → expand → synthesize.

Casefile written atomically at every phase boundary; trace rendered on exit even
on failure. Budget counters live on Deps and are reported in run_metadata."""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from time import perf_counter

import httpx
from dotenv import load_dotenv
from unidecode import unidecode

from .deps import Deps
from .expand import expand
from .llm.client import LLM
from .report import render_report
from .resolve import resolve
from .store.cache import Cache
from .store.casefile import write_casefile
from .synth import synthesize
from .tools import Company, Exa, Fetch, GitHub, Gravatar, OpenAlex, Serper, Usernames, Wayback
from .trace.events import BudgetUpdate, PhaseTransition, Stop
from .trace.render import render_trace
from .trace.writer import TraceWriter
from .types import Casefile, Output, Resolution, RunMetadata
from .understand import understand
from .understand.parse import parse_input

# "do deep research on the CTO of Ariglad" → "the CTO of Ariglad"
_REQUEST_PREFIX = re.compile(
    r"^(?:please\s+)?(?:do|run|give|get|find|tell|look|show|search)\b[^,]*?\b(?:on|about|for|up)\s+", re.I)
_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.I)


def _slug(text: str, max_words: int = 4) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", unidecode(text).lower())[:max_words])[:48]


def run_label(text: str) -> str:
    """Directory-safe label for a target.

    ponytail: a heuristic on the raw input, not the real parsed name. The real
    name comes from understand(), which needs the trace dir to already exist, so
    naming cannot wait for it. Hard-ID inputs use the derived name; everything
    else uses the first comma segment with any request phrasing stripped. Upgrade
    path if the labels ever mislead: allocate a temp dir, rename after the gate.
    """
    seed = parse_input(text)
    if seed.regime.startswith("HARD_ID") and seed.names:
        return _slug(seed.names[0].form) or "target"
    head = _ARTICLE.sub("", _REQUEST_PREFIX.sub("", text.split(",")[0].strip()))
    return _slug(head) or "target"


def allocate_run_dir(text: str, run_root: str = "runs") -> Path:
    """Claim `runs/<label>-<n>`, n counting from 1 per label.

    mkdir is the atomic claim, so two concurrent runs of the same target never
    take the same number.
    """
    root, label = Path(run_root), run_label(text)
    n = 1
    for p in root.glob(f"{label}-*"):
        tail = p.name[len(label) + 1:]
        if tail.isdigit():
            n = max(n, int(tail) + 1)
    while True:
        run_dir = root / f"{label}-{n}"
        try:
            run_dir.mkdir(parents=True)
            return run_dir
        except FileExistsError:
            n += 1


def _phase(trace: TraceWriter, deps: Deps, t0: float, frm: str, to: str) -> None:
    trace.emit(BudgetUpdate(event_id=uuid.uuid4().hex[:16], phase=frm,
                            tool_calls=int(deps.counters.get("tool_calls", 0)),
                            llm_calls=int(deps.counters.get("llm_calls", 0)),
                            usd=float(deps.counters.get("usd", 0.0)), seconds=perf_counter() - t0))
    trace.emit(PhaseTransition(event_id=uuid.uuid4().hex[:16], from_phase=frm, to_phase=to))


async def investigate(text: str, run_root: str = "runs", job_id: str | None = None):
    load_dotenv()
    run_dir = Path(run_root) / job_id if job_id else allocate_run_dir(text, run_root)
    job_id = run_dir.name

    # Casefile defaults are status="failed", phase="understand" — write it now so
    # a concurrent GET sees "running" (via the API layer) instead of unknown_job.
    cf = Casefile(job_id=job_id, input=text)
    write_casefile(run_dir, cf)

    trace = TraceWriter(run_dir)
    cache = Cache()
    http = httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "people-research-agent/0.1"})
    deps = Deps.build(trace=trace, cache=cache, http=http)
    deps.tools = {
        "serper": Serper(deps), "fetch": Fetch(deps), "exa": Exa(deps), "company": Company(deps),
        "github": GitHub(deps), "gravatar": Gravatar(deps), "wayback": Wayback(deps),
        "usernames": Usernames(deps), "openalex": OpenAlex(deps),
    }
    t0 = perf_counter()

    try:
        # Inside the try: LLM() raises on a missing OPENROUTER_API_KEY, and that has to
        # come back as a typed `failed` envelope like any other error, not a raised crash.
        llm = LLM(cache=cache, trace=trace, counters=deps.counters)
        deps.llm = llm
        cf.seed = await understand(text, deps, llm)
        cf.phase = "resolve"
        write_casefile(run_dir, cf)
        _phase(trace, deps, t0, "understand", "resolve")

        try:
            cf.resolution = await resolve(cf.seed, deps, llm)
        except Exception as e:  # noqa: BLE001 — typed failure, never a crash
            cf.resolution = Resolution(status="failed", reason=f"resolve error: {type(e).__name__}: {str(e)[:200]}")
        cf.phase = "expand"
        write_casefile(run_dir, cf)
        _phase(trace, deps, t0, "resolve", "expand")

        if cf.resolution.status == "confirmed":
            cf.findings = await expand(cf.resolution, cf.seed, deps, llm,
                                       resolve_spent=int(cf.resolution.budget.get("tool_calls", 0)),
                                       on_batch=lambda f: (setattr(cf, "findings", f), write_casefile(run_dir, cf)))
        if not cf.findings:
            trace.emit(Stop(event_id=uuid.uuid4().hex[:16], stop_reason=f"S4:{cf.resolution.status}",
                            numbers={"claims": 0,
                                     "tool_calls": deps.counters.get("tool_calls", 0),
                                     "usd": round(deps.counters.get("usd", 0.0), 4)}))
        _phase(trace, deps, t0, "expand", "synthesize")

        cf.output = await synthesize(cf.seed, cf.resolution, cf.findings, job_id,
                                     counters=deps.counters, seconds=perf_counter() - t0, llm=llm)
        cf.status = cf.output.status
        cf.phase = "done"
        write_casefile(run_dir, cf)
    except Exception as e:  # noqa: BLE001 — API boundary: a typed failure, never a raised crash
        cf.status = "failed"
        cf.output = Output(status="failed", input=text,
                           run_metadata=RunMetadata(job_id=job_id,
                                                     stop_reason=f"error: {type(e).__name__}: {str(e)[:200]}"))
        write_casefile(run_dir, cf)
    finally:
        await http.aclose()
        render_trace(run_dir)

    if cf.output:
        (run_dir / "output.json").write_text(cf.output.model_dump_json(indent=2))
        # Every caller gets the dossier — CLI, API, eval. Report rendering must never
        # fail a run whose output.json is already on disk, so the error lands in the
        # report itself, where whoever opens it will see it.
        try:
            render_report(run_dir)
        except Exception as e:  # noqa: BLE001
            (run_dir / "report.md").write_text(
                f"# Report failed to render\n\n`{type(e).__name__}: {e}`\n\n"
                f"The findings are intact in `output.json`. "
                f"Re-render with `pi report {run_dir}` after fixing.\n")
    return run_dir, cf.output
