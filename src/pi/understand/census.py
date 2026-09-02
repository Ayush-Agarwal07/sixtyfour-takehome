"""Surname rarity from the US 2010 Census surname table (occurrences per 100k).

Buckets: rare < SURNAME_RARE_MAX · common ≥ SURNAME_COMMON_MIN · uncommon between ·
not_found when absent (the table lists every surname with ≥100 US bearers, so an
absent name is either very rare in the US or non-US). Loaded once, lazily.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from ..constants import SURNAME_COMMON_MIN, SURNAME_RARE_MAX

_CSV_PATH = Path(__file__).parent / "data" / "surnames.csv"


@lru_cache(maxsize=1)
def _table() -> dict[str, float]:
    with _CSV_PATH.open(newline="") as f:
        return {row["surname"].strip().casefold(): float(row["per100k"])
                for row in csv.DictReader(f)}


def surname_per100k(surname: str) -> float | None:
    return _table().get(surname.strip().casefold())


def surname_bucket(surname: str) -> str:
    """rare | uncommon | common | not_found."""
    per100k = surname_per100k(surname)
    if per100k is None:
        return "not_found"
    if per100k < SURNAME_RARE_MAX:
        return "rare"
    if per100k >= SURNAME_COMMON_MIN:
        return "common"
    return "uncommon"
