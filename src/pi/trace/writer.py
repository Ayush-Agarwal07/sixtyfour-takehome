"""Append-only JSONL trace writer + reasoning sidecars.

One event per line. Synchronous append + flush is enough for the trace (durability
of *state* is the casefile's job, via atomic replace). Reasoning tokens go to
reasoning/{event_id}.txt and are referenced from the event.
"""
from __future__ import annotations

from pathlib import Path

from .events import BaseEvent


class TraceWriter:
    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self.trace_path = self.run_dir / "trace.jsonl"
        self.reasoning_dir = self.run_dir / "reasoning"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.reasoning_dir.mkdir(parents=True, exist_ok=True)

    def emit(self, event: BaseEvent) -> None:
        line = event.model_dump_json()
        with self.trace_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()

    def write_reasoning(self, event_id: str, text: str) -> str:
        """Store reasoning text in a sidecar; return the ref to store on the event."""
        path = self.reasoning_dir / f"{event_id}.txt"
        path.write_text(text or "", encoding="utf-8")
        return f"reasoning/{event_id}.txt"
