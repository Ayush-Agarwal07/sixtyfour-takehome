"""Phase 3 EXPAND — slice version: one batch, no planner (Stage 3 deepens this).

Reads the confirmed candidate's own pages (never floating evidence), extracts
claims via JSON-LD or span-checked prose LLM, files every Evidence under the
confirmed cid. Source class and claim tier come from pi.sources (one classifier).
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

import extruct
from pydantic import BaseModel, Field

from .. import constants
from ..sources import classify, claim_tier, is_unfetchable
from ..types import Claim, Confidence, Evidence, Findings, GraphNode, Term

_EXTRACT_PROMPT = (Path(__file__).resolve().parent.parent / "llm" / "prompts" / "extract.md").read_text()


def _sha16(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def _score(source_class: str, rung: str) -> Confidence:
    prior = constants.LOGODDS_PRIOR
    tier = claim_tier(source_class)
    rw = constants.EXTRACTION_RUNG.get(rung, 0.0)
    terms = [Term(factor="prior", weight=prior), Term(factor=f"source_tier:{source_class}", weight=tier)]
    if rung != "none":
        terms.append(Term(factor=f"extraction:{rung}", weight=rw))
    lo = sum(t.weight for t in terms)
    return Confidence(score=_sigmoid(lo), logodds=lo, terms=terms)


class _ExTuple(BaseModel):
    predicate: str
    value: str
    span: str = ""
    context_date: str | None = None


class _Extraction(BaseModel):
    tuples: list[_ExTuple] = Field(default_factory=list)
    links: list[dict] = Field(default_factory=list)
    reasoning: str = ""


def _extract_jsonld(html: str) -> list[tuple[str, str, str]]:
    try:
        data = extruct.extract(html, syntaxes=["json-ld"], uniform=True)
    except Exception:  # noqa: BLE001
        return []
    out: list[tuple[str, str, str]] = []
    for it in data.get("json-ld", []):
        t = it.get("@type", "")
        is_person = (isinstance(t, str) and t.lower() == "person") or (isinstance(t, list) and "Person" in t)
        if not is_person:
            continue
        jt = it.get("jobTitle")
        if isinstance(jt, str):
            out.append(("title", jt, jt))
        wf = it.get("worksFor")
        name = wf.get("name") if isinstance(wf, dict) else (wf if isinstance(wf, str) else None)
        if name:
            out.append(("employer", name, name))
    return out


def window_text(text: str, names: list[str], radius: int = 1500, cap: int = 24000) -> str:
    """C14: keep ±radius chars around each name-variant occurrence, capped."""
    if not text:
        return ""
    low = text.lower()
    spans: list[tuple[int, int]] = []
    for n in names[:4]:
        for m in re.finditer(re.escape(n.lower()), low):
            spans.append((max(0, m.start() - radius), min(len(text), m.end() + radius)))
    if not spans:
        return text[:cap]
    spans.sort()
    merged = [spans[0]]
    for a, b in spans[1:]:
        if a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    out = "\n…\n".join(text[a:b] for a, b in merged)
    return out[:cap]


async def _llm_extract(text: str, seed, url: str, llm) -> list[tuple[str, str, str]]:
    names = [v.form for v in seed.names]
    prompt = (f"Target: {seed.input}\nName variants: {', '.join(names[:4])}\n"
              f"Employer anchor: {seed.orgs[:1]} Title anchor: {seed.titles[:1]}\nPage: {url}\n\n"
              f"Text:\n{window_text(text, names)}")
    ex = await llm.complete("T3", prompt, _Extraction, phase="expand", system=_EXTRACT_PROMPT)
    return [(t.predicate, t.value, t.span) for t in ex.tuples]


def _span_ok(span: str, text: str) -> bool:
    if not span:
        return False
    if span.lower() in text.lower():
        return True
    try:
        from rapidfuzz import fuzz
        return fuzz.partial_ratio(span.lower(), text.lower()) >= 90
    except Exception:  # noqa: BLE001
        return False


def _assemble(tuples, url, text, cid, rung, employer_domain, identity_link: str = "anchor_match:name",
              names: list[str] | None = None) -> list[Claim]:
    sc = classify(url, anchor_domains={employer_domain} if employer_domain else None, names=names)
    claims = []
    seen: set[str] = set()
    for pred, value, span in tuples:
        if pred not in _PREDICATES or not value.strip():
            continue
        cid_key = _sha16(pred + value.lower().strip() + url)
        if cid_key in seen:
            continue
        seen.add(cid_key)
        if rung == "prose_llm" and not _span_ok(span, text or ""):
            continue  # span not in page → drop (anti-fabrication)
        ev = Evidence(evidence_id=_sha16(url + span + value), candidate_id=cid, url=url,
                      snippet=(span or value)[:300], source_class=sc, extraction_method=rung)
        claims.append(Claim(id=cid_key, predicate=pred,
                            value=value.lower().strip(), value_raw=value,
                            confidence=_score(sc, rung), identity_link=identity_link, evidence=[ev]))
    return claims


_PREDICATES = {"employer", "title", "employment", "education", "location", "email", "phone", "website",
               "handle", "repo", "publication", "talk", "award", "funding_event", "board_or_advisor",
               "founded", "relationship", "other"}


def _email_employer_claim(seed, cid) -> Claim:
    """The email domain is a user-supplied hard id, not a page. Scored honestly:
    prior + seed tier, no extraction rung. Not a specialization payoff."""
    dom = seed.orgs[0]
    email = seed.hard_ids.get("email", "")
    ev = Evidence(evidence_id=_sha16("email" + dom), candidate_id=cid, url=f"mailto:{email}",
                  snippet=f"input email is at domain {dom}", source_class="seed", extraction_method="none")
    return Claim(id=_sha16("employer" + dom), predicate="employer", value=dom, value_raw=dom,
                 confidence=_score("seed", "none"), identity_link="hard_key:email", evidence=[ev])


async def _read_page(url: str, deps) -> dict | None:
    try:
        return await deps.exa.contents(url) if is_unfetchable(url) else await deps.fetch.get(url)
    except Exception:  # noqa: BLE001
        return None


def _identity_link_for(seed, cand, url: str) -> str:
    if seed.regime == "HARD_ID_URL" and url.rstrip("/").lower() in {u.rstrip("/").lower() for u in seed.hard_ids.values()}:
        return "hard_key:seed_url"
    if cand.reciprocal:
        return "hard_key:reciprocal_link"
    attrs = [a for a, obs in cand.attrs.items() if obs]
    return "anchor_match:" + ",".join(attrs) if attrs else "anchor_match:name"


async def expand(resolution, seed, deps, llm) -> Findings:
    cid = resolution.confirmed_cid
    cand = next(c for c in resolution.candidates if c.cid == cid)
    org = seed.orgs[0] if seed.orgs else ""
    employer_domain = seed.org_domains.get(org, org if "." in org else "")
    names = [v.form for v in seed.names]
    label = names[0] if names else seed.input
    nodes = [GraphNode(id=f"person:{cid}", type="person", label=label)]
    claims: list[Claim] = []

    if seed.regime == "HARD_ID_EMAIL" and seed.orgs:
        claims.append(_email_employer_claim(seed, cid))

    for url in cand.urls[:3]:                     # the person's own pages only
        page = await _read_page(url, deps)
        if not page or not page.get("text"):
            continue
        tuples = _extract_jsonld(page["html"]) if page.get("html") else []
        rung = "json_ld"
        if not tuples:
            tuples = await _llm_extract(page["text"], seed, url, llm)
            rung = "prose_llm"
        claims += _assemble(tuples, url, page["text"], cid, rung, employer_domain,
                            identity_link=_identity_link_for(seed, cand, url), names=names)
        if tuples:
            break                                 # one productive read is enough for the slice

    return Findings(nodes=nodes, claims=claims, stop_reason="slice_one_batch")
