#!/usr/bin/env python
"""Check one run's output against the invariants that must always hold.

    python check_run.py runs/<job_id>

ponytail: a script, not a test suite — it takes a run dir, which pytest cannot.
Add cases here when a new invariant becomes never-cut.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pi import constants
from pi.types import Output


def check(run_dir: str) -> int:
    d = Path(run_dir)
    if not (d / "output.json").exists():          # crashed or killed mid-run
        print(f"SKIP {d.name}: no output.json")
        return 0
    out = json.loads((d / "output.json").read_text())
    Output.model_validate(out)                      # envelope schema
    cid, bad = out["identity"]["cid"], []

    for section, value in out["profile"].items():
        for c in value if isinstance(value, list) else ([value] if value else []):
            where = f"{section}/{c['predicate']}"
            if not c["identity_link"]:
                bad.append(f"{where}: no identity_link")
            if not c["evidence"]:
                bad.append(f"{where}: no evidence")
            for e in c["evidence"]:
                if cid and e["candidate_id"] != cid:
                    bad.append(f"{where}: evidence from {e['candidate_id']}, not {cid}")
                if not e["url"] or not e["snippet"]:
                    bad.append(f"{where}: evidence with no url or span")

    b = out["run_metadata"]["budget"]
    if b.get("tool_calls", 0) > constants.S3_TOTAL_TOOL_CALLS:
        bad.append(f"budget: {b['tool_calls']} tool calls over cap {constants.S3_TOTAL_TOOL_CALLS}")
    resolve = b.get("resolve") or {}
    if "cap" in resolve and resolve.get("tool_calls", 0) > resolve["cap"]:
        bad.append(f"budget.resolve: {resolve['tool_calls']} tool calls over cap {resolve['cap']}")

    for line in bad:
        print("FAIL", line)
    if not bad:
        print(f"ok  {d.name}  status={out['status']}  cid={cid}  "
              f"claims={sum(len(v) if isinstance(v, list) else bool(v) for v in out['profile'].values())}  "
              f"tool_calls={b.get('tool_calls')}/{constants.S3_TOTAL_TOOL_CALLS}  ${b.get('usd', 0):.4f}")
    return 1 if bad else 0


if __name__ == "__main__":
    paths = sys.argv[1:] or sorted(p.parent for p in Path("runs").glob("*/output.json"))
    raise SystemExit(max(check(str(p)) for p in paths))
