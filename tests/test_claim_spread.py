"""plan/reference-confidence-scoring.md §6 spread check + §7 merge/conflict."""
from __future__ import annotations

from datetime import date

from pi.score.claim_score import merge_claims, score_claim
from pi.types import Claim, Confidence, Evidence, Temporal


def _ev(url: str, source_class: str, ev_id: str, extraction_method: str = "prose_llm") -> Evidence:
    return Evidence(evidence_id=ev_id, candidate_id="c1", url=url, snippet="x",
                     source_class=source_class, extraction_method=extraction_method)


def _claim(predicate: str, value: str, evidence: list[Evidence], temporal: Temporal | None = None) -> Claim:
    return Claim(id=f"{predicate}:{value}:{evidence[0].evidence_id}", predicate=predicate, value=value,
                 value_raw=value, temporal=temporal or Temporal(), confidence=Confidence(score=0, logodds=0),
                 identity_link="anchor_match:name", evidence=evidence)


def test_official_page_site_parser_fresh_single_source():
    c = score_claim(source_class="company_site", rung="site_parser")
    assert round(c.logodds, 2) == 1.7
    assert round(c.score, 2) == 0.85


def test_two_independent_primaries_json_ld():
    c = score_claim(source_class="company_site", rung="json_ld", n_independent=2)
    assert round(c.logodds, 2) == 3.2
    assert round(c.score, 2) == 0.96


def test_aggregator_prose_llm_stale_title():
    c = score_claim(source_class="aggregator", rung="prose_llm", predicate="title", years_stale=2.0)
    assert round(c.logodds, 2) == -2.0
    assert round(c.score, 2) == 0.12


def test_merge_corroborates_across_independent_sources():
    claims = [
        _claim("employer", "acme", [_ev("https://linkedin.com/in/x", "professional_network", "e1")]),
        _claim("employer", "acme", [_ev("https://sixtyfour.ai/team", "company_site", "e2")]),
    ]
    merged, conflicts = merge_claims(claims, today=date(2026, 1, 1))
    assert len(merged) == 1 and not conflicts
    assert any(t.factor == "corroboration:2src" for t in merged[0].confidence.terms)


def test_merge_two_aggregators_yields_no_corroboration():
    claims = [
        _claim("employer", "acme", [_ev("https://zoominfo.com/p/x", "aggregator", "e1")]),
        _claim("employer", "acme", [_ev("https://rocketreach.co/x", "aggregator", "e2")]),
    ]
    merged, _conflicts = merge_claims(claims, today=date(2026, 1, 1))
    assert len(merged) == 1
    assert not any(t.factor.startswith("corroboration") for t in merged[0].confidence.terms)


def test_merge_flags_soft_conflict_for_two_ongoing_employers():
    ongoing = Temporal(start=date(2020, 1, 1), end_state="ongoing")
    claims = [
        _claim("employer", "acme", [_ev("https://acme.com/team", "company_site", "e1")], temporal=ongoing),
        _claim("employer", "beta", [_ev("https://beta.com/team", "company_site", "e2")], temporal=ongoing),
    ]
    merged, conflicts = merge_claims(claims, today=date(2026, 1, 1))
    assert len(merged) == 2
    assert len(conflicts) == 1
    assert conflicts[0].kind == "soft" and conflicts[0].predicate == "employer"
    assert {conflicts[0].values[0], conflicts[0].values[1]} == {"acme", "beta"}
    for c in merged:
        assert any(t.factor == "conflict:soft" for t in c.confidence.terms)


def test_merge_keeps_score_when_start_set_but_no_context_date():
    # B5: a dated claim (temporal.start set) must not eat the no_context_date
    # penalty just because context_date itself is unset.
    temporal = Temporal(start=date(2019, 1, 1))
    claims = [_claim("title", "engineer", [_ev("https://acme.com/team", "company_site", "e1")], temporal=temporal)]
    expected = score_claim(source_class="company_site", rung="prose_llm", predicate="title", has_context_date=True)
    merged, _conflicts = merge_claims(claims, today=date(2026, 1, 1))
    assert round(merged[0].confidence.score, 4) == round(expected.score, 4)
    assert not any(t.factor == "no_context_date" for t in merged[0].confidence.terms)


def test_merge_undated_titles_yield_no_conflict():
    claims = [
        _claim("title", "engineer", [_ev("https://linkedin.com/in/x", "professional_network", "e1")]),
        _claim("title", "manager", [_ev("https://linkedin.com/in/x", "professional_network", "e2")]),
    ]
    merged, conflicts = merge_claims(claims, today=date(2026, 1, 1))
    assert len(merged) == 2
    assert not conflicts
