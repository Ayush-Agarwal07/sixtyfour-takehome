"""The EXPAND loop (planner + expander): no network, no LLM."""
from __future__ import annotations

import pi.expand.expander as expander_mod
from pi import constants
from pi.deps import Deps
from pi.expand.expander import expand
from pi.expand.graph import Graph
from pi.trace.writer import TraceWriter
from pi.types import Candidate, Confidence, GraphEdge, GraphNode, Resolution, Seed, Variant

PAGE_URL = "https://janeroe.dev"
PAGE_TEXT = "Jane Roe is a software engineer at Ramp in New York."
PAGE_HTML = (
    "<html><body><p>Jane Roe is a software engineer at Ramp in New York.</p>"
    '<a href="https://example.com/other">other</a>'
    '<footer><a href="https://crunchbase.com/person/jane">cb</a></footer>'
    "</body></html>"
)


def _counters() -> dict:
    return {"tool_calls": 0, "llm_calls": 0, "usd": 0.0}


class FakeGitHub:
    def __init__(self, counters: dict):
        self.counters = counters
        self.commit_email_calls: list[tuple[str, str]] = []

    async def profile(self, login: str):
        self.counters["tool_calls"] += 1
        return {"login": login, "name": "Jane Roe", "bio": "", "company": "Ramp", "blog": "",
                "location": "", "email": "", "twitter_username": "", "html_url": f"https://github.com/{login}"}

    async def repos(self, login: str, n: int = 5):
        self.counters["tool_calls"] += 1
        return [{"full_name": f"{login}/proj", "html_url": "x", "description": "", "pushed_at": "", "language": "Python"}]

    async def commit_emails(self, full_name: str, login: str):
        self.counters["tool_calls"] += 1
        self.commit_email_calls.append((full_name, login))
        return [{"email": "jane@ramp.com", "first": "2021-01-01", "last": "2021-06-01", "count": 10}]

    async def code_search(self, q: str, n: int = 10):
        self.counters["tool_calls"] += 1
        return []


class FakeSerper:
    def __init__(self, counters: dict, results: list[dict] | None = None):
        self.counters = counters
        self.results = results if results is not None else [
            {"url": "https://news.example.com/jane", "title": "Jane Roe profile",
             "snippet": "Jane Roe at Ramp", "query": "q"}]

    async def search(self, q: str, num: int = 10):
        self.counters["tool_calls"] += 1
        return self.results


class FakeFetch:
    def __init__(self, counters: dict, pages: dict[str, dict]):
        self.counters = counters
        self.pages = pages
        self.calls: list[str] = []

    async def get(self, url: str):
        self.counters["tool_calls"] += 1
        self.calls.append(url)
        page = self.pages.get(url)
        if page is None:
            raise RuntimeError(f"no fake page for {url}")
        return page


class FakeGravatar:
    def __init__(self, counters: dict):
        self.counters = counters
        self.calls: list[str] = []

    async def profile(self, email: str):
        self.counters["tool_calls"] += 1
        self.calls.append(email)
        return None


class FakeUsernames:
    def __init__(self, counters: dict, hits: dict[str, list[dict]] | None = None):
        self.counters = counters
        self.hits = hits or {}
        self.calls: list[str] = []

    async def probe(self, handle: str):
        self.counters["tool_calls"] += 1
        self.calls.append(handle)
        return self.hits.get(handle, [])


class FakeOpenAlex:
    def __init__(self, counters: dict, author_result: dict | None, works_result: list[dict] | None = None):
        self.counters = counters
        self.author_result = author_result
        self.works_result = works_result if works_result is not None else []
        self.author_calls: list[tuple[str, list[str]]] = []

    async def author(self, name: str, hints: list[str]):
        self.counters["tool_calls"] += 1
        self.author_calls.append((name, list(hints)))
        return self.author_result

    async def works(self, author_id: str, n: int = 5):
        self.counters["tool_calls"] += 1
        return self.works_result


class FakeWayback:
    def __init__(self, counters: dict):
        self.counters = counters

    async def snapshot(self, url: str, year=None):
        self.counters["tool_calls"] += 1
        return None


