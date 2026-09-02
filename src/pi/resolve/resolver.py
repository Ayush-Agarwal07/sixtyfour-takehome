"""Phase 2 RESOLVE — enumerate → cluster → match → score → (fetch | disconfirm) → gate.

Math first; the model may veto a pass but never override a fail (D12). Evidence
gathering is bounded by the regime cap and GATE_MAX_CYCLES. Never a confident
wrong ID: anything short of the margin returns ambiguous/abstained with the
candidate table.
"""
from __future__ import annotations

import uuid

from .. import constants
from ..sources import classify, identity_tier, is_unfetchable
from ..trace.events import CandidateScore, GateDecision, GateTest, Rejection
from ..types import Candidate, Link, Resolution, SourceText
from ..understand.census import surname_bucket
from .cluster import attach_floating, candidate_from_floating, cluster
from .disconfirm import disconfirm, run_actions
from .enumerate import enumerate_candidates
from .gate import gate_decision, math_pass, t1_disambiguate, t1_gate
from .identity_score import compute_dominant, compute_unique, score_candidate
from .links import apply_page_links
from .match import match_candidates
from .role_resolve import role_resolve

_FETCH_PRIORITY = {"personal_site": 5, "code_host": 4, "company_site": 4, "academic": 3,
                   "professional_network": 3, "unknown": 2, "press": 2, "social": 1, "aggregator": 0}


async def read_page(url: str, deps) -> dict | None:
    """httpx for normal hosts, Exa contents for unfetchable ones (LinkedIn/X/…)."""
    try:
        if is_unfetchable(url):
            return await deps.exa.contents(url)
        return await deps.fetch.get(url)
    except Exception:  # noqa: BLE001
        return None


def _surname(seed) -> str | None:
    if not seed.names:
        return None
    parts = seed.names[0].form.replace(".", "").split()
    return surname_bucket(parts[-1]) if parts else None


def _emit(deps, event) -> None:
    if deps.trace:
        deps.trace.emit(event)


def _ranked(cands: list[Candidate]):
    r = sorted(cands, key=lambda c: c.score.score, reverse=True)
    top = r[0]
    runner = r[1] if len(r) > 1 else None
    return r, top, runner, top.score.score, (runner.score.score if runner else 0.0)


def _score_all(seed, cands: list[Candidate]) -> None:
    bucket = _surname(seed)
    uniq = compute_unique(cands)
    dom = compute_dominant(cands, seed.regime)
    for c in cands:
        c.score = score_candidate(seed, c, bucket, c.cid in uniq, c.cid in dom)


def _gate_test(deps, ranked, note: str | None = None) -> bool:
    _, top, runner, p_top, p_run = _ranked(ranked)
    ok = math_pass(p_top, p_run)
    _emit(deps, GateTest(event_id=uuid.uuid4().hex[:16], phase="resolve", p_top=p_top, p_runner_up=p_run,
                         margin=p_top - p_run, math_pass=ok, note=note))
    return ok


def _emit_scores(deps, ranked):
    for c in ranked[:3]:
        _emit(deps, CandidateScore(event_id=uuid.uuid4().hex[:16], phase="resolve", cid=c.cid,
                                   logodds=c.score.logodds, score=c.score.score, terms=c.score.terms))


def _best_unfetched(c: Candidate, fetched: set[str], anchors: set[str], names: list[str], exa_ok: bool) -> str | None:
    best, best_p = None, -1
    for u in c.urls:
        if u in fetched:
            continue
        cls = classify(u, anchor_domains=anchors, names=names)
        p = _FETCH_PRIORITY.get(cls, 1)
        if is_unfetchable(u):
            p = 3 if exa_ok else 0
        if p > best_p:
            best, best_p = u, p
    return best if best_p > 0 else None


