"""Regime′ classification — pure function, no I/O.

plan/reference-identity-scoring.md "Regime → prior & caps" table;
plan/design-decisions.md Regime′ row: a resolvable company domain → NAME_STRONG
by default, downgraded to NAME_WEAK only for the huge-company stoplist or an
unresolvable org.
"""
from __future__ import annotations

import re

from .. import constants
from ..types import Regime

_WORD = re.compile(r"[a-z0-9]+")


def is_huge_org(org: str) -> bool:
    """True if `org`'s slug contains a token on constants.HUGE_COMPANY_STOPLIST.

    Exposed so callers (understand.parse) don't have to reimplement the check.
    """
    tokens = set(_WORD.findall(org.lower()))
    return bool(tokens & constants.HUGE_COMPANY_STOPLIST)


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
    if role_description and not name:
        return "DEFINITE_DESC"
    if name and company_resolved and not org_is_huge:
        return "NAME_STRONG"
    if name and ((org and not company_resolved) or org_is_huge):
        return "NAME_WEAK"
    return "BARE_NAME"
