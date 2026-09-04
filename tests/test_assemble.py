"""Tuples → Claims + graph nodes/edges: anti-fabrication span check and graph wiring."""
from __future__ import annotations

from datetime import date

from pi.expand.assemble import assemble
from pi.types import Seed

TEXT = "Andrew is a product designer at Ramp in New York."
TODAY = date(2024, 1, 1)


def _seed():
    return Seed(input="andrew", regime="NAME_STRONG", org_domains={})


def _assemble(tuples, *, rung="prose_llm", source_class="personal_site", text=TEXT):
    return assemble(tuples, url="https://example.com/a", text=text, cid="c1", rung=rung,
                    source_class=source_class, identity_link="anchor_match:name", seed=_seed(), today=TODAY)


def test_prose_span_absent_is_dropped():
    claims, _, _ = _assemble([("title", "CEO", "was the CEO of Acme", None)])
    assert claims == []


def test_prose_span_present_is_kept():
    claims, _, _ = _assemble([("title", "product designer", "product designer at Ramp", None)])
    assert len(claims) == 1 and claims[0].evidence[0].candidate_id == "c1"


def test_fuzzy_span_kept():
    claims, _, _ = _assemble([("title", "product designer", "product  designer at Ramp", None)])
    assert len(claims) == 1


def test_employment_ongoing_makes_company_node_and_edge():
    claims, nodes, edges = _assemble(
        [("employment", "Ramp", "Ramp", "2019 – Present")], rung="json_ld", source_class="company_site")
    assert len(claims) == 1 and claims[0].temporal.end_state == "ongoing"
    assert any(n.type == "company" for n in nodes)
    assert any(e.type == "employment" for e in edges)


def test_bare_domain_website_gets_a_well_formed_account_node_id():
    claims, nodes, edges = _assemble(
        [("website", "henr.ee", "henr.ee", None)], rung="json_ld", source_class="personal_site")
    assert len(claims) == 1
    account_nodes = [n for n in nodes if n.type == "account"]
    assert len(account_nodes) == 1 and account_nodes[0].id == "account:henr.ee:henr.ee"


def test_relationship_makes_unresolved_person_node_and_no_other_claim():
    claims, nodes, edges = _assemble(
        [("relationship", "co_founder: Jane Doe", "co_founder: Jane Doe", None)],
        rung="json_ld", source_class="personal_site")
    assert len(claims) == 1 and claims[0].value == "co_founder: Jane Doe"
    person_nodes = [n for n in nodes if n.type == "person"]
    assert len(person_nodes) == 1 and person_nodes[0].id.startswith("person:unresolved:jane-doe:")
    assert any(e.type == "relationship" for e in edges)


def test_duplicate_tuples_give_one_claim():
    claims, _, _ = _assemble(
        [("employer", "Ramp", "Ramp", None), ("employer", "Ramp", "Ramp", None)],
        rung="json_ld", source_class="company_site")
    assert len(claims) == 1
