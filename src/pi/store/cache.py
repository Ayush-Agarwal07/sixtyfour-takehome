"""HTTP + LLM disk caches.

- http: keyed by normalized url, TTL by source class.
- llm: keyed by (model, sha256(prompt+schema)), no TTL.
PI_NO_CACHE=1 disables both (honest variance runs); PI_OFFLINE=1 makes a miss
raise (replay mode). diskcache is imported lazily so importing this module is
cheap and Stage 0 tests don't need the dep.
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
        self._http: Any = None
        self._llm: Any = None

    def _open(self, sub: str) -> Any:
        import diskcache  # lazy: only when caching is actually used

        return diskcache.Cache(str(self.root / sub))

    @property
    def http(self) -> Any:
        if self._http is None:
            self._http = self._open("http")
        return self._http

    @property
    def llm(self) -> Any:
        if self._llm is None:
            self._llm = self._open("llm")
        return self._llm

    # ---- http ----
    def get_http(self, url: str) -> Optional[Any]:
        if self.no_cache:
            return None
        val = self.http.get(normalize_url(url))
        if val is None and self.offline:
            raise CacheMiss(f"offline: no cached http for {url}")
        return val

    def set_http(self, url: str, value: Any, source_class: str = "aggregator") -> None:
        if self.no_cache:
            return
        ttl = CACHE_TTL_S.get(source_class, CACHE_TTL_S["aggregator"])
        self.http.set(normalize_url(url), value, expire=ttl)

    # ---- llm ----
    def get_llm(self, model: str, prompt: str, schema: str = "") -> Optional[Any]:
        if self.no_cache:
            return None
        val = self.llm.get(llm_key(model, prompt, schema))
        if val is None and self.offline:
            raise CacheMiss("offline: no cached llm response")
        return val

    def set_llm(self, model: str, prompt: str, value: Any, schema: str = "") -> None:
        if self.no_cache:
            return
        self.llm.set(llm_key(model, prompt, schema), value)  # no TTL
