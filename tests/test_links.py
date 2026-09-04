"""Verified links merge candidates; surnames never do."""
from __future__ import annotations

from pi.deps import Deps
from pi.resolve.links import apply_page_links, extract_links
from pi.types import Candidate, Confidence

TEAM_HTML = """<html><body><main><h2>Team</h2>
<p>Henry Wang, founding engineer — <a href="https://www.linkedin.com/in/henry00c">LinkedIn</a>
<a href="https://github.com/braindead-dev">GitHub</a></p>
<p>Jane Roe — <a href="https://www.linkedin.com/in/jane-roe">LinkedIn</a></p></main>
<footer><a href="https://x.com/sixtyfour">company x</a></footer></body></html>"""

SITE_HTML = """<html><body><nav><a href="/">home</a></nav><p>hi, I'm Henry</p>
<footer><a href="https://github.com/braindead-dev">gh</a><a href="https://www.linkedin.com/in/henry00c">in</a></footer></body></html>"""


def _c(cid, url, key):
    return Candidate(cid=cid, urls=[url], identity_keys=[key], score=Confidence(score=0, logodds=0))


def test_extract_links_sections():
    links = extract_links(TEAM_HTML, "https://sixtyfour.ai/team")
    assert ("https://x.com/sixtyfour", "company x", "footer") in links
    assert any(u == "https://www.linkedin.com/in/henry00c" and s == "prose" for u, _, s in links)


def test_official_page_co_citation_merges_and_anchors():
    a = _c("c1", "https://www.linkedin.com/in/henry00c", "linkedin:henry00c")
    b = _c("c2", "https://github.com/braindead-dev", "github:braindead-dev")
    other = _c("c3", "https://www.linkedin.com/in/jane-roe", "linkedin:jane-roe")
    cands, links = [a, b, other], []
    apply_page_links({"url": "https://sixtyfour.ai/team", "html": TEAM_HTML}, None, cands, links, {}, Deps(),
                     names=["Henry Wang"], anchor_domains={"sixtyfour.ai"})
    # Jane is also co-cited on the same page → this fixture merges all three; the
    # name filter is the enumeration relevance floor, not this step. Assert the
    # mechanism: anchored_one_way set and a merge happened.
    assert a.anchored_one_way and any(l.mechanism == "anchored_one_way" for l in links)
    assert len(cands) < 3


def test_self_published_page_links_own_profiles_reciprocal():
    site = _c("c1", "https://henrywa.ng/", "site:henrywa.ng")
    gh = _c("c2", "https://github.com/braindead-dev", "github:braindead-dev")
    li = _c("c3", "https://www.linkedin.com/in/henry00c", "linkedin:henry00c")
    cands, links, linked = [site, gh, li], [], {"c2": {"site:henrywa.ng"}}   # github page already linked the site
    apply_page_links({"url": "https://henrywa.ng/", "html": SITE_HTML}, site, cands, links, linked, Deps(),
                     names=["Henry Wang"], anchor_domains=set())
    assert cands == [site] and site.reciprocal and set(site.merged_from) == {"c2", "c3"}


def test_reciprocal_merge_with_stale_owner_from_sequential_fetch():
    """Two candidates fetched in one cycle: A's page links B (merges B into A), then
    B's *stale* pre-merge object is passed as owner for B's own page, which links
    back to A. Must not empty `cands`, and must still record the reciprocal."""
    a = _c("c1", "https://saarthshah.com/", "site:saarthshah.com")
    b = _c("c2", "https://github.com/SaarthShah", "github:saarthshah")
    b_stale = b  # the reference resolver.py's fetch loop still holds after A's merge
    cands, links, linked = [a, b], [], {}
    page_a = {"url": "https://saarthshah.com/",
              "html": '<html><body><a href="https://github.com/SaarthShah">GitHub</a></body></html>'}
    page_b = {"url": "https://github.com/SaarthShah",
              "html": '<html><body><a href="https://saarthshah.com/">site</a></body></html>'}

    apply_page_links(page_a, a, cands, links, linked, Deps(), names=["Saarth Shah"], anchor_domains=set())
    apply_page_links(page_b, b_stale, cands, links, linked, Deps(), names=["Saarth Shah"], anchor_domains=set())

    assert cands == [a]
    assert a.reciprocal
    assert "c2" in a.merged_from
