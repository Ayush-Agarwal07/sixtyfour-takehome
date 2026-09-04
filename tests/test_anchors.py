"""Anchors: identity anchor set + the deterministic same-person score (DESIGN.md §13)."""
from pi.expand.anchors import Anchors
from pi.types import Candidate, Claim, Confidence, Evidence, Seed, Variant


def _seed(**kw) -> Seed:
    kw.setdefault("input", "jane roe")
    kw.setdefault("regime", "NAME_STRONG")
    kw.setdefault("names", [Variant(form="Jane Roe")])
    return Seed(**kw)


def _cand(**kw) -> Candidate:
    kw.setdefault("cid", "c1")
    kw.setdefault("score", Confidence(score=0.9, logodds=2.0))
    return Candidate(**kw)


def _ev(**kw) -> Evidence:
    kw.setdefault("evidence_id", "e1")
    kw.setdefault("candidate_id", "c1")
    kw.setdefault("url", "https://x.example/1")
    kw.setdefault("snippet", "s")
    kw.setdefault("source_class", "company_site")
    kw.setdefault("extraction_method", "prose_llm")
    return Evidence(**kw)


def _claim(cid: str, predicate: str, value: str, **kw) -> Claim:
    kw.setdefault("confidence", Confidence(score=0.9, logodds=2.0))
    kw.setdefault("attachment_confidence", 0.95)
    kw.setdefault("identity_link", "anchor_match:name")
    kw.setdefault("evidence", [_ev(evidence_id=cid + "-ev")])
    return Claim(id=cid, predicate=predicate, value=value, value_raw=value, **kw)


def test_owned_page_with_name_and_employer_scores_near_certain():
    a = Anchors(_seed(orgs=["Ramp"]), _cand())
    p, matched, name_present = a.score("Jane Roe is an engineer at Ramp.", owned=True)
    assert p >= 0.95 and name_present and matched == ["employer"]


def test_name_only_scores_middle_band():
    a = Anchors(_seed(), _cand())
    p, matched, name_present = a.score("Jane Roe writes here.")
    assert abs(p - 0.622) < 0.01
    assert name_present and matched == []


def test_no_name_no_anchor_scores_below_skip():
    a = Anchors(_seed(orgs=["Ramp"]), _cand())
    p, matched, name_present = a.score("A different person entirely.")
    assert p < 0.5 and not name_present


def test_grow_from_trusted_school_is_weak_and_stays_unverified():
    """A school anchor is weak (shared by thousands of namesakes): name + one weak
    category lands at ≈0.750 — real evidence, but still `unverified`, not `profile`."""
    a = Anchors(_seed(), _cand())
    a.grow([_claim("c1", "education", "MIT")])
    p, matched, _ = a.score("Jane Roe studied at MIT.")
    assert abs(p - 0.750) < 0.01
    assert "school" in matched


def test_grow_two_weak_categories_crosses_profile_band():
    a = Anchors(_seed(), _cand())
    a.grow([_claim("c1", "education", "MIT"), _claim("c2", "location", "Boston")])
    p, matched, _ = a.score("Jane Roe studied at MIT and lives in Boston.")
    assert p >= 0.8
    assert {"school", "location"} <= set(matched)


def test_collaborator_phrase_never_gets_first_word_expansion():
    """'David Smith' as a collaborator anchor must not reduce to the bare first name
    'david' — that would match nearly any text about a different David."""
    a = Anchors(_seed(), _cand())
    a.grow([_claim("c1", "relationship", "colleague: David Smith")])
    p, matched, _ = a.score("David is around today.")
    assert "collaborator" not in matched


def test_email_or_domain_in_body_counts_as_identity_a_bare_handle_does_not():
    """A page that states the person's own personal domain identifies them as well as
    the name does. A page that only echoes a probed handle (its URL and a soft-404 body
    do this by construction) does not — it must not get the identity bonus."""
    a = Anchors(_seed(), _cand(handles={"site": "janeroe.dev"}))
    p, matched, identity = a.score("profile of jr — janeroe.dev")
    assert p >= 0.8 and identity

    a2 = Anchors(_seed(), _cand(handles={"github": "rarehandle123"}))
    p2, matched2, identity2 = a2.score("rarehandle123 not found")
    assert p2 < 0.5



def test_no_identity_is_capped_below_profile_even_with_anchors_and_link():
    a = Anchors(_seed(orgs=["Ramp"], locations=["Boston"], schools=["MIT"]), _cand())
    p, _, identity = a.score("Works at Ramp in Boston, studied at MIT.", linked=True)
    assert p < 0.8 and not identity
    p2, _, identity2 = a.score("Jane Roe works at Ramp in Boston, studied at MIT.", linked=True)
    assert p2 >= 0.9 and identity2
