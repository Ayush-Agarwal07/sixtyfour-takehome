"""The identity log-odds table (plan/reference-identity-scoring.md).

Pure: takes decided signals, sums weighted terms, sigmoids. Matching upstream
decides *which* signals hold; this only prices them. Every worked row in the
reference is asserted in tests/test_identity_table.py.
"""
from __future__ import annotations

import math

from .. import constants
from ..sources import host_of, registrable_domain
from ..types import AttrObservation, Confidence, Term


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def to_confidence(terms: list[Term]) -> Confidence:
    lo = sum(t.weight for t in terms)
    return Confidence(score=sigmoid(lo), logodds=lo, terms=terms)


def _mult(o: AttrObservation) -> float:
    return constants.T4_CATEGORY_MULT.get(getattr(o, "category", "exact_match"), 1.0)


def anchor_weight(anchors: dict[str, list[AttrObservation]] | None, *, kinds: set[str] | None = None) -> float:
    """Σ over attributes of the best single-source weight (tier × attr × category)."""
    total = 0.0
    for pred, obs in (anchors or {}).items():
        obs = [o for o in obs if kinds is None or getattr(o, "kind", "snippet") in kinds]
        if not obs:
            continue
        attr = constants.ATTR_FACTORS.get(pred, 0.0)
        total += max(o.source_tier * attr * _mult(o) for o in obs)
    return total


def score(
    *,
    regime: str,
    surname_bucket: str | None = None,
    name_form: str = "exact",
    anchors: dict[str, list[AttrObservation]] | None = None,
    is_unique: bool = False,
    reciprocal: bool = False,
    anchored_one_way: bool = False,
    dominant: bool = False,
    hard_key: str | None = None,
    negatives: list[Term] | None = None,
) -> Confidence:
    terms: list[Term] = [Term(factor="prior", weight=constants.REGIME_PRIORS[regime])]

    if hard_key:
        terms.append(Term(factor=f"hard_key:{hard_key}", weight=constants.IDENTITY_HARD_KEYS[hard_key]))
    if reciprocal:
        terms.append(Term(factor="reciprocal_link", weight=constants.IDENTITY_HARD_KEYS["reciprocal_link"]))
    if anchored_one_way:
        terms.append(Term(factor="anchored_one_way", weight=constants.ANCHORED_ONE_WAY))

    for pred, obs in (anchors or {}).items():
        obs = [o for o in obs if _mult(o) > 0]
        if not obs:
            continue
        attr = constants.ATTR_FACTORS.get(pred, 0.0)
        best = max(obs, key=lambda o: o.source_tier * attr * _mult(o))
        base = best.source_tier * attr * _mult(best)
        terms.append(Term(factor=f"anchor:{pred}:{best.source_class}", weight=round(base, 3)))
        keys = {(o.source_class if o.source_class != "aggregator" else "aggregator",
                 registrable_domain(host_of(o.url)) if o.source_class != "aggregator" else "*") for o in obs}
        if len(keys) > 1:
            corr = min(constants.CORROBORATION_CAP, constants.CORROBORATION_PER_SOURCE * (len(keys) - 1))
            terms.append(Term(factor=f"corroboration:{pred}:{len(keys)}src", weight=round(corr, 3)))

    if surname_bucket:
        terms.append(Term(factor=f"surname:{surname_bucket}", weight=constants.SURNAME_RARITY[surname_bucket]))
    form_w = constants.NAME_FORM.get(name_form, 0.0)
    if form_w:
        terms.append(Term(factor=f"name_form:{name_form}", weight=form_w))
    if is_unique:
        terms.append(Term(factor="uniqueness", weight=constants.UNIQUENESS_BONUS))
    if dominant:
        terms.append(Term(factor="dominant_cluster", weight=constants.DOMINANT_CLUSTER_BONUS))

    terms += negatives or []
    return to_confidence(terms)


def compute_unique(cands) -> set[str]:
    """A2: +0.8 iff exactly one candidate reaches UNIQUENESS_MIN_ANCHOR on
    enumeration-time (snippet) evidence. Fetch order cannot manufacture it."""
    strong = [c for c in cands if anchor_weight(c.attrs, kinds={"snippet"}) >= constants.UNIQUENESS_MIN_ANCHOR]
    return {strong[0].cid} if len(strong) == 1 else set()


def compute_dominant(cands, regime: str) -> set[str]:
    """A5: public-figure signal for name-only regimes — one cluster holds most of the
    identity-bearing SERP urls."""
    if regime not in ("BARE_NAME", "NAME_WEAK"):
        return set()
    total = sum(len(c.urls) for c in cands)
    if total < constants.DOMINANT_CLUSTER_MIN_URLS:
        return set()
    top = max(cands, key=lambda c: len(c.urls))
    return {top.cid} if len(top.urls) / total >= constants.DOMINANT_CLUSTER_SHARE else set()


def score_candidate(seed, cand, surname_bucket: str | None, is_unique: bool, dominant: bool = False) -> Confidence:
    return score(regime=seed.regime, surname_bucket=surname_bucket, name_form=getattr(cand, "name_form", "exact"),
                 anchors=cand.attrs, is_unique=is_unique, reciprocal=cand.reciprocal,
                 anchored_one_way=cand.anchored_one_way, dominant=dominant,
                 hard_key=cand.hard_key, negatives=cand.negatives)
