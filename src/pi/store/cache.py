"""HTTP + LLM disk caches (diskcache, lazy).

- http: keyed by normalized url, TTL by source class.
- generic namespaces (search results, api responses): keyed by (ns, key).
- llm: keyed by (model, sha256(prompt+schema)), no TTL.
PI_NO_CACHE=1 disables all (honest variance runs); PI_OFFLINE=1 makes a miss raise
(replay mode).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Optional

from ..constants import CACHE_TTL_S
from .urlnorm import normalize_url


class CacheMiss(RuntimeError):
    """Raised on a miss when PI_OFFLINE=1 (replay mode)."""


def _flag(name: str) -> bool:
    return os.getenv(name, "0") == "1"


def llm_key(model: str, prompt: str, schema: str = "") -> str:
    h = hashlib.sha256((prompt + "\x00" + schema).encode("utf-8")).hexdigest()
    return f"{model}:{h}"


class Cache:
    def __init__(self, root: str | Path = ".cache"):
        self.root = Path(root)
        self.no_cache = _flag("PI_NO_CACHE")
        self.offline = _flag("PI_OFFLINE")
        self._stores: dict[str, Any] = {}

    def _open(self, sub: str) -> Any:
        import diskcache  # lazy
        if sub not in self._stores:
            self._stores[sub] = diskcache.Cache(str(self.root / sub))
        return self._stores[sub]

    # ---- generic ----
    def get(self, ns: str, key: str) -> Optional[Any]:
        if self.no_cache:
            return None
        val = self._open(ns).get(key)
        if val is None and self.offline:
            raise CacheMiss(f"offline: no cached {ns} for {key[:80]}")
        return val

    def set(self, ns: str, key: str, value: Any, ttl: Optional[float] = None) -> None:
        if self.no_cache:
            return
        self._open(ns).set(key, value, expire=ttl)

    # ---- http ----
    def get_http(self, url: str) -> Optional[Any]:
        return self.get("http", normalize_url(url))

    def set_http(self, url: str, value: Any, source_class: str = "unknown") -> None:
        ttl = CACHE_TTL_S.get(source_class, CACHE_TTL_S["unknown"])
        self.set("http", normalize_url(url), value, ttl)

    # ---- llm ----
    def get_llm(self, model: str, prompt: str, schema: str = "") -> Optional[Any]:
        return self.get("llm", llm_key(model, prompt, schema))

    def set_llm(self, model: str, prompt: str, value: Any, schema: str = "") -> None:
        self.set("llm", llm_key(model, prompt, schema), value, None)