class FakeLLM:
    """T2 (planner): picks the first N frontier-line ids from the prompt, optionally
    skipping any whose action is `skip_action`. T3 (extraction): one employer tuple
    whose span is verbatim in the fetched page text."""

    def __init__(self, skip_action: str | None = None, pick_n: int = 2):
        self.calls: list[str] = []
        self.skip_action = skip_action
        self.pick_n = pick_n

    async def complete(self, tier: str, prompt: str, model, *, phase=None, system=None):
        self.calls.append(tier)
        if tier == "T2":
            ids = []
            for line in prompt.splitlines():
                if " | " not in line:
                    continue
                fid, rest = line.split(" | ", 1)
                action = rest.split()[0] if rest.split() else ""
                if self.skip_action and action == self.skip_action:
                    continue
                ids.append(fid)
            return model(picks=ids[: self.pick_n])
        if tier == "T3":
            return model(tuples=[{"predicate": "employer", "value": "Ramp",
                                  "span": "engineer at Ramp in New York", "context_date": None}], links=[])
        if tier == "T4":
            return model(results=[])
        raise AssertionError(f"unexpected tier {tier}")


def _seed(**kw) -> Seed:
    kw.setdefault("input", "jane roe")
    kw.setdefault("regime", "NAME_STRONG")
    kw.setdefault("names", [Variant(form="Jane Roe")])
    return Seed(**kw)


def _cand(**kw) -> Candidate:
    kw.setdefault("cid", "c1")
    kw.setdefault("score", Confidence(score=0.9, logodds=2.0))
    return Candidate(**kw)


def _resolution(cand: Candidate) -> Resolution:
    return Resolution(status="confirmed", confirmed_cid=cand.cid, candidates=[cand])


def _deps(tmp_path, counters, *, pages=None, serper_results=None, exa=False) -> Deps:
    trace = TraceWriter(tmp_path)
    tools = {
        "github": FakeGitHub(counters),
        "serper": FakeSerper(counters, serper_results),
        "fetch": FakeFetch(counters, pages or {}),
        "gravatar": FakeGravatar(counters),
        "wayback": FakeWayback(counters),
    }
    return Deps(trace=trace, counters=counters, tools=tools)


def _events(tmp_path, event_type: str) -> list[dict]:
    import json
    out = []
    for line in (tmp_path / "trace.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e.get("event_type") == event_type:
            out.append(e)
    return out


async def test_expand_loop_produces_isolated_claims_and_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "EXPAND_CAP", 8)
    counters = _counters()
    cand = _cand(urls=[PAGE_URL], handles={"github": "janeroe"})
    seed = _seed()
    deps = _deps(tmp_path, counters, pages={PAGE_URL: {"url": PAGE_URL, "html": PAGE_HTML, "text": PAGE_TEXT}})
    llm = FakeLLM(pick_n=2)

    findings = await expand(_resolution(cand), seed, deps, llm)

    assert findings.stop_reason in {"S1", "S2", "S3", "S3_batches", "S5_planner", "S_frontier_empty"}
    assert all(e.candidate_id == "c1" for c in findings.claims for e in c.evidence)
    assert counters["tool_calls"] <= min(constants.EXPAND_CAP, constants.S3_TOTAL_TOOL_CALLS)

    planner_events = _events(tmp_path, "planner_decision")
    assert len(planner_events) >= 1

    github = deps.tools["github"]
    assert github.commit_email_calls, "commit_emails should run inline for a top repo after github"


async def test_conflicting_ongoing_titles_emit_one_conflict_detected_event(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "EXPAND_CAP", 8)
    counters = _counters()
    url2 = "https://janeroe.me"
    text1, text2 = "Jane Roe is the Head of Design at Ramp.", "Jane Roe is the Design Lead at Ramp."
    pages = {
        PAGE_URL: {"url": PAGE_URL, "html": f"<html><body><p>{text1}</p></body></html>", "text": text1},
        url2: {"url": url2, "html": f"<html><body><p>{text2}</p></body></html>", "text": text2},
    }
    cand = _cand(urls=[PAGE_URL, url2])
    seed = _seed()
    deps = _deps(tmp_path, counters, pages=pages)

    class ConflictLLM:
        async def complete(self, tier, prompt, model, *, phase=None, system=None):
            if tier == "T2":
                ids = [line.split(" | ", 1)[0] for line in prompt.splitlines() if " | " in line]
                return model(picks=ids[:2])
            if tier == "T3":
                if PAGE_URL in prompt:
                    return model(tuples=[{"predicate": "title", "value": "Head of Design",
                                          "span": "Head of Design at Ramp", "context_date": "2020 - present"}],
                                links=[])
                return model(tuples=[{"predicate": "title", "value": "Design Lead",
                                      "span": "Design Lead at Ramp", "context_date": "2019 - present"}], links=[])
            raise AssertionError(f"unexpected tier {tier}")

    await expand(_resolution(cand), seed, deps, ConflictLLM())

    events = _events(tmp_path, "conflict_detected")
    assert len(events) == 1
    assert events[0]["predicate"] == "title"
    assert sorted(events[0]["values"]) == ["design lead", "head of design"]


