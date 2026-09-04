"""Graph traversal/reinforce triggers and coverage-slot recomputation — pure, no I/O."""
from __future__ import annotations

from pi.expand.graph import Graph
from pi.expand.slots import Slots
from pi.types import Claim, Confidence, Evidence, GraphEdge, GraphNode, Temporal

ROOT = GraphNode(id="person:c1", type="person", label="Andrew")


def _node(id_: str, attachment: float = 1.0) -> GraphNode:
    return GraphNode(id=id_, type="company", label=id_, attachment_confidence=attachment)


def _edge(src: str, dst: str) -> GraphEdge:
    return GraphEdge(id=f"{src}->{dst}", src=src, dst=dst, type="employment", mechanism="test")


def test_descendants_counts_a_three_deep_chain():
    g = Graph(ROOT)
    for n in (_node("a"), _node("b"), _node("c")):
        g.add_node(n)
    g.add_edge(_edge("person:c1", "a"))
    g.add_edge(_edge("a", "b"))
    g.add_edge(_edge("b", "c"))
    assert g.descendants("person:c1") == 3


def test_reinforce_candidates_finds_weak_attachment_not_strong():
    g = Graph(ROOT)
    for n in (_node("x", 0.4), _node("x1"), _node("x2"), _node("x3"),
              _node("y", 0.9), _node("y1"), _node("y2"), _node("y3")):
        g.add_node(n)
    for src, dst in [("person:c1", "x"), ("x", "x1"), ("x1", "x2"), ("x2", "x3"),
                     ("person:c1", "y"), ("y", "y1"), ("y1", "y2"), ("y2", "y3")]:
        g.add_edge(_edge(src, dst))
    candidates = {n.id for n in g.reinforce_candidates()}
    assert "x" in candidates
    assert "y" not in candidates


def _evidence(source_class: str, url: str) -> Evidence:
    return Evidence(evidence_id=url, candidate_id="c1", url=url, snippet="s",
                    source_class=source_class, extraction_method="prose_llm")


def _claim(predicate: str, value: str, evidence: list[Evidence], *, ongoing: bool = False) -> Claim:
    temporal = Temporal(end_state="ongoing") if ongoing else Temporal()
    return Claim(id=value, predicate=predicate, value=value, value_raw=value, temporal=temporal,
                confidence=Confidence(score=0.9, logodds=2.0), identity_link="anchor_match:name",
                evidence=evidence)


def test_three_employment_claims_close_employment_history():
    claims = [
        _claim("employment", "acme.com", [_evidence("company_site", "https://acme.com")]),
        _claim("employment", "beta.com", [_evidence("company_site", "https://beta.com")]),
        _claim("employment", "gamma.com", [_evidence("company_site", "https://gamma.com")]),
    ]
    slots = Slots()
    slots.update(claims)
    assert slots.slots["employment_history"].current == 3
    assert slots.slots["employment_history"].closed is True


def test_title_claim_needs_two_independent_keys_for_current_role():
    one_key = [_claim("title", "CEO", [_evidence("press", "https://techcrunch.com/a")])]
    slots = Slots()
    slots.update(one_key)
    assert slots.slots["current_role"].current == 0
    assert slots.slots["current_role"].closed is False

    two_keys = [_claim("title", "CEO", [_evidence("press", "https://techcrunch.com/a"),
                                        _evidence("personal_site", "https://example.com/b")])]
    slots = Slots()
    slots.update(two_keys)
    assert slots.slots["current_role"].current == 1
    assert slots.slots["current_role"].closed is True


def test_unverified_probe_hit_needs_high_attachment_to_fill_contact():
    probe_evidence = Evidence(evidence_id="u", candidate_id="c1", url="https://github.com/andrew",
                              snippet="unverified username match", source_class="code_host",
                              extraction_method="username_probe")
    weak = _claim("handle", "andrew", [probe_evidence]).model_copy(update={"attachment_confidence": 0.45})
    slots = Slots()
    slots.update([weak])
    assert slots.slots["contact"].current == 0

    confirmed = weak.model_copy(update={"attachment_confidence": 0.85})
    slots = Slots()
    slots.update([confirmed])
    assert slots.slots["contact"].current == 1


def test_barren_three_times_closes_a_slot():
    slots = Slots()
    slots.barren(["education"])
    slots.barren(["education"])
    assert slots.slots["education"].closed is False
    slots.barren(["education"])
    assert slots.slots["education"].closed is True
    assert slots.slots["education"].barren_fetches == 3
