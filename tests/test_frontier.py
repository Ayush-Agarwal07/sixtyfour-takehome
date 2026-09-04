"""Frontier item generation, ranking, and reinforce/skip bookkeeping — pure, no I/O."""
from __future__ import annotations

from pi.expand.frontier import Frontier
from pi.expand.graph import Graph
from pi.expand.slots import Slots
from pi.types import Candidate, Confidence, FrontierItem, GraphEdge, GraphNode, Seed, Variant


def _seed(**kw) -> Seed:
    kw.setdefault("input", "andrew doe")
    kw.setdefault("regime", "NAME_STRONG")
    kw.setdefault("names", [Variant(form="Andrew Doe")])
    return Seed(**kw)


def _cand(**kw) -> Candidate:
    kw.setdefault("cid", "c1")
    kw.setdefault("score", Confidence(score=0.9, logodds=2.0))
    return Candidate(**kw)


def test_seed_produces_a_fetch_per_url_and_gravatar_and_wayback():
    cand = _cand(urls=["https://example.com/andrew", "https://sub.example.org/andrew"])
    seed = _seed(hard_ids={"email": "andrew@acme.com"})
    f = Frontier()
    f.seed(cand, seed, exa_ok=True, github_ok=True, anchor_domains={"acme.com"})

    fetch_urls = {i.args["url"] for i in f.items.values() if i.action == "fetch"}
    assert "https://example.com/andrew" in fetch_urls
    assert "https://sub.example.org/andrew" in fetch_urls

    gravatar_items = [i for i in f.items.values() if i.action == "gravatar"]
    assert len(gravatar_items) == 1 and gravatar_items[0].args["email"] == "andrew@acme.com"

    wayback_items = [i for i in f.items.values() if i.action == "wayback"]
    assert len(wayback_items) == 1 and wayback_items[0].args["url"] == "https://acme.com"


def test_from_links_footer_gets_lower_relevance_and_drops_aggregator():
    f = Frontier()
    links = [
        ("https://example.com/other", "other", "footer"),
        ("https://crunchbase.com/person/x", "cb", "prose"),
    ]
    # parent_attachment 1.5 so the footer item (× SECTION_MULT["footer"]=0.2) lands
    # exactly at FRONTIER_RELEVANCE_FLOOR (0.3) and is still kept, not dropped.
    f.from_links("https://example.com/page", links, 1.5, names=[], anchor_domains=None, exa_ok=True)
    kept = list(f.items.values())
    assert len(kept) == 1
    assert kept[0].args["url"] == "https://example.com/other"
    assert abs(kept[0].relevance - 0.3) < 1e-9


def _reinforce_graph() -> Graph:
    root = GraphNode(id="person:c1", type="person", label="Andrew")
    g = Graph(root)
    g.add_node(GraphNode(id="company:acme.com", type="company", label="Acme", attachment_confidence=0.4))
    for i in range(3):
        g.add_node(GraphNode(id=f"leaf{i}", type="account", label=f"leaf{i}"))
        g.add_edge(GraphEdge(id=f"e{i}", src="company:acme.com", dst=f"leaf{i}", type="affiliation",
                             mechanism="test"))
    g.add_edge(GraphEdge(id="root-edge", src="person:c1", dst="company:acme.com", type="employment",
                         mechanism="test"))
    return g


def test_rank_puts_reinforce_first_and_closed_slot_last():
    f = Frontier()
    graph = _reinforce_graph()
    f.reinforce(graph)

    open_item = FrontierItem(id=f.key("fetch", {"url": "https://foo.com"}), action="fetch",
                             args={"url": "https://foo.com"}, origin="link", open_slot="education",
                             relevance=0.9, why="x")
    closed_item = FrontierItem(id=f.key("fetch", {"url": "https://bar.com"}), action="fetch",
                               args={"url": "https://bar.com"}, origin="link", open_slot="employment_history",
                               relevance=0.9, why="x")
    f.add(open_item)
    f.add(closed_item)

    slots = Slots()
    slots.slots["employment_history"].current = 3
    slots.slots["employment_history"].closed = True

    ranked = f.rank(slots)
    assert ranked[0][0].origin == "reinforce"
    assert ranked[-1][0].id == closed_item.id


def test_forced_returns_reinforce_item_after_two_skips():
    f = Frontier()
    graph = _reinforce_graph()
    f.reinforce(graph)
    reinforce_id = next(i.id for i in f.items.values() if i.origin == "reinforce")

    assert f.forced() == []
    f.skipped([reinforce_id])
    f.skipped([reinforce_id])
    forced = f.forced()
    assert len(forced) == 1 and forced[0].id == reinforce_id


def test_add_dedupes_an_identical_action():
    f = Frontier()
    item = FrontierItem(id=f.key("fetch", {"url": "https://x.com"}), action="fetch",
                        args={"url": "https://x.com"}, origin="link", open_slot=None, relevance=0.5, why="a")
    same_action_item = FrontierItem(id=f.key("fetch", {"url": "https://x.com"}), action="fetch",
                                    args={"url": "https://x.com"}, origin="link", open_slot=None,
                                    relevance=0.7, why="b")
    f.add(item)
    f.add(same_action_item)
    assert len(f.items) == 1


def test_class_of_maps_new_actions_to_code_host_and_academic():
    from pi.expand.frontier import _class_of

    probe = FrontierItem(id="1", action="username_probe", args={"handle": "x"}, origin="link",
                         relevance=0.5, why="w")
    code = FrontierItem(id="2", action="github_code", args={"q": "x"}, origin="link", relevance=0.5, why="w")
    oa = FrontierItem(id="3", action="openalex", args={"name": "x"}, origin="link", relevance=0.5, why="w")
    assert _class_of(probe) == "code_host"
    assert _class_of(code) == "code_host"
    assert _class_of(oa) == "academic"


def test_seed_adds_linkedin_template_only_when_no_linkedin_key_and_exa():
    f = Frontier()
    f.seed(_cand(identity_keys=["github:adoe"]), _seed(), exa_ok=True, github_ok=True, anchor_domains=set())
    assert any("site:linkedin.com/in" in i.args.get("q", "") for i in f.items.values())
    g = Frontier()
    g.seed(_cand(identity_keys=["linkedin:andrew-doe"]), _seed(), exa_ok=True, github_ok=True, anchor_domains=set())
    assert not any("site:linkedin.com/in" in i.args.get("q", "") for i in g.items.values())
