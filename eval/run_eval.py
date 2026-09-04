#!/usr/bin/env python
"""Live eval harness — run each target N times through the real pipeline.

Usage: python eval/run_eval.py [--runs N] [--targets eval/targets.json] [--no-cache]

Runs are sequential (free-tier keys, no fan-out). Each target is a dict
{"input": str, "expect": "confirmed|ambiguous|abstained" or a list of acceptable statuses, "must_contain": str|null}.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _profile_claim_count(profile) -> int:
    return ((1 if profile.current_role else 0) + len(profile.employment) + len(profile.education)
            + (1 if profile.location else 0) + len(profile.contact) + len(profile.accounts)
            + len(profile.public_output) + len(profile.relationships) + len(profile.notable))


async def _run_one(investigate, target: dict, run_idx: int) -> dict:
    _, output = await investigate(target["input"])
    status = output.status if output else "failed"
    top_p = output.identity.confidence.score if output and output.identity else 0.0
    claims = _profile_claim_count(output.profile) if output else 0
    budget = (output.run_metadata.budget if output and output.run_metadata else {}) or {}
    tool_calls = budget.get("tool_calls", 0)
    usd = float(budget.get("usd", 0.0))
    seconds = float(budget.get("seconds", 0.0))

    expect = target["expect"]
    identity_correct = status in (expect if isinstance(expect, list) else [expect])
    must_contain = target.get("must_contain")
    contains_ok = must_contain is None or must_contain.lower() in (output.model_dump_json().lower() if output else "")
    ok = identity_correct and contains_ok

    print(f"{target['input']} | {run_idx} | {status} | {top_p:.3f} | {claims} | {tool_calls} | "
          f"{usd:.3f} | {seconds:.0f} | {ok}")
    return {"identity_correct": identity_correct, "usd": usd, "seconds": seconds}


async def _run_all(investigate, targets: list[dict], runs: int) -> None:
    n_correct = n_runs = 0
    total_usd = total_seconds = 0.0
    for target in targets:
        for i in range(1, runs + 1):
            row = await _run_one(investigate, target, i)
            n_runs += 1
            n_correct += int(row["identity_correct"])
            total_usd += row["usd"]
            total_seconds += row["seconds"]

    mean_cost = total_usd / n_runs if n_runs else 0.0
    mean_seconds = total_seconds / n_runs if n_runs else 0.0
    print(f"{len(targets)} targets, {runs} runs each, identity correct {n_correct}/{n_runs}, "
          f"mean cost ${mean_cost:.3f}, mean {mean_seconds:.0f}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--targets", default="eval/targets.json")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    if args.no_cache:
        os.environ["PI_NO_CACHE"] = "1"

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from pi.run import investigate  # noqa: E402 — import after PI_NO_CACHE is set

    targets = json.loads(Path(args.targets).read_text())
    asyncio.run(_run_all(investigate, targets, args.runs))


if __name__ == "__main__":
    main()
