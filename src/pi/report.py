"""output.json → report.md: the dossier a human reads.

`trace.md` answers "what did the agent do"; this answers "what did it find".
Everything here comes from output.json, so a report can be re-rendered for any
past run without touching the network.

ponytail: string building, no template engine. Mermaid for the graph because
GitHub renders it natively — no image pipeline, no dependency.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

MAX_GRAPH_NODES = 40                  # beyond this a mermaid diagram stops being readable

_SECTION_TITLES = {
    "employment": "Employment",
    "education": "Education",
    "contact": "Contact",
    "accounts": "Accounts",
    "public_output": "Public output",
    "relationships": "Relationships",
    "notable": "Notable",
}


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.") or "—"


def _bar(score: float) -> str:
    """Five blocks, so a column of confidences is scannable without reading digits."""
    filled = round(max(0.0, min(1.0, score)) * 5)
    return "█" * filled + "░" * (5 - filled)


def _conf(claim: dict) -> str:
    score = (claim.get("confidence") or {}).get("score", 0.0)
    return f"{_bar(score)} {score:.2f}"

def _cell(text: str) -> str:
    """Table cells: no pipes, no newlines."""
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def _dates(claim: dict) -> str:
    t = claim.get("temporal") or {}
    start, end, state = t.get("start"), t.get("end"), t.get("end_state")
    if not start and not end:
        return "—"
    if state == "ongoing":
        return f"{start or '?'} → now"
    return f"{start or '?'} → {end or '?'}"


def _sources(claim: dict) -> str:
    seen, out = set(), []
    for e in claim.get("evidence") or []:
        url = e.get("url") or ""
        h = _host(url)
        if h not in seen:
            seen.add(h)
            out.append(f"[{h}]({url})")
    return ", ".join(out) or "—"


def _claim_rows(claims: list[dict]) -> list[str]:
    rows = ["| Value | Dates | Confidence | Source |", "|---|---|---|---|"]
    for c in claims:
        rows.append(f"| {_cell(c.get('value_raw') or c.get('value'))} | {_dates(c)} "
                    f"| {_conf(c)} | {_cell(_sources(c))} |")
    return rows


def _mermaid_id(node_id: str) -> str:
    """Readable prefix + digest. The digest is load-bearing: two node ids that
    differ only past the prefix would otherwise collide into one diagram node."""
    stem = re.sub(r"[^A-Za-z0-9]", "_", node_id)[:24]
    return f"n{stem}_{hashlib.sha256(node_id.encode()).hexdigest()[:8]}"


def _graph(graph: dict) -> list[str]:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not nodes:
        return ["_No graph nodes._"]

    kept = sorted(nodes, key=lambda n: (n.get("depth", 0), -n.get("attachment_confidence", 0)))
    kept = kept[:MAX_GRAPH_NODES]
    ids = {n["id"] for n in kept}
    shape = {"person": ("([", "])"), "company": ("[", "]"), "account": ("(", ")")}

    out = ["```mermaid", "graph LR"]
    for n in kept:
        open_b, close_b = shape.get(n.get("type", ""), ("[", "]"))
        label = str(n.get("label", ""))
        label = _host(label) if label.startswith("http") else label
        label = label[:40].replace('"', "'")          # a quote would end the mermaid label
        out.append(f'  {_mermaid_id(n["id"])}{open_b}"{label}"{close_b}')
    for e in edges:
        if e.get("src") in ids and e.get("dst") in ids:
            out.append(f'  {_mermaid_id(e["src"])} -->|{str(e.get("type", ""))[:24]}| {_mermaid_id(e["dst"])}')
    out.append("```")
    if len(nodes) > len(kept):
        out.append(f"\n_Showing {len(kept)} of {len(nodes)} nodes, shallowest and best-attached first._")
    return out


def render_report(run_dir: str | Path) -> Path:
    d = Path(run_dir)
    out = json.loads((d / "output.json").read_text(encoding="utf-8"))
    profile = out.get("profile") or {}
    identity = out.get("identity") or {}
    by_id = {}
    for value in profile.values():
        for c in value if isinstance(value, list) else ([value] if value else []):
            by_id[c.get("id")] = c

    role = profile.get("current_role")
    name = ((out.get("seed") or {}).get("names") or [{}])[0].get("form") or out.get("input", "")
    L: list[str] = [f"# {name}", ""]

    status = out.get("status", "?")
    score = (identity.get("confidence") or {}).get("score", 0)
    head = [f"**{status.upper()}**"]
    if out.get("regime"):
        head.append(out["regime"])
    head.append(f"identity {score:.3f} {_bar(score)}")
    L += [" · ".join(head), "", f"> Input: `{out.get('input', '')}`", ""]

    stop = (out.get("run_metadata") or {}).get("stop_reason") or ""
    if status == "failed":
        L += [f"The run did not finish: `{stop}`. Nothing below is a finding.", ""]
    elif status != "confirmed":
        L += ["The agent did not confirm an identity. "
              "See **Identity resolution** below for the candidates and what would settle it.", ""]

    if role:
        L += [f"**{role.get('value_raw') or role.get('value')}**"
              + (f" · {(profile.get('location') or {}).get('value_raw')}" if profile.get("location") else ""), ""]

    if out.get("summary"):
        L += ["## Summary", ""]
        for s in out["summary"]:
            L.append(f"- {s.get('text', '')}")
        L.append("")

    for key, title in _SECTION_TITLES.items():
        claims = profile.get(key) or []
        if claims:
            L += [f"## {title}", ""] + _claim_rows(claims) + [""]

    if out.get("timeline"):
        L += ["## Timeline", "", "| Date | Event | Source |", "|---|---|---|"]
        for t in out["timeline"]:
            L.append(f"| {t.get('date', '')} | {_cell(t.get('text'))} | [{_host(t.get('url', ''))}]({t.get('url', '')}) |")
        L.append("")

    L += ["## How it connects", ""] + _graph(out.get("graph") or {}) + [""]

    payoff = [by_id[cid] for cid in out.get("specialization_payoff") or [] if cid in by_id]
    if payoff:
        L += ["## Non-obvious findings", "",
              "Claims whose only source was a specialized pivot — commit email, Wayback, "
              "Gravatar, username probe, or a verified reciprocal link.", ""]
        L += _claim_rows(payoff) + [""]

    if out.get("conflicts"):
        L += ["## Conflicts", "", "| Predicate | Kind | Values |", "|---|---|---|"]
        for c in out["conflicts"]:
            L.append(f"| {c.get('predicate', '')} | {c.get('kind', '')} | {_cell(', '.join(map(str, c.get('values', []))))} |")
        L.append("")

    negatives = [n for n in out.get("negative_findings") or [] if n.get("predicate") != "coverage"]
    coverage = [n for n in out.get("negative_findings") or [] if n.get("predicate") == "coverage"]
    if negatives:
        L += ["## Asserted in the input, not confirmed", ""]
        for n in negatives:
            L.append(f"- **{n.get('sought', '')}** ({n.get('predicate', '')}) — {n.get('note') or n.get('status', '')}")
        L.append("")
    if coverage:
        L += ["## Coverage gaps at stop", "", "| Looked for | Found / target |", "|---|---|"]
        for n in coverage:
            L.append(f"| {n.get('sought', '')} | {n.get('found', 0)} / {n.get('target', '?')} |")
        L.append("")

    ir = out.get("identity_resolution") or {}
    L += ["## Identity resolution", ""]
    L += [f"- {identity.get('how_confirmed', '—')}", ""]
    if ir.get("candidates"):
        L += ["| Candidate | Score | Terms |", "|---|---|---|"]
        for c in ir["candidates"]:
            terms = "; ".join(f"{t['factor']} {t['weight']:+.1f}" for t in c.get("terms", []))
            marker = " ← confirmed" if c.get("cid") == identity.get("cid") else ""
            L.append(f"| `{c.get('cid')}`{marker} | {c.get('score', 0):.3f} | {_cell(terms)} |")
        L.append("")
    rejected = ir.get("rejected") or []
    # One line per reasoned rejection; the boilerplate "below gate margin" ones collapse,
    # otherwise a common-name run buries its real reasons under a dozen identical lines.
    boilerplate = [r for r in rejected if r.get("reason", "").strip().lower() == "below gate margin"]
    for r in rejected:
        if r not in boilerplate:
            L.append(f"- **rejected `{r.get('cid')}`** — {r.get('reason', '')}")
    if boilerplate:
        cids = ", ".join(f"`{r.get('cid')}`" for r in boilerplate)
        L.append(f"- **rejected below the gate margin** — {cids}")
    if rejected:
        L.append("")
    if ir.get("what_would_disambiguate"):
        L += ["**What would settle it:**", ""]
        for w in ir["what_would_disambiguate"]:
            L.append(f"- {w}")
        L.append("")

    b = (out.get("run_metadata") or {}).get("budget") or {}
    L += ["## Run", "",
          f"| job | tool calls | cache hits | LLM calls | cost | seconds | stop |",
          "|---|---|---|---|---|---|---|",
          f"| `{(out.get('run_metadata') or {}).get('job_id', '')}` | {b.get('tool_calls', '—')} "
          f"| {b.get('cache_hits', '—')} | {b.get('llm_calls', '—')} | ${float(b.get('usd', 0)):.3f} | {b.get('seconds', '—')} "
          f"| {(out.get('run_metadata') or {}).get('stop_reason', '')} |", ""]
    L += ["_Confidence is ordinal, not frequency-calibrated: 0.9 is more reliable than 0.6, "
          "it does not mean 90% correct._", ""]

    path = d / "report.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path
