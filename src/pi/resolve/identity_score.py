"""The §3 identity log-odds table (plan/reference-identity-scoring.md).

Pure: takes decided signals, sums weighted terms, sigmoids. The clustering /
matching upstream decides *which* signals hold; this only prices them. Every
worked row in reference-identity-scoring.md is asserted in tests/test_identity_table.py.
"""
from __future__ import annotations

import math
from urllib.parse import urlsplit

from .. import constants
from ..types import AttrObservation, Confidence, Term


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def to_confidence(terms: list[Term]) -> Confidence:
    lo = sum(t.weight for t in terms)
    return Confidence(score=sigmoid(lo), logodds=lo, terms=terms)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def score(
    *,
    regime: str,
    surname_bucket: str | None = None,
    name_form: str = "exact",
    anchors: dict[str, list[AttrObservation]] | None = None,
    is_unique: bool = False,
    reciprocal: bool = False,
    anchored_one_way: bool = False,
    hard_key: str | None = None,
    negatives: list[Term] | None = None,
) -> Confidence:
    """Price one candidate. `anchors` maps a predicate → the observations that
    matched the seed for it, each carrying its own source tier (Types′)."""
    terms: list[Term] = [Term(factor="prior", weight=constants.REGIME_PRIORS[regime])]

    if hard_key:
        terms.append(Term(factor=f"hard_key:{hard_key}", weight=constants.IDENTITY_HARD_KEYS[hard_key]))
    if reciprocal:
        terms.append(Term(factor="reciprocal_link", weight=constants.IDENTITY_HARD_KEYS["reciprocal_link"]))
    if anchored_one_way:
        terms.append(Term(factor="anchored_one_way", weight=constants.ANCHORED_ONE_WAY))

    for pred, obs in (anchors or {}).items():
        if not obs:
            continue
        attr = constants.ATTR_FACTORS.get(pred, 0.0)
        base = max(o.source_tier for o in obs) * attr
        terms.append(Term(factor=f"anchor:{pred}", weight=round(base, 3)))
        # ponytail: independence keyed by host only (registrable_domain deferred to Stage 3).
        n_independent = len({_host(o.url) for o in obs})
        if n_independent > 1:
            corr = min(constants.CORROBORATION_CAP, constants.CORROBORATION_PER_SOURCE * (n_independent - 1))
            terms.append(Term(factor=f"corroboration:{pred}:{n_independent}src", weight=round(corr, 3)))

    if surname_bucket:
        terms.append(Term(factor=f"surname:{surname_bucket}", weight=constants.SURNAME_RARITY[surname_bucket]))
    form_w = constants.NAME_FORM.get(name_form, 0.0)
    if form_w:
        terms.append(Term(factor=f"name_form:{name_form}", weight=form_w))
    if is_unique:
        terms.append(Term(factor="uniqueness", weight=constants.UNIQUENESS_BONUS))

    terms += negatives or []
    return to_confidence(terms)


def _n_anchors(cand) -> int:
    return sum(1 for obs in cand.attrs.values() if obs)


def _max_tier(cand) -> float:
    return max((o.source_tier for obs in cand.attrs.values() for o in obs), default=0.0)


def compute_unique(cands) -> set[str]:
    """Unique′: a candidate is unique iff it is the ONLY one with any ≥prof-tier
    anchor, OR the only one with ≥2 anchors, OR the only one with an official-tier
    match. Two same-name candidates that tie satisfy none → neither is unique."""
    prof = [c for c in cands if _max_tier(c) >= constants.ANCHOR_MIN_PROF_TIER]
    ge2 = [c for c in cands if _n_anchors(c) >= 2]
    official = [c for c in cands if _max_tier(c) >= constants.ANCHOR_TIERS["official_org"]]
    uniq: set[str] = set()
    for c in cands:
        if (len(prof) == 1 and c in prof) or (len(ge2) == 1 and c in ge2) or (len(official) == 1 and c in official):
            uniq.add(c.cid)
    return uniq


def score_candidate(seed, cand, surname_bucket: str | None, is_unique: bool):
    return score(regime=seed.regime, surname_bucket=surname_bucket,
                 anchors=cand.attrs, is_unique=is_unique,
                 reciprocal=getattr(cand, "reciprocal", False))
