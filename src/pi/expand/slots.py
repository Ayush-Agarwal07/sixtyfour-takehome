"""Coverage slots — what EXPAND still needs, recomputed from claims each batch."""
from __future__ import annotations

from .. import constants
from ..score.claim_score import independence_key
from ..types import Claim, Slot

_CONTACT_METHODS = {"gravatar", "github_emails", "json_ld"}
_CONTACT_CLASSES = {"company_site", "personal_site", "code_host"}


def _keys(c: Claim) -> set[tuple[str, str]]:
    return {independence_key(e) for e in c.evidence}


class Slots:
    def __init__(self) -> None:
        self.slots: dict[str, Slot] = {
            name: Slot(name=name, target=target) for name, target in constants.SLOT_TARGETS.items()
        }

    def _current_role_current(self, claims: list[Claim]) -> int:
        predicates = [p for p, sl in constants.PREDICATE_SLOTS.items() if "current_role" in sl]
        relevant = [c for c in claims if c.predicate in predicates]
        ongoing = [c for c in relevant if c.temporal.end_state == "ongoing" and len(_keys(c)) >= 2]
        if ongoing:
            return len({c.value for c in ongoing})
        # ponytail: when no claim is ongoing, fall back to the single best title
        # claim (by confidence) instead of counting every weakly-corroborated title.
        titles = [c for c in relevant if c.predicate == "title"]
        if titles:
            best = max(titles, key=lambda c: c.confidence.score)
            if len(_keys(best)) >= 2:
                return 1
        return 0

    def _contact_current(self, claims: list[Claim]) -> int:
        predicates = [p for p, sl in constants.PREDICATE_SLOTS.items() if "contact" in sl]
        values: set[str] = set()
        for c in claims:
            if c.predicate not in predicates:
                continue
            if c.attachment_confidence < 0.8:
                continue
            if any(e.extraction_method in _CONTACT_METHODS or e.source_class in _CONTACT_CLASSES
                   for e in c.evidence):
                values.add(c.value)
        return len(values)

    def _current_for(self, name: str, claims: list[Claim]) -> int:
        if name == "current_role":
            return self._current_role_current(claims)
        if name == "contact":
            return self._contact_current(claims)
        values: set[str] = set()
        for c in claims:
            if name in constants.PREDICATE_SLOTS.get(c.predicate, []):
                values.add(c.value)
        return len(values)

    def update(self, claims: list[Claim]) -> list[Slot]:
        changed: list[Slot] = []
        for slot in self.slots.values():
            new_current = self._current_for(slot.name, claims)
            if new_current > slot.current:
                slot.barren_fetches = 0     # productive: this batch filled the slot further
            new_closed = new_current >= slot.target or slot.barren_fetches >= constants.SLOT_BARREN_LIMIT
            if new_current != slot.current or new_closed != slot.closed:
                changed.append(slot)
            slot.current = new_current
            slot.closed = new_closed
        return changed

    def barren(self, slot_names: list[str]) -> None:
        for name in slot_names:
            slot = self.slots.get(name)
            if slot is None:
                continue
            slot.barren_fetches += 1
            slot.closed = slot.current >= slot.target or slot.barren_fetches >= constants.SLOT_BARREN_LIMIT

    def gap(self, name: str) -> float:
        slot = self.slots.get(name)
        if slot is None or slot.target == 0:
            return 0.0
        return max(0, slot.target - slot.current) / slot.target

    def all_closed(self) -> bool:
        return all(slot.closed for slot in self.slots.values())
