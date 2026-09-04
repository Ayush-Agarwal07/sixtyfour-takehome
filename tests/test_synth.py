"""Phase 4 SYNTHESIZE: profile derivation, T2 summary citation gating, payoff, budget."""
from __future__ import annotations

from datetime import date

from pi.synth.synthesize import synthesize
from pi.types import (
    Candidate, Claim, Confidence, Evidence, Findings, Resolution, Seed, Slot,
    SummarySentence, Temporal, Variant,
)


class FakeLLM:
    """Returns the fixed set of sentences the test hands it."""

    def __init__(self, sentences: list[SummarySentence]):
        self.sentences = sentences

    async def complete(self, tier, prompt, model, *, phase=None, system=None):
        return model(summary=self.sentences, reasoning="ok")


class FailingLLM:
    async def complete(self, tier, prompt, model, *, phase=None, system=None):
        raise RuntimeError("upstream boom")


def _seed(**kw) -> Seed:
    kw.setdefault("input", "jane roe")
    kw.setdefault("regime", "NAME_STRONG")
    kw.setdefault("names", [Variant(form="Jane Roe")])
    return Seed(**kw)


def _cand(**kw) -> Candidate:
    kw.setdefault("cid", "c1")
    kw.setdefault("score", Confidence(score=0.9, logodds=2.0))
    return Candidate(**kw)


def _resolution(**kw) -> Resolution:
    kw.setdefault("status", "confirmed")
    kw.setdefault("confirmed_cid", "c1")
    kw.setdefault("candidates", [_cand()])
    return Resolution(**kw)


def _ev(**kw) -> Evidence:
    kw.setdefault("evidence_id", "ev1")
    kw.setdefault("candidate_id", "c1")
    kw.setdefault("url", "https://example.com/x")
    kw.setdefault("snippet", "s")
    kw.setdefault("source_class", "personal_site")
    kw.setdefault("extraction_method", "prose")
    return Evidence(**kw)


def _claim(id: str, predicate: str, value: str, *, score: float = 0.8, evidence=None, **kw) -> Claim:
    kw.setdefault("value_raw", value)
    kw.setdefault("confidence", Confidence(score=score, logodds=1.0))
    kw.setdefault("identity_link", "anchor_match:name")
    kw.setdefault("temporal", Temporal())
    return Claim(id=id, predicate=predicate, value=value, evidence=evidence or [_ev(evidence_id=id + "-ev")], **kw)


async def test_summary_drops_hallucinated_citation_keeps_real_one():
    claim = _claim("cl1", "title", "engineer")
    findings = Findings(claims=[claim])
    llm = FakeLLM([
        SummarySentence(text="Jane is an engineer.", claim_ids=["cl1"]),
        SummarySentence(text="Jane invented fire.", claim_ids=["nope-does-not-exist"]),
    ])
    out = await synthesize(_seed(), _resolution(), findings, "job1", llm=llm)
    assert [s.claim_ids for s in out.summary] == [["cl1"]]


async def test_current_role_prefers_ongoing_over_higher_confidence():
    not_ongoing = _claim("t1", "title", "founder", score=0.9, temporal=Temporal(end_state="ended"))
    ongoing = _claim("t2", "title", "engineer", score=0.5, temporal=Temporal(end_state="ongoing"))
    findings = Findings(claims=[not_ongoing, ongoing])
    out = await synthesize(_seed(), _resolution(), findings, "job1")
    assert out.profile.current_role is not None
    assert out.profile.current_role.id == "t2"


async def test_payoff_lists_github_emails_claim_only():
    gh = _claim("gh1", "email", "jane@ramp.com",
               evidence=[_ev(evidence_id="e1", extraction_method="github_emails", source_class="code_host")])
    plain = _claim("p1", "title", "engineer",
                  evidence=[_ev(evidence_id="e2", extraction_method="prose")])
    findings = Findings(claims=[gh, plain])
    out = await synthesize(_seed(), _resolution(), findings, "job1")
    assert out.specialization_payoff == ["gh1"]


