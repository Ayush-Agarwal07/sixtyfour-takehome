"""Property test: generate_variants never invents characters.

"Never invents" means: every alphabetic character in every returned variant
traces back either to the input itself, or to a `nicknames`-package lookup on
one of the input's own tokens (a real nickname/formal-name pair like
Bob/Robert differs in letters by definition — that's a bounded, grounded
lookup, not fabrication; see the CRITICAL INVARIANT docstring in variants.py).
No middle names, no invented handles, no chosen-out-of-thin-air English names.
"""
from __future__ import annotations

from nicknames import NickNamer
from unidecode import unidecode

from pi.understand.variants import generate_variants

_NICKNAMER = NickNamer()


def _letters(s: str) -> set[str]:
    return {c for c in unidecode(s).casefold() if c.isalpha()}


def _allowed_letters(name: str) -> set[str]:
    allowed = _letters(name)
    for tok in name.split():
        base = unidecode(tok).casefold()
        for related in _NICKNAMER.nicknames_of(base) | _NICKNAMER.canonicals_of(base):
            allowed |= _letters(related)
    return allowed


def test_diacritic_name_no_fabricated_characters():
    name = "José Núñez"
    allowed = _allowed_letters(name)
    variants = generate_variants(name)
    assert variants
    for v in variants:
        assert _letters(v.form) <= allowed, f"fabricated letters in {v.form!r}"


def test_nickname_name_no_fabrication_order_swap_and_expansion():
    name = "Bob Smith"
    allowed = _allowed_letters(name)
    variants = generate_variants(name)
    forms = [v.form for v in variants]

    for v in variants:
        assert _letters(v.form) <= allowed, f"fabricated letters in {v.form!r}"

    # order swap (given-name-last) present for a 2-token name
    assert any(f.casefold() == "smith bob" for f in forms)

    # nickname expansion produced at least one extra form for "Bob"
    assert any("robert" in f.casefold() for f in forms)

    # every Variant carries weight 0.0 — scoring is downstream
    assert all(v.weight == 0.0 for v in variants)