async def resolve(seed, deps, llm) -> Resolution:
    counters = deps.counters
    start = counters.get("tool_calls", 0)

    def spent() -> int:
        return int(counters.get("tool_calls", 0) - start)

    # ── DEFINITE_DESC: name the role-holder first ────────────────────────
    forced: list[dict] = []
    if seed.regime == "DEFINITE_DESC":
        new_seed, holder, forced = await role_resolve(seed, deps, llm, read_page)
        if new_seed.regime == "DEFINITE_DESC":
            status = "ambiguous" if holder.competing else "abstained"
            return Resolution(status=status, budget={"tool_calls": spent()},
                              reason=f"could not name a single {seed.role_description or seed.titles} at {seed.orgs}",
                              what_would_disambiguate=(["provide the person's name"] +
                                                       [f"did you mean {n}?" for n in holder.competing]))
        for f in ("names", "regime", "titles", "role_description", "original_regime", "tense"):
            setattr(seed, f, getattr(new_seed, f))

    if not seed.names or not seed.names[0].form.strip():
        return Resolution(status="abstained", budget={"tool_calls": spent()},
                          reason="no person name and no definite role in the input",
                          what_would_disambiguate=["provide a name, an email, or a profile URL"])

    cap = constants.REGIME_CAPS[seed.regime]
    names = [v.form for v in seed.names]
    anchor_domains = set(seed.org_domains.values()) | {o.lower() for o in seed.orgs if "." in o}

    # ── enumerate + cluster ──────────────────────────────────────────────
    results = await enumerate_candidates(seed, deps)
    seen = {r["url"] for r in results}
    results += [r for r in forced if r["url"] not in seen]
    cands, floating = cluster(results, seed)
    if not cands:
        c = candidate_from_floating(floating)
        if c is None:
            return Resolution(status="abstained", budget={"tool_calls": spent()},
                              reason=f"no pages about '{names[0]}' matched the enumeration queries",
                              what_would_disambiguate=["add an employer, a city, or a profile URL"])
        cands = [c]
        floating = []
    floating = attach_floating(cands, floating)
    budget = min(spent() + constants.RESOLVE_BUDGET_BASE + constants.RESOLVE_BUDGET_PER_CANDIDATE * len(cands), cap)

    # HARD_ID_URL: the seed URL is a hard key for the candidate that owns it
    if seed.regime == "HARD_ID_URL":
        seed_url = next(iter(seed.hard_ids.values())).rstrip("/").lower()
        for c in cands:
            if any(u.rstrip("/").lower() == seed_url for u in c.urls):
                c.hard_key = "seed_url_resolves"

    # ── match + score on snippets ───────────────────────────────────────
    await match_candidates(seed, cands, llm)
    _score_all(seed, cands)
    ranked, top, runner, p_top, p_run = _ranked(cands)
    _emit_scores(deps, ranked)
    ok = _gate_test(deps, ranked)

    if seed.regime == "BARE_NAME" and _surname(seed) == "common" and len(cands) >= 3 and not ok:
        return _undecided(seed, ranked, spent(), reason="common bare name with several distinct people")

    links: list[Link] = []
    linked: dict[str, set[str]] = {}
    fetched: set[str] = set()
    exa_ok = "exa" in deps.tools

    def on_page(page: dict, owner: Candidate | None) -> None:
        apply_page_links(page, owner, cands, links, linked, deps, names=names, anchor_domains=anchor_domains)

    async def fetch_into(c: Candidate, url: str) -> bool:
        page = await read_page(url, deps)
        fetched.add(url)
        if not page or not page.get("text"):
            return False
        cls = classify(url, anchor_domains=anchor_domains, names=names)
        c.sources.append(SourceText(url=url, kind="page", source_class=cls, tier=identity_tier(cls),
                                    text=page["text"][:3000]))
        on_page(page, c)
        return True

    # ── evidence cycles ─────────────────────────────────────────────────
    for cycle in range(1, constants.GATE_MAX_CYCLES + 1):
        if not ok:
            if spent() >= budget:
                break
            touched: set[str] = set()
            # fetch the anchor org's page once, if enumeration found it (co-citation / anchored one-way)
            official = next((s for s in floating if s.source_class == "company_site" and s.url not in fetched), None)
            if official is not None and spent() < budget:
                page = await read_page(official.url, deps)
                fetched.add(official.url)
                if page:
                    on_page(page, None)
                    for c in cands:
                        if any(o.anchored_one_way for o in [c]):
                            c.sources.append(SourceText(url=official.url, kind="page", source_class="company_site",
                                                        tier=identity_tier("company_site"), text=page.get("text", "")[:3000]))
                            touched.add(c.cid)
            # top-FETCH_K by discrimination
            for c in _ranked(cands)[0][:constants.FETCH_K]:
                if spent() >= budget:
                    break
                url = _best_unfetched(c, fetched, anchor_domains, names, exa_ok)
                if url and await fetch_into(c, url):
                    touched.add(c.cid)
            if not touched:
                break
            await match_candidates(seed, cands, llm, only={c.cid for c in cands})
            _score_all(seed, cands)
            ranked, top, runner, p_top, p_run = _ranked(cands)
            _emit_scores(deps, ranked)
            ok = _gate_test(deps, ranked, note=f"after fetch cycle {cycle}")
            if not ok:
                continue
        # math passes → try to falsify before trusting it (C5)
        if spent() < budget:
            await disconfirm(seed, top, runner, deps, llm, read_page, spent=spent(), budget=budget,
                             anchor_domains=anchor_domains, on_page=on_page)
            await match_candidates(seed, cands, llm, only={top.cid})
            _score_all(seed, cands)
            ranked, top, runner, p_top, p_run = _ranked(cands)
            _emit_scores(deps, ranked)
            ok = _gate_test(deps, ranked, note="after disconfirmation")
        if ok:
            break

    if not ok:
        res = _undecided(seed, ranked, spent(), reason="gate math not met after evidence cycles", links=links)
        if len(ranked) >= 2:
            try:
                v = await t1_disambiguate(seed, ranked, links, llm, spent=spent(), budget=budget)
                for r in v.rejected:
                    for c in ranked:
                        if c.cid == r.get("cid") and r.get("reason"):
                            c.rejected_reason = r["reason"]
                if v.what_would_disambiguate:
                    res.what_would_disambiguate = v.what_would_disambiguate
                eid = uuid.uuid4().hex[:16]
                ref = deps.trace.write_reasoning(eid, v.reasoning) if deps.trace else None
                _emit(deps, GateDecision(event_id=eid, phase="resolve", decision="ABSTAIN", cid=None,
                                         reasoning_ref=ref, rejected=v.rejected))
            except Exception as e:  # noqa: BLE001 — the typed ambiguous answer stands without it
                res.reason += f" (disambiguation call failed: {type(e).__name__})"
        return res

    # ── T1 gate (veto only) ──────────────────────────────────────────────
    verdict = await t1_gate(seed, ranked, links, llm, spent=spent(), budget=budget)
    decision = gate_decision(True, verdict.decision)
    if decision == "continue" and verdict.next_evidence and spent() < budget:
        action = {"tool": "fetch", "args": {"url": verdict.next_evidence}} if verdict.next_evidence.startswith("http") \
            else {"tool": "search", "args": {"q": verdict.next_evidence}}
        await run_actions([action], top, seed, deps, read_page, anchor_domains=anchor_domains, on_page=on_page)
        await match_candidates(seed, cands, llm, only={top.cid})
        _score_all(seed, cands)
        ranked, top, runner, p_top, p_run = _ranked(cands)
        ok = _gate_test(deps, ranked, note="after CONTINUE evidence")
        if ok:
            verdict = await t1_gate(seed, ranked, links, llm, spent=spent(), budget=budget)
            decision = gate_decision(True, verdict.decision)
        else:
            decision = "continue"

    eid = uuid.uuid4().hex[:16]
    ref = deps.trace.write_reasoning(eid, verdict.reasoning) if deps.trace else None
    for r in verdict.rejected:
        for c in ranked:
            if c.cid == r.get("cid") and c is not top:
                c.rejected_reason = r.get("reason", "")
                _emit(deps, Rejection(event_id=uuid.uuid4().hex[:16], phase="resolve", cid=c.cid, reason=c.rejected_reason))
    _emit(deps, GateDecision(event_id=eid, phase="resolve", decision=verdict.decision.upper(), cid=top.cid,
                             reasoning_ref=ref, rejected=verdict.rejected, next_evidence=verdict.next_evidence))

    if decision == "confirm":
        for c in ranked:
            if c is not top and not c.rejected_reason:
                c.rejected_reason = "below gate margin; not in the top candidates shown to T1"
        how = "; ".join(f"{t.factor}={t.weight:+.1f}" for t in top.score.terms if t.weight > 0)
        return Resolution(status="confirmed", confirmed_cid=top.cid, candidates=ranked, links=links,
                          budget={"tool_calls": spent(), "cap": budget},
                          how_confirmed=f"math P={p_top:.3f} margin={p_top - p_run:.2f} [{how}]; T1 CONFIRM")
    for c in ranked:
        if c is not top and not c.rejected_reason:
            c.rejected_reason = "not selected"
    status = "abstained" if decision == "abstain" else ("ambiguous" if runner else "abstained")
    return Resolution(status=status, candidates=ranked, links=links, budget={"tool_calls": spent(), "cap": budget},
                      reason=f"T1 {verdict.decision}: {verdict.reasoning[:300]}",
                      what_would_disambiguate=verdict.what_would_disambiguate)


def _undecided(seed, ranked: list[Candidate], spent: int, *, reason: str, links: list[Link] | None = None) -> Resolution:
    plausible = [c for c in ranked if c.score.score >= 0.3]
    for c in ranked[1:]:
        c.rejected_reason = c.rejected_reason or "below gate margin"
    status = "ambiguous" if len(plausible) >= 2 else "abstained"
    wwd = ["add a current or former employer", "add a city or region", "add a school",
           "give a profile URL (LinkedIn, GitHub) or an email"]
    return Resolution(status=status, candidates=ranked, links=links or [], budget={"tool_calls": spent},
                      reason=reason, what_would_disambiguate=wwd)
