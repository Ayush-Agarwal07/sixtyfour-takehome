"""Every worked row of plan/reference-identity-scoring.md, asserted, plus the
end-to-end arithmetic for the run that used to confirm the wrong Sarah Chen."""
from __future__ import annotations

from pi.constants import GATE_MARGIN, GATE_P_THRESHOLD
from pi.resolve.identity_score import compute_unique, score
from pi.types import AttrObservation, Candidate, Confidence, Term


def obs(tier: float, host: str, cls: str = "", cat: str = "exact_match", kind: str = "snippet") -> AttrObservation:
    return AttrObservation(value="x", source_class=cls or {2.5: "company_site", 2.0: "personal_site",
                                                          1.2: "professional_network", 1.0: "press", 0.5: "aggregator"}[tier],
                           source_tier=tier, url=f"https://{host}/p", snippet="", category=cat, kind=kind)


def test_henry_wang_team_page_confirms():
    c = score(regime="NAME_STRONG", surname_bucket="common", is_unique=True, anchored_one_way=True,
              anchors={"employer": [obs(2.5, "sixtyfour.ai"), obs(1.2, "linkedin.com")],
                       "title": [obs(2.5, "sixtyfour.ai")]})
    assert round(c.logodds, 2) == 5.05 and c.score >= GATE_P_THRESHOLD


def test_henry_wang_linkedin_only_continues():
    c = score(regime="NAME_STRONG", surname_bucket="common", is_unique=True,
              anchors={"employer": [obs(1.2, "linkedin.com")], "title": [obs(1.2, "linkedin.com")]})
    assert round(c.logodds, 2) == 1.3 and 0.30 < c.score < GATE_P_THRESHOLD


def test_wrong_henry_wang_rejected():
    c = score(regime="NAME_STRONG", surname_bucket="common",
              negatives=[Term(factor="contradicts:employer", weight=-0.5)])
    assert c.score < 0.30


def test_andrew_goering_email_confirms():
    c = score(regime="HARD_ID_EMAIL", surname_bucket="rare", is_unique=True,
              anchors={"employer": [obs(1.2, "linkedin.com")]})
    assert round(c.logodds, 2) == 4.0 and c.score >= GATE_P_THRESHOLD


def test_jsmith_email_continues():
    c = score(regime="HARD_ID_EMAIL", surname_bucket="common", name_form="initials", is_unique=True,
              anchors={"employer": [obs(1.2, "linkedin.com")]})
    assert round(c.logodds, 2) == 1.3 and 0.30 < c.score < GATE_P_THRESHOLD


def test_profile_url_input_confirms():
    c = score(regime="HARD_ID_URL", hard_key="seed_url_resolves")
    assert round(c.logodds, 2) == 3.5 and c.score >= GATE_P_THRESHOLD


def test_two_figma_sarah_chens_tie_below_gate():
    kw = dict(regime="NAME_STRONG", surname_bucket="common", is_unique=False,
              anchors={"employer": [obs(1.2, "linkedin.com")], "title": [obs(1.2, "linkedin.com")]})
    a, b = score(**kw), score(**kw)
    assert round(a.logodds, 2) == 0.5 and a.score < GATE_P_THRESHOLD and abs(a.score - b.score) < GATE_MARGIN


def test_sarah_chen_after_portfolio_confirms_with_margin():
    real = score(regime="NAME_STRONG", surname_bucket="common", is_unique=True, reciprocal=True,
                 anchors={"employer": [obs(2.0, "sarahchen.com", cat="matches_former", kind="page"), obs(1.2, "linkedin.com")],
                          "title": [obs(2.0, "sarahchen.com", kind="page")]})
    other = score(regime="NAME_STRONG", surname_bucket="common",
                  anchors={"employer": [obs(1.2, "linkedin.com")], "title": [obs(1.2, "linkedin.com")]})
    assert real.score >= GATE_P_THRESHOLD and real.score - other.score >= GATE_MARGIN


def test_epic_systems_sarah_chen_no_longer_confirms():
    """runs/5d2837983dcf confirmed this person at 0.964. With page-level matching:
    former Figma match keeps 1.2 (LinkedIn text is professional_network, not
    self-published), current title contradicts on a page, Chen is common, and
    uniqueness needs snippet-level evidence."""
    c = score(regime="NAME_STRONG", surname_bucket="common", is_unique=False,
              anchors={"employer": [obs(1.2, "linkedin.com", cat="matches_former", kind="page")]},
              negatives=[Term(factor="contradicts:title", weight=-0.72)])
    assert c.score < 0.5


def test_uniqueness_ignores_page_level_evidence():
    a = Candidate(cid="a", attrs={"employer": [obs(2.0, "a.com", kind="page")]}, score=Confidence(score=0, logodds=0))
    b = Candidate(cid="b", attrs={"employer": [obs(1.2, "linkedin.com")]}, score=Confidence(score=0, logodds=0))
    assert compute_unique([a, b]) == {"b"}
    assert compute_unique([a]) == set()
