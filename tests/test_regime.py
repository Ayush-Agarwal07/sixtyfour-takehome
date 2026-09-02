"""Regime′ classification — pure function, no I/O, no network."""
from __future__ import annotations

from pi.understand.regime import classify, is_definite_role


def _classify(**kw):
    base = dict(name=None, org=None, title=None, role_description=None, hard_ids={},
                company_resolved=False, org_is_huge=False)
    base.update(kw)
    return classify(**base)


def test_hard_id_email_wins():
    assert _classify(hard_ids={"email": "a@b.com"}, name="Someone") == "HARD_ID_EMAIL"


def test_definite_desc_needs_definite_role_and_org():
    assert _classify(role_description="the CTO of Ariglad", org="Ariglad") == "DEFINITE_DESC"
    assert _classify(title="CTO", org="Ariglad") == "DEFINITE_DESC"
    assert _classify(title="product designer", org="Figma") == "BARE_NAME"     # not definite → typed abstain
    assert _classify(role_description="the CTO of Ariglad") == "BARE_NAME"     # no org


def test_definite_roles():
    assert is_definite_role("head of design") and is_definite_role("chief people officer") and is_definite_role("co-founder")
    assert not is_definite_role("software engineer")


def test_name_regimes():
    assert _classify(name="Henry Wang", org="Sixtyfour AI", company_resolved=True) == "NAME_STRONG"
    assert _classify(name="Jane Doe", org="Nobody Can Find", company_resolved=False) == "NAME_WEAK"
    assert _classify(name="Jane Doe", org="Google", company_resolved=True, org_is_huge=True) == "NAME_WEAK"
    assert _classify(name="Jane Doe") == "BARE_NAME"
