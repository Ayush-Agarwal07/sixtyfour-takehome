"""Source classification — the one place a URL becomes a source class and a tier.

Used by RESOLVE (identity anchors), EXPAND (claim confidence), caching (TTL), and
the trace. plan/reference-tables B1/B2. First match wins.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from . import constants

_SECOND_LEVEL = {"co", "com", "ac", "org", "gov", "edu", "net", "ne", "or"}
_TOKEN = re.compile(r"[a-z0-9]+")


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def registrable_domain(host: str) -> str:
    """Naive eTLD+1: last two labels, or three when the second-level label is a
    known public suffix under a 2-letter country code (co.uk, com.au)."""
    parts = host.lower().removeprefix("www.").split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _in(host: str, table: set[str]) -> bool:
    return any(host == h or host.endswith("." + h) for h in table)


def is_unfetchable(url: str) -> bool:
    return _in(host_of(url), constants.UNFETCHABLE_HOSTS)


def _name_tokens(names: list[str] | None) -> set[str]:
    out: set[str] = set()
    for n in names or []:
        for t in _TOKEN.findall(n.lower()):
            if len(t) >= 4:
                out.add(t)
    return out


def classify(url: str, *, anchor_domains: set[str] | None = None,
             names: list[str] | None = None) -> str:
    """Return one of constants.DOMAIN_CLASSES for `url`."""
    host = host_of(url)
    if not host:
        return "unknown"
    reg = registrable_domain(host)
    path = urlsplit(url).path.lower()

    if anchor_domains and (reg in anchor_domains or host in anchor_domains):
        return "company_site"
    if _in(host, constants.CODE_HOSTS):
        return "code_host"
    if _in(host, constants.PROFESSIONAL_NETWORK_HOSTS):
        return "professional_network"
    if _in(host, constants.SOCIAL_HOSTS):
        return "social"
    if _in(host, constants.GOVERNMENT_HOSTS) or host.endswith(".gov"):
        return "government_registry"
    if _in(host, constants.ACADEMIC_HOSTS) or host.endswith(".edu") or ".ac." in host or host.endswith(".ac.uk"):
        return "academic"
    if _in(host, constants.AGGREGATOR_HOSTS):
        return "aggregator"
    # self-published platforms: the person's own space on a shared host
    if _in(host, constants.PERSONAL_PLATFORM_HOSTS):
        if reg in ("medium.com", "substack.com") and not (path.startswith("/@") or host != reg):
            return "press"
        return "personal_site"
    if _in(host, constants.PRESS_HOSTS):
        return "press"
    toks = _name_tokens(names)
    label = reg.split(".")[0]
    if toks and any(t in label or label in t for t in toks if len(label) >= 3):
        return "personal_site"
    return "unknown"


def identity_tier(source_class: str) -> float:
    return constants.IDENTITY_TIER.get(source_class, constants.IDENTITY_TIER["unknown"])


def claim_tier(source_class: str) -> float:
    return constants.CLAIM_TIER.get(source_class, constants.CLAIM_TIER["unknown"])


_GH_RESERVED = {"orgs", "features", "topics", "trending", "sponsors", "marketplace",
                "explore", "login", "join", "about", "pricing", "search", "settings"}


def identity_key(url: str, *, names: list[str] | None = None) -> tuple[str, str] | None:
    """A URL that belongs to exactly one person → (platform, handle). Else None.
    linkedin.com/in/{slug}, github.com/{user}, x.com/{handle}, personal_site root."""
    host = host_of(url)
    parts = [p for p in urlsplit(url).path.split("/") if p]
    if host.endswith("linkedin.com") and len(parts) >= 2 and parts[0] == "in":
        return ("linkedin", parts[1].lower())
    if host == "github.com" and len(parts) == 1 and parts[0].lower() not in _GH_RESERVED:
        return ("github", parts[0].lower())
    if host in ("x.com", "twitter.com") and len(parts) == 1 and parts[0].lower() not in {"i", "home", "search", "hashtag"}:
        return ("x", parts[0].lower())
    if classify(url, names=names) == "personal_site":
        reg = registrable_domain(host)
        if reg in constants.PERSONAL_PLATFORM_HOSTS:
            # medium.com/@h, substack sub-domain, github.io user site → platform-scoped key
            if parts and parts[0].startswith("@"):
                return ("site", f"{reg}/{parts[0].lower()}")
            return ("site", host)
        return ("site", reg)
    return None


def is_rare_handle(handle: str, names: list[str] | None = None) -> bool:
    """C17: a handle is rare enough to merge across platforms when it is long,
    not a common word, and not just a bare first or last name."""
    h = re.sub(r"[-_.]", "", handle.lower())
    if len(h) < constants.RARE_HANDLE_MIN_LEN or h in constants.COMMON_HANDLE_WORDS:
        return False
    for n in names or []:
        toks = _TOKEN.findall(n.lower())
        if h in toks:
            return False
        if len(toks) >= 2:
            f, l = toks[0], toks[-1]
            if h in {f + l, l + f, f[0] + l, f + l[0], l + f[0], f[0] + l[0]}:
                return False      # jsmith, johns, smithj, johnsmith — the common handle patterns
    return True
