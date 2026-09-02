"""Stage 1: prose spans must be verbatim in the page or they're dropped."""
from __future__ import annotations

from pi.expand.expander import _assemble

TEXT = "Andrew is a product designer at Ramp in New York."


def test_fuzzy_span_kept():
    kept = _assemble([("title", "product designer", "product  designer at Ramp")],
                     "https://example.com/a", TEXT, "c1", "prose_llm", "ramp.com")
    assert len(kept) == 1


def test_prose_span_in_text_is_kept():
    kept = _assemble([("title", "product designer", "product designer at Ramp")],
                     "https://example.com/a", TEXT, "c1", "prose_llm", "ramp.com")
    assert len(kept) == 1 and kept[0].evidence[0].candidate_id == "c1"


def test_prose_span_absent_is_dropped():
    dropped = _assemble([("title", "CEO", "was the CEO of Acme")],
                        "https://example.com/a", TEXT, "c1", "prose_llm", "ramp.com")
    assert dropped == []


def test_structured_rung_not_span_checked():
    # json_ld came from a parser, not prose — no span requirement
    kept = _assemble([("employer", "Ramp", "Ramp")],
                     "https://ramp.com/team", "", "c1", "json_ld", "ramp.com")
    assert len(kept) == 1
