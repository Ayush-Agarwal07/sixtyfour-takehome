"""One classifier for every URL → source class, identity key, tiers."""
from __future__ import annotations

from pi.sources import classify, identity_key, identity_tier, is_rare_handle, registrable_domain


def test_classes():
    names = ["Henry Wang"]
    assert classify("https://www.linkedin.com/in/henry00c") == "professional_network"
    assert classify("https://github.com/braindead-dev") == "code_host"
    assert classify("https://www.zoominfo.com/p/Matthew-Shalhoub/1") == "aggregator"
    assert classify("https://www.ycombinator.com/companies/ariglad") == "press"
    assert classify("https://techcrunch.com/2025/01/01/x") == "press"
    assert classify("https://henrywa.ng/", names=names) == "personal_site"
    assert classify("https://sixtyfour.ai/team", anchor_domains={"sixtyfour.ai"}) == "company_site"
    assert classify("https://cs.stanford.edu/~x") == "academic"
    assert classify("https://www.randomconference.org/speakers") == "unknown"
    assert classify("https://medium.com/@henrywang/post") == "personal_site"


def test_identity_keys():
    assert identity_key("https://www.linkedin.com/in/sarah-che/") == ("linkedin", "sarah-che")
    assert identity_key("https://github.com/braindead-dev") == ("github", "braindead-dev")
    assert identity_key("https://github.com/orgs/foo") is None
    assert identity_key("https://x.com/henry") == ("x", "henry")
    assert identity_key("https://www.zoominfo.com/p/x/1") is None
    assert identity_key("https://henrywa.ng/about", names=["Henry Wang"]) == ("site", "henrywa.ng")


def test_tiers_and_domains():
    assert identity_tier("company_site") == 2.5 and identity_tier("aggregator") == 0.5
    assert registrable_domain("www.bbc.co.uk") == "bbc.co.uk"
    assert registrable_domain("blog.example.com") == "example.com"


def test_rare_handle():
    assert is_rare_handle("braindead-dev", ["Henry Wang"])
    assert not is_rare_handle("henry", ["Henry Wang"])
    assert not is_rare_handle("jsmith", ["John Smith"])
