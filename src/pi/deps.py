"""Dependency injection seam + traced tool base.

`Deps` is constructor-injected into every phase and tool (the test seam — swap
`http`/`llm`/`cache` for fakes). `@traced` wraps an async tool method so every
call emits a `tool_call` event with latency and outcome, and enforces the tool's
provider semaphore + timeout.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from functools import wraps
from time import perf_counter
from typing import Any, Awaitable, Callable, Optional

from . import constants
from .trace.events import ToolCall
from .trace.writer import TraceWriter


@dataclass
class Deps:
    http: Any = None
    llm: Any = None
    cache: Any = None
    trace: Optional[TraceWriter] = None
    sqlite: Any = None
    semaphores: dict[str, asyncio.Semaphore] = field(default_factory=dict)

    @classmethod
    def build(cls, *, trace: TraceWriter | None = None, **kw: Any) -> "Deps":
        sems = {name: asyncio.Semaphore(n) for name, n in constants.SEMAPHORES.items()}
        return cls(trace=trace, semaphores=sems, **kw)

    def semaphore(self, name: str) -> asyncio.Semaphore:
        return self.semaphores.setdefault(name, asyncio.Semaphore(constants.SEMAPHORES.get(name, 4)))


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def traced(
    tool_name: str,
    *,
    provider: str | None = None,
    timeout: float | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorate an async Tool method. Emits a tool_call event; enforces the
    provider semaphore and timeout if the tool exposes `self.deps`.
    """
    def deco(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(fn)
        async def wrapper(self: "Tool", *args: Any, **kwargs: Any) -> Any:
            deps: Deps | None = getattr(self, "deps", None)
            start = perf_counter()
            ok, err, cache_hit = True, None, False

            async def _call() -> Any:
                return await fn(self, *args, **kwargs)

            try:
                if deps is not None and provider:
                    async with deps.semaphore(provider):
                        result = await asyncio.wait_for(_call(), timeout) if timeout else await _call()
                else:
                    result = await asyncio.wait_for(_call(), timeout) if timeout else await _call()
                cache_hit = bool(getattr(self, "_last_cache_hit", False))
                return result
            except Exception as e:  # noqa: BLE001 — traced then re-raised
                ok, err = False, f"{type(e).__name__}: {e}"
                raise
            finally:
                if deps is not None and deps.trace is not None:
                    deps.trace.emit(ToolCall(
                        event_id=_new_id(),
                        tool=tool_name,
                        args={k: _short(v) for k, v in kwargs.items()},
                        latency_ms=(perf_counter() - start) * 1000,
                        ok=ok,
                        error=err,
                        cache_hit=cache_hit,
                    ))
        return wrapper
    return deco


def _short(v: Any, limit: int = 120) -> Any:
    s = v if isinstance(v, (int, float, bool, type(None))) else str(v)
    if isinstance(s, str) and len(s) > limit:
        return s[:limit] + "…"
    return s


class Tool:
    """Base for all tools. Subclasses set `name` and decorate their async
    entrypoint with @traced. A missing key must raise ToolUnavailable, never 500.
    """
    name: str = "tool"

    def __init__(self, deps: Deps):
        self.deps = deps
        self._last_cache_hit = False


class ToolUnavailable(RuntimeError):
    """Raised when a tool's credential/config is missing. Callers degrade, not crash."""