async def test_forced_reinforce_fires_after_planner_skips_it_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "EXPAND_CAP", 20)
    counters = _counters()
    cand = _cand(urls=[PAGE_URL])
    seed = _seed()
    deps = _deps(tmp_path, counters, pages={PAGE_URL: {"url": PAGE_URL, "html": "<html></html>", "text": ""}})
    llm = FakeLLM(skip_action="verify", pick_n=1)

    def _patched_graph(root: GraphNode) -> Graph:
        g = Graph(root)
        g.add_node(GraphNode(id="company:weak.com", type="company", label="Weak Co", attachment_confidence=0.3))
        for i in range(3):
            g.add_node(GraphNode(id=f"leaf{i}", type="account", label=f"leaf{i}"))
            g.add_edge(GraphEdge(id=f"e{i}", src="company:weak.com", dst=f"leaf{i}", type="affiliation",
                                 mechanism="pretest"))
        return g

    monkeypatch.setattr(expander_mod, "Graph", _patched_graph)

    await expand(_resolution(cand), seed, deps, llm)

    reinforce_events = _events(tmp_path, "reinforce")
    assert reinforce_events, "a forced reinforce should have fired once the planner skipped it twice"


def test_normalize_args_maps_query_to_q():
    from pi.expand.planner import _normalize_args
    assert _normalize_args({"query": "henry wang"}) == {"q": "henry wang"}


def test_register_new_actions_drops_already_done_or_pending_and_dedupes():
    from pi.expand.frontier import Frontier
    from pi.expand.planner import _register_new_actions

    f = Frontier()
    dup_args = {"url": "https://henr.ee"}
    f.done.add(f.key("fetch", dup_args))  # already executed earlier this run

    kept = _register_new_actions([{"tool": "fetch", "args": dup_args}], f)
    assert kept == []

    fresh = _register_new_actions([{"tool": "search", "args": {"query": "henry wang sixtyfour"}}], f)
    assert len(fresh) == 1 and fresh[0]["args"] == {"q": "henry wang sixtyfour"}
    assert f.key("search", {"q": "henry wang sixtyfour"}) in f.items  # fed through frontier.add

    # the exact same suggestion again this run is now pending ("attempted") → dropped
    again = _register_new_actions([{"tool": "search", "args": {"query": "henry wang sixtyfour"}}], f)
    assert again == []


async def test_two_consecutive_empty_planner_batches_stop_with_s5_planner(tmp_path):
    counters = _counters()
    cand = _cand(urls=[PAGE_URL])
    seed = _seed()
    deps = _deps(tmp_path, counters, pages={PAGE_URL: {"url": PAGE_URL, "html": "<html></html>", "text": ""}})

    class NeverPicksLLM:
        async def complete(self, tier, prompt, model, *, phase=None, system=None):
            if tier == "T2":
                return model(picks=[])
            return model(tuples=[], links=[])

    findings = await expand(_resolution(cand), seed, deps, NeverPicksLLM())

    assert findings.stop_reason == "S5_planner"


async def test_social_link_on_own_page_yields_handle_claim_not_a_frontier_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "EXPAND_CAP", 6)
    counters = _counters()
    cand = _cand(urls=[PAGE_URL])
    seed = _seed()
    html = PAGE_HTML.replace(
        "</body>", '<a href="https://x.com/henrywang">@henrywang</a></body>')
    deps = _deps(tmp_path, counters, pages={PAGE_URL: {"url": PAGE_URL, "html": html, "text": PAGE_TEXT}})
    exa_calls: list[str] = []

    class FakeExa:
        async def contents(self, url: str):
            counters["tool_calls"] += 1
            exa_calls.append(url)
            return None

    deps.tools["exa"] = FakeExa()  # so a frontier item for x.com would be fetchable, if one existed
    llm = FakeLLM(pick_n=4)

    findings = await expand(_resolution(cand), seed, deps, llm)

    handle_claims = [c for c in findings.claims if c.predicate == "handle" and "x.com" in c.value]
    assert len(handle_claims) == 1
    assert "https://x.com/henrywang" not in exa_calls


