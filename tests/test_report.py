"""report.md rendering: sections present, graph well-formed, nothing invented."""
from __future__ import annotations

import json
import re

from pi.report import render_report

_CLAIM = {
    "id": "cl1", "predicate": "employer", "value": "ramp.com", "value_raw": "Ramp",
    "temporal": {"start": "2023-01-01", "end": None, "end_state": "ongoing"},
    "confidence": {"score": 0.95, "logodds": 3.0, "terms": []},
    "attachment_confidence": 1.0, "identity_link": "hard_key:email",
    "evidence": [{"evidence_id": "e1", "candidate_id": "c1", "url": "https://ramp.com/team",
                  "snippet": "Andrew | Ramp", "source_class": "company_site",
                  "extraction_method": "json_ld"}],
}

_OUT = {
    "status": "confirmed", "input": "andrew.goering@ramp.com", "regime": "HARD_ID_EMAIL",
    "seed": {"names": [{"form": "Andrew Goering"}]},
    "identity": {"confidence": {"score": 0.987, "terms": []}, "cid": "c1",
                 "how_confirmed": "math P=0.987; T1 CONFIRM"},
    "summary": [{"text": "Andrew Goering works at Ramp.", "claim_ids": ["cl1"]}],
    "profile": {"current_role": None, "employment": [_CLAIM], "education": [], "location": None,
                "contact": [], "accounts": [], "public_output": [], "relationships": [],
                "notable": []},
    "graph": {
        "nodes": [{"id": "person:c1", "type": "person", "label": "Andrew Goering", "depth": 0,
                   "attachment_confidence": 1.0},
                  {"id": "company:ramp", "type": "company", "label": 'Ramp "Inc"', "depth": 1,
                   "attachment_confidence": 0.9}],
        "edges": [{"id": "e", "src": "person:c1", "dst": "company:ramp", "type": "employment",
                   "mechanism": "team page", "evidence_ids": ["e1"]}],
    },
    "timeline": [{"date": "2023-01", "text": "employment: Ramp", "claim_id": "cl1",
                  "url": "https://ramp.com/team"}],
    "conflicts": [], "negative_findings": [],
    "identity_resolution": {
        "candidates": [{"cid": "c1", "score": 0.987, "terms": [{"factor": "prior", "weight": 0.0}],
                        "urls": []}],
        "rejected": [{"cid": "c2", "reason": "different employer"},
                     {"cid": "c3", "reason": "below gate margin"},
                     {"cid": "c4", "reason": "below gate margin"}],
        "what_would_disambiguate": [],
    },
    "specialization_payoff": ["cl1"],
    "run_metadata": {"job_id": "andrew-goering-1", "stop_reason": "S2",
                     "budget": {"tool_calls": 6, "llm_calls": 4, "usd": 0.016, "seconds": 29.1}},
}


def _render(tmp_path, out=None):
    (tmp_path / "output.json").write_text(json.dumps(out or _OUT))
    return render_report(tmp_path).read_text()


def test_sections_and_facts_render(tmp_path):
    md = _render(tmp_path)
    for heading in ("# Andrew Goering", "## Summary", "## Employment", "## Timeline",
                    "## How it connects", "## Identity resolution", "## Run"):
        assert heading in md
    assert "CONFIRMED" in md
    assert "Ramp" in md and "2023-01-01 → now" in md
    assert "[ramp.com](https://ramp.com/team)" in md          # every fact keeps its source
    assert "0.95" in md                                        # and its confidence


def test_graph_is_wellformed_mermaid(tmp_path):
    body = re.search(r"```mermaid\n(.*?)```", _render(tmp_path), re.S).group(1)
    assert body.startswith("graph LR")
    ids = re.findall(r"^\s+(n\w+)[\(\[]", body, re.M)
    assert len(ids) == len(set(ids)) == 2                      # no id collision merges nodes
    assert '"Ramp \'Inc\'"' in body                            # quotes cannot break the label
    assert body.count("-->") == 1


def test_boilerplate_rejections_collapse_but_reasons_survive(tmp_path):
    md = _render(tmp_path)
    assert "different employer" in md
    assert md.count("below the gate margin") == 1
    assert "`c3`, `c4`" in md


def test_abstained_run_still_reports(tmp_path):
    out = dict(_OUT, status="abstained", summary=[], timeline=[],
               identity={"confidence": {"score": 0.0, "terms": []}, "cid": None,
                         "how_confirmed": "gate math not met"},
               graph={"nodes": [], "edges": []},
               profile={k: ([] if isinstance(v, list) else None) for k, v in _OUT["profile"].items()})
    md = _render(tmp_path, out)
    assert "ABSTAINED" in md
    assert "did not confirm an identity" in md
    assert "_No graph nodes._" in md


def test_failed_run_leads_with_the_error(tmp_path):
    out = dict(_OUT, status="failed", regime=None, summary=[], timeline=[],
               identity={}, graph={"nodes": [], "edges": []},
               run_metadata={"job_id": "x", "stop_reason": "error: ToolUnavailable: OPENROUTER_API_KEY",
                             "budget": {}})
    md = _render(tmp_path, out)
    assert "**FAILED**" in md
    assert "ToolUnavailable" in md and "Nothing below is a finding" in md
    assert "· None ·" not in md          # an absent regime is omitted, not printed as None
