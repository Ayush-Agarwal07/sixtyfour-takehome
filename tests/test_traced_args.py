"""@traced records positional arguments and counts calls."""
from __future__ import annotations

from pi.deps import Deps, Tool, traced
from pi.store.cache import Cache
from pi.trace.writer import TraceWriter


class T(Tool):
    @traced("t.run", provider="fetch")
    async def run(self, q: str, num: int = 10):
        return q


async def test_positional_args_logged_and_counted(tmp_path):
    deps = Deps.build(trace=TraceWriter(tmp_path))
    await T(deps).run("hello world")
    line = (tmp_path / "trace.jsonl").read_text().strip().splitlines()[-1]
    assert '"q":"hello world"' in line and '"num":10' in line
    assert deps.counters["tool_calls"] == 1


class CachedNone(Tool):
    def __init__(self, deps):
        super().__init__(deps)
        self.calls = 0

    @traced("t.lookup", provider="fetch")
    async def lookup(self, key: str):
        async def _fn():
            self.calls += 1
            return None
        return await self.cached("ns", key, None, _fn)


async def test_cached_none_not_refetched_and_reports_hit(tmp_path):
    deps = Deps.build(cache=Cache(tmp_path / "cache"))
    t = CachedNone(deps)
    assert await t.lookup("k") is None
    assert await t.lookup("k") is None
    assert t.calls == 1
    assert t._last_cache_hit is True


async def test_cache_hit_still_counts_tool_calls_and_cache_hits(tmp_path):
    deps = Deps.build(trace=TraceWriter(tmp_path), cache=Cache(tmp_path / "cache"))
    t = CachedNone(deps)
    await t.lookup("k")
    await t.lookup("k")
    assert deps.counters["tool_calls"] == 2
    assert deps.counters["cache_hits"] == 1
