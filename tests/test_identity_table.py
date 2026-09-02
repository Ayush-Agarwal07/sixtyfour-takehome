"""Every worked row of plan/reference-identity-scoring.md, asserted."""
from __future__ import annotations

from pi.constants import GATE_MARGIN, GATE_P_THRESHOLD
from pi.resolve.identity_score import score
from pi.types import AttrObservation


def obs(tier: float, host: str) -> AttrObservation:
    return AttrObservation(value="x", source_class="", source_tier=tier,
                           url=f"https://{host}/p", snippet="")


def test_henry_wang_team_page_confirms():
    c = score(regime="NAME_STRONG", surname_bucket="common", is_unique=True,
              anchored_one_way=True,
              anchors={"employer": [obs(2.5, "sixtyfour.ai"), obs(1.2, "linkedin.com")],
                       "title": [obs(2.5, "sixtyfour.ai")]})
    assert round(c.logodds, 2) == 5.05
    assert c.score >= GATE_P_THRESHOLD


def test_henry_wang_linkedin_only_continues():
    c = score(regime="NAME_STRONG", surname_bucket="common", is_unique=True,
              anchors={"employer": [obs(1.2, "linkedin.com")], "title": [obs(1.2, "linkedin.com")]})
    assert round(c.logodds, 2) == 1.3
    assert 0.30 < c.score < GATE_P_THRESHOLD          # CONTINUE band


def test_wrong_henry_wang_rejected():
    from pi.types import Term
    c = score(regime="NAME_STRONG", surname_bucket="common",
              negatives=[Term(factor="snippet_contradict:employer", weight=-0.5)])
    assert c.score < 0.30


def test_andrew_goering_email_confirms():
    c = score(regime="HARD_ID_EMAIL", surname_bucket="rare", is_unique=True,
              anchors={"employer": [obs(1.2, "linkedin.com")]})
    assert round(c.logodds, 2) == 4.0
    assert c.score >= GATE_P_THRESHOLD


def test_jsmith_email_continues():
    c = score(regime="HARD_ID_EMAIL", surname_bucket="common", name_form="initials",
              is_unique=True, anchors={"employer": [obs(1.2, "linkedin.com")]})
    assert round(c.logodds, 2) == 1.3
    assert 0.30 < c.score < GATE_P_THRESHOLD


def test_profile_url_input_confirms():
    c = score(regime="HARD_ID_URL", hard_key="seed_url_resolves")   # no surname known
    assert round(c.logodds, 2) == 3.5
    assert c.score >= GATE_P_THRESHOLD


def test_two_figma_sarah_chens_tie_below_gate():
    kw = dict(regime="NAME_STRONG", surname_bucket="common", is_unique=False,
              anchors={"employer": [obs(1.2, "linkedin.com")], "title": [obs(1.2, "linkedin.com")]})
    a, b = score(**kw), score(**kw)
    assert round(a.logodds, 2) == 0.5
    assert a.score < GATE_P_THRESHOLD                 # neither confirms
    assert abs(a.score - b.score) < GATE_MARGIN       # margin fails → fetch or abstain


def test_sarah_chen_after_portfolio_confirms_with_margin():
    real = score(regime="NAME_STRONG", surname_bucket="common", is_unique=True, reciprocal=True,
                 anchors={"employer": [obs(2.0, "sarahchen.com"), obs(1.2, "linkedin.com")],
                          "title": [obs(2.0, "sarahchen.com")]})
    other = score(regime="NAME_STRONG", surname_bucket="common",
                  anchors={"employer": [obs(1.2, "linkedin.com")], "title": [obs(1.2, "linkedin.com")]})
    assert real.score >= GATE_P_THRESHOLD
    assert real.score - other.score >= GATE_MARGIN
