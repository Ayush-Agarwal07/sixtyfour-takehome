"""Claim confidence log-odds + cross-source merge/conflict detection.

plan/reference-confidence-scoring.md §6 (spread check) and §7 (merge). Pure:
every input is a fact about the evidence or a constrained categorical, never a
model-emitted float.
"""
from __future__ import annotations

import itertools
import math
from datetime import date

from .. import constants
from ..sources import claim_tier, host_of, registrable_domain
from ..types import Claim, Confidence, Conflict, Evidence, Temporal, Term

PREDICATE_CLASS = {
    "employer": "current_employer",
    "employment": "current_employer",
    "founded": "immutable",
    "title": "current_title",
    "location": "current_location",
    "email": "contact",
    "phone": "contact",
    "handle": "contact",
    "website": "contact",
}


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def score_claim(*, source_class: str, rung: str, predicate: str = "other", n_independent: int = 1,
                 years_stale: float = 0.0, has_context_date: bool = True,
                 conflict: str | None = None) -> Confidence:
    cls = PREDICATE_CLASS.get(predicate, "immutable")
    terms = [
        Term(factor="prior", weight=constants.LOGODDS_PRIOR),
        Term(factor=f"source_tier:{source_class}", weight=claim_tier(source_class)),
    ]
    if rung != "none":
        terms.append(Term(factor=f"extraction:{rung}", weight=constants.EXTRACTION_RUNG.get(rung, 0.0)))

    if n_independent >= 2:
        w = constants.CORROBORATION_SECOND
        total = 0.0
        for _ in range(n_independent - 1):
            total += w
            w *= constants.CORROBORATION_DECAY
        terms.append(Term(factor=f"corroboration:{n_independent}src", weight=round(total, 4)))

    if cls != "immutable":
        if years_stale:
            rec = constants.RECENCY_DECAY[cls] * years_stale
            if rec:
                terms.append(Term(factor=f"recency:{cls}:{years_stale:.1f}yr", weight=round(rec, 4)))
        if not has_context_date:
            terms.append(Term(factor="no_context_date", weight=constants.NO_CONTEXT_DATE_PENALTY))

    if conflict:
        terms.append(Term(factor=f"conflict:{conflict}", weight=constants.CONFLICT_WEIGHTS[conflict]))

    lo = sum(t.weight for t in terms)
    return Confidence(score=_sigmoid(lo), logodds=lo, terms=terms)


def independence_key(ev: Evidence) -> tuple[str, str]:
    if ev.source_class == "aggregator":
        return ("aggregator", "*")
    return (ev.source_class, registrable_domain(host_of(ev.url)))


def _temporal_richness(t: Temporal) -> int:
    return sum(x is not None for x in (t.start, t.end, t.context_date)) + (t.end_state != "unknown")


def _rescore(c: Claim, today: date, conflict: str | None = None) -> Confidence:
    ev = c.evidence
    sc = max(ev, key=lambda e: claim_tier(e.source_class)).source_class
    rung = max(ev, key=lambda e: constants.EXTRACTION_RUNG.get(e.extraction_method, 0.0)).extraction_method
    n_independent = len({independence_key(e) for e in ev})
    ctx = c.temporal.context_date
    years_stale = (today - ctx).days / 365 if ctx else 0.0
    has_context_date = ctx is not None or c.temporal.start is not None
    return score_claim(source_class=sc, rung=rung, predicate=c.predicate, n_independent=n_independent,
                        years_stale=years_stale, has_context_date=has_context_date, conflict=conflict)


def _is_current(c: Claim) -> bool:
    return c.temporal.end_state == "ongoing"


def merge_claims(claims: list[Claim], today: date) -> tuple[list[Claim], list[Conflict]]:
    groups: dict[tuple[str, str], list[Claim]] = {}
    for c in claims:
        groups.setdefault((c.predicate, c.value), []).append(c)

    merged: list[Claim] = []
    for group in groups.values():
        first = group[0]
        seen: set[str] = set()
        evidence: list[Evidence] = []
        for c in group:
            for e in c.evidence:
                if e.evidence_id not in seen:
                    seen.add(e.evidence_id)
                    evidence.append(e)
        temporal = max((c.temporal for c in group), key=_temporal_richness)
        attachment_confidence = max(c.attachment_confidence for c in group)
        merged.append(first.model_copy(update={
            "evidence": evidence, "temporal": temporal, "attachment_confidence": attachment_confidence,
        }))
    merged = [c.model_copy(update={"confidence": _rescore(c, today)}) for c in merged]

    # ponytail: hard employment conflicts need full-time knowledge we do not extract; everything is soft
    conflicts: list[Conflict] = []
    conflicted_ids: set[str] = set()
    for predicate in ("employer", "title", "location"):
        current = [c for c in merged if c.predicate == predicate and _is_current(c)]
        for a, b in itertools.combinations(current, 2):
            if a.value != b.value:
                conflicts.append(Conflict(kind="soft", predicate=predicate, values=[a.value, b.value],
                                           sources=[a.evidence[0].url, b.evidence[0].url],
                                           severity=constants.CONFLICT_WEIGHTS["soft"]))
                conflicted_ids.add(a.id)
                conflicted_ids.add(b.id)

    if conflicted_ids:
        merged = [c.model_copy(update={"confidence": _rescore(c, today, "soft")}) if c.id in conflicted_ids else c
                  for c in merged]

    merged.sort(key=lambda c: c.confidence.score, reverse=True)
    return merged, conflicts
