"""Identity anchor set of the confirmed person + the deterministic same-person
test (DESIGN.md §13). Every new EXPAND source is scored against this set
before its claims attach to the confirmed person — never a model float.
"""
from __future__ import annotations

import re

from .. import constants
from ..score.claim_score import _sigmoid
from ..sources import host_of, registrable_domain
from .extract import handle_of

_CATS = ("employer", "school", "location", "handle", "email", "domain", "collaborator")
_EXPANDABLE = ("employer", "school", "location")
_SKIP_FIRST_WORD = {"university", "institute", "college", "school"}
_WEAK_WORDS = ("university", "college", "institute", "school", "hospital", "health", "department")
_TOKEN = re.compile(r"[a-z0-9]+")
_PLAIN = re.compile(r"[a-z0-9 ]+")


def _phrases(raw: str, cat: str) -> set[str]:
    p = (raw or "").strip().lower()
    if len(p) < 3:
        return set()
    out = {p}
    if cat not in _EXPANDABLE:
        return out          # never expand collaborator/handle/email/domain: "David Smith" must not yield "david"
    words = p.split()
    if len(words) > 1:
        # ponytail: first-word/pre-comma heuristics; upgrade = org alias table
        if len(words[0]) >= 5 and words[0] not in _SKIP_FIRST_WORD:
            out.add(words[0])
        pre_comma = p.split(",")[0].strip()
        if pre_comma != p and len(pre_comma) >= 5 and not any(w in pre_comma for w in _WEAK_WORDS):
            out.add(pre_comma)
    return out


def _hit(phrase: str, text: str) -> bool:
    if _PLAIN.fullmatch(phrase):
        return re.search(r"\b" + re.escape(phrase) + r"\b", text) is not None
    return phrase in text


class Anchors:
    """Identity anchor set of the confirmed person + the same-person test."""

    def __init__(self, seed, cand) -> None:
        self.names: list[list[str]] = [ts for v in seed.names
                                       if (ts := [t for t in _TOKEN.findall(v.form.lower()) if len(t) >= 2])]
        self.terms: dict[str, set[str]] = {c: set() for c in _CATS}
        self.raw: dict[str, list[str]] = {c: [] for c in _CATS}
        self.weak: set[str] = set()     # phrases shared by thousands of namesakes
        for org in list(seed.orgs) + list(seed.org_domains.values()):
            self._add("employer", org)
        for s in seed.schools:
            self._add("school", s)
        for loc in seed.locations:
            self._add("location", loc)
        for key, h in cand.handles.items():
            self._add("domain" if key == "site" else "handle", h)
        for ik in cand.identity_keys:
            plat, _, val = ik.partition(":")
            if plat == "site":
                self._add("domain", val)
            elif plat in ("linkedin", "github"):
                self._add("handle", val)
        for kind, val in seed.hard_ids.items():
            if kind == "email":
                self._add("email", val)
            elif kind == "url":
                h = handle_of(val)
                self._add("handle", h) if h else self._add("domain", host_of(val))

    def _add(self, cat: str, raw: str) -> None:
        if not raw:
            return
        self.raw[cat].append(raw)
        phrases = _phrases(raw, cat)
        self.terms[cat] |= phrases
        # school/location are always weak (shared by thousands); so is any org/employer
        # value naming a university/college/institute/school/hospital/health/department —
        # e.g. "Stanford" from "Stanford University" inherits the weakness of its raw value.
        if cat in ("school", "location") or any(w in raw.lower() for w in _WEAK_WORDS):
            self.weak |= phrases

    def grow(self, claims) -> None:
        """Only claims trusted enough (>= ATTACH_TRUSTED) grow the anchor set."""
        for c in claims:
            if c.attachment_confidence < constants.ATTACH_TRUSTED:
                continue
            if c.predicate in ("employer", "employment", "founded"):
                self._add("employer", c.value)
                self._add("employer", c.value_raw)
            elif c.predicate == "education":
                self._add("school", c.value)
            elif c.predicate == "location":
                self._add("location", c.value)
            elif c.predicate == "handle":
                h = handle_of(c.value)
                if h:
                    self._add("handle", h)
            elif c.predicate == "email":
                self._add("email", c.value)
            elif c.predicate == "website":
                self._add("domain", registrable_domain(host_of(c.value)))
            elif c.predicate == "relationship":
                self._add("collaborator", c.value_raw.partition(":")[2].strip())

    def score(self, text: str, *, url: str = "", owned: bool = False,
             linked: bool = False) -> tuple[float, list[str], bool]:
        body = (text or "").lower()[:40_000]
        low = (f"{url.lower()}\n{body}" if url else body)[:40_000]
        name_present = any(all(t in body for t in toks) for toks in self.names)
        # identity: the name, or the person's own email/personal domain, actually stated in
        # the body — a handle does NOT count (a probe hit's URL and a soft-404 body echo the
        # handle by construction, so it proves nothing about who the page is about).
        identity = name_present or any(_hit(p, body) for cat in ("email", "domain") for p in self.terms[cat])
        matched = sorted(cat for cat, phrases in self.terms.items() if any(_hit(p, low) for p in phrases))
        weights = []
        for cat in matched:
            strong = any(_hit(p, low) and p not in self.weak for p in self.terms[cat])
            weights.append(constants.ATTACH_PER_CATEGORY if strong else constants.ATTACH_PER_CATEGORY_WEAK)
        weights.sort(reverse=True)
        lo = (constants.ATTACH_PRIOR
              + (constants.ATTACH_NAME if identity else constants.ATTACH_NO_NAME)
              + sum(weights[: constants.ATTACH_CATEGORY_CAP])
              + (constants.ATTACH_OWNED if owned else 0.0)
              + (constants.ATTACH_LINKED_FROM_TRUSTED if linked else 0.0))
        p = _sigmoid(lo)
        if not identity and not owned:   # shared anchors + a link never outvote a missing name
            p = min(p, constants.ATTACH_NO_IDENTITY_CAP)
        return p, matched, identity
