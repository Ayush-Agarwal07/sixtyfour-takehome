"""census.surname_bucket: rare/uncommon/common by per-100k frequency, else not_found."""
from __future__ import annotations

from pi.understand.census import surname_bucket


def test_smith_is_common():
    assert surname_bucket("Smith") == "common"
    assert surname_bucket("smith") == "common"          # case-insensitive


def test_unlisted_surname_is_not_found():
    assert surname_bucket("Goering") == "not_found"
