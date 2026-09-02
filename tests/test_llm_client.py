"""Lenient JSON extraction + cost fallback (no network)."""
from __future__ import annotations

from types import SimpleNamespace

from pi.llm.client import LLM, _extract_json


def test_extract_json_variants():
    assert _extract_json('{"a": 1}') == '{"a": 1}'
    assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _extract_json('Sure: {"a": {"b": 2}} done') == '{"a": {"b": 2}}'


def test_cost_fallback_from_prices():
    llm = LLM(client=object(), counters={})
    usage = SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=0, model_extra={})
    llm._emit("anthropic/claude-sonnet-5", "T1", None, None, usage=usage, latency_ms=1, cache_hit=False, reasoning=None)
    assert round(llm.counters["usd"], 2) == 2.0 and llm.counters["llm_calls"] == 1
