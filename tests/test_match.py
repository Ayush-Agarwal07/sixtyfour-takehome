"""T4 matcher output → observations with the citing source's tier, and negatives."""
from __future__ import annotations

from pi.resolve.match import AttrCat, MatchRow, _apply, seed_anchors
from pi.types import Candidate, Confidence, Seed, SourceText, Variant


def _cand():
    return Candidate(cid="c1", urls=["https://www.linkedin.com/in/sarah-che"],
                     sources=[SourceText(url="https://www.linkedin.com/in/sarah-che", kind="snippet",
                                         source_class="professional_network", tier=1.2, text="Sarah Chen - Epic"),
                              SourceText(url="https://www.linkedin.com/in/sarah-che", kind="page",
                                         source_class="professional_network", tier=1.2, text="Technical Solutions Engineer at Epic Systems. Past: Product Designer, Figma")],
                     score=Confidence(score=0, logodds=0))


def _seed():
    return Seed(input="sarah chen, product designer, ex-figma", regime="NAME_STRONG",
                names=[Variant(form="Sarah Chen")], orgs=["figma"], titles=["product designer"],
                tense={"figma": "former"})


def test_contradiction_produces_negative_and_former_match_keeps_tier():
    c, s = _cand(), _seed()
    row = MatchRow(cid="c1", name="exact",
                   employer=AttrCat(category="matches_former", sources=[2]),
                   title=AttrCat(category="contradicts", sources=[2]))
    _apply(c, row, seed_anchors(s), s)
    assert c.attrs["employer"][0].category == "matches_former" and c.attrs["employer"][0].source_tier == 1.2
    assert "title" not in c.attrs
    assert any(t.factor == "contradicts:title" and t.weight == -0.72 for t in c.negatives)   # 1.2 × 0.6 on a page


def test_name_mismatch_is_a_negative():
    c, s = _cand(), _seed()
    _apply(c, MatchRow(cid="c1", name="mismatch"), seed_anchors(s), s)
    assert c.negatives[0].factor == "name_mismatch" and c.negatives[0].weight == -2.0


def test_matches_former_downgraded_when_seed_tense_is_current():
    c, s = _cand(), _seed()
    s.tense = {"figma": "current"}
    _apply(c, MatchRow(cid="c1", employer=AttrCat(category="matches_former", sources=[1])), seed_anchors(s), s)
    assert c.attrs["employer"][0].category == "partial"
