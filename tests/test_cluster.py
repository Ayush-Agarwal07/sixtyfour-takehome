"""Cluster′: identity keys only. Never merge two same-name people on a shared employer."""
from __future__ import annotations

from pi.resolve.cluster import attach_floating, cluster
from pi.types import Seed, Variant


def _seed(**kw):
    base = dict(input="sarah chen figma", regime="NAME_STRONG", names=[Variant(form="Sarah Chen")],
                orgs=["figma"], titles=["product designer"], org_domains={"figma": "figma.com"})
    base.update(kw)
    return Seed(**base)


def test_two_figma_sarah_chens_stay_separate():
    results = [
        {"url": "https://www.linkedin.com/in/sarah-chen-1", "title": "Sarah Chen", "snippet": "Product Designer at Figma"},
        {"url": "https://www.linkedin.com/in/sarah-chen-2", "title": "Sarah Chen", "snippet": "Designer, Figma"},
    ]
    cands, floating = cluster(results, _seed())
    assert len(cands) == 2 and floating == []


def test_aggregators_and_press_are_floating_not_people():
    results = [
        {"url": "https://www.linkedin.com/in/sarah-chen-1", "title": "Sarah Chen", "snippet": "Designer at Figma"},
        {"url": "https://www.zoominfo.com/p/Sarah-Chen/1", "title": "Sarah Chen", "snippet": "Figma"},
        {"url": "https://techcrunch.com/x", "title": "Figma hires Sarah Chen", "snippet": "..."},
        {"url": "https://www.zoominfo.com/p/Matthew-Shalhoub/1", "title": "Matthew Shalhoub", "snippet": "unrelated"},
    ]
    cands, floating = cluster(results, _seed())
    assert [c.urls for c in cands] == [["https://www.linkedin.com/in/sarah-chen-1"]]
    assert {s.source_class for s in floating} == {"aggregator", "press"}   # Shalhoub dropped by relevance floor


def test_single_candidate_attaches_floating_as_evidence_not_urls():
    results = [
        {"url": "https://www.linkedin.com/in/sarah-chen-1", "title": "Sarah Chen", "snippet": "Designer at Figma"},
        {"url": "https://www.figma.com/team", "title": "Team", "snippet": "Sarah Chen, product designer"},
    ]
    cands, floating = cluster(results, _seed())
    left = attach_floating(cands, floating)
    assert left == [] and len(cands[0].sources) == 2 and cands[0].urls == ["https://www.linkedin.com/in/sarah-chen-1"]
    assert cands[0].sources[1].source_class == "company_site"


def test_rare_handle_merges_across_platforms_common_does_not():
    results = [
        {"url": "https://github.com/schen-designs", "title": "schen-designs (Sarah Chen)", "snippet": "designer"},
        {"url": "https://x.com/schen-designs", "title": "Sarah Chen", "snippet": "figma"},
        {"url": "https://github.com/sarah", "title": "sarah (Sarah Chen)", "snippet": "x"},
        {"url": "https://x.com/sarah", "title": "Sarah Chen", "snippet": "y"},
    ]
    cands, _ = cluster(results, _seed())
    keys = sorted(tuple(sorted(c.identity_keys)) for c in cands)
    assert ("github:schen-designs", "x:schen-designs") in keys
    assert ("github:sarah",) in keys and ("x:sarah",) in keys
