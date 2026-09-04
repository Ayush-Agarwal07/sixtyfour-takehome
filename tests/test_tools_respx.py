"""GitHub, Gravatar, Wayback tools — mocked HTTP via respx. No live network calls."""
from __future__ import annotations

import httpx
import respx

from pi.deps import Deps, ToolUnavailable
from pi.store.cache import Cache
from pi.tools import GitHub, Gravatar, OpenAlex, Usernames, Wayback


# ───────────────────────────── GitHub ─────────────────────────────

@respx.mock
async def test_github_profile_found():
    respx.get("https://api.github.com/users/octocat").mock(
        return_value=httpx.Response(200, json={
            "login": "octocat", "name": "The Octocat", "bio": "hi",
            "company": None, "blog": "", "location": None, "email": None,
            "twitter_username": None, "html_url": "https://github.com/octocat",
            "public_repos": 8, "extra_field": "ignored",
        })
    )
    async with httpx.AsyncClient() as client:
        gh = GitHub(Deps(http=client))
        result = await gh.profile("octocat")
    assert result is not None
    assert result["login"] == "octocat"
    assert "extra_field" not in result


@respx.mock
async def test_github_profile_missing():
    respx.get("https://api.github.com/users/doesnotexist").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        gh = GitHub(Deps(http=client))
        result = await gh.profile("doesnotexist")
    assert result is None


@respx.mock
async def test_github_commit_emails_aggregates_and_skips_noreply():
    respx.get(url__startswith="https://api.github.com/repos/o/r/commits").mock(
        return_value=httpx.Response(200, json=[
            {"commit": {"author": {"email": "a@corp.com", "name": "A", "date": "2019-03-01T00:00:00Z"}}},
            {"commit": {"author": {"email": "a@corp.com", "name": "A", "date": "2021-06-01T00:00:00Z"}}},
            {"commit": {"author": {"email": "x@users.noreply.github.com", "name": "X", "date": "2020-01-01T00:00:00Z"}}},
        ])
    )
    async with httpx.AsyncClient() as client:
        gh = GitHub(Deps(http=client))
        result = await gh.commit_emails("o/r", "author")
    assert result == [{"email": "a@corp.com", "name": "A", "first": "2019-03-01", "last": "2021-06-01", "count": 2}]


# ───────────────────────────── Gravatar ─────────────────────────────

@respx.mock
async def test_gravatar_profile_missing():
    respx.get(url__regex=r"https://gravatar\.com/.*\.json").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        g = Gravatar(Deps(http=client))
        result = await g.profile("nobody@example.com")
    assert result is None


@respx.mock
async def test_gravatar_profile_found():
    respx.get(url__regex=r"https://gravatar\.com/.*\.json").mock(
        return_value=httpx.Response(200, json={"entry": [{
            "displayName": "Jane Doe",
            "aboutMe": "hi",
            "urls": [{"value": "https://jane.dev"}],
            "accounts": [{"url": "https://x.com/jane", "shortname": "twitter"}],
        }]})
    )
    async with httpx.AsyncClient() as client:
        g = Gravatar(Deps(http=client))
        result = await g.profile("jane@example.com")
    assert result["display_name"] == "Jane Doe"
    assert result["accounts"] == [{"url": "https://x.com/jane", "service": "twitter"}]


# ───────────────────────────── Wayback ─────────────────────────────

@respx.mock
async def test_wayback_snapshot_missing():
    respx.get("https://archive.org/wayback/available").mock(
        return_value=httpx.Response(200, json={"archived_snapshots": {}})
    )
    async with httpx.AsyncClient() as client:
        w = Wayback(Deps(http=client))
        result = await w.snapshot("https://example.com/team")
    assert result is None


@respx.mock
async def test_wayback_snapshot_found():
    respx.get("https://archive.org/wayback/available").mock(
        return_value=httpx.Response(200, json={"archived_snapshots": {"closest": {
            "available": True,
            "url": "https://web.archive.org/web/20200101000000/https://example.com/team",
            "timestamp": "20200101000000",
        }}})
    )
    respx.get("https://web.archive.org/web/20200101000000/https://example.com/team").mock(
        return_value=httpx.Response(200, text="<html><body><p>Our team is great and does many things.</p></body></html>")
    )
    async with httpx.AsyncClient() as client:
        w = Wayback(Deps(http=client))
        result = await w.snapshot("https://example.com/team")
    assert result is not None
    assert result["text"] != ""
    assert len(result["timestamp"]) == 8


# ───────────────────────────── Usernames ─────────────────────────────

