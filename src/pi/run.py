"""Orchestrator: understand → resolve → gate → expand → synthesize.

Casefile written atomically at every phase boundary; trace rendered on exit even
on failure. ponytail: no budget/stop machinery in the slice (one batch) — S1–S4
land in Stage 3.
"""
from __future__ import annotations

import uuid
from pathlib import Path

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
from .trace.events import PhaseTransition, Stop
from .trace.render import render_trace
from .trace.writer import TraceWriter
from .types import Casefile
from .understand import understand


def _phase(trace: TraceWriter, frm: str, to: str) -> None:
    trace.emit(PhaseTransition(event_id=uuid.uuid4().hex[:16], from_phase=frm, to_phase=to))


async def investigate(text: str, run_root: str = "runs"):
    load_dotenv()
    job_id = uuid.uuid4().hex[:12]
    run_dir = Path(run_root) / job_id
    trace = TraceWriter(run_dir)
    cache = Cache()
    http = httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "people-research-agent/0.1"})
    deps = Deps.build(trace=trace, cache=cache, http=http)
    deps.serper, deps.fetch, deps.exa = Serper(deps), Fetch(deps), Exa(deps)
    deps.company = Company(deps)
    llm = LLM(cache=cache, trace=trace)

    cf = Casefile(job_id=job_id, input=text)
    try:
        cf.seed = await understand(text, deps, llm)
        cf.phase = "resolve"
        write_casefile(run_dir, cf)
        _phase(trace, "understand", "resolve")

        cf.resolution = await resolve(cf.seed, deps, llm)
        cf.phase = "expand"
        write_casefile(run_dir, cf)
        _phase(trace, "resolve", "expand")

        if cf.resolution.status == "confirmed":
            cf.findings = await expand(cf.resolution, cf.seed, deps, llm)
        stop = cf.findings.stop_reason if cf.findings else "no_expand"
        trace.emit(Stop(event_id=uuid.uuid4().hex[:16], stop_reason=stop,
                        numbers={"claims": len(cf.findings.claims) if cf.findings else 0}))
        _phase(trace, "expand", "synthesize")

        cf.output = synthesize(cf.seed, cf.resolution, cf.findings, job_id)
        cf.status = cf.output.status
        cf.phase = "done"
        write_casefile(run_dir, cf)
    finally:
        await http.aclose()
        render_trace(run_dir)

    (run_dir / "output.json").write_text(cf.output.model_dump_json(indent=2)) if cf.output else None
    return run_dir, cf.output
