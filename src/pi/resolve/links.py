"""Identity links over fetched pages (C19/C21/A1).

- A candidate's own page (personal_site/code_host) linking another candidate's
  identity key → merge (self-published pages point at their owner's other profiles);
  mutual links → `reciprocal` (+3.0).
- A floating official/self-published page linking a candidate's profile →
  `anchored_one_way` (+1.5); linking two candidates near the name → co-citation merge.
"""
from __future__ import annotations

import uuid
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from ..sources import classify, identity_key
from ..trace.events import Merge
from ..types import Candidate, Link

_SECTION_TAGS = {"nav": "nav", "footer": "footer", "aside": "sidebar", "header": "nav"}
_CO_CITE_CLASSES = {"company_site", "personal_site", "academic", "government_registry"}


def extract_links(html: str, base_url: str) -> list[tuple[str, str, str]]:
    if not html:
        return []
    try:
        tree = HTMLParser(html)
    except Exception:  # noqa: BLE001
        return []
    out: list[tuple[str, str, str]] = []
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        section = "prose"
        p = a.parent
        while p is not None:
            if p.tag in _SECTION_TAGS:
                section = _SECTION_TAGS[p.tag]
                break
            p = p.parent
        out.append((urljoin(base_url, href), (a.text() or "").strip()[:80], section))
    return out


def _key_index(cands: list[Candidate]) -> dict[str, Candidate]:
    return {k: c for c in cands for k in c.identity_keys}


def merge(into: Candidate, other: Candidate, cands: list[Candidate], reason: str, deps) -> None:
    into.urls += [u for u in other.urls if u not in into.urls]
    into.identity_keys += [k for k in other.identity_keys if k not in into.identity_keys]
    into.handles.update(other.handles)
    into.sources += other.sources
    into.merged_from.append(other.cid)
    into.merged_from += other.merged_from
    if other.cid in [c.cid for c in cands]:
        cands.remove(other)
    if deps.trace:
        deps.trace.emit(Merge(event_id=uuid.uuid4().hex[:16], phase="resolve",
                              from_cid=other.cid, to_cid=into.cid, reason=reason))


def apply_page_links(page: dict, owner: Candidate | None, cands: list[Candidate], links: list[Link],
                     linked: dict[str, set[str]], deps, *, names: list[str], anchor_domains: set[str]) -> None:
    """Process one fetched page. `owner` is the candidate whose page this is, or
    None for a floating page. `linked[cid]` accumulates keys linked from each
    candidate's own pages for the reciprocal test."""
    page_url = page.get("final_url") or page["url"]
    page_cls = classify(page_url, anchor_domains=anchor_domains, names=names)
    idx = _key_index(cands)
    cited: list[Candidate] = []
    for url, _text, section in extract_links(page.get("html", ""), page_url):
        key = identity_key(url, names=names)
        if not key:
            continue
        ks = f"{key[0]}:{key[1]}"
        target = idx.get(ks)
        if owner is not None:
            if target is None or target is owner or ks in owner.identity_keys:
                continue
            linked.setdefault(owner.cid, set()).add(ks)
            links.append(Link(from_url=page_url, to_url=url, mechanism="one_way", section=section))
            if page_cls in ("personal_site", "code_host"):
                # a self-published page names its owner's other profile
                mutual = any(k in linked.get(target.cid, set()) for k in owner.identity_keys)
                owner.reciprocal = owner.reciprocal or mutual
                owner.anchored_one_way = True
                merge(owner, target, cands, f"{'reciprocal' if mutual else 'self-published'} link {page_url} → {url}", deps)
                idx = _key_index(cands)
        else:
            if target is None:
                continue
            if page_cls in _CO_CITE_CLASSES:
                target.anchored_one_way = True
                links.append(Link(from_url=page_url, to_url=url, mechanism="anchored_one_way", section=section))
                if target not in cited:
                    cited.append(target)
            else:
                links.append(Link(from_url=page_url, to_url=url, mechanism="one_way", section=section))
    # co-citation on an official/self-published page → same person
    if owner is None and len(cited) >= 2:
        root = cited[0]
        for other in cited[1:]:
            if other in cands and other is not root:
                merge(root, other, cands, f"co-citation on {page_url}", deps)
