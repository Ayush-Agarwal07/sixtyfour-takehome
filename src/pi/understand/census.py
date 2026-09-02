"""Phase 1 UNDERSTAND — pure, no-network surname-rarity lookup.

Buckets a surname by US-Census-style per-100k frequency: rare <10, uncommon
10-100, common >100, not_found when the surname is absent from the bundled
table. Feeds the surname-rarity term in plan/reference-identity-scoring.md via
constants.SURNAME_RARITY — this module only buckets; it does not score.
"""
from __future__ import annotations

import csv
from pathlib import Path

from ..constants import SURNAME_RARE_MAX, SURNAME_UNCOMMON_MAX

_CSV_PATH = Path(__file__).parent / "data" / "surnames.csv"


def _load(path: Path) -> dict[str, float]:
    with path.open(newline="") as f:
        return {row["surname"].strip().casefold(): float(row["per100k"])
                for row in csv.DictReader(f)}


# ponytail: loaded once at import time (stdlib csv, ~90 rows) — no lazy cache
# needed for a table this small.
_TABLE = _load(_CSV_PATH)


def surname_bucket(surname: str) -> str:
    """rare | uncommon | common | not_found, by per-100k frequency."""
    per100k = _TABLE.get(surname.strip().casefold())
    if per100k is None:
        return "not_found"
    if per100k < SURNAME_RARE_MAX:
        return "rare"
    if per100k <= SURNAME_UNCOMMON_MAX:
        return "uncommon"
    return "common"
