"""CLI entrypoint: `pi investigate "<target>"` · `pi render <run_dir>` · `pi report <run_dir>`."""
from __future__ import annotations

import asyncio
import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print('pi investigate "<freeform target>"  |  pi render <run_dir>  |  pi report <run_dir>')
        return 0
    if argv[0] == "investigate" and len(argv) > 1:
        from .run import investigate
        run_dir, output = asyncio.run(investigate(" ".join(argv[1:])))
        status = output.status if output else "failed"
        print(f"{status}  →  {run_dir}/output.json   "
              f"(report: {run_dir}/report.md · trace: {run_dir}/trace.md)")
        return 0
    if argv[0] == "render" and len(argv) > 1:
        from .trace.render import render_trace
        render_trace(argv[1])
        print(f"{argv[1]}/trace.md")
        return 0
    if argv[0] == "report" and len(argv) > 1:
        from .report import render_report
        print(render_report(argv[1]))
        return 0
    print(f"pi: unknown command '{argv[0]}'")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
