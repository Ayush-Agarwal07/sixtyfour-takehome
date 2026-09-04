"""Dependency injection seam + traced tool base.

`Deps` is constructor-injected into every phase and tool (the test seam — swap
`http`/`llm`/`cache` for fakes). `@traced` wraps an async tool method so every
call emits a `tool_call` event with ALL arguments (positional included), latency
and outcome; enforces the provider semaphore + timeout; and counts the call in
`deps.counters["tool_calls"]` (the budget unit, C10).
"""
from __future__ import annotations

import asyncio
import inspect
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
    semaphores: dict[str, asyncio.Semaphore] = field(default_factory=dict)
    counters: dict[str, float] = field(default_factory=lambda: {"tool_calls": 0, "llm_calls": 0, "usd": 0.0, "cache_hits": 0})
    tools: dict[str, Any] = field(default_factory=dict)   # name -> Tool instance (serper, fetch, exa, company, github…)

    @classmethod
    def build(cls, *, trace: TraceWriter | None = None, **kw: Any) -> "Deps":
        sems = {name: asyncio.Semaphore(n) for name, n in constants.SEMAPHORES.items()}
        return cls(trace=trace, semaphores=sems, **kw)

    def semaphore(self, name: str) -> asyncio.Semaphore:
        return self.semaphores.setdefault(name, asyncio.Semaphore(constants.SEMAPHORES.get(name, 4)))

    # convenience accessors (tests construct Deps(http=client) and set tools ad hoc)
    def __getattr__(self, name: str) -> Any:
        tools = self.__dict__.get("tools") or {}
        if name in tools:
            return tools[name]
        raise AttributeError(name)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _short(v: Any, limit: int = 160) -> Any:
    if isinstance(v, (int, float, bool, type(None))):
        return v
    s = str(v)
    return s if len(s) <= limit else s[:limit] + "…"


def traced(
    tool_name: str,
    *,
    provider: str | None = None,
    timeout: float | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorate an async Tool method. Emits a tool_call event (with every
    argument), enforces the provider semaphore and timeout, counts the call."""
    def deco(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        sig = inspect.signature(fn)

        @wraps(fn)
        async def wrapper(self: "Tool", *args: Any, **kwargs: Any) -> Any:
            deps: Deps | None = getattr(self, "deps", None)
            try:
                bound = sig.bind(self, *args, **kwargs)
                bound.apply_defaults()
                logged = {k: _short(v) for k, v in bound.arguments.items() if k != "self"}
            except TypeError:
                logged = {**{f"arg{i}": _short(a) for i, a in enumerate(args)},
                          **{k: _short(v) for k, v in kwargs.items()}}
            start = perf_counter()
            ok, err = True, None
            self._last_cache_hit = False

            async def _call() -> Any:
                return await fn(self, *args, **kwargs)

            try:
                if deps is not None and provider:
                    async with deps.semaphore(provider):
                        return await asyncio.wait_for(_call(), timeout) if timeout else await _call()
                return await asyncio.wait_for(_call(), timeout) if timeout else await _call()
            except Exception as e:  # noqa: BLE001 — traced then re-raised
                ok, err = False, f"{type(e).__name__}: {e}"
                raise
            finally:
                hit = bool(getattr(self, "_last_cache_hit", False))
                if deps is not None:
                    deps.counters["tool_calls"] = deps.counters.get("tool_calls", 0) + 1
                    if hit:
                        deps.counters["cache_hits"] = deps.counters.get("cache_hits", 0) + 1
                    if deps.trace is not None:
                        deps.trace.emit(ToolCall(
                            event_id=_new_id(), tool=tool_name, args=logged,
                            latency_ms=(perf_counter() - start) * 1000,
                            ok=ok, error=err, cache_hit=hit,
                        ))
        return wrapper
    return deco


_NONE = {"__none__": True}


class Tool:
    """Base for all tools. Subclasses decorate their async entrypoint with
    @traced (which carries the tool name). A missing key must raise
    ToolUnavailable, never 500.
    """

    def __init__(self, deps: Deps):
        self.deps = deps
        self._last_cache_hit = False

    async def cached(self, ns: str, key: str, ttl: float | None, fn: Callable[[], Awaitable[Any]],
                      *, cache_none: bool = True) -> Any:
        """Cache-or-compute the 9-site get/check/set shape. A `None` from `fn`
        (the "not found" result) is cached too, via a sentinel, so replay
        (PI_OFFLINE=1) doesn't refetch and miss — unless `cache_none=False`
        (the negative isn't immutable, e.g. a rate-limit or "never archived")."""
        cache = self.deps.cache
        if cache is not None:
            hit = cache.get(ns, key)
            if hit is not None:
                self._last_cache_hit = True
                return None if hit == _NONE else hit
        val = await fn()
        if cache is not None and (val is not None or cache_none):
            cache.set(ns, key, val if val is not None else _NONE, ttl)
        self._last_cache_hit = False
        return val


class ToolUnavailable(RuntimeError):
    """Raised when a tool's credential/config is missing. Callers degrade, not crash."""
