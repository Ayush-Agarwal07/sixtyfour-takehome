"""Regime′ classification — pure function, no I/O.

Resolvable company → NAME_STRONG; huge-company stoplist or unresolvable org →
NAME_WEAK; role-only input → DEFINITE_DESC only when the role is definite
(CTO, founder, head of …); otherwise BARE_NAME and the resolver abstains typed.
"""
from __future__ import annotations

import re

from .. import constants
from ..types import Regime

_WORD = re.compile(r"[a-z0-9-]+")


def is_huge_org(org: str) -> bool:
    tokens = set(_WORD.findall(org.lower()))
    return bool(tokens & constants.HUGE_COMPANY_STOPLIST)


def is_definite_role(text: str | None) -> bool:
    """True for roles that name at most one or two people at an org."""
    if not text:
        return False
    t = text.lower()
    tokens = _WORD.findall(t)
    if any(tok in constants.DEFINITE_ROLES for tok in tokens):
        return True
    if re.search(r"\bchief\s+\w+\s+officer\b", t) or re.search(r"\b(head|vp|director)\s+of\b", t):
        return True
    return False


def classify(
    *,
    name: str | None,
    org: str | None,
    title: str | None,
    role_description: str | None,
    hard_ids: dict,
    company_resolved: bool,
    org_is_huge: bool,
) -> Regime:
    if hard_ids.get("email"):
        return "HARD_ID_EMAIL"
    if any(k in hard_ids for k in ("linkedin", "github", "x")):
        return "HARD_ID_URL"
    if not name:
        role = role_description or title
        if role and org and is_definite_role(role):
            return "DEFINITE_DESC"
        return "BARE_NAME"          # no name, no definite role → resolver abstains typed
    if company_resolved and not org_is_huge:
        return "NAME_STRONG"
    if org:
        return "NAME_WEAK"
    return "BARE_NAME"