class _NeverPicksLLM:
    """T2 always returns no picks — proves a forced pivot runs with zero help from
    the planner (fix-round F1)."""

    async def complete(self, tier, prompt, model, *, phase=None, system=None):
        if tier == "T2":
            return model(picks=[])
        if tier == "T4":
            return model(results=[])
        return model(tuples=[], links=[])


async def test_username_probe_is_forced_dedupes_skips_bare_name_and_site_domain(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "EXPAND_CAP", 10)
    counters = _counters()
    cand = _cand(handles={
        "twitter": "rarehandle123", "github": "rarehandle123",   # same handle, two known keys -> probed once
        "linkedin": "jane",                                       # bare first name -> not probed
        "site": "rarehandle123.com",                              # a website domain, no platform template -> skipped
    })
    seed = _seed()
    deps = _deps(tmp_path, counters, serper_results=[])
    hits = {"rarehandle123": [
        {"platform": "reddit", "url": "https://www.reddit.com/user/rarehandle123", "created": "2019-05-01",
         "body": {"data": {"subreddit": {"public_description": "Jane Roe's account"}}}},
        {"platform": "keybase", "url": "https://keybase.io/rarehandle123", "created": None, "body": None},
    ]}
    fake_usernames = FakeUsernames(counters, hits)
    deps.tools["usernames"] = fake_usernames

    findings = await expand(_resolution(cand), seed, deps, _NeverPicksLLM())

    # the pivot ran even though the planner never picked anything off the frontier
    assert fake_usernames.calls == ["rarehandle123"]            # deduped across the twitter+github keys
    assert "jane" not in fake_usernames.calls                   # bare first name
    assert "rarehandle123.com" not in fake_usernames.calls      # site domain has no platform URL shape (F2)

    # the handle being probed is itself a registered anchor (it's the candidate's own
    # known handle), so a confirming hit's URL alone earns the "handle" anchor category
    # on top of the name match — profile band (0.85), not just name-only middle band.
    # (The pure name-only 0.622 arithmetic is covered by test_anchors.py and by
    # test_github_code_produces_claim_and_skips_own_repos, whose discovered text
    # never references a pre-registered anchor.)
    probe_claims = {c.value: c for c in findings.claims
                    if c.predicate == "handle" and any(e.extraction_method == "username_probe" for e in c.evidence)}
    assert len(probe_claims) == 1                                          # keybase (no body) never crosses ATTACH_SKIP
    reddit_claim = probe_claims["https://www.reddit.com/user/rarehandle123"]
    assert abs(reddit_claim.attachment_confidence - 0.846) < 0.01
    assert reddit_claim.evidence[0].snippet == "username match; same-person test 0.85"
    account_ids = {n.id for n in findings.nodes if n.type == "account"}
    assert any("reddit.com" in nid for nid in account_ids)
    assert not any("keybase.io" in nid for nid in account_ids)

    attach_events = _events(tmp_path, "attachment_test")
    probe_events = [e for e in attach_events if "rarehandle123" in e["url"]]
    assert sum(1 for e in probe_events if e["band"] == "profile") == 1
    assert sum(1 for e in probe_events if e["band"] == "skip") == 1


async def test_discovered_email_enqueues_gravatar_once(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "EXPAND_CAP", 8)
    counters = _counters()
    cand = _cand(urls=[PAGE_URL])
    seed = _seed()
    html = ('<html><head><script type="application/ld+json">'
            '{"@context": "https://schema.org", "@type": "Person", "email": "founder@rareaustralium.io"}'
            "</script></head><body>Jane Roe is a software engineer.</body></html>")
    deps = _deps(tmp_path, counters,
                pages={PAGE_URL: {"url": PAGE_URL, "html": html, "text": "Jane Roe is a software engineer."}},
                serper_results=[])
    fake_gravatar = deps.tools["gravatar"]
    llm = FakeLLM(pick_n=3)

    await expand(_resolution(cand), seed, deps, llm)

    assert fake_gravatar.calls == ["founder@rareaustralium.io"]


