"""Canonicalize a claim value for grouping/merging. Predicate-aware, pure text.

plan/reference-confidence-scoring.md merge rules (§7).
"""
from __future__ import annotations

import re
import string

_PAREN_RE = re.compile(r"\([^)]*\)")
_LEGAL_SUFFIX_RE = re.compile(
    r"[\s,]*\b(?:inc|llc|ltd|corp|corporation|co|gmbh|plc)\.?$", re.IGNORECASE
)
_EDU_PREFIXES = ("the ", "university of ", "school of ")
_STRIP_CHARS = string.punctuation + " "
_TITLE_TABLE = str.maketrans("", "", string.punctuation.replace("&", ""))


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def canonicalize(predicate: str, value: str, org_domains: dict[str, str] | None = None) -> str:
    v = _norm(value)

    if predicate in ("employer", "employment", "founded"):
        v = re.sub(r"\s+", " ", _PAREN_RE.sub("", v)).strip()
        while True:
            nv = _LEGAL_SUFFIX_RE.sub("", v).strip()
            if nv == v:
                break
            v = nv
        v = v.strip(_STRIP_CHARS)
        if org_domains:
            for org, domain in org_domains.items():
                if org.lower().strip() == v or v == domain.split(".")[0].lower():
                    return domain
        return v

    if predicate == "education":
        changed = True
        while changed:
            changed = False
            for prefix in _EDU_PREFIXES:
                if v.startswith(prefix):
                    v = v[len(prefix):]
                    changed = True
        return v.strip(_STRIP_CHARS)

    if predicate == "title":
        v = v.translate(_TITLE_TABLE)
        return re.sub(r"\s+", " ", v).strip(_STRIP_CHARS)

    if predicate in ("email", "handle"):
        return v.lstrip("@").strip(_STRIP_CHARS)

    if predicate == "location":
        return v.split(",")[0].strip(_STRIP_CHARS)

    return v.strip(_STRIP_CHARS)
