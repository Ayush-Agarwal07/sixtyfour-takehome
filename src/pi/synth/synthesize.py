"""Phase 4 SYNTHESIZE — programmatic profile + T2 narrated summary.

Everything in the output is derived from the resolution and findings; nothing is
hardcoded. identity_resolution carries every candidate, rejections, and what
would disambiguate (C24). The summary is model-written but every sentence must
cite real claim ids — a hallucinated citation drops the sentence, never the run.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from .. import constants
from ..types import (
    CandidateResolutionView, Claim, Confidence, Graph, Identity, IdentityResolution,
    Output, Profile, RejectedView, RunMetadata, SummarySentence, TimelineEntry,
)

_CONTACT = {"email", "phone", "website", "handle"}
_PAYOFF_METHODS = {"github_emails", "gravatar", "wayback", "username_probe", "github_code", "openalex"}
_SYNTH_PROMPT = (Path(__file__).resolve().parent.parent / "llm" / "prompts" / "synth.md").read_text()


class SummaryOut(BaseModel):
    summary: list[SummarySentence] = Field(default_factory=list)
    reasoning: str = ""


def _negative_findings(seed, claims) -> list[dict]:
    out = []
    checks = [("employer", o) for o in seed.orgs] + [("title", t) for t in seed.titles] + \
             [("education", s) for s in seed.schools] + [("location", l) for l in seed.locations]
    for pred, sought in checks:
        tok = sought.lower().replace(".com", "").split()[0]
        if not any(c.predicate in (pred, "employment") and tok in c.value for c in claims):
            out.append({"predicate": pred, "sought": sought, "status": "not_confirmed",
                        "note": "asserted in the input; no claim with a page span confirmed it"})
    return out


_SLOT_LABELS = {
    "identity_anchors": "identity anchors (verified handle, email, or site)",
    "current_role": "current role corroborated by 2 independent sources",
    "employment_history": "employment history (3 positions)",
    "education": "education",
    "contact": "verified contact",
    "public_output": "public output (repos, publications, talks)",
    "social_graph": "relationships (co-founders, co-authors, colleagues)",
    "notable_artifacts": "notable artifacts (awards, funding, founded, boards)",
}


def _open_slot_findings(findings) -> list[dict]:
    """Coverage slots still below target at stop: what the run looked for and how much it found."""
    if not findings:
        return []
    return [{"predicate": "coverage", "sought": _SLOT_LABELS.get(s.name, s.name), "slot": s.name,
             "found": s.current, "target": s.target, "status": "not_found" if s.current == 0 else "partial"}
            for s in findings.slots if not s.closed]


def _build_profile(claims: list[Claim]) -> Profile:
    profile = Profile()
    titles: list[Claim] = []
    employers: list[Claim] = []
    for c in claims:
        if c.predicate == "title":
            titles.append(c)
        elif c.predicate in ("employer", "employment"):
            employers.append(c)
        elif c.predicate == "education":
            profile.education.append(c)
        elif c.predicate == "location" and profile.location is None:
            profile.location = c
        elif c.predicate in _CONTACT:
            profile.contact.append(c)
        elif c.predicate == "relationship":
            profile.relationships.append(c)
        elif c.predicate in ("repo", "publication", "talk"):
            profile.public_output.append(c)
        else:
            profile.notable.append(c)

    ongoing = [c for c in titles if c.temporal.end_state == "ongoing"]
    pool = ongoing or titles
    profile.current_role = max(pool, key=lambda c: c.confidence.score) if pool else None

    best_by_value: dict[str, Claim] = {}
    for c in employers:
        cur = best_by_value.get(c.value)
        if cur is None or c.confidence.score > cur.confidence.score:
            best_by_value[c.value] = c
    dated = sorted((c for c in best_by_value.values() if c.temporal.start), key=lambda c: c.temporal.start, reverse=True)
    undated = [c for c in best_by_value.values() if not c.temporal.start]
    profile.employment = dated + undated
    return profile


def _claim_line(c: Claim) -> str:
    ongoing = ", ongoing" if c.temporal.end_state == "ongoing" else ""
    return f"[{c.id}] {c.predicate}={c.value_raw} (p={c.confidence.score:.2f}{ongoing})"


def _timeline(claims: list[Claim]) -> list[TimelineEntry]:
    rows = []
    for c in claims:
        d = c.temporal.start or c.temporal.context_date
        if not d:
            continue
        date_str = f"{d.year:04d}" if c.temporal.precision == "year" else f"{d.year:04d}-{d.month:02d}"
        text = f"{c.predicate}: {c.value_raw}"
        if c.temporal.end_state == "ended" and c.temporal.end:
            text += f" (ended {c.temporal.end.year})"
        url = c.evidence[0].url if c.evidence else ""
        rows.append((date_str, c.confidence.score, TimelineEntry(date=date_str, text=text, claim_id=c.id, url=url)))
    rows.sort(key=lambda r: (r[0], -r[1]))
    seen: set[tuple[str, str]] = set()
    out: list[TimelineEntry] = []
    for date_str, _score, entry in rows:
        key = (entry.date, entry.text)
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
        if len(out) >= 40:
            break
    return out


async def _summarize(seed, claims: list[Claim], conflicts, llm,
                     timeline: list[TimelineEntry] | None = None) -> list[SummarySentence]:
    if not llm or not claims:
        return []
    lines = [f"Target: {seed.input}"]
    lines += [_claim_line(c) for c in claims[:60]]
    lines += [f"CONFLICT {cf.kind} {cf.predicate}: {' vs '.join(cf.values)}" for cf in conflicts]
    if timeline:
        lines.append("TIMELINE")
        lines += [f"{t.date} — {t.text} [{t.claim_id}]" for t in timeline[:25]]
    prompt = "\n".join(lines)
    try:
        out = await llm.complete("T2", prompt, SummaryOut, phase="synthesize", system=_SYNTH_PROMPT)
    except Exception:  # noqa: BLE001 — a bad summary is never fatal to the run
        return []
    ids = {c.id for c in claims}
    kept = [s for s in out.summary if s.claim_ids and all(cid in ids for cid in s.claim_ids)]
    return kept[:8]


async def synthesize(seed, resolution, findings, job_id: str, *, counters: dict | None = None,
                     seconds: float | None = None, llm=None) -> Output:
    all_claims = findings.claims if findings else []
    # attachment < ATTACH_PROFILE: a real claim about a possibly different person — it
    # never feeds the profile, timeline, summary, or payoff (DESIGN.md §13).
    claims = [c for c in all_claims if c.attachment_confidence >= constants.ATTACH_PROFILE]
    unverified = [c for c in all_claims if c.attachment_confidence < constants.ATTACH_PROFILE]
    nodes = findings.nodes if findings else []
    stop = findings.stop_reason if findings else ("no_expand:" + resolution.status)

    profile = _build_profile(claims)

    confirmed = next((c for c in resolution.candidates if c.cid == resolution.confirmed_cid), None)
    top = confirmed or (resolution.candidates[0] if resolution.candidates else None)
    hard_keys = [f"{k}:{v}" for k, v in seed.hard_ids.items()]
    if top and top.reciprocal:
        hard_keys.append("reciprocal_link")
    how_confirmed = resolution.how_confirmed or resolution.reason
    timeline = _timeline(claims)
    accounts_found = len({c.value for c in claims if c.predicate == "handle" and c.confidence.score >= 0.5})
    identity = Identity(
        confidence=top.score if (top and resolution.status == "confirmed") else Confidence(score=0.0, logodds=0.0),
        cid=resolution.confirmed_cid, hard_keys=hard_keys,
        how_confirmed=how_confirmed,
        public_figure=how_confirmed.startswith("public figure"),
        footprint_since=timeline[0].date[:4] if timeline else None,
        accounts_found=accounts_found,
    )
    ir = IdentityResolution(
        candidates=[CandidateResolutionView(cid=c.cid, score=c.score.score, terms=c.score.terms, urls=c.urls)
                    for c in resolution.candidates[:5]],
        rejected=[RejectedView(cid=c.cid, reason=c.rejected_reason) for c in resolution.candidates
                  if c.rejected_reason and c.cid != resolution.confirmed_cid],
        what_would_disambiguate=resolution.what_would_disambiguate,
    )
    payoff = [c.id for c in claims
              if any(e.extraction_method in _PAYOFF_METHODS for e in c.evidence)
              or c.identity_link == "hard_key:reciprocal_link"]

    conflicts = findings.conflicts if findings else []
    negative_findings = (_negative_findings(seed, claims) + _open_slot_findings(findings)) \
        if resolution.status == "confirmed" else []

    summary = await _summarize(seed, claims, conflicts, llm, timeline)

    budget = dict(counters or {})
    budget["resolve"] = dict(resolution.budget)
    if seconds is not None:
        budget["seconds"] = round(seconds, 1)

    return Output(
        status=resolution.status, input=seed.input, seed=seed, regime=seed.original_regime or seed.regime,
        identity=identity, summary=summary, profile=profile, unverified=unverified,
        graph=Graph(nodes=nodes, edges=findings.edges if findings else []),
        conflicts=conflicts,
        negative_findings=negative_findings,
        identity_resolution=ir, specialization_payoff=payoff, timeline=timeline,
        run_metadata=RunMetadata(job_id=job_id, stop_reason=stop, budget=budget,
                                 models={t: m[0] for t, m in constants.TASK_MODELS.items()},
                                 timings={"seconds": seconds}),
    )