async def test_github_code_produces_claim_and_skips_own_repos(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "EXPAND_CAP", 10)
    monkeypatch.setenv("GITHUB_PAT", "test-token")
    counters = _counters()
    cand = _cand(handles={"github": "janeroe"})
    seed = _seed()
    deps = _deps(tmp_path, counters, serper_results=[])

    class CodeSearchGithub(FakeGitHub):
        async def code_search(self, q: str, n: int = 10):
            self.counters["tool_calls"] += 1
            return [
                {"repo": "JaneRoe/selfproj", "path": "a.py",   # login casing differs — must still be skipped
                 "html_url": "https://github.com/JaneRoe/selfproj/blob/HEAD/a.py",
                 "raw_url": "https://raw.githubusercontent.com/JaneRoe/selfproj/HEAD/a.py"},
                {"repo": "acme/other", "path": "b.py",
                 "html_url": "https://github.com/acme/other/blob/HEAD/b.py",
                 "raw_url": "https://raw.githubusercontent.com/acme/other/HEAD/b.py"},
            ]

    deps.tools["github"] = CodeSearchGithub(counters)
    fake_fetch = FakeFetch(counters, {
        "https://raw.githubusercontent.com/acme/other/HEAD/b.py":
            {"text": "credits: Jane Roe built this tool.", "html": ""},
    })
    deps.tools["fetch"] = fake_fetch

    class _GithubCodeLLM:
        async def complete(self, tier, prompt, model, *, phase=None, system=None):
            if tier == "T2":
                ids = [line.split(" | ", 1)[0] for line in prompt.splitlines() if " | " in line]
                return model(picks=ids[:4])
            if tier == "T3":
                return model(tuples=[{"predicate": "employer", "value": "Acme Corp",
                                      "span": "credits: Jane Roe built this tool.", "context_date": None}], links=[])
            if tier == "T4":
                return model(results=[])
            raise AssertionError(tier)

    findings = await expand(_resolution(cand), seed, deps, _GithubCodeLLM())

    gc_claims = [c for c in findings.claims if any(e.extraction_method == "github_code" for e in c.evidence)]
    assert gc_claims and gc_claims[0].value_raw == "Acme Corp"
    assert not any("janeroe" in url.lower() for url in fake_fetch.calls)   # his own repo's raw_url, any case, never fetched
    # name only (no anchor category match on this text) → middle band, DESIGN.md §13 arithmetic
    assert abs(gc_claims[0].attachment_confidence - 0.622) < 0.01


async def test_github_code_falls_back_to_raw_body_when_trafilatura_empties_text(tmp_path, monkeypatch):
    """fix-round F4: raw.githubusercontent.com serves plain markdown, not html, so
    Fetch's trafilatura step can return text="" for a real CONTRIBUTORS.md
    (runs/84879a52a545) — extraction must still see the raw fetched body."""
    monkeypatch.setattr(constants, "EXPAND_CAP", 10)
    monkeypatch.setenv("GITHUB_PAT", "test-token")
    counters = _counters()
    cand = _cand()
    seed = _seed()
    deps = _deps(tmp_path, counters, serper_results=[])

    class CodeSearchGithub(FakeGitHub):
        async def code_search(self, q: str, n: int = 10):
            self.counters["tool_calls"] += 1
            return [{"repo": "Stanford-Health/wearipedia", "path": "CONTRIBUTORS.md",
                     "html_url": "https://github.com/Stanford-Health/wearipedia/blob/HEAD/CONTRIBUTORS.md",
                     "raw_url": "https://raw.githubusercontent.com/Stanford-Health/wearipedia/HEAD/CONTRIBUTORS.md"}]

    deps.tools["github"] = CodeSearchGithub(counters)
    contributors_md = ("# List of contributors\n\n- Rodrigo Castellon (rjcaste@stanford.edu)\n"
                       "- Jane Roe (jane@berkeley.edu)\n- Suvan Kumar (kumarsuvan0@gmail.com)\n")
    deps.tools["fetch"] = FakeFetch(counters, {
        "https://raw.githubusercontent.com/Stanford-Health/wearipedia/HEAD/CONTRIBUTORS.md":
            {"text": "", "html": contributors_md},   # trafilatura found no <article> in a raw markdown file
    })

    class _EmailSpanLLM:
        async def complete(self, tier, prompt, model, *, phase=None, system=None):
            if tier == "T2":
                return model(picks=[])   # github_code is a forced pivot; picks are irrelevant
            if tier == "T3":
                assert "jane@berkeley.edu" in prompt   # the raw body, not the (empty) text, reached the LLM
                return model(tuples=[{"predicate": "email", "value": "jane@berkeley.edu",
                                      "span": "Jane Roe (jane@berkeley.edu)", "context_date": None}], links=[])
            if tier == "T4":
                return model(results=[])
            raise AssertionError(tier)

    findings = await expand(_resolution(cand), seed, deps, _EmailSpanLLM())

    email_claims = [c for c in findings.claims
                    if c.predicate == "email" and any(e.extraction_method == "github_code" for e in c.evidence)]
    assert email_claims and email_claims[0].value == "jane@berkeley.edu"


