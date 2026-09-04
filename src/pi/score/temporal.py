"""Temporal parsing — string shape decides precision, never the model.

plan/reference-confidence-scoring.md "Temporal rules". Pure: no I/O, no LLM.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime

from ..types import Temporal

_RANGE_SEPS = [" - ", " – ", " — ", " to "]
_ONGOING_WORDS = {"present", "current", "now", "today", "ongoing"}
_PREFIXES = ("since ", "from ")

_YEAR_RE = re.compile(r"^\d{4}$")
_YM_RE = re.compile(r"^\d{4}-\d{2}$")
_YMD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REL_RE = re.compile(r"^(\d+)\s+years?(?:\s+ago)?$")


def _strip_prefix(tok: str) -> str:
    tok = tok.strip()
    low = tok.lower()
    for p in _PREFIXES:
        if low.startswith(p):
            return tok[len(p):].strip()
    return tok


def _parse_token(tok: str, context_date: date | None) -> tuple[date, date | None, str] | None:
    """(period_start, period_end_or_None, precision) for one date-like token, or None."""
    tok = _strip_prefix(tok)
    if _YMD_RE.match(tok):
        d = datetime.strptime(tok, "%Y-%m-%d").date()
        return d, None, "day"
    if _YM_RE.match(tok):
        y, m = (int(x) for x in tok.split("-"))
        last = calendar.monthrange(y, m)[1]
        return date(y, m, 1), date(y, m, last), "month"
    if _YEAR_RE.match(tok):
        y = int(tok)
        return date(y, 1, 1), date(y, 12, 31), "year"
    for fmt in ("%b %Y", "%B %Y"):
        try:
            d = datetime.strptime(tok, fmt).date()
        except ValueError:
            continue
        last = calendar.monthrange(d.year, d.month)[1]
        return date(d.year, d.month, 1), date(d.year, d.month, last), "month"
    m = _REL_RE.match(tok.lower())
    if m:
        if context_date is None:
            return None
        y = context_date.year - int(m.group(1))
        return date(y, 1, 1), date(y, 12, 31), "year"
    return None


def parse_temporal(raw: str | None, context_date: date | None = None) -> Temporal:
    if not raw or not raw.strip():
        return Temporal(context_date=context_date)

    s = raw.strip()
    a, b = s, None
    for sep in _RANGE_SEPS:
        if sep in s:
            a, b = (p.strip() for p in s.split(sep, 1))
            break

    if b is not None and b.lower() in _ONGOING_WORDS:
        parsed = _parse_token(a, context_date)
        if parsed is None:
            return Temporal(context_date=context_date)
        start, _end, precision = parsed
        return Temporal(start=start, end=None, end_state="ongoing", precision=precision,
                         context_date=context_date)

    if b is not None:
        pa, pb = _parse_token(a, context_date), _parse_token(b, context_date)
        if pa is None or pb is None:
            return Temporal(context_date=context_date)
        end = pb[1] if pb[1] is not None else pb[0]
        return Temporal(start=pa[0], end=end, end_state="ended", precision=pa[2],
                         context_date=context_date)

    parsed = _parse_token(a, context_date)
    if parsed is None:
        return Temporal(context_date=context_date)
    start, end, precision = parsed
    end_state = "ended" if end is not None else "unknown"
    return Temporal(start=start, end=end, end_state=end_state, precision=precision,
                     context_date=context_date)
