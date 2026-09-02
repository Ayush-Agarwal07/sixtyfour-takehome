"""Phase 4 SYNTHESIZE — slice version: programmatic profile, no T2 summary yet.

Everything in the output is derived from the resolution and findings; nothing is
hardcoded. identity_resolution carries every candidate, rejections, and what
would disambiguate (C24)."""
from __future__ import annotations

from .. import constants
from ..types import (
    CandidateResolutionView, Confidence, Graph, Identity, IdentityResolution,
    Output, Profile, RejectedView, RunMetadata,
)

_CONTACT = {"email", "phone", "website", "handle"}


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


def synthesize(seed, resolution, findings, job_id: str, *, counters: dict | None = None,
               seconds: float | None = None) -> Output:
    claims = findings.claims if findings else []
    nodes = findings.nodes if findings else []
    stop = findings.stop_reason if findings else ("no_expand:" + resolution.status)

    profile = Profile()
    for c in claims:
        if c.predicate == "title" and profile.current_role is None:
            profile.current_role = c
        elif c.predicate in ("employer", "employment"):
            profile.employment.append(c)
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

    confirmed = next((c for c in resolution.candidates if c.cid == resolution.confirmed_cid), None)
    top = confirmed or (resolution.candidates[0] if resolution.candidates else None)
    hard_keys = [f"{k}:{v}" for k, v in seed.hard_ids.items()]
    if top and top.reciprocal:
        hard_keys.append("reciprocal_link")
    identity = Identity(
        confidence=top.score if (top and resolution.status == "confirmed") else Confidence(score=0.0, logodds=0.0),
        cid=resolution.confirmed_cid, hard_keys=hard_keys,
        how_confirmed=resolution.how_confirmed or resolution.reason,
    )
    ir = IdentityResolution(
        candidates=[CandidateResolutionView(cid=c.cid, score=c.score.score, terms=c.score.terms, urls=c.urls)
                    for c in resolution.candidates[:5]],
        rejected=[RejectedView(cid=c.cid, reason=c.rejected_reason) for c in resolution.candidates
                  if c.rejected_reason and c.cid != resolution.confirmed_cid],
        what_would_disambiguate=resolution.what_would_disambiguate,
    )
    payoff = [c.id for c in claims if c.evidence and c.evidence[0].extraction_method
              in ("github_emails", "wayback", "gravatar", "reciprocal")]
    budget = dict(counters or {})
    budget.update(resolution.budget)
    if seconds is not None:
        budget["seconds"] = round(seconds, 1)

    return Output(
        status=resolution.status, input=seed.input, seed=seed, regime=seed.original_regime or seed.regime,
        identity=identity, profile=profile,
        graph=Graph(nodes=nodes, edges=findings.edges if findings else []),
        negative_findings=_negative_findings(seed, claims) if resolution.status == "confirmed" else [],
        identity_resolution=ir, specialization_payoff=payoff,
        run_metadata=RunMetadata(job_id=job_id, stop_reason=stop, budget=budget,
                                 models={t: m[0] for t, m in constants.TASK_MODELS.items()}),
    )
