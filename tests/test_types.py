"""Stage 0 gate: every model instantiates; Output round-trips; events discriminate."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pi
from pi.trace.events import parse_event
from pi.types import (
    AttrObservation, Candidate, Casefile, Claim, Confidence, Evidence, Findings,
    GraphEdge, GraphNode, Identity, Output, Profile, Resolution, Seed, Temporal,
    Term, Variant,
)
from _samples import all_sample_events


def _confidence() -> Confidence:
    return Confidence(score=0.91, logodds=2.31, terms=[Term(factor="prior", weight=-1.5)])


def test_core_models_instantiate():
    seed = Seed(input="henry wang, sixtyfour ai", regime="NAME_STRONG",
                names=[Variant(form="Henry Wang")], orgs=["sixtyfour ai"])
    cand = Candidate(cid="c1", score=_confidence(),
                     attrs={"employer": [AttrObservation(
                         value="Sixtyfour", source_class="official_org",
                         source_tier=2.5, url="https://sixtyfour.ai/team",
                         snippet="Henry Wang, ...")]})
    ev = Evidence(evidence_id="ev1", candidate_id="c1", url="https://x", snippet="s",
                  source_class="official_org", extraction_method="json_ld")
    claim = Claim(id="cl1", predicate="employer", value="sixtyfour.ai", value_raw="Sixtyfour AI",
                  temporal=Temporal(start=date(2024, 1, 1), end_state="ongoing", precision="month"),
                  confidence=_confidence(), identity_link="hard_key:github_handle", evidence=[ev])
    res = Resolution(status="confirmed", confirmed_cid="c1", candidates=[cand])
    node = GraphNode(id="person:c1", type="person", label="Henry Wang")
    edge = GraphEdge(id="e1", src="person:c1", dst="company:sixtyfour.ai",
                     type="employment", mechanism="team page")
    findings = Findings(nodes=[node], edges=[edge], claims=[claim])
    cf = Casefile(job_id="job1", input=seed.input, seed=seed, resolution=res, findings=findings)
    assert cf.job_id == "job1"
    assert cand.attrs["employer"][0].source_tier == 2.5  # Types′ carries the tier


def test_output_round_trips():
    out = Output(status="confirmed", input="henry wang",
                 identity=Identity(confidence=_confidence(), cid="c1"),
                 profile=Profile())
    blob = out.model_dump_json()
    again = Output.model_validate_json(blob)
    assert again.status == "confirmed"
    assert again.identity and again.identity.cid == "c1"


def test_every_event_serializes_and_discriminates():
    events = all_sample_events()
    seen_types = set()
    for e in events:
        data = json.loads(e.model_dump_json())
        parsed = parse_event(data)
        # discriminated back to the same concrete class
        assert type(parsed) is type(e), (type(parsed), type(e))
        seen_types.add(data["event_type"])
    # all 18 event types present
    assert len(seen_types) == 18


def test_package_exports():
    assert pi.__version__
    assert hasattr(pi, "Seed") and hasattr(pi, "Output") and hasattr(pi, "Deps")
