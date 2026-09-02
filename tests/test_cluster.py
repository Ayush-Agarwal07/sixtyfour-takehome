"""Cluster′: over-split, never merge two same-name people on a shared employer."""
from __future__ import annotations

from pi.resolve.cluster import cluster
from pi.types import Seed, Variant


def _seed():
    return Seed(input="sarah chen figma", regime="NAME_STRONG",
                names=[Variant(form="Sarah Chen")], orgs=["figma"], titles=["designer"])


def test_two_figma_sarah_chens_stay_separate():
    results = [
        {"url": "https://www.linkedin.com/in/sarah-chen-1", "title": "Sarah Chen", "snippet": "Product Designer at Figma"},
        {"url": "https://www.linkedin.com/in/sarah-chen-2", "title": "Sarah Chen", "snippet": "Designer, Figma"},
    ]
    cands = cluster(results, _seed())
    assert len(cands) == 2                          # shared "figma" token must NOT merge them


def test_surname_filter_drops_unrelated_and_picks_employer():
    results = [
        {"url": "https://www.linkedin.com/in/sarah-chen-1", "title": "Sarah Chen", "snippet": "Designer at Figma"},
        {"url": "https://www.zoominfo.com/p/Matthew-Shalhoub/1", "title": "Matthew Shalhoub", "snippet": "unrelated"},
    ]
    cands = cluster(results, _seed())
    assert len(cands) == 1 and "employer" in cands[0].attrs


def test_no_surname_match_yields_nothing():
    assert cluster([{"url": "https://x.io/y", "title": "nobody", "snippet": "nothing here"}], _seed()) == []
