"""Phase 2 RESOLVE — Stage 2: enumerate → cluster → score → disconfirm → gate.

Math first, model may veto a pass but never override a fail (D12). When the margin
fails, the run fetches the top candidates' profiles (the executed disconfirmation),
rescores on page-level evidence, and re-gates once. Still short of the margin →
ambiguous/abstain with a disambiguation table. Never a confident wrong ID.
"""
from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from pydantic import BaseModel

from .. import constants
from ..trace.events import CandidateScore, Disconfirmation, GateDecision, GateTest, Merge
from ..types import AttrObservation, Resolution
from ..expand.expander import _read_page
from .cluster import AGGREGATORS, cluster
from .identity_score import compute_unique, score_candidate


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


async def _read_profile(cand, deps) -> str:
    """Best-effort profile text for a candidate (its first readable URL)."""
    for u in cand.urls[:2]:
        page = await _read_page(u, deps)
        if page and page["text"]:
            return page["text"].lower()
    return ""


class GateVerdict(BaseModel):
    decision: str = "ABSTAIN"          # CONFIRM | ABSTAIN | CONTINUE
    reasoning: str = ""
    rejected_reason: str = ""


def gate_decision(math_pass: bool, model_decision: str) -> str:
    """math first; the model may veto a pass, never override a fail."""
    if not math_pass:
        return "continue"
    return {"CONFIRM": "confirm", "ABSTAIN": "abstain"}.get(model_decision, "continue")


def _math_pass(p_top: float, p_run: float) -> bool:
    return p_top >= constants.GATE_P_THRESHOLD and (p_top - p_run) >= constants.GATE_MARGIN


def _surname_bucket(seed) -> str | None:
    if not seed.names:
        return None
    surname = seed.names[0].form.split()[-1]
    try:
        from ..understand.census import surname_bucket
        return surname_bucket(surname)
    except Exception:
        return "not_found"          # ponytail: census (Worker A) may not be present yet


def _score_all(seed, cands) -> None:
    bucket = _surname_bucket(seed)
    uniq = compute_unique(cands)
    for c in cands:
        c.score = score_candidate(seed, c, bucket, c.cid in uniq)


def _ranked(cands):
    r = sorted(cands, key=lambda c: c.score.score, reverse=True)
    top, runner = r[0], (r[1] if len(r) > 1 else None)
    return r, top, runner, top.score.score, (runner.score.score if runner else 0.0)


async def _enumerate(seed, deps) -> list[dict]:
    name = seed.names[0].form if seed.names else ""
    org = seed.orgs[0] if seed.orgs else (seed.titles[0] if seed.titles else "")
    queries = [f'"{name}" {org}'.strip()]
    if name:
        queries.append(f'site:linkedin.com/in "{name}" {org}'.strip())
    results, seen = [], set()
    for q in queries[:2]:              # ponytail: ≤2 live searches (free tier)
        try:
            for r in await deps.serper.search(q, num=10):
                if r["url"] not in seen:
                    seen.add(r["url"])
                    results.append(r)
        except Exception:
            continue
    return results


async def _disconfirm(seed, ranked, deps) -> tuple[list, dict]:
    """Fetch the top-2 profiles for page-level evidence, then either separate a
    tie (stronger anchors) or MERGE them if they mutually reference each other's
    host (verified reciprocal link, §4.7 — the legitimate merge of one person's
    two sites). Returns the possibly-merged candidate list."""
    from ..expand.expander import _read_page

    tier = constants.ANCHOR_TIERS["self_published"]
    texts: dict[str, str] = {}
    for c in ranked[:2]:
        page = await _read_page(c.urls[0], deps)
        if not page or not page["text"]:
            continue
        text = page["text"].lower()
        texts[c.cid] = text
        for o in (x.lower() for x in seed.orgs):
            token = o.replace(".", " ").split()[0]
            if token and token in text:
                c.attrs.setdefault("employer", []).append(AttrObservation(
                    value=o, source_class="self_published", source_tier=tier,
                    url=c.urls[0], snippet=text[:200]))
                break
        for t in (x.lower() for x in seed.titles):
            if t and t in text:
                c.attrs.setdefault("title", []).append(AttrObservation(
                    value=t, source_class="self_published", source_tier=tier,
                    url=c.urls[0], snippet=text[:200]))
                break

    cands = list(ranked)
    if len(ranked) >= 2:
        a, b = ranked[0], ranked[1]
        ha, hb = _host(a.urls[0]), _host(b.urls[0])
        # Only merge two DISTINCT personal domains that reference each other. Never
        # same-host, never aggregators — two LinkedIn slugs are two different people,
        # and every LinkedIn page trivially contains "linkedin.com".
        if (a.cid in texts and b.cid in texts and ha and hb and ha != hb
                and ha not in AGGREGATORS and hb not in AGGREGATORS
                and hb in texts[a.cid] and ha in texts[b.cid]):
            a.urls += [u for u in b.urls if u not in a.urls]
            for k, v in b.attrs.items():
                a.attrs.setdefault(k, []).extend(v)
            a.reciprocal = True
            cands = [c for c in ranked if c.cid != b.cid]
            if deps.trace:
                deps.trace.emit(Merge(event_id=uuid.uuid4().hex[:16], phase="resolve",
                    from_cid=b.cid, to_cid=a.cid, reason=f"verified reciprocal link {ha} <-> {hb}"))

    if deps.trace:
        deps.trace.emit(Disconfirmation(
            event_id=uuid.uuid4().hex[:16], phase="resolve",
            hypothesis="top candidates near-tied — fetch profiles to separate or merge them",
            actions=[{"tool": "read_page", "url": c.urls[0]} for c in ranked[:2]],
            result="rescored on page-level evidence"))
    return cands, texts


