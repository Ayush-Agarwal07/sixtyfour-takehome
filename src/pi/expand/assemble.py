"""Extraction tuples → scored Claims + graph nodes/edges (EXPAND assembly step)."""
from __future__ import annotations

import hashlib
import re
from datetime import date

from ..score.canonical import canonicalize
from ..score.claim_score import score_claim
from ..score.temporal import parse_temporal
from ..sources import host_of
from ..types import Claim, Evidence, GraphEdge, GraphNode
from .extract import Tuple

_PREDICATES = {"employer", "title", "employment", "education", "location", "email", "phone", "website",
               "handle", "repo", "publication", "talk", "award", "funding_event", "board_or_advisor",
               "founded", "relationship", "other"}
_ORG_PREDICATES = {"employer", "employment", "founded"}


def _sha16(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "unknown"


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


def assemble(tuples: list[Tuple], *, url: str, text: str, cid: str, rung: str, source_class: str,
            identity_link: str, seed, today: date, method: str | None = None,
            attachment: float = 1.0) -> tuple[list[Claim], list[GraphNode], list[GraphEdge]]:
    claims: list[Claim] = []
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    seen_claim_ids: set[str] = set()
    seen_node_ids: set[str] = set()
    seen_edge_ids: set[str] = set()

    for predicate, value_raw, span, context_date_raw in tuples:
        if predicate not in _PREDICATES:
            continue
        value_raw = (value_raw or "").strip()
        if not value_raw:
            continue
        if rung == "prose_llm" and not _span_ok(span, text or ""):
            continue  # span not in page → drop (anti-fabrication)

        value = value_raw if predicate == "relationship" else canonicalize(predicate, value_raw, seed.org_domains)
        claim_id = _sha16(predicate + value + url)
        if claim_id in seen_claim_ids:
            continue
        seen_claim_ids.add(claim_id)

        parse_context = today if method == "github_emails" else None
        temporal = parse_temporal(context_date_raw, context_date=parse_context)
        if method == "wayback":
            temporal.context_date = today

        ev = Evidence(evidence_id=_sha16(url + span + value), candidate_id=cid, url=url,
                     snippet=(span or value)[:300], source_class=source_class,
                     extraction_method=method or rung)
        confidence = score_claim(source_class=source_class, rung=rung, predicate=predicate,
                                 has_context_date=temporal.context_date is not None or temporal.start is not None)
        claims.append(Claim(id=claim_id, predicate=predicate, value=value, value_raw=value_raw,
                            temporal=temporal, confidence=confidence, attachment_confidence=attachment,
                            identity_link=identity_link, evidence=[ev]))

        edge_id = _sha16(cid + value + url)
        if predicate in _ORG_PREDICATES:
            node_id = f"company:{value}"
            if node_id not in seen_node_ids:
                seen_node_ids.add(node_id)
                nodes.append(GraphNode(id=node_id, type="company", label=value_raw, depth=1,
                                       attachment_confidence=attachment))
            if edge_id not in seen_edge_ids:
                seen_edge_ids.add(edge_id)
                edges.append(GraphEdge(id=edge_id, src=f"person:{cid}", dst=node_id,
                                       type="ownership" if predicate == "founded" else "employment",
                                       mechanism=f"{method or rung} on {host_of(url)}",
                                       evidence_ids=[ev.evidence_id]))
        elif predicate == "relationship":
            kind, _, name = value_raw.partition(":")
            kind, name = kind.strip(), name.strip()
            node_id = f"person:unresolved:{_slug(name)}:{_sha16(url)[:8]}"
            if node_id not in seen_node_ids:
                seen_node_ids.add(node_id)
                nodes.append(GraphNode(id=node_id, type="person", label=name or value_raw, depth=1,
                                       attachment_confidence=attachment))
            if edge_id not in seen_edge_ids:
                seen_edge_ids.add(edge_id)
                edges.append(GraphEdge(id=edge_id, src=f"person:{cid}", dst=node_id, type="relationship",
                                       mechanism=kind, evidence_ids=[ev.evidence_id]))
        elif predicate in ("handle", "website"):
            node_id = f"account:{host_of(value) or value}:{value}"
            if node_id not in seen_node_ids:
                seen_node_ids.add(node_id)
                nodes.append(GraphNode(id=node_id, type="account", label=value_raw, depth=1,
                                       attachment_confidence=attachment))
            if edge_id not in seen_edge_ids:
                seen_edge_ids.add(edge_id)
                edges.append(GraphEdge(id=edge_id, src=f"person:{cid}", dst=node_id, type="affiliation",
                                       mechanism=f"{method or rung} on {host_of(url)}",
                                       evidence_ids=[ev.evidence_id]))

    return claims, nodes, edges
