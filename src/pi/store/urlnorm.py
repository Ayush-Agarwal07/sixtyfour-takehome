"""URL normalization for cache keys.

Blocklist not allowlist (reference-contracts §9): stripping an unknown param risks
the wrong page; keeping one costs at most a duplicate fetch. Store under the
normalized key, but always cite the ORIGINAL url in evidence.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..constants import TRACKING_PARAMS

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())

    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]

    # force https; keep only a non-default explicit port
    netloc = host
    if parts.port and str(parts.port) != _DEFAULT_PORTS["https"]:
        netloc = f"{host}:{parts.port}"

    # path: strip a trailing slash; treat root as empty for stable equality
    path = parts.path or ""
    if path in ("", "/"):
        path = ""
    elif path.endswith("/"):
        path = path.rstrip("/")

    # drop tracking params, sort the rest
    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    kept.sort()
    query = urlencode(kept)

    # drop fragment entirely
    return urlunsplit(("https", netloc, path, query, ""))


# ponytail: registrable_domain (eTLD+1) removed with the tldextract dep — no caller
# yet. Re-add a naive last-2-labels version in Stage 2 when corroboration needs a
# source-independence key. Multi-part TLDs (co.uk) will be imperfect; fine for scope.