def _t1_gate(seed, top, runner, llm, profile_excerpt: str = "") -> GateVerdict:
    hard = ", ".join(f"{k}={v}" for k, v in seed.hard_ids.items())
    lines = [f"Seed target: {seed.input}"]
    if hard:
        lines.append(f"Hard identifier in seed: {hard} — this strongly anchors identity; "
                     "confirm unless the profile clearly contradicts it.")
    lines += ["",
              f"Top candidate {top.cid}: P={top.score.score:.3f}",
              f"  urls: {top.urls[:3]}",
              f"  matched: {{{', '.join(f'{k}={[o.value for o in v]}' for k, v in top.attrs.items())}}}"]
    if profile_excerpt:
        lines.append(f"  profile text (ground truth): {profile_excerpt[:400]}")
    if runner:
        lines.append(f"Runner-up {runner.cid}: P={runner.score.score:.3f}  urls: {runner.urls[:2]}")
    lines += ["",
              "CONFIRM if the top candidate is the seed target. ABSTAIN only if (a) the runner-up is a "
              "genuinely comparable rival that could be the real target, or (b) the profile text clearly "
              "CONTRADICTS a stated seed attribute (a different employer/role/field than the seed states). "
              "Do NOT abstain merely because information is incomplete — a well-anchored match should confirm.",
              'Return {"decision":"CONFIRM|ABSTAIN|CONTINUE","reasoning":"...","rejected_reason":"..."}.']
    return llm.complete("T1", "\n".join(lines), GateVerdict, phase="resolve")


async def resolve(seed, deps, llm) -> Resolution:
    results = await _enumerate(seed, deps)
    cands = cluster(results, seed) if results else []
    if not cands:
        return Resolution(status="abstained", budget={"tool_calls": len(results)})

    _score_all(seed, cands)
    ranked, top, runner, p_top, p_run = _ranked(cands)
    math_pass = _math_pass(p_top, p_run)
    texts: dict = {}
    if deps.trace:
        for c in ranked[:3]:
            deps.trace.emit(CandidateScore(event_id=uuid.uuid4().hex[:16], phase="resolve",
                cid=c.cid, logodds=c.score.logodds, score=c.score.score, terms=c.score.terms))
        deps.trace.emit(GateTest(event_id=uuid.uuid4().hex[:16], phase="resolve",
            p_top=p_top, p_runner_up=p_run, margin=p_top - p_run, math_pass=math_pass))

    if not math_pass:                                  # cycle 2: fetch to separate/merge, rescore
        cands, texts = await _disconfirm(seed, ranked, deps)
        _score_all(seed, cands)
        ranked, top, runner, p_top, p_run = _ranked(cands)
        math_pass = _math_pass(p_top, p_run)
        if deps.trace:
            deps.trace.emit(GateTest(event_id=uuid.uuid4().hex[:16], phase="resolve",
                p_top=p_top, p_runner_up=p_run, margin=p_top - p_run, math_pass=math_pass,
                note="after disconfirm"))

    if not math_pass:
        for c in ranked[1:4]:
            c.rejected_reason = "ambiguous: margin below gate"
        status = "ambiguous" if len(cands) > 1 else "abstained"
        return Resolution(status=status, candidates=ranked, budget={"tool_calls": len(results)})

    if top.cid not in texts:                           # ground the gate on the real profile
        texts[top.cid] = await _read_profile(top, deps)
    verdict = _t1_gate(seed, top, runner, llm, texts.get(top.cid, ""))
    eid = uuid.uuid4().hex[:16]
    ref = deps.trace.write_reasoning(eid, verdict.reasoning) if deps.trace else None
    if runner and verdict.rejected_reason:
        runner.rejected_reason = verdict.rejected_reason
    if deps.trace:
        deps.trace.emit(GateDecision(event_id=eid, phase="resolve", decision=verdict.decision,
            cid=top.cid, reasoning_ref=ref,
            rejected=([{"cid": runner.cid, "reason": runner.rejected_reason}]
                      if runner and runner.rejected_reason else [])))

    if gate_decision(math_pass, verdict.decision) == "confirm":
        return Resolution(status="confirmed", confirmed_cid=top.cid, candidates=ranked,
                          budget={"tool_calls": len(results), "llm_calls": 1})
    return Resolution(status="abstained", candidates=ranked, budget={"tool_calls": len(results)})
