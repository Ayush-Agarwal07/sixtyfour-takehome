"""Derive name hypotheses + employer domain from an email. No network.

The local part is a weak identity signal: `andrew.goering` gives a confident
first.last, but `jsmith` could be flast or a bare first name. We emit ranked
hypotheses and let identity scoring weigh them (initials form carries a penalty).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_DIGITS_TAIL = re.compile(r"\d+$")
_SEP = re.compile(r"[._-]")


@dataclass
class NameHypothesis:
    first: str | None = None
    last: str | None = None
    first_initial: str | None = None
    pattern: str = ""
    form: str = "exact"        # exact|initials|partial — feeds constants.NAME_FORM
    confidence: float = 0.0


@dataclass
class EmailDerivation:
    email: str
    domain: str
    hypotheses: list[NameHypothesis] = field(default_factory=list)


def derive_from_email(email: str) -> EmailDerivation:
    local, _, domain = email.strip().lower().partition("@")
    local = _DIGITS_TAIL.sub("", local)
    hyps: list[NameHypothesis] = []

    sep = next((c for c in "._-" if c in local), None)
    if sep:
        a, b = local.split(sep, 1)
        b = _SEP.split(b)[0]                      # keep the first two tokens only
        if len(a) == 1:
            hyps.append(NameHypothesis(first_initial=a, last=b, pattern="flast",
                                       form="initials", confidence=0.6))
        else:
            hyps.append(NameHypothesis(first=a, last=b, pattern="first_last",
                                       form="exact", confidence=0.9))
    else:
        # no separator: ambiguous. flast (j+smith) and a bare first name are common.
        if len(local) > 2:
            hyps.append(NameHypothesis(first_initial=local[0], last=local[1:],
                                       pattern="flast", form="initials", confidence=0.4))
        hyps.append(NameHypothesis(first=local, pattern="first",
                                   form="partial", confidence=0.3))

    return EmailDerivation(email=email, domain=domain, hypotheses=hyps)