async def test_openalex_produces_publication_and_coauthor_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "EXPAND_CAP", 8)
    counters = _counters()
    cand = _cand()
    seed = _seed(schools=["MIT"])
    deps = _deps(tmp_path, counters, serper_results=[])
    author_result = {"id": "https://openalex.org/A1", "display_name": "Jane Roe",
                     "institutions": ["MIT"], "works_count": 5, "orcid": "0000-0001-2345-6789"}
    works_result = [{"title": "A Paper", "year": 2021, "doi": "10.1/x", "venue": "NeurIPS",
                     "coauthors": ["Jane Roe", "Alex Kim", "Bo Chen", "Extra Person"], "url": "10.1/x"}]
    deps.tools["openalex"] = FakeOpenAlex(counters, author_result, works_result)

    findings = await expand(_resolution(cand), seed, deps, FakeLLM(pick_n=4))

    pub_claims = [c for c in findings.claims if c.predicate == "publication"]
    assert len(pub_claims) == 1 and "A Paper" in pub_claims[0].value_raw
    coauthor_values = {c.value_raw for c in findings.claims
                       if c.predicate == "relationship" and c.value_raw.startswith("co_author:")}
    assert coauthor_values == {"co_author: Alex Kim", "co_author: Bo Chen", "co_author: Extra Person"}
    assert any(c.predicate == "other" and "ORCID" in c.value_raw for c in findings.claims)


async def test_openalex_author_none_yields_no_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "EXPAND_CAP", 6)
    counters = _counters()
    cand = _cand()
    seed = _seed(schools=["MIT"])
    deps = _deps(tmp_path, counters, serper_results=[])
    fake_openalex = FakeOpenAlex(counters, None)
    deps.tools["openalex"] = fake_openalex

    findings = await expand(_resolution(cand), seed, deps, FakeLLM(pick_n=4))

    assert fake_openalex.author_calls
    assert not any(c.predicate == "publication" for c in findings.claims)


async def test_handle_hygiene_press_page_yields_no_handle_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "EXPAND_CAP", 6)
    counters = _counters()
    yc_url = "https://ycombinator.com/companies/acme/people/jane-roe"
    cand = _cand(urls=[yc_url])
    seed = _seed()
    html = ("<html><body><p>Jane Roe is a software engineer.</p>"
            '<a href="https://twitter.com/ycombinator">tw</a>'
            '<a href="https://linkedin.com/in/christopher-price-1">li</a>'
            "</body></html>")
    deps = _deps(tmp_path, counters,
                pages={yc_url: {"url": yc_url, "html": html, "text": "Jane Roe is a software engineer."}},
                serper_results=[])

    findings = await expand(_resolution(cand), seed, deps, FakeLLM(pick_n=3))

    assert [c for c in findings.claims if c.predicate == "handle"] == []


