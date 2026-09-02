"""Phase 1 UNDERSTAND — pure, no-network name-variant generation.

`generate_variants` produces cheap, mechanically-derived forms of a name for
RESOLVE's enumeration step: as-given, initials, order-swap (given-name-last),
nickname expansion (`nicknames` package, both directions), and diacritic-strip
(`unidecode`). Scoring (constants.NAME_FORM weights) happens downstream in
resolve/identity_score.py — every Variant here is origin="parsed", weight=0.0.

CRITICAL INVARIANT (no fabrication): a variant may never contain an alphabetic
character that isn't either (a) already in the input, or (b) drawn from a
`nicknames`-package lookup for one of the input's own tokens. (a) covers
as-given / initials / order-swap / diacritic-strip, which by construction only
rearrange or drop letters. (b) is the deliberate, narrow exception for
nickname expansion: a real nickname/formal-name pair (Bob/Robert) differs in
letters by definition — that's not invention, it's a bounded reference-table
lookup (same status as census.py's surname table), which is exactly why
constants.NAME_FORM scores "nickname" at its own -0.4 penalty instead of
banning it outright. What's still never allowed, from any path: middle names,
invented handles, or an English name "chosen" by heuristic/guesswork rather
than looked up.
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
    forms: list[str] = []

    def add(form: str) -> None:
        form = " ".join(form.split())
        key = form.casefold()
        if form and key not in seen:
            seen.add(key)
            forms.append(form)

    add(name)                      # as-given
    add(unidecode(name))           # diacritic strip

    tokens = name.split(" ")
    if len(tokens) >= 2:
        add(f"{tokens[0][0]}. {' '.join(tokens[1:])}")     # initials
    if len(tokens) == 2:
        # order swap: given-name-last cultures write surname first.
        # ponytail: only defined for 2 tokens — ambiguous which token is the
        # surname once there are 3+.
        add(f"{tokens[1]} {tokens[0]}")

    for i, tok in enumerate(tokens):
        base = unidecode(tok).casefold()
        related = _NICKNAMER.nicknames_of(base) | _NICKNAMER.canonicals_of(base)
        for r in related:
            swapped = list(tokens)
            swapped[i] = r.title()
            add(" ".join(swapped))

    return [Variant(form=f, origin="parsed", weight=0.0) for f in forms]
