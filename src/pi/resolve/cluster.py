"""Cluster′ — SERP results → candidate people + floating evidence.

A candidate is seeded by an identity-bearing URL (linkedin.com/in/{slug},
github.com/{user}, x.com/{handle}, a personal site). Distinct keys are distinct
people until a verified link (reciprocal, co-citation, rare shared handle) says
otherwise. Press, company, academic, aggregator and unknown pages are NOT people;
they are floating evidence, attached to a candidate only by a link on a fetched
page, or to the sole candidate when there is exactly one. Never by surname.
"""
from __future__ import annotations

import re

from ..sources import classify, identity_key, identity_tier, is_rare_handle
from ..types import Candidate, Confidence, SourceText

_TOKEN = re.compile(r"[a-z0-9]+")
_IDENTITY_CLASSES = {"professional_network", "code_host", "social", "personal_site"}


def _name_forms(seed) -> list[str]:
    return [v.form for v in seed.names]


def _surname_tokens(seed) -> set[str]:
    toks: set[str] = set()
    for form in _name_forms(seed):
        parts = _TOKEN.findall(form.lower())
        if parts:
            toks.add(parts[-1])
            if len(parts) >= 2:
                toks.add(parts[0])      # order-swapped forms put the surname first
    return {t for t in toks if len(t) >= 3}


def _anchor_domains(seed) -> set[str]:
    out = set(seed.org_domains.values())
    out |= {o.lower() for o in seed.orgs if "." in o}
    return out


def cluster(results: list[dict], seed) -> tuple[list[Candidate], list[SourceText]]:
    names = _name_forms(seed)
    surnames = _surname_tokens(seed)
    anchors = _anchor_domains(seed)
    groups: dict[str, dict] = {}
    floating: list[SourceText] = []

    for r in results:
        url = r["url"]
        blob = f"{r.get('title', '')} — {r.get('snippet', '')}"
        if surnames and not r.get("force") and not any(t in blob.lower() for t in surnames):
            continue                                  # relevance floor (forced results bypass it)
        cls = classify(url, anchor_domains=anchors, names=names)
        src = SourceText(url=url, kind="snippet", source_class=cls, tier=identity_tier(cls), text=blob[:600])
        key = identity_key(url, names=names)
        if key and cls in _IDENTITY_CLASSES:
            ks = f"{key[0]}:{key[1]}"
            g = groups.setdefault(ks, {"urls": [], "sources": [], "keys": [ks], "handles": {key[0]: key[1]}})
            if url not in g["urls"]:
                g["urls"].append(url)
                g["sources"].append(src)
        else:
            floating.append(src)

    # C17: merge groups that share a RARE handle across platforms
    by_handle: dict[str, list[str]] = {}
    for ks, g in groups.items():
        for platform, handle in g["handles"].items():
            if platform != "site" and is_rare_handle(handle, names):
                by_handle.setdefault(handle, []).append(ks)
    merged_into: dict[str, str] = {}
    for handle, keys in by_handle.items():
        root = keys[0]
        for other in keys[1:]:
            root, other = merged_into.get(root, root), merged_into.get(other, other)
            if root == other:
                continue
            g, o = groups[root], groups[other]
            g["urls"] += [u for u in o["urls"] if u not in g["urls"]]
            g["sources"] += o["sources"]
            g["keys"] += o["keys"]
            g["handles"].update(o["handles"])
            merged_into[other] = root
            del groups[other]

    cands: list[Candidate] = []
    for i, (ks, g) in enumerate(groups.items(), 1):
        cands.append(Candidate(cid=f"c{i}", urls=g["urls"], identity_keys=g["keys"], handles=g["handles"],
                               sources=g["sources"], score=Confidence(score=0.0, logodds=0.0)))
    return cands, floating


def attach_floating(cands: list[Candidate], floating: list[SourceText]) -> list[SourceText]:
    """With exactly one candidate, floating evidence describes that person-hypothesis:
    attach it as evidence (never as a URL to expand). Otherwise keep it floating for
    co-citation after fetching. Returns what is still floating."""
    if len(cands) == 1:
        cands[0].sources.extend(floating)
        return []
    return floating


def candidate_from_floating(floating: list[SourceText]) -> Candidate | None:
    """No identity-bearing URL at all: the person may exist only on press/company
    pages. One candidate with no urls; evidence only."""
    ev = [s for s in floating if s.source_class != "aggregator"]
    if not ev:
        return None
    return Candidate(cid="c1", urls=[], identity_keys=[], sources=ev, score=Confidence(score=0.0, logodds=0.0))