async def test_usernames_probe_hits():
    # respx.mock(assert_all_mocked=False) only patches the transport correctly when
    # used as a context manager (as a bare decorator-with-kwargs it silently no-ops
    # in this respx version, i.e. real network — verified against the running suite).
    with respx.mock(assert_all_mocked=False) as rsx:
        rsx.get("https://api.github.com/users/saarthshah").mock(
            return_value=httpx.Response(200, json={"created_at": "2018-05-01T12:00:00Z"})
        )
        rsx.get("https://www.reddit.com/user/saarthshah/about.json").mock(
            return_value=httpx.Response(200, json={"data": {"name": "saarthshah", "created_utc": 1500000000}})
        )
        rsx.get("https://devpost.com/saarthshah").mock(return_value=httpx.Response(404))
        rsx.get("https://huggingface.co/saarthshah").mock(return_value=httpx.Response(200, text="<html></html>"))
        rsx.route().mock(return_value=httpx.Response(404))  # everything else: missing

        async with httpx.AsyncClient() as client:
            u = Usernames(Deps(http=client))
            hits = await u.probe("saarthshah")

    by_platform = {h["platform"]: h for h in hits}
    assert "devpost" not in by_platform
    assert by_platform["github"]["created"] == "2018-05-01"
    assert by_platform["reddit"]["created"] is not None
    assert by_platform["huggingface"]["url"] == "https://huggingface.co/saarthshah"


# ───────────────────────────── GitHub.code_search ─────────────────────────────

async def test_github_code_search_without_pat(monkeypatch):
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    async with httpx.AsyncClient() as client:
        gh = GitHub(Deps(http=client))
        try:
            await gh.code_search('"Saarth Shah"')
        except ToolUnavailable:
            return
    raise AssertionError("expected ToolUnavailable")


@respx.mock
async def test_github_code_search_with_pat(monkeypatch):
    monkeypatch.setenv("GITHUB_PAT", "x")
    respx.get(url__startswith="https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json={"items": [
            {"repository": {"full_name": "StanfordHealth/wearipedia"}, "path": "CONTRIBUTORS.md",
             "html_url": "https://github.com/StanfordHealth/wearipedia/blob/main/CONTRIBUTORS.md"},
        ]})
    )
    async with httpx.AsyncClient() as client:
        gh = GitHub(Deps(http=client))
        result = await gh.code_search('"Saarth Shah"')
    assert result[0]["repo"] == "StanfordHealth/wearipedia"
    assert result[0]["raw_url"] == (
        "https://raw.githubusercontent.com/StanfordHealth/wearipedia/HEAD/CONTRIBUTORS.md"
    )


@respx.mock
async def test_github_code_search_403_not_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_PAT", "x")
    route = respx.get(url__startswith="https://api.github.com/search/code")
    route.side_effect = [
        httpx.Response(403),
        httpx.Response(200, json={"items": [
            {"repository": {"full_name": "o/r"}, "path": "f.md", "html_url": "https://github.com/o/r/blob/main/f.md"},
        ]}),
    ]
    async with httpx.AsyncClient() as client:
        deps = Deps.build(cache=Cache(tmp_path / "cache"), http=client)
        gh = GitHub(deps)
        first = await gh.code_search('"Saarth Shah"')
        second = await gh.code_search('"Saarth Shah"')
    assert first == []
    assert route.call_count == 2
    assert second[0]["repo"] == "o/r"


# ───────────────────────────── OpenAlex ─────────────────────────────

_AUTHORS_JSON = {"results": [
    {"id": "https://openalex.org/A1", "display_name": "Saarth Shah", "works_count": 3,
     "last_known_institutions": [{"display_name": "Massachusetts Institute of Technology"}],
     "affiliations": [], "ids": {}},
    {"id": "https://openalex.org/A2", "display_name": "Saarth Shah", "works_count": 5,
     "last_known_institutions": [{"display_name": "Stanford University"}],
     "affiliations": [], "ids": {"orcid": "https://orcid.org/0000-0000-0000-0001"}},
]}


@respx.mock
async def test_openalex_author_matches_hint():
    respx.get(url__regex=r"https://api\.openalex\.org/authors.*").mock(
        return_value=httpx.Response(200, json=_AUTHORS_JSON)
    )
    async with httpx.AsyncClient() as client:
        oa = OpenAlex(Deps(http=client))
        result = await oa.author("Saarth Shah", ["Stanford"])
    assert result is not None
    assert result["id"] == "https://openalex.org/A2"
    assert result["orcid"] == "https://orcid.org/0000-0000-0000-0001"


@respx.mock
async def test_openalex_author_no_hint_match():
    respx.get(url__regex=r"https://api\.openalex\.org/authors.*").mock(
        return_value=httpx.Response(200, json=_AUTHORS_JSON)
    )
    async with httpx.AsyncClient() as client:
        oa = OpenAlex(Deps(http=client))
        result = await oa.author("Saarth Shah", ["Nowhere"])
    assert result is None


@respx.mock
async def test_openalex_works_parses_fields():
    respx.get(url__regex=r"https://api\.openalex\.org/works.*").mock(
        return_value=httpx.Response(200, json={"results": [
            {"title": "A Paper", "publication_year": 2022, "doi": "https://doi.org/10.1/x",
             "primary_location": {"source": {"display_name": "NeurIPS"}},
             "authorships": [{"author": {"display_name": "Saarth Shah"}},
                              {"author": {"display_name": "Coauthor A"}}],
             "id": "https://openalex.org/W1"},
        ]})
    )
    async with httpx.AsyncClient() as client:
        oa = OpenAlex(Deps(http=client))
        result = await oa.works("https://openalex.org/A2", n=5)
    assert result[0]["title"] == "A Paper"
    assert result[0]["year"] == 2022
    assert result[0]["venue"] == "NeurIPS"
    assert result[0]["coauthors"] == ["Saarth Shah", "Coauthor A"]
