"""CLI entrypoint. `investigate` is wired (Stage 1); render/eval land later."""
from __future__ import annotations

import asyncio
import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print('pi investigate "<freeform target>"')
        return 0
    if argv[0] == "investigate" and len(argv) > 1:
        from .run import investigate
        run_dir, output = asyncio.run(investigate(" ".join(argv[1:])))
        status = output.status if output else "failed"
        print(f"{status}  →  {run_dir}/output.json   (trace: {run_dir}/trace.md)")
        return 0
    print(f"pi: unknown command '{argv[0]}'")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
