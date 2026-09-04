"""HTTP surface: POST/GET /investigate, trace + SSE stream, /health.

Every failure is typed JSON — validation, capacity, auth, unknown job, and any
uncaught exception all come back as `{"error": ...}`, never a raw 500.
`create_app()` reads its env config fresh at call time so tests can build an
isolated app per case (see tests/test_api.py).
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .. import constants
from ..run import allocate_run_dir, investigate
from ..store.casefile import read_casefile, write_casefile
from ..types import Casefile

STREAM_POLL_S = 0.5
STREAM_IDLE_TIMEOUT_S = 60.0


def _mark_incomplete_failed(run_root: str) -> None:
    # ponytail: no resume; partial casefile served as-is (C9 failed_restart)
    root = Path(run_root)
    if not root.is_dir():
        return
    for path in root.glob("*/casefile.json"):
        try:
            cf = read_casefile(path.parent)
        except Exception:
            continue
        if cf.phase != "done":
            cf.status = "failed"
            write_casefile(path.parent, cf)


def _read_casefile_or_none(run_dir: Path) -> Optional[Casefile]:
    """Casefile.json missing, unreadable, or corrupt all mean "no such job" — never a 500."""
    try:
        return read_casefile(run_dir)
    except Exception:
        return None


def create_app() -> FastAPI:
    api_key = os.environ.get("PI_API_KEY")
    max_inflight = int(os.environ.get("MAX_INFLIGHT", constants.MAX_INFLIGHT_DEFAULT))
    daily_cap = int(os.environ.get("DAILY_JOB_CAP", 200))
    run_root = os.environ.get("PI_RUN_ROOT", "runs")

    jobs: dict[str, asyncio.Task] = {}
    queued: set[str] = set()
    running = asyncio.Semaphore(constants.MAX_RUNNING_JOBS)
    daily: dict[str, int] = {}

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        _mark_incomplete_failed(run_root)
        yield

    app = FastAPI(lifespan=_lifespan)

    @app.middleware("http")
    async def _auth(request: Request, call_next):
        if api_key and request.url.path != "/health":
            if request.headers.get("X-API-Key") != api_key:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    async def _run(job_id: str, target: str) -> None:
        try:
            async with running:
                queued.discard(job_id)
                await investigate(target, run_root, job_id=job_id)
        finally:
            jobs.pop(job_id, None)
            queued.discard(job_id)

    @app.post("/investigate")
    async def post_investigate(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid_json"}, status_code=422)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_json"}, status_code=422)
        target = str(body.get("target", "")).strip()
        if not target:
            return JSONResponse({"error": "empty_input"}, status_code=422)
        if len(target) > 500:
            return JSONResponse({"error": "input_too_long"}, status_code=422)

        today = datetime.now(timezone.utc).date().isoformat()
        if daily.get(today, 0) >= daily_cap:
            return JSONResponse({"error": "daily_cap"}, status_code=429)
        if len(jobs) >= max_inflight:
            return JSONResponse({"error": "capacity", "retry_after_s": 30}, status_code=429)

        daily[today] = daily.get(today, 0) + 1
        job_id = allocate_run_dir(target, run_root).name
        write_casefile(Path(run_root) / job_id, Casefile(job_id=job_id, input=target))
        queued.add(job_id)
        jobs[job_id] = asyncio.create_task(_run(job_id, target))
        return JSONResponse(
            {"job_id": job_id, "status": "queued", "poll": f"/investigate/{job_id}"}, status_code=202
        )

    @app.get("/investigate/{job_id}")
    async def get_investigate(job_id: str):
        run_dir = Path(run_root) / job_id
        cf = _read_casefile_or_none(run_dir)
        if cf is None:
            return JSONResponse({"error": "unknown_job"}, status_code=404)
        task = jobs.get(job_id)
        if job_id in queued:
            status = "queued"
        elif task is not None and not task.done() and cf.phase != "done":
            status = "running"
        else:
            status = cf.status
        output_path = run_dir / "output.json"
        output = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else None
        return {
            "job_id": job_id, "status": status, "phase": cf.phase, "output": output,
            "trace": f"/investigate/{job_id}/trace",
        }

    @app.get("/investigate/{job_id}/trace")
    async def get_trace(job_id: str, format: Optional[str] = None):
        run_dir = Path(run_root) / job_id
        if _read_casefile_or_none(run_dir) is None:
            return JSONResponse({"error": "unknown_job"}, status_code=404)
        if format == "jsonl":
            path = run_dir / "trace.jsonl"
            return Response(path.read_text(encoding="utf-8") if path.exists() else "",
                             media_type="application/x-ndjson")
        path = run_dir / "trace.md"
        return Response(path.read_text(encoding="utf-8") if path.exists() else "", media_type="text/markdown")

    @app.get("/investigate/{job_id}/stream")
    async def stream(job_id: str):
        run_dir = Path(run_root) / job_id
        if _read_casefile_or_none(run_dir) is None:
            return JSONResponse({"error": "unknown_job"}, status_code=404)
        trace_path = run_dir / "trace.jsonl"

        async def gen():
            pos = 0
            idle = 0.0
            while True:
                if trace_path.exists():
                    text = trace_path.read_text(encoding="utf-8")
                    if len(text) > pos:
                        chunk, pos = text[pos:], len(text)
                        idle = 0.0
                        for line in chunk.splitlines():
                            if line.strip():
                                yield f"data: {line}\n\n"
                task = jobs.get(job_id)
                cf = _read_casefile_or_none(run_dir)
                phase_done = cf is not None and cf.phase == "done"
                if phase_done or task is None or task.done():
                    yield "event: done\ndata: {}\n\n"
                    return
                await asyncio.sleep(STREAM_POLL_S)
                idle += STREAM_POLL_S
                if idle >= STREAM_IDLE_TIMEOUT_S:
                    return

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/health")
    async def health():
        today = datetime.now(timezone.utc).date().isoformat()
        return {"ok": True, "running": len(jobs) - len(queued), "queued": len(queued),
                "jobs_today": daily.get(today, 0)}

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        return JSONResponse({"error": "internal", "detail": str(exc)[:200]}, status_code=500)

    return app


app = create_app()
