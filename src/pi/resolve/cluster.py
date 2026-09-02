"""Cluster′ — SERP results → candidate people.

A person is keyed by their LinkedIn slug (one LinkedIn per person). Distinct slugs
= distinct people, so two same-name strangers stay split. But a single person's
other sites merge into them, and with no LinkedIn at all the name-matching results
are treated as one person — so we confirm someone with many sites instead of
tying their own profiles against each other. Attrs are string-matched from the
snippet (ponytail; a batched T4 match replaces this if string-matching proves crude).
"""
from __future__ import annotations

from urllib.parse import urlsplit

from .. import constants
from ..types import AttrObservation, Candidate, Confidence

AGGREGATORS = {
    "linkedin.com", "x.com", "twitter.com", "facebook.com", "instagram.com",
    "crunchbase.com", "zoominfo.com", "whitepages.com", "rocketreach.co",
    "wikipedia.org", "threads.net", "bloomberg.com",
}


def _host(u: str) -> str:
    return (urlsplit(u).hostname or "").lower().removeprefix("www.")


def _tier(url: str, employer_domain: str) -> tuple[str, float]:
    h = _host(url)
    if employer_domain and h.endswith(employer_domain):
        return "official_org", constants.ANCHOR_TIERS["official_org"]
    if h in ("linkedin.com", "x.com", "twitter.com"):
        return "professional_network_snippet", constants.ANCHOR_TIERS["professional_network_snippet"]
    if h == "github.com":
        return "self_published", constants.ANCHOR_TIERS["self_published"]
    if h in AGGREGATORS:
        return "aggregator", constants.ANCHOR_TIERS["aggregator"]
    return "self_published", constants.ANCHOR_TIERS["self_published"]   # personal-ish


def _mk_candidate(cid: str, group: dict, orgs: list[str], titles: list[str], emp_domain: str) -> Candidate:
    snip = " ".join(group["snips"]).lower()
    best_url = max(group["urls"], key=lambda u: _tier(u, emp_domain)[1])
    source_class, tier = _tier(best_url, emp_domain)
    attrs: dict[str, list[AttrObservation]] = {}
    for o in orgs:
        token = o.replace(".", " ").split()[0] if o else ""     # "ramp.com"/"sixtyfour ai" → "ramp"/"sixtyfour"
        if token and token in snip:
            attrs.setdefault("employer", []).append(AttrObservation(
                value=o, source_class=source_class, source_tier=tier,
                url=best_url, snippet=group["snips"][0][:200]))
            break
    for t in titles:
        if t and t in snip:
            attrs.setdefault("title", []).append(AttrObservation(
                value=t, source_class=source_class, source_tier=tier,
                url=best_url, snippet=group["snips"][0][:200]))
            break
    return Candidate(cid=cid, urls=group["urls"], attrs=attrs,
                     score=Confidence(score=0.0, logodds=0.0))


def cluster(results: list[dict], seed) -> list[Candidate]:
    surname = seed.names[0].form.split()[-1].lower() if seed.names else ""
    orgs = [o.lower() for o in seed.orgs]
    emp_domain = orgs[0] if (orgs and "." in orgs[0]) else ""
    titles = [t.lower() for t in seed.titles]

    linkedins: dict[str, dict] = {}
    main = {"urls": [], "snips": []}
    for r in results:
        blob = f"{r['title']} {r['snippet']}"
        if surname and surname not in blob.lower():          # relevance floor
            continue
        h, path = _host(r["url"]), urlsplit(r["url"]).path.strip("/")
        if h == "linkedin.com" and path.startswith("in/"):
            bucket = linkedins.setdefault(path.split("/", 2)[1], {"urls": [], "snips": []})
        else:
            bucket = main
        bucket["urls"].append(r["url"])
        bucket["snips"].append(blob)

    if len(linkedins) == 1:                                   # one person: LinkedIn + their other sites
        _, lb = next(iter(linkedins.items()))
        groups = [{"urls": lb["urls"] + main["urls"], "snips": lb["snips"] + main["snips"]}]
    elif len(linkedins) >= 2:                                 # distinct people; ambiguous `main` dropped
        groups = list(linkedins.values())
    elif main["urls"]:                                        # no LinkedIn: name-matching sites are one person
        groups = [main]
    else:
        groups = []

    return [_mk_candidate(f"c{i}", g, orgs, titles, emp_domain) for i, g in enumerate(groups, 1)]
