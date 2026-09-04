"""plan/reference-confidence-scoring.md §7 value canonicalization for merging."""
from __future__ import annotations

from pi.score.canonical import canonicalize


def test_employer_resolves_to_org_domain():
    assert canonicalize("employer", "Sixtyfour AI", {"sixtyfour ai": "sixtyfour.ai"}) == "sixtyfour.ai"


def test_employer_strips_parenthetical_and_legal_suffix():
    assert canonicalize("employer", "CloudMD (TSXV:DOC)") == "cloudmd"


def test_education_strips_university_of():
    assert canonicalize("education", "The University of Toronto") == "toronto"


def test_title_keeps_seniority_words():
    assert canonicalize("title", "Senior Software Engineer") == "senior software engineer"


def test_handle_strips_leading_at():
    assert canonicalize("handle", "@aiavci") == "aiavci"


def test_location_takes_text_before_first_comma():
    assert canonicalize("location", "Lexington, Massachusetts, United States") == "lexington"
