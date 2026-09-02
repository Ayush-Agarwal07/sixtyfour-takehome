"""Phase 4 SYNTHESIZE — slice version: programmatic profile, no T2 summary.

ponytail: the profile is assembled deterministically from claims by predicate. The
T2 narration, conflicts, negative_findings, and inferences land in Stage 4.
"""
from __future__ import annotations

from ..types import (
    CandidateResolutionView, Confidence, Graph, Identity, IdentityResolution,
    Output, Profile, RunMetadata,
)

_CONTACT = {"email", "phone", "website", "handle"}


def synthesize(seed, resolution, findings, job_id: str) -> Output:
    claims = findings.claims if findings else []
    nodes = findings.nodes if findings else []
    stop = findings.stop_reason if findings else "no_expand"

    profile = Profile()
    for c in claims:
        if c.predicate == "title" and profile.current_role is None:
            profile.current_role = c
        elif c.predicate == "employer":
            profile.employment.append(c)
        elif c.predicate == "education":
            profile.education.append(c)
        elif c.predicate in _CONTACT:
            profile.contact.append(c)
        else:
            profile.notable.append(c)

    cand = resolution.candidates[0] if resolution.candidates else None
    identity = Identity(
        confidence=cand.score if cand else Confidence(score=0.0, logodds=0.0),
        cid=resolution.confirmed_cid,
        hard_keys=[f"email:{seed.hard_ids['email']}"] if seed.hard_ids.get("email") else [],
        how_confirmed="hard-ID email + snippet match + T1 gate",
    )
    ir = IdentityResolution(candidates=[CandidateResolutionView(
        cid=cand.cid, score=cand.score.score, terms=cand.score.terms, urls=cand.urls)] if cand else [])

    payoff = [c.id for c in claims
              if c.evidence and c.evidence[0].extraction_method == "email_domain"]

    return Output(
        status=resolution.status, input=seed.input, seed=seed, regime=seed.regime,
        identity=identity, profile=profile,
        graph=Graph(nodes=nodes, edges=findings.edges if findings else []),
        identity_resolution=ir, specialization_payoff=payoff,
        run_metadata=RunMetadata(job_id=job_id, stop_reason=stop,
                                 models={"slice": "openai/gpt-4o-mini"}),
    )
