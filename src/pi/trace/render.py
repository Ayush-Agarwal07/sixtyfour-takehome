"""Render trace.jsonl → trace.md.

Trace Quality is graded on whether a reader can follow the agent's decisions from
the log alone. So this is not a dump: phase transitions are headings, the
consequential decisions (gate / planner / disconfirmation) get their own blocks
showing chosen-vs-not, and the mechanical calls collapse into one table.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_events(trace_path: Path) -> list[dict[str, Any]]:
    if not trace_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def _reasoning(run_dir: Path, ref: str | None) -> str:
    if not ref:
        return ""
    p = run_dir / ref
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def render_trace(run_dir: str | Path) -> str:
    run_dir = Path(run_dir)
    events = _read_events(run_dir / "trace.jsonl")
    lines: list[str] = ["# Trace", ""]
    tool_rows: list[dict[str, Any]] = []

    for e in events:
        et = e.get("event_type")

        if et == "phase_transition":
            lines.append(f"## Phase: {e['from_phase']} → {e['to_phase']}")
            lines.append("")

        elif et == "candidate_score":
            terms = ", ".join(f"{t['factor']}={t['weight']:+.2f}" for t in e.get("terms", []))
            lines.append(f"- candidate `{e['cid']}`: P={e['score']:.3f} (LO {e['logodds']:+.2f}) — {terms}")

        elif et == "merge":
            lines.append(f"- **merge** `{e['from_cid']}` → `{e['to_cid']}`: {e.get('reason','')}")

        elif et == "rejection":
            lines.append(f"- **rejected** `{e['cid']}`: {e.get('reason','')}")

        elif et == "budget_update":
            lines.append(f"- budget: tool_calls={e.get('tool_calls')} llm_calls={e.get('llm_calls')} "
                         f"usd={e.get('usd', 0):.4f} seconds={e.get('seconds', 0):.0f}")

        elif et == "gate_test":
            verdict = "PASS" if e["math_pass"] else "FAIL"
            lines.append(
                f"- **gate math**: {verdict} — P(top)={e['p_top']:.3f}, "
                f"P(runner)={e['p_runner_up']:.3f}, margin={e['margin']:.3f}"
            )

        elif et == "gate_decision":
            lines.append(f"### Gate decision → **{e['decision']}**"
                         + (f" (cid `{e['cid']}`)" if e.get("cid") else ""))
            for r in e.get("rejected", []):
                lines.append(f"  - rejected `{r.get('cid')}`: {r.get('reason')}")
            if e.get("next_evidence"):
                lines.append(f"  - next evidence: {e['next_evidence']}")
            reason = _reasoning(run_dir, e.get("reasoning_ref"))
            if reason:
                lines.append(f"  - reasoning: {reason[:600]}")
            lines.append("")

        elif et == "planner_decision":
            lines.append("### Planner decision")
            def _label(x: dict) -> str:   # "fetch https://henrywa.ng/", not a frontier-item hash
                arg = next(iter((x.get("args") or {}).values()), None)
                return f"{x.get('action') or x.get('id')} {arg}".strip() if arg is not None else str(x.get("action") or x.get("id"))
            ftop = "; ".join(_label(x) for x in e.get("formula_top", [])[:4])
            chosen = "; ".join(_label(x) + (" (pivot)" if x.get("origin") == "pivot" else "") for x in e.get("chosen", []))
            lines.append(f"  - formula top: {ftop or '—'}")
            lines.append(f"  - **chosen**: {chosen or '—'}")
            for na in e.get("new_actions", []):
                lines.append(f"  - + injected: {na.get('tool')} {na.get('args')} — {na.get('hypothesis','')}")
            reason = _reasoning(run_dir, e.get("reasoning_ref"))
            if reason:
                lines.append(f"  - reasoning: {reason[:600]}")
            lines.append("")

        elif et == "disconfirmation":
            lines.append("### Disconfirmation")
            lines.append(f"  - hypothesis: {e['hypothesis']}")
            for a in e.get("actions", []):
                lines.append(f"  - action: {a}")
            lines.append(f"  - result: {e.get('result','')}")
            lines.append("")

        elif et == "role_resolution":
            lines.append(f"### Role resolution @ {e['company']} → "
                         f"{e.get('resolved_holder') or '(unresolved)'}")
            if e.get("note"):
                lines.append(f"  - {e['note']}")
            lines.append("")

        elif et == "reinforce":
            lines.append(f"- **reinforce** node `{e['node_id']}` "
                         f"(descendants={e['descendants']}, attachment={e['attachment']:.2f})")

        elif et == "conflict_detected":
            lines.append(f"- **conflict** ({e['kind']}) on {e['predicate']}: "
                         f"{e.get('values')} severity={e.get('severity')}")

        elif et == "attachment_test":
            anchors_s = ", ".join(e.get("matched") or []) or "-"
            t4_s = f" t4={e['t4']}" if e.get("t4") else ""
            rescore_s = " (re-score)" if e.get("note") else ""
            lines.append(f"- **same-person test** {e['url']} → {e['score']:.2f} [{e.get('band', '')}] "
                         f"name={'yes' if e.get('name_present') else 'no'} anchors={anchors_s}{t4_s}{rescore_s}")

        elif et == "slot_update":
            state = "closed" if e["closed"] else "open"
            lines.append(f"- slot `{e['slot']}` {e['current']}/{e['target']} ({state})")

        elif et == "stop":
            lines.append(f"## Stop — {e['stop_reason']}")
            lines.append(f"  - {e.get('numbers')}")
            lines.append("")

        elif et in ("tool_call", "llm_call"):
            tool_rows.append(e)

    # mechanical calls collapse into a table
    if tool_rows:
        lines.append("## Calls")
        lines.append("")
        lines.append("| # | kind | name | args | latency_ms | cost_usd | cache | ok |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for i, e in enumerate(tool_rows, 1):
            if e["event_type"] == "tool_call":
                name, cost = e.get("tool", ""), ""
                args = ", ".join(f"{k}={str(v)[:70]}" for k, v in (e.get("args") or {}).items())
                ok = "ok" if e.get("ok", True) else f"ERR:{e.get('error','')[:40]}"
            else:
                name = f"{e.get('tier','')}/{e.get('model','')}"
                u = e.get("usage") or {}
                args = f"in={u.get('in', 0)} out={u.get('out', 0)}" + (f" — {e['note'][:60]}" if e.get("note") else "")
                cost = f"{e.get('cost_usd', 0):.4f}"
                ok = "ok"
            args = args.replace("|", "\\|")
            lines.append(
                f"| {i} | {e['event_type']} | {name} | {args} | "
                f"{e.get('latency_ms', 0):.0f} | {cost} | "
                f"{'hit' if e.get('cache_hit') else '—'} | {ok} |"
            )
        lines.append("")

    md = "\n".join(lines)
    (run_dir / "trace.md").write_text(md, encoding="utf-8")
    return md
