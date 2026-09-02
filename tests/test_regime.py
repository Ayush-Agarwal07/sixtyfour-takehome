"""Regime′ classification — pure function, no I/O, no network."""
from __future__ import annotations

from pi.understand.regime import classify


def _classify(**kw):
    base = dict(
        name=None, org=None, title=None, role_description=None,
        hard_ids={}, company_resolved=False, org_is_huge=False,
    )
    base.update(kw)
    return classify(**base)


def test_hard_id_email_wins_regardless_of_other_fields():
    assert _classify(hard_ids={"email": "a@b.com"}, name="Someone") == "HARD_ID_EMAIL"


def test_definite_desc_role_description_no_name():
    assert _classify(role_description="the CTO of Ariglad") == "DEFINITE_DESC"


def test_name_strong_company_resolved_not_huge():
    assert _classify(
        name="Henry Wang", org="Sixtyfour AI",
        company_resolved=True, org_is_huge=False,
    ) == "NAME_STRONG"


def test_name_weak_org_present_not_resolved():
    assert _classify(
        name="Jane Doe", org="Some Startup Nobody Can Find",
        company_resolved=False, org_is_huge=False,
    ) == "NAME_WEAK"


def test_name_weak_org_is_huge():
    assert _classify(
        name="Jane Doe", org="Google",
        company_resolved=True, org_is_huge=True,
    ) == "NAME_WEAK"


def test_bare_name_alone():
    assert _classify(name="Jane Doe") == "BARE_NAME"
