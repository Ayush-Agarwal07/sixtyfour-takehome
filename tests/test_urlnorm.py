"""Stage 0 gate: url normalization, including the 'keep unknown param' case."""
from __future__ import annotations

from pi.store.urlnorm import normalize_url


def test_scheme_www_fragment_trailing_slash():
    assert normalize_url("http://www.Example.com/path/#section") == "https://example.com/path"


def test_tracking_params_stripped_unknown_kept():
    norm = normalize_url("https://example.com/a?utm_source=x&id=42&fbclid=zz")
    assert "utm_source" not in norm and "fbclid" not in norm
    assert "id=42" in norm  # unknown param KEPT (blocklist, not allowlist)


def test_remaining_params_sorted_stable():
    a = normalize_url("https://example.com/a?b=2&a=1")
    b = normalize_url("https://example.com/a?a=1&b=2")
    assert a == b == "https://example.com/a?a=1&b=2"


def test_equivalent_urls_collapse():
    a = normalize_url("http://www.Example.com/p/?utm_medium=e#x")
    b = normalize_url("https://example.com/p")
    assert a == b
