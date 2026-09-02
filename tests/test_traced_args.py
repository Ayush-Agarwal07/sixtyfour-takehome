"""@traced records positional arguments and counts calls."""
from __future__ import annotations

from pi.deps import Deps, Tool, traced
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
