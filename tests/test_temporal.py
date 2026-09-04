"""plan/reference-confidence-scoring.md temporal rules."""
from __future__ import annotations

from datetime import date

from pi.score.temporal import parse_temporal
from pi.types import Temporal


def test_year_only_is_a_closed_range():
    t = parse_temporal("2019")
    assert t.start == date(2019, 1, 1) and t.end == date(2019, 12, 31)
    assert t.precision == "year" and t.end_state == "ended"


def test_month_range_present_is_ongoing():
    t = parse_temporal("Jan 2020 - Present")
    assert t.start == date(2020, 1, 1) and t.end is None
    assert t.end_state == "ongoing" and t.precision == "month"


def test_year_range_is_ended():
    t = parse_temporal("2019 – 2021")
    assert t.start == date(2019, 1, 1) and t.end == date(2021, 12, 31)
    assert t.end_state == "ended"


def test_relative_without_context_drops_dates_but_keeps_claim():
    assert parse_temporal("since 2 years ago") == Temporal()


def test_relative_with_context_resolves_year():
    t = parse_temporal("since 2 years ago", context_date=date(2025, 6, 1))
    assert t.start == date(2023, 1, 1)
