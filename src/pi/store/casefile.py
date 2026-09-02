"""Atomic casefile persistence.

Write temp + os.replace so a kill mid-write never corrupts the casefile (the
durability layer — reference-contracts §9, C9). Trace-as-source-of-truth is the
production answer; here the casefile is the served state.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from ..types import Casefile


def casefile_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "casefile.json"


def write_casefile(run_dir: str | Path, casefile: Casefile) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    casefile.updated_at = datetime.now(timezone.utc)
    path = casefile_path(run_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(casefile.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic on POSIX
    return path


def read_casefile(run_dir: str | Path) -> Casefile:
    return Casefile.model_validate_json(casefile_path(run_dir).read_text(encoding="utf-8"))
