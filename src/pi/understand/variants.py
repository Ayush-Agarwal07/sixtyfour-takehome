"""Phase 1 UNDERSTAND — pure, no-network name-variant generation.

Forms: as-given, diacritic-strip, initials, order-swap (2 tokens), nickname
expansion (`nicknames` package). Each Variant records its `kind` so scoring can
apply constants.NAME_FORM. No fabrication: a variant may contain only characters
from the input or from a `nicknames` table lookup on an input token. Never middle
names, handles, or chosen English names.
"""
from __future__ import annotations

from nicknames import NickNamer
from unidecode import unidecode

from ..types import Variant

_NICKNAMER = NickNamer()


def generate_variants(name: str) -> list[Variant]:
    name = " ".join(name.split())
    if not name:
        return []
    seen: set[str] = set()
    out: list[Variant] = []

    def add(form: str, kind: str) -> None:
        form = " ".join(form.split())
        key = form.casefold()
        if form and key not in seen:
            seen.add(key)
            out.append(Variant(form=form, kind=kind, origin="parsed", weight=0.0))

    add(name, "as_given")
    add(unidecode(name), "diacritic_stripped")
    tokens = name.split(" ")
    if len(tokens) >= 2:
        add(f"{tokens[0][0]}. {' '.join(tokens[1:])}", "initials")
    if len(tokens) == 2:
        add(f"{tokens[1]} {tokens[0]}", "order_swap")
    for i, tok in enumerate(tokens):
        base = unidecode(tok).casefold()
        for r in _NICKNAMER.nicknames_of(base) | _NICKNAMER.canonicals_of(base):
            swapped = list(tokens)
            swapped[i] = r.title()
            add(" ".join(swapped), "nickname")
    return out
