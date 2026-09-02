"""Orchestrator: understand → resolve → gate → expand → synthesize.

Casefile written atomically at every phase boundary; trace rendered on exit even
on failure. Budget counters live on Deps and are reported in run_metadata."""
from __future__ import annotations

import uuid
from pathlib import Path
from time import perf_counter

import httpx
from dotenv import load_dotenv

from .deps import Deps
from .expand import expand
from .llm.client import LLM
from .resolve import resolve
from .store.cache import Cache
from .store.casefile import write_casefile
from .synth import synthesize
from .tools import Company, Exa, Fetch, Serper
from .trace.events import BudgetUpdate, PhaseTransition, Stop
from .trace.render import render_trace
from .trace.writer import TraceWriter
from .types import Casefile, Resolution
from .understand import understand


def _phase(trace: TraceWriter, deps: Deps, t0: float, frm: str, to: str) -> None:
    trace.emit(BudgetUpdate(event_id=uuid.uuid4().hex[:16], phase=frm,
                            tool_calls=int(deps.counters.get("tool_calls", 0)),
                            llm_calls=int(deps.counters.get("llm_calls", 0)),
                            usd=float(deps.counters.get("usd", 0.0)), seconds=perf_counter() - t0))
    trace.emit(PhaseTransition(event_id=uuid.uuid4().hex[:16], from_phase=frm, to_phase=to))


async def investigate(text: str, run_root: str = "runs"):
    load_dotenv()
    job_id = uuid.uuid4().hex[:12]
    run_dir = Path(run_root) / job_id
    trace = TraceWriter(run_dir)
    cache = Cache()
    http = httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "people-research-agent/0.1"})
    deps = Deps.build(trace=trace, cache=cache, http=http)
    deps.tools = {"serper": Serper(deps), "fetch": Fetch(deps), "exa": Exa(deps), "company": Company(deps)}
    llm = LLM(cache=cache, trace=trace, counters=deps.counters)
    deps.llm = llm
    t0 = perf_counter()

    cf = Casefile(job_id=job_id, input=text)
    try:
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
            cf.findings = await expand(cf.resolution, cf.seed, deps, llm)
        stop = cf.findings.stop_reason if cf.findings else f"S4:{cf.resolution.status}"
        trace.emit(Stop(event_id=uuid.uuid4().hex[:16], stop_reason=stop,
                        numbers={"claims": len(cf.findings.claims) if cf.findings else 0,
                                 "tool_calls": deps.counters.get("tool_calls", 0),
                                 "usd": round(deps.counters.get("usd", 0.0), 4)}))
        _phase(trace, deps, t0, "expand", "synthesize")

        cf.output = synthesize(cf.seed, cf.resolution, cf.findings, job_id,
                               counters=deps.counters, seconds=perf_counter() - t0)
        cf.status = cf.output.status
        cf.phase = "done"
        write_casefile(run_dir, cf)
    finally:
        await http.aclose()
        render_trace(run_dir)

    if cf.output:
        (run_dir / "output.json").write_text(cf.output.model_dump_json(indent=2))
    return run_dir, cf.output