async def test_abstained_resolution_has_empty_summary_and_no_negative_findings():
    resolution = _resolution(status="abstained", confirmed_cid=None, reason="ambiguous")
    seed = _seed(orgs=["Acme Corp"])
    llm = FakeLLM([SummarySentence(text="whatever", claim_ids=["x"])])
    out = await synthesize(seed, resolution, None, "job1", llm=llm)
    assert out.summary == []
    assert out.negative_findings == []


async def test_summarize_failure_yields_empty_summary_not_a_crash():
    claim = _claim("cl1", "title", "engineer")
    findings = Findings(claims=[claim])
    out = await synthesize(_seed(), _resolution(), findings, "job1", llm=FailingLLM())
    assert out.summary == []
    assert out.status == "confirmed"


async def test_open_slot_becomes_negative_finding_when_confirmed():
    findings = Findings(claims=[], slots=[Slot(name="education", target=1, current=0, closed=False)])
    out = await synthesize(_seed(), _resolution(), findings, "job1")
    assert any(n["predicate"] == "coverage" and n["slot"] == "education" and n["status"] == "not_found"
               for n in out.negative_findings)


async def test_timeline_sorted_ascending_with_precision_and_excludes_undated():
    early = _claim("t1", "employment", "Acme", temporal=Temporal(start=date(2013, 6, 1), precision="month"))
    late = _claim("t2", "title", "engineer", temporal=Temporal(start=date(2020, 1, 1), precision="year"))
    undated = _claim("t3", "location", "nyc")
    findings = Findings(claims=[late, early, undated])
    out = await synthesize(_seed(), _resolution(), findings, "job1")
    assert [(e.claim_id, e.date) for e in out.timeline] == [("t1", "2013-06"), ("t2", "2020")]


async def test_footprint_since_is_earliest_timeline_year():
    early = _claim("t1", "employment", "Acme", temporal=Temporal(start=date(2013, 6, 1), precision="month"))
    late = _claim("t2", "title", "engineer", temporal=Temporal(start=date(2020, 1, 1), precision="year"))
    findings = Findings(claims=[late, early])
    out = await synthesize(_seed(), _resolution(), findings, "job1")
    assert out.identity.footprint_since == "2013"


async def test_accounts_found_counts_distinct_handles_at_or_above_threshold():
    h1 = _claim("h1", "handle", "@jane", score=0.9)
    h2 = _claim("h2", "handle", "@jane_roe", score=0.5)
    h3 = _claim("h3", "handle", "@low", score=0.4)
    dup = _claim("h4", "handle", "@jane", score=0.9)
    findings = Findings(claims=[h1, h2, h3, dup])
    out = await synthesize(_seed(), _resolution(), findings, "job1")
    assert out.identity.accounts_found == 2


async def test_unverified_claim_excluded_from_profile_and_timeline():
    low = _claim("lo1", "employer", "Shadow Corp", attachment_confidence=0.6,
                temporal=Temporal(start=date(2020, 1, 1)))
    high = _claim("hi1", "employer", "Real Co", attachment_confidence=0.9,
                 temporal=Temporal(start=date(2021, 1, 1)))
    findings = Findings(claims=[low, high])
    out = await synthesize(_seed(), _resolution(), findings, "job1")
    assert [c.id for c in out.unverified] == ["lo1"]
    assert {c.id for c in out.profile.employment} == {"hi1"}
    assert {e.claim_id for e in out.timeline} == {"hi1"}


async def test_budget_keeps_run_totals_and_nests_resolve_numbers():
    counters = {"tool_calls": 40, "llm_calls": 3, "usd": 0.05}
    resolution = _resolution()
    resolution.budget = {"tool_calls": 12, "seconds": 5.0}
    out = await synthesize(_seed(), resolution, None, "job1", counters=counters, seconds=10.0)
    budget = out.run_metadata.budget
    assert budget["tool_calls"] == 40
    assert budget["resolve"] == {"tool_calls": 12, "seconds": 5.0}
    assert out.run_metadata.timings == {"seconds": 10.0}
