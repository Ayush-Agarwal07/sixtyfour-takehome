"""Phase 3 EXPAND — slice version: one batch, no planner.

ponytail: the slice takes the confirmed candidate's URLs, emits a free employer
claim from the email domain, and fetches until ONE page yields facts. Frontier,
planner, graph growth, wow-sources land in Stage 3. Span-checked prose is kept —
it's the anti-fabrication guard, not a nicety.
"""
from __future__ import annotations

import hashlib
import math
from urllib.parse import urlsplit

import extruct
from pydantic import BaseModel

from .. import constants
from ..types import Claim, Confidence, Evidence, Findings, GraphNode, Term


def _sha16(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def _source_class(url: str, employer_domain: str = "") -> str:
    h = (urlsplit(url).hostname or "").lower()
    if "github" in h:
        return "self_published"
    if employer_domain and h.endswith(employer_domain):
        return "official_org"
    return "reputable_secondary"


def _score(source_class: str, rung: str) -> Confidence:
    prior = constants.LOGODDS_PRIOR
    tier = constants.CLAIM_SOURCE_TIERS.get(source_class, 0.2)
    rw = constants.EXTRACTION_RUNG.get(rung, 0.0)
    lo = prior + tier + rw
    return Confidence(score=_sigmoid(lo), logodds=lo, terms=[
        Term(factor="prior", weight=prior),
        Term(factor=f"source_tier:{source_class}", weight=tier),
        Term(factor=f"extraction:{rung}", weight=rw)])


class _ExTuple(BaseModel):
    predicate: str
    value: str
    span: str = ""


class _Extraction(BaseModel):
    tuples: list[_ExTuple] = []


def _extract_jsonld(html: str) -> list[tuple[str, str, str]]:
    try:
        data = extruct.extract(html, syntaxes=["json-ld"], uniform=True)
    except Exception:
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


def _llm_extract(text: str, seed, url: str, llm) -> list[tuple[str, str, str]]:
    prompt = (f"Target: {seed.input}\nPage: {url}\n\nText:\n{text[:6000]}\n\n"
              "Extract facts about the TARGET only (not other people). For each, copy a "
              "verbatim `span` from the text that supports it. Predicates: employer, title, "
              "education, location, website, handle, repo, publication, award. "
              'Return {"tuples":[{"predicate":"...","value":"...","span":"..."}]}.')
    ex = llm.complete("T3", prompt, _Extraction, phase="expand")
    return [(t.predicate, t.value, t.span) for t in ex.tuples]


def _assemble(tuples, url, text, cid, rung, employer_domain) -> list[Claim]:
    sc = _source_class(url, employer_domain)
    claims = []
    for pred, value, span in tuples:
        if rung == "prose_llm" and span and span.lower() not in (text or "").lower():
            continue  # span not in page → drop (anti-fabrication)
        ev = Evidence(evidence_id=_sha16(url + span + value), candidate_id=cid, url=url,
                      snippet=(span or value)[:300], source_class=sc, extraction_method=rung)
        claims.append(Claim(id=_sha16(pred + value + url), predicate=pred,
                            value=value.lower().strip(), value_raw=value,
                            confidence=_score(sc, rung), identity_link="anchor_match:name",
                            evidence=[ev]))
    return claims


def _email_employer_claim(seed, cid) -> Claim:
    dom = seed.orgs[0]
    email = seed.hard_ids.get("email", "")
    ev = Evidence(evidence_id=_sha16("email" + dom), candidate_id=cid, url=f"mailto:{email}",
                  snippet=f"email address at domain {dom}", source_class="official_org",
                  extraction_method="email_domain")
    return Claim(id=_sha16("employer" + dom), predicate="employer", value=dom, value_raw=dom,
                 confidence=_score("official_org", "json_ld"),
                 identity_link="hard_key:email", evidence=[ev])


async def _read_page(url: str, deps) -> dict | None:
    """httpx for normal hosts, Exa contents for unfetchable ones (LinkedIn/X/…)."""
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    unfetchable = any(host == h or host.endswith("." + h) for h in constants.UNFETCHABLE_HOSTS)
    try:
        return await deps.exa.contents(url) if unfetchable else await deps.fetch.get(url)
    except Exception:
        return None


async def expand(resolution, seed, deps, llm) -> Findings:
    cid = resolution.confirmed_cid
    cand = resolution.candidates[0]
    employer_domain = seed.orgs[0] if seed.orgs else ""
    label = seed.names[0].form if seed.names else seed.input
    nodes = [GraphNode(id=f"person:{cid}", type="person", label=label)]
    claims: list[Claim] = []

    if seed.regime == "HARD_ID_EMAIL" and seed.orgs:
        claims.append(_email_employer_claim(seed, cid))

    for url in cand.urls[:3]:                     # ≤3 reads; httpx or Exa per host
        page = await _read_page(url, deps)
        if not page or not page["text"]:
            continue
        tuples = _extract_jsonld(page["html"]) if page["html"] else []
        rung = "json_ld"
        if not tuples:
            tuples = _llm_extract(page["text"], seed, url, llm)
            rung = "prose_llm"
        claims += _assemble(tuples, url, page["text"], cid, rung, employer_domain)
        if tuples:
            break                                 # one productive read is enough for the slice

    return Findings(nodes=nodes, claims=claims, stop_reason="slice_one_batch")