async def test_handle_hygiene_personal_site_keeps_only_name_token_handles(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "EXPAND_CAP", 6)
    counters = _counters()
    site_url = "https://jane-roe.example"   # registrable-domain label "jane-roe"
    cand = _cand(urls=[site_url])
    seed = _seed()
    html = ("<html><body><p>Jane Roe is a software engineer.</p>"
            '<a href="https://twitter.com/janeroe">tw</a>'                       # his real handle
            '<a href="https://linkedin.com/in/christopher-price-1">li</a>'       # a relationship, no name token
            '<a href="https://x.com/jane-roe">x</a>'                             # equals the page's own domain label
            "</body></html>")
    deps = _deps(tmp_path, counters,
                pages={site_url: {"url": site_url, "html": html, "text": "Jane Roe is a software engineer."}},
                serper_results=[])

    findings = await expand(_resolution(cand), seed, deps, FakeLLM(pick_n=3))

    handle_claims = [c for c in findings.claims if c.predicate == "handle"]
    assert {c.value for c in handle_claims} == {"https://twitter.com/janeroe"}


async def test_two_hop_fetch_yields_trusted_owned_page_and_skips_namesake_link(tmp_path, monkeypatch):
    """The confirmed candidate's own page scores `trusted`; a page it links to whose
    text never mentions the name scores `skip` — no claims, no further page links."""
    monkeypatch.setattr(constants, "EXPAND_CAP", 8)
    counters = _counters()
    owned_url = "https://janeroe.dev"
    other_url = "https://otherdomain.example/article"
    owned_html = ('<html><body><p>Jane Roe is a software engineer.</p>'
                 f'<a href="{other_url}">unrelated</a></body></html>')
    cand = _cand(urls=[owned_url])
    seed = _seed()
    deps = _deps(tmp_path, counters, pages={
        owned_url: {"url": owned_url, "html": owned_html, "text": "Jane Roe is a software engineer."},
        other_url: {"url": other_url, "html": "", "text": "This article discusses cheese production in the 1990s."},
    }, serper_results=[])

    findings = await expand(_resolution(cand), seed, deps, FakeLLM(pick_n=4))

    assert not any(any(e.url == other_url for e in c.evidence) for c in findings.claims)
    events = _events(tmp_path, "attachment_test")
    owned_events = [e for e in events if e["url"] == owned_url]
    other_events = [e for e in events if e["url"] == other_url]
    assert owned_events and owned_events[0]["band"] == "trusted"
    assert other_events and other_events[0]["band"] == "skip"


async def test_middle_band_page_runs_t4_and_a_contradiction_drops_it_to_skip(tmp_path, monkeypatch):
    """A middle-band page (name only, no anchor category on the page's own text)
    triggers the T4 same-person check; a `contradicts` verdict overrides the score to
    ATTACH_CONTRADICTED. (`orgs=["mit.edu"]` only lifts the SERP hit over the
    frontier's relevance floor and gives `match_candidates` a non-empty seed anchor to
    test against — the fetched page's own text never mentions it, so it still scores
    name-only pre-T4.)"""
    monkeypatch.setattr(constants, "EXPAND_CAP", 15)
    counters = _counters()
    blog_url = "https://blog.example/post"
    cand = _cand()
    seed = _seed(orgs=["mit.edu"], schools=["MIT"])
    deps = _deps(tmp_path, counters,
                pages={blog_url: {"url": blog_url, "html": "", "text": "Jane Roe once wrote a blog post about gardening."}},
                serper_results=[{"url": blog_url, "title": "Jane Roe covers MIT robotics",
                                 "snippet": "community piece", "query": "q"}])

    class T4LLM:
        async def complete(self, tier, prompt, model, *, phase=None, system=None):
            if tier == "T2":
                ids = [line.split(" | ", 1)[0] for line in prompt.splitlines() if " | " in line]
                return model(picks=ids[:4])
            if tier == "T3":
                return model(tuples=[], links=[])
            if tier == "T4":
                return model(results=[{"cid": "page", "name": "exact",
                                       "employer": {"category": "contradicts", "sources": [1]}}])
            raise AssertionError(tier)

    findings = await expand(_resolution(cand), seed, deps, T4LLM())

    assert not any(any(e.url == blog_url for e in c.evidence) for c in findings.claims)
    blog_events = [e for e in _events(tmp_path, "attachment_test") if e["url"] == blog_url]
    assert blog_events and blog_events[0]["t4"] == "contradicts:employer"
    assert abs(blog_events[0]["score"] - constants.ATTACH_CONTRADICTED) < 1e-6
    assert blog_events[0]["band"] == "skip"
