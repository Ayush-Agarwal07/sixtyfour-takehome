"""EXPAND extraction ladder — page/API payloads → predicate tuples.

Structured rungs (JSON-LD, GitHub profile/emails, Gravatar) need no span check;
`extract_prose` is the LLM fallback and its spans are checked at assembly time.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from ..resolve.links import extract_links as extract_links_html  # re-export
from ..sources import host_of

Tuple = tuple[str, str, str, str | None]     # (predicate, value_raw, span, context_date_raw)
LinkT = tuple[str, str, str]                 # (url, anchor_text, section)

__all__ = [
    "Tuple", "LinkT", "extract_jsonld", "extract_github_profile", "extract_github_emails",
    "extract_gravatar", "window_text", "extract_prose", "extract_links_html", "handle_of",
]

# platforms whose profile URL is exactly {host}/{handle} (or one fixed segment prefix below)
_HANDLE_ROOT_HOSTS = {
    "x.com", "twitter.com", "github.com", "behance.net", "dev.to", "instagram.com",
    "kaggle.com", "huggingface.co", "dribbble.com", "devpost.com",
}


def handle_of(url: str) -> str | None:
    """Bare handle from a KNOWN platform profile-URL shape only: last path segment,
    `@`/`/` stripped. None for anything else (a bare website root included — a
    website domain is not a handle; C17/handle hygiene/fix-round F2)."""
    host = host_of(url)
    parts = [p for p in urlsplit(url).path.split("/") if p]
    if not parts:
        return None
    if host.endswith("linkedin.com"):
        if len(parts) < 2 or parts[0] != "in":
            return None
    elif host.endswith("reddit.com"):
        if len(parts) < 2 or parts[0] != "user":
            return None
    elif host in ("medium.com", "youtube.com"):
        if not parts[0].startswith("@"):
            return None
    elif host not in _HANDLE_ROOT_HOSTS:
        return None
    h = parts[-1].strip("/").lstrip("@")
    return h or None

_EXTRACT_PROMPT = (Path(__file__).resolve().parent.parent / "llm" / "prompts" / "extract.md").read_text()

_FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "live.com", "icloud.com", "me.com", "proton.me", "protonmail.com", "aol.com",
}


def extract_jsonld(html: str) -> list[Tuple]:
    import extruct
    try:
        data = extruct.extract(html, syntaxes=["json-ld"], uniform=True)
    except Exception:  # noqa: BLE001
        return []
    out: list[Tuple] = []
    for it in data.get("json-ld", []):
        t = it.get("@type", "")
        is_person = (isinstance(t, str) and t.lower() == "person") or (isinstance(t, list) and "Person" in t)
        if not is_person:
            continue
        jt = it.get("jobTitle")
        if isinstance(jt, str) and jt.strip():
            out.append(("title", jt, jt, None))
        wf = it.get("worksFor")
        name = wf.get("name") if isinstance(wf, dict) else (wf if isinstance(wf, str) else None)
        if name:
            out.append(("employer", name, name, None))
        alumni = it.get("alumniOf")
        for a in (alumni if isinstance(alumni, list) else ([alumni] if alumni else [])):
            aname = a.get("name") if isinstance(a, dict) else (a if isinstance(a, str) else None)
            if aname:
                out.append(("education", aname, aname, None))
        addr = it.get("address")
        loc = addr.get("addressLocality") if isinstance(addr, dict) else None
        if loc:
            out.append(("location", loc, loc, None))
        email = it.get("email")
        if isinstance(email, str) and email.strip():
            out.append(("email", email, email, None))
        same_as = it.get("sameAs")
        for u in (same_as if isinstance(same_as, list) else ([same_as] if same_as else [])):
            if isinstance(u, str) and u.strip():
                out.append(("handle", u, u, None))
    return out


def extract_github_profile(p: dict) -> list[Tuple]:
    out: list[Tuple] = []
    company = (p.get("company") or "").strip().rsplit("@", 1)[-1].strip()
    if company:
        out.append(("employer", company, company, None))
    loc = (p.get("location") or "").strip()
    if loc:
        out.append(("location", loc, loc, None))
    blog = (p.get("blog") or "").strip()
    if blog:
        out.append(("website", blog, blog, None))
    email = (p.get("email") or "").strip()
    if email:
        out.append(("email", email, email, None))
    tw = (p.get("twitter_username") or "").strip()
    if tw:
        v = f"https://x.com/{tw}"
        out.append(("handle", v, v, None))
    bio = (p.get("bio") or "").strip()
    if bio:
        out.append(("other", bio, bio, None))
    return out


def extract_github_repos(repos: list[dict]) -> list[Tuple]:
    """`repos` is GitHub.repos output (non-forks): one `repo` tuple each, dated by last push."""
    out: list[Tuple] = []
    for r in repos:
        url = (r.get("html_url") or "").strip()
        if not url:
            continue
        span = f"{r.get('full_name') or url}: {r.get('description') or ''}".rstrip(": ")
        out.append(("repo", url, span, (r.get("pushed_at") or "")[:10] or None))
    return out


def extract_github_emails(entries: list[dict]) -> list[Tuple]:
    """`entries` is GitHub.commit_emails output: [{email, name, first, last, count}]."""
    out: list[Tuple] = []
    for e in entries:
        email = (e.get("email") or "").strip()
        if not email or "@" not in email:
            continue
        domain = email.rpartition("@")[2].lower()
        count, first, last = e.get("count", 0), e.get("first") or "", e.get("last") or ""
        span = f"{count} commits authored from {email} between {first} and {last}"
        if domain in _FREE_MAIL_DOMAINS:
            out.append(("email", email, span, None))
        else:
            out.append(("employment", domain, span, f"{first[:4]} – {last[:4]}"))
            out.append(("email", email, span, None))
    return out


def extract_gravatar(p: dict) -> list[Tuple]:
    out: list[Tuple] = []
    for a in p.get("accounts") or []:
        url = a.get("url") if isinstance(a, dict) else a
        if url:
            out.append(("handle", url, url, None))
    for url in p.get("urls") or []:
        if url:
            out.append(("website", url, url, None))
    return out


def window_text(text: str, names: list[str], radius: int = 1500, cap: int = 24000) -> str:
    """C14: keep ±radius chars around each name-variant occurrence, capped."""
    if not text:
        return ""
    low = text.lower()
    spans: list[tuple[int, int]] = []
    for n in names[:4]:
        for m in re.finditer(re.escape(n.lower()), low):
            spans.append((max(0, m.start() - radius), min(len(text), m.end() + radius)))
    if not spans:
        return text[:cap]
    spans.sort()
    merged = [spans[0]]
    for a, b in spans[1:]:
        if a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    out = "\n…\n".join(text[a:b] for a, b in merged)
    return out[:cap]


class _ExTuple(BaseModel):
    predicate: str
    value: str
    span: str = ""
    context_date: str | None = None


class _Extraction(BaseModel):
    tuples: list[_ExTuple] = Field(default_factory=list)
    links: list[dict] = Field(default_factory=list)
    reasoning: str = ""


async def extract_prose(text: str, seed, url: str, llm) -> tuple[list[Tuple], list[LinkT]]:
    names = [v.form for v in seed.names]
    prompt = (f"Target: {seed.input}\nName variants: {', '.join(names[:4])}\n"
              f"Employer anchor: {seed.orgs[:1]} Title anchor: {seed.titles[:1]}\nPage: {url}\n\n"
              f"Text:\n{window_text(text, names)}")
    ex = await llm.complete("T3", prompt, _Extraction, phase="expand", system=_EXTRACT_PROMPT)
    tuples: list[Tuple] = [(t.predicate, t.value, t.span, t.context_date) for t in ex.tuples]
    links: list[LinkT] = [(l.get("url", ""), l.get("anchor_text", ""), l.get("section", "prose"))
                          for l in ex.links if l.get("url")]
    return tuples, links
