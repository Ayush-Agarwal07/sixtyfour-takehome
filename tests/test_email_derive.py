"""Stage 1: email derivation + the hard-ID parse path."""
from __future__ import annotations

from pi.understand.email_derive import derive_from_email
from pi.understand.parse import parse_input


def test_andrew_goering_first_last():
    d = derive_from_email("andrew.goering@ramp.com")
    assert d.domain == "ramp.com"
    top = d.hypotheses[0]
    assert top.first == "andrew" and top.last == "goering" and top.form == "exact"


def test_jsmith_is_initials():
    d = derive_from_email("jsmith@ramp.com")
    forms = {(h.first_initial, h.last, h.form) for h in d.hypotheses}
    assert ("j", "smith", "initials") in forms


def test_trailing_digits_stripped():
    d = derive_from_email("sarah.chen42@example.io")
    assert d.hypotheses[0].last == "chen"


def test_parse_email_regime():
    s = parse_input("andrew.goering@ramp.com")
    assert s.regime == "HARD_ID_EMAIL"
    assert s.hard_ids["email"] == "andrew.goering@ramp.com"
    assert "ramp.com" in s.orgs
    assert any("Andrew" in v.form for v in s.names)


def test_parse_profile_url_regime():
    s = parse_input("https://linkedin.com/in/andrew-goering")
    assert s.regime == "HARD_ID_URL"
    assert "linkedin" in s.hard_ids


def test_parse_bare_name_never_crashes():
    s = parse_input("some random person")
    assert s.regime == "BARE_NAME" and s.names
