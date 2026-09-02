"""census.surname_bucket over the full 2010 table (162k rows)."""
from __future__ import annotations

from pi.understand.census import surname_bucket


def test_common_names_are_common():
    for n in ("Smith", "wang", "Chen", "Patel", "Nguyen"):
        assert surname_bucket(n) == "common", n


def test_rare_names_are_rare():
    for n in ("Goering", "Shalhoub", "Avci"):
        assert surname_bucket(n) == "rare", n


def test_uncommon_and_not_found():
    assert surname_bucket("Kowalski") == "uncommon"
    assert surname_bucket("Xqzvvbnm") == "not_found"
