"""Stage 0 gate: a run emitting every event type renders a readable trace.md,
and the casefile writes atomically.
"""
from __future__ import annotations

from pi.store.casefile import read_casefile, write_casefile
from pi.trace.render import render_trace
from pi.trace.writer import TraceWriter
from pi.types import Casefile
from _samples import (
    GATE_REASONING_EVENT_ID, PLANNER_REASONING_EVENT_ID, all_sample_events,
)


def test_render_produces_readable_markdown(tmp_path):
    writer = TraceWriter(tmp_path)
    # a couple of reasoning sidecars referenced by decision events
    writer.write_reasoning(GATE_REASONING_EVENT_ID,
                           "Top candidate dominates on employer + reciprocal link; runner-up wrong employer.")
    writer.write_reasoning(PLANNER_REASONING_EVENT_ID,
                           "employment_history slot still open; the personal site fetch is highest-yield.")
    for e in all_sample_events():
        writer.emit(e)

    md = render_trace(tmp_path)

    assert (tmp_path / "trace.jsonl").exists()
    assert (tmp_path / "trace.md").exists()
    # phase heading, each decision block, and the calls table are all present
    assert "## Phase: understand → resolve" in md
    assert "### Gate decision → **CONFIRM**" in md
    assert "### Planner decision" in md
    assert "### Disconfirmation" in md
    assert "## Calls" in md
    # reasoning made it into the rendered decision
    assert "reciprocal link" in md
    # the trace jsonl has one line per event
    assert len((tmp_path / "trace.jsonl").read_text().strip().splitlines()) == len(all_sample_events())


def test_casefile_atomic_round_trip(tmp_path):
    cf = Casefile(job_id="jobX", input="test target", status="confirmed", phase="done")
    write_casefile(tmp_path, cf)
    # no leftover temp file; real file present
    assert (tmp_path / "casefile.json").exists()
    assert not (tmp_path / "casefile.json.tmp").exists()
    back = read_casefile(tmp_path)
    assert back.job_id == "jobX" and back.status == "confirmed" and back.phase == "done"


def test_casefile_overwrite_keeps_valid_file(tmp_path):
    write_casefile(tmp_path, Casefile(job_id="j", input="a", phase="understand"))
    write_casefile(tmp_path, Casefile(job_id="j", input="a", phase="resolve"))
    assert read_casefile(tmp_path).phase == "resolve"
