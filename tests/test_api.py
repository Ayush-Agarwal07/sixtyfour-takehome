"""HTTP surface tests: httpx ASGITransport against a fresh create_app() per case.

The real `investigate` is monkeypatched out — these tests exercise routing,
validation, capacity, auth and streaming, not the pipeline itself.
"""
from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest

from pi.store.casefile import write_casefile
from pi.trace.events import Stop
from pi.trace.render import render_trace
from pi.types import Casefile, Output, RunMetadata


def _build_app(monkeypatch, tmp_path, sleep_s: float = 0.05, **env):
    monkeypatch.delenv("PI_API_KEY", raising=False)
    monkeypatch.setenv("PI_RUN_ROOT", str(tmp_path))
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))

    from pi.api import app as app_module

    app = app_module.create_app()

    async def fake_investigate(target: str, run_root: str, job_id: str | None = None):
        from pathlib import Path

        run_dir = Path(run_root) / job_id
        run_dir.mkdir(parents=True, exist_ok=True)
        stop = Stop(event_id=uuid.uuid4().hex[:16], stop_reason="S4:test", numbers={})
        with (run_dir / "trace.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(stop.model_dump_json() + "\n")
        await asyncio.sleep(sleep_s)
        output = Output(status="confirmed", input=target, run_metadata=RunMetadata(job_id=job_id))
        cf = Casefile(job_id=job_id, input=target, status="confirmed", phase="done", output=output)
        write_casefile(run_dir, cf)
        (run_dir / "output.json").write_text(output.model_dump_json(indent=2))
        render_trace(run_dir)
        return run_dir, output

    monkeypatch.setattr(app_module, "investigate", fake_investigate)
    return app


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_post_and_poll_until_confirmed(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    async with _client(app) as client:
        resp = await client.post("/investigate", json={"target": "andrew.goering@ramp.com"})
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued" and "job_id" in body
        job_id = body["job_id"]

        for _ in range(50):
            poll = await client.get(f"/investigate/{job_id}")
            if poll.json()["status"] == "confirmed":
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("job never reached confirmed")

        assert poll.json()["phase"] == "done"
        assert poll.json()["output"] is not None


async def test_validation_errors(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    async with _client(app) as client:
        r1 = await client.post("/investigate", json={"target": "   "})
        assert r1.status_code == 422 and r1.json() == {"error": "empty_input"}

        r2 = await client.post("/investigate", json={"target": "x" * 600})
        assert r2.status_code == 422 and r2.json() == {"error": "input_too_long"}


async def test_unknown_job_404(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    async with _client(app) as client:
        r = await client.get("/investigate/doesnotexist")
        assert r.status_code == 404 and r.json() == {"error": "unknown_job"}


async def test_invalid_json_body_returns_422(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    async with _client(app) as client:
        r1 = await client.post(
            "/investigate", content=b"{not valid json", headers={"content-type": "application/json"}
        )
        assert r1.status_code == 422 and r1.json() == {"error": "invalid_json"}

        r2 = await client.post("/investigate", json=["not", "an", "object"])
        assert r2.status_code == 422 and r2.json() == {"error": "invalid_json"}


async def test_missing_casefile_is_unknown_job_not_500(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    # a run dir that exists but has no casefile.json — e.g. a partially written run
    (tmp_path / "half-written").mkdir()
    async with _client(app) as client:
        r1 = await client.get("/investigate/half-written")
        assert r1.status_code == 404 and r1.json() == {"error": "unknown_job"}

        r2 = await client.get("/investigate/half-written/trace")
        assert r2.status_code == 404 and r2.json() == {"error": "unknown_job"}

        r3 = await client.get("/investigate/half-written/stream")
        assert r3.status_code == 404 and r3.json() == {"error": "unknown_job"}


async def test_api_key_required_except_health(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path, PI_API_KEY="secret")
    async with _client(app) as client:
        r1 = await client.post("/investigate", json={"target": "a"})
        assert r1.status_code == 401 and r1.json() == {"error": "unauthorized"}

        r2 = await client.post("/investigate", json={"target": "a"}, headers={"X-API-Key": "secret"})
        assert r2.status_code == 202

        r3 = await client.get("/health")
        assert r3.status_code == 200


async def test_max_inflight_returns_429(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path, sleep_s=0.5, MAX_INFLIGHT=2)
    async with _client(app) as client:
        r1 = await client.post("/investigate", json={"target": "a"})
        r2 = await client.post("/investigate", json={"target": "b"})
        r3 = await client.post("/investigate", json={"target": "c"})
        assert r1.status_code == 202 and r2.status_code == 202
        assert r3.status_code == 429
        assert r3.json() == {"error": "capacity", "retry_after_s": 30}


async def test_trace_and_stream(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    async with _client(app) as client:
        resp = await client.post("/investigate", json={"target": "a"})
        job_id = resp.json()["job_id"]

        lines: list[str] = []
        async with client.stream("GET", f"/investigate/{job_id}/stream", timeout=10.0) as stream_resp:
            assert stream_resp.status_code == 200
            async for line in stream_resp.aiter_lines():
                if line:
                    lines.append(line)
                if line.startswith("event: done"):
                    break

        assert any(l.startswith("data:") for l in lines)
        assert any(l.startswith("event: done") for l in lines)

        r_md = await client.get(f"/investigate/{job_id}/trace")
        assert r_md.status_code == 200
        assert "text/markdown" in r_md.headers["content-type"]

        r_jsonl = await client.get(f"/investigate/{job_id}/trace", params={"format": "jsonl"})
        assert r_jsonl.status_code == 200
        assert "application/x-ndjson" in r_jsonl.headers["content-type"]
        assert json.loads(r_jsonl.text.strip().splitlines()[0])["event_type"] == "stop"
