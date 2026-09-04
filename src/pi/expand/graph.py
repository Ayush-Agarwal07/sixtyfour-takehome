"""Findings graph — nodes/edges rooted at the confirmed person.

Pure in-memory structure: root-to-node path is the provenance chain (root
depth 0). No I/O. Reinforce candidates (C7) are load-bearing nodes whose
attachment confidence is still weak.
"""
from __future__ import annotations

from collections import deque

from .. import constants
from ..types import GraphEdge, GraphNode


class Graph:
    def __init__(self, root: GraphNode) -> None:
        self.root_id = root.id
        self.nodes: dict[str, GraphNode] = {root.id: root}
        self.edges: dict[str, GraphEdge] = {}

    def add_node(self, n: GraphNode) -> None:
        existing = self.nodes.get(n.id)
        if existing is None:
            self.nodes[n.id] = n
            return
        existing.attachment_confidence = max(existing.attachment_confidence, n.attachment_confidence)

    def add_edge(self, e: GraphEdge) -> None:
        self.edges.setdefault(e.id, e)

    def children(self, node_id: str) -> list[str]:
        return [e.dst for e in self.edges.values() if e.src == node_id]

    def descendants(self, node_id: str) -> int:
        seen: set[str] = set()
        queue: deque[str] = deque(self.children(node_id))
        while queue:
            nid = queue.popleft()
            if nid in seen:
                continue
            seen.add(nid)
            queue.extend(self.children(nid))
        return len(seen)

    def set_attachment(self, node_id: str, value: float) -> None:
        if node_id in self.nodes:
            self.nodes[node_id].attachment_confidence = value

    def attachment(self, node_id: str) -> float:
        n = self.nodes.get(node_id)
        return n.attachment_confidence if n is not None else 1.0

    def reinforce_candidates(self) -> list[GraphNode]:
        return [n for nid, n in self.nodes.items() if nid != self.root_id
                and self.descendants(nid) >= constants.REINFORCE_MIN_DESCENDANTS
                and self.attachment(nid) < constants.REINFORCE_MAX_ATTACHMENT]

    def summary(self, limit: int = 25) -> list[dict]:
        return [{"id": n.id, "type": n.type, "label": n.label, "attachment": n.attachment_confidence}
                for n in list(self.nodes.values())[:limit]]

    def to_findings_lists(self) -> tuple[list[GraphNode], list[GraphEdge]]:
        return list(self.nodes.values()), list(self.edges.values())
