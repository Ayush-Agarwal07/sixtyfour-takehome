"""Phase 3 EXPAND — the agentic loop (Stage 3): frontier → planner → parallel
tool actions → extraction ladder → assembly → merge/score → slots/graph update,
repeated in batches of up to PLANNER_MAX_PICKS until S1-S5 stop.

Orchestrator context stays flat: only claims (~100 tokens each) flow to the
planner, never raw page text (Findings Quality: cost control).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import uuid
from collections import deque
from datetime import date
from time import perf_counter

from .. import constants
from ..resolve.match import match_candidates
from ..resolve.resolver import read_page
from ..score.claim_score import merge_claims, score_claim
from ..sources import classify, host_of, identity_key, registrable_domain
from ..trace.events import (
    AttachmentTest, BudgetUpdate, ConflictDetected, FrontierUpdate, PlannerDecision, Reinforce, SlotUpdate, Stop,
)
from ..types import Candidate, Claim, Confidence, Conflict, Evidence, Findings, FrontierItem, GraphNode, SourceText
from .anchors import Anchors
from .assemble import _sha16, assemble
from .extract import (
    _FREE_MAIL_DOMAINS, extract_github_emails, extract_github_profile, extract_github_repos, extract_gravatar,
    extract_jsonld, extract_links_html, extract_prose, handle_of,
)
from .frontier import Frontier
from .graph import Graph
from .planner import plan
from .slots import Slots

_HANDLE_RESERVED = {"share", "intent", "home", "login", "search"}

# cand.handles keys → the platform-profile URL template that key's bare value fills in.
# "site" (a personal-website domain) has none on purpose — a domain is not a handle
# (fix-round F2: a bare website must never reach the username prober).
_HANDLE_PLATFORM_URL = {
    "github": "https://github.com/{h}", "x": "https://x.com/{h}", "twitter": "https://x.com/{h}",
    "linkedin": "https://linkedin.com/in/{h}", "behance": "https://behance.net/{h}",
    "medium": "https://medium.com/@{h}", "devto": "https://dev.to/{h}", "dev.to": "https://dev.to/{h}",
    "reddit": "https://reddit.com/user/{h}", "instagram": "https://instagram.com/{h}",
    "youtube": "https://youtube.com/@{h}", "kaggle": "https://kaggle.com/{h}",
    "huggingface": "https://huggingface.co/{h}", "dribbble": "https://dribbble.com/{h}",
    "devpost": "https://devpost.com/{h}",
}
# probe-hit platforms whose "page" is the JSON the probe already fetched, not html
# to re-read (fix-round F3).
_JSON_PROBE_PLATFORMS = {"github", "reddit", "hackernews", "keybase"}


def _slug_has_name_token(slug: str, names: list[str]) -> bool:
    s = slug.lower()
    return any(len(tok) >= 3 and tok in s
              for n in names for tok in re.findall(r"[a-z0-9]+", n.lower()))


def _should_probe(h: str, names: list[str]) -> bool:
    """Probe rule (fix-round F2) — deliberately separate from sources.is_rare_handle,
    which is the cross-platform *merge* rule and blocks first+last concatenations to
    avoid over-merging. Here a concatenation like "saarthshah" IS probed: it's the
    person's actual main handle, not merge noise."""
    hl = h.lower()
    if len(hl) < constants.RARE_HANDLE_MIN_LEN or hl in constants.COMMON_HANDLE_WORDS:
        return False
    toks = {t for n in names for t in re.findall(r"[a-z0-9]+", n.lower())}
    return hl not in toks


def _email_employer_claim(seed, cid) -> Claim:
    """The email domain is a user-supplied hard id, not a page. Scored honestly:
    prior + seed tier, no extraction rung. Not a specialization payoff."""
    dom = seed.orgs[0]
    email = seed.hard_ids.get("email", "")
    ev = Evidence(evidence_id=_sha16("email" + dom), candidate_id=cid, url=f"mailto:{email}",
                  snippet=f"input email is at domain {dom}", source_class="seed", extraction_method="none")
    return Claim(id=_sha16("employer" + dom), predicate="employer", value=dom, value_raw=dom,
                 confidence=score_claim(source_class="seed", rung="none", predicate="employer"),
                 identity_link="hard_key:email", evidence=[ev])


def _identity_link_for(seed, cand, url: str) -> str:
    if seed.regime == "HARD_ID_URL" and url.rstrip("/").lower() in {u.rstrip("/").lower() for u in seed.hard_ids.values()}:
        return "hard_key:seed_url"
    if cand.reciprocal:
        return "hard_key:reciprocal_link"
    attrs = [a for a, obs in cand.attrs.items() if obs]
    return "anchor_match:" + ",".join(attrs) if attrs else "anchor_match:name"


def _evidence_on_node(e: Evidence, node_id: str) -> bool:
    if node_id.startswith("account:") and node_id.count(":") >= 2:
        val = node_id.split(":", 2)[2]
        return e.url == val or host_of(e.url) == host_of(val)
    if node_id.startswith("company:"):
        dom = node_id.split(":", 1)[1]
        h = host_of(e.url)
        return bool(h) and (registrable_domain(h) == dom or dom in h)
    return False


async def expand(resolution, seed, deps, llm, *, resolve_spent: int = 0, on_batch=None) -> Findings:
    cid = resolution.confirmed_cid
    cand = next(c for c in resolution.candidates if c.cid == cid)
    names = [v.form for v in seed.names]
    label = names[0] if names else seed.input
    root_id = f"person:{cid}"
    root = GraphNode(id=root_id, type="person", label=label, attachment_confidence=cand.score.score)
    graph = Graph(root)
    slots = Slots()
    frontier = Frontier()
    anchor_domains = seed.anchor_domains
    exa_ok = "exa" in deps.tools
    github_ok = "github" in deps.tools
    frontier.seed(cand, seed, exa_ok=exa_ok, github_ok=github_ok, anchor_domains=anchor_domains)

    cap = min(constants.EXPAND_CAP, constants.S3_TOTAL_TOOL_CALLS - resolve_spent)
    start_calls = deps.counters.get("tool_calls", 0)
    t0 = perf_counter()

    claims: list[Claim] = []
    if seed.regime == "HARD_ID_EMAIL" and seed.orgs:
        claims.append(_email_employer_claim(seed, cid))
    conflicts: list[Conflict] = []
    emitted_conflicts: set[tuple[str, tuple[str, ...]]] = set()
    link_depth: dict[str, int] = {}
    last_batch_claims: list[Claim] = []

    # ── same-person test (DESIGN.md §13): every new source is scored
    # against this anchor set before its tuples are assembled.
    def _norm(u: str) -> str:
        return u.rstrip("/").lower()

    anchors = Anchors(seed, cand)
    owned_urls = {_norm(u) for u in cand.urls}
    if seed.hard_ids.get("url"):
        owned_urls.add(_norm(seed.hard_ids["url"]))
    trusted_urls = set(owned_urls)
    link_parent: dict[str, str] = {}
    middle: dict[str, str] = {}          # url -> text, for the post-merge re-score
    contradicted: set[str] = set()
    t4_used = 0

    def _band(p: float) -> str:
        if p < constants.ATTACH_SKIP:
            return "skip"
        if p < constants.ATTACH_PROFILE:
            return "unverified"
        if p < constants.ATTACH_TRUSTED:
            return "profile"
        return "trusted"

    # ── new-tool pivots (Task B + fix-round F1): usernames/openalex/github_code/
    # discovered-email-gravatar are FORCED actions, never ranked on the planner
    # frontier — the formula buried them for 8 batches (relevance*class_prior/cost
    # loses to cheap high-relevance fetches). `pending_pivots` is drained by the
    # batch loop directly, ≤2 per batch, ahead of the planner's own picks.
    pending_pivots: deque[FrontierItem] = deque()
    enqueued_handles: set[str] = set()
    enqueued_emails: set[str] = set()
    openalex_done = False
    github_code_email_done = False

    def _maybe_probe_handle(h: str) -> None:
        if not h or h in enqueued_handles or len(enqueued_handles) >= constants.PROBE_MAX_HANDLES_PER_RUN:
            return
        if not _should_probe(h, names):
            return
        enqueued_handles.add(h)
        args = {"handle": h}
        pending_pivots.append(FrontierItem(id=frontier.key("username_probe", args), action="username_probe",
                                           args=args, origin="link", relevance=0.85, open_slot="identity_anchors",
                                           why=f"pivot on discovered username {h}"))

    def _maybe_enqueue_openalex(reason: str) -> None:
        nonlocal openalex_done
        if openalex_done or not names:
            return
        openalex_done = True
        hints = (list(seed.schools) + [c.value for c in claims if c.predicate in ("employer", "employment")]
                + [c.value for c in claims if c.predicate in ("education", "publication")])
        args = {"name": names[0], "hints": hints}
        predicted = constants.CLASS_SLOTS.get("academic", [])
        pending_pivots.append(FrontierItem(id=frontier.key("openalex", args), action="openalex", args=args,
                                           origin="link", relevance=0.85,
                                           open_slot=predicted[0] if predicted else None, why=reason))

    def _enqueue_github_code(q: str, why: str) -> None:
        predicted = constants.CLASS_SLOTS.get("code_host", [])
        pending_pivots.append(FrontierItem(id=frontier.key("github_code", {"q": q}), action="github_code",
                                           args={"q": q}, origin="link", relevance=0.85,
                                           open_slot=predicted[0] if predicted else None, why=why))

    # confirmed candidate's own handles, at start — only from a KNOWN platform key
    # (fix-round F2): cand.handles["site"] is a website domain, not a handle, and
    # has no template below, so it is never fed to the prober.
    for key, h in cand.handles.items():
        tmpl = _HANDLE_PLATFORM_URL.get(key.lower())
        if not tmpl:
            continue
        derived = handle_of(tmpl.format(h=h))
        if derived:
            _maybe_probe_handle(derived)
    if seed.schools:
        _maybe_enqueue_openalex("seed schools present")
    if names and os.getenv("GITHUB_PAT"):
        _enqueue_github_code(f'"{names[0]}"', f"pivot on code search for {names[0]}")

    async def _attachment(url: str, text: str, *, owned: bool = False, linked: bool | None = None,
                          depth: int = 1) -> tuple[float, str]:
        """Same-person test → (attachment, identity_link). Emits AttachmentTest."""
        nonlocal t4_used
        linked_v = (_norm(link_parent.get(url, "")) in trusted_urls) if linked is None else linked
        p, matched, identity = anchors.score(text, url=url, owned=owned, linked=linked_v)
        t4: str | None = None
        if constants.ATTACH_SKIP <= p < constants.ATTACH_PROFILE and not owned and t4_used < constants.ATTACH_T4_MAX and text:
            t4_used += 1
            page_cand = Candidate(cid="page", score=Confidence(score=0.0, logodds=0.0),
                                  sources=[SourceText(url=url, kind="page",
                                                      source_class=classify(url, anchor_domains=anchor_domains, names=names),
                                                      tier=1.0, text=text[:1500])])
            updates = {}
            if not seed.orgs and anchors.raw["employer"]:
                updates["orgs"] = anchors.raw["employer"][:1]
            if not seed.schools and anchors.raw["school"]:
                updates["schools"] = anchors.raw["school"][:1]
            if not seed.locations and anchors.raw["location"]:
                updates["locations"] = anchors.raw["location"][:1]
            seed_m = seed.model_copy(update=updates)
            try:
                await match_candidates(seed_m, [page_cand], llm)
                hit = next((t for t in page_cand.negatives if t.factor.startswith("contradicts:")), None)
                # contradicts:title doesn't condemn a page — titles change, employer/education/location don't
                if hit is not None and hit.factor in ("contradicts:employer", "contradicts:education", "contradicts:location"):
                    p = constants.ATTACH_CONTRADICTED
                    contradicted.add(url)
                    t4 = hit.factor
                elif hit is not None:
                    t4 = hit.factor
                else:
                    t4 = "no_contradiction"
            except Exception:  # noqa: BLE001 — a bad T4 call never blocks attachment
                t4 = "t4_error"

        band = _band(p)
        if p >= constants.ATTACH_TRUSTED:
            trusted_urls.add(_norm(url))
        # a page a contradiction condemned stays out even when a later action re-reads it
        if constants.ATTACH_SKIP <= p < constants.ATTACH_PROFILE and url not in contradicted and len(middle) < 20:
            middle[url] = text[:20_000]

        if deps.trace:
            deps.trace.emit(AttachmentTest(event_id=uuid.uuid4().hex[:16], phase="expand", url=url,
                                           score=round(p, 3), matched=matched,
                                           name_present=identity,  # name, or the person's own email/personal domain in the body
                                           owned=owned, linked=linked_v, t4=t4, band=band))

        if owned:
            identity_link = _identity_link_for(seed, cand, url)
        elif matched:
            identity_link = "anchor_match:" + ",".join(matched)
        else:
            identity_link = f"graph_path:{depth}"
        return p, identity_link

    async def run_action(item: FrontierItem) -> dict | None:
        """Execute one frontier action. Any failure → None (@traced already logged
        the ToolCall)."""
        try:
            if item.action in ("fetch", "exa_contents"):
                url = item.args["url"]
                page = await read_page(url, deps)
                if not page or not page.get("text"):
                    return None
                html = page.get("html") or ""
                text = page["text"]
                owned = item.why == "confirmed candidate page" or _norm(url) in owned_urls
                att, ident = await _attachment(url, text, owned=owned, depth=link_depth.get(url, 1))
                if att < constants.ATTACH_SKIP:
                    return None
                tuples = extract_jsonld(html) if html else []
                rung = "json_ld"
                if not tuples:
                    tuples, _links = await extract_prose(text, seed, url, llm)
                    rung = "prose_llm"
                sc = classify(url, anchor_domains=anchor_domains, names=names)
                new_claims, new_nodes, new_edges = assemble(
                    tuples, url=url, text=text, cid=cid, rung=rung, source_class=sc,
                    identity_link=ident, seed=seed, today=date.today(), attachment=att)
                return {"claims": new_claims, "nodes": new_nodes, "edges": new_edges,
                        "page": {"url": url, "html": html}, "attachment": att, "identity_link": ident}

            if item.action == "github":
                login = item.args["login"]
                profile = await deps.github.profile(login)
                if not profile:
                    return None
                owned = login.lower() == (cand.handles.get("github") or "").lower()
                url = profile.get("html_url") or f"https://github.com/{login}"
                att, ident = await _attachment(url, json.dumps(profile), owned=owned)
                if att < constants.ATTACH_SKIP:
                    return None
                tuples = extract_github_profile(profile)
                new_claims, new_nodes, new_edges = assemble(
                    tuples, url=url, text="", cid=cid, rung="site_parser", source_class="code_host",
                    identity_link=ident, seed=seed, today=date.today(),
                    method="github_api", attachment=att)
                repos = await deps.github.repos(login, 3)
                for r in repos:
                    r_tuples = extract_github_repos([r])
                    if not r_tuples:
                        continue
                    r_claims, r_nodes, r_edges = assemble(
                        r_tuples, url=r["html_url"], text="", cid=cid, rung="site_parser",
                        source_class="code_host", identity_link=ident, seed=seed, today=date.today(),
                        method="github_api", attachment=att)
                    new_claims += r_claims
                    new_nodes += r_nodes
                    new_edges += r_edges
                # inline, not enqueued: commit-email → employer is the specialization
                # payoff (Findings Quality), and a queued frontier item never got picked.
                for r in repos[:2]:
                    full_name = r.get("full_name")
                    if not full_name:
                        continue
                    entries = await deps.github.commit_emails(full_name, login)
                    if not entries:
                        continue
                    email_tuples = extract_github_emails(entries)
                    repo_url = f"https://github.com/{full_name}"
                    e_claims, e_nodes, e_edges = assemble(
                        email_tuples, url=repo_url, text="", cid=cid, rung="site_parser", source_class="code_host",
                        identity_link=ident, seed=seed, today=date.today(),
                        method="github_emails", attachment=att)
                    new_claims += e_claims
                    new_nodes += e_nodes
                    new_edges += e_edges
                return {"claims": new_claims, "nodes": new_nodes, "edges": new_edges,
                        "attachment": att, "identity_link": ident}

            if item.action == "gravatar":
                email = item.args["email"]
                profile = await deps.gravatar.profile(email)
                if not profile:
                    return None
                h = hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()
                url = f"https://gravatar.com/{h}"
                linked = email in anchors.terms["email"] or email in seed.hard_ids.values()
                att, ident = await _attachment(url, json.dumps(profile), linked=linked)
                if att < constants.ATTACH_SKIP:
                    return None
                tuples = extract_gravatar(profile)
                new_claims, new_nodes, new_edges = assemble(
                    tuples, url=url, text="", cid=cid, rung="site_parser", source_class="personal_site",
                    identity_link=ident, seed=seed, today=date.today(),
                    method="gravatar", attachment=att)
                account_links = [(a.get("url") if isinstance(a, dict) else a, "", "prose")
                                for a in (profile.get("accounts") or [])
                                if (a.get("url") if isinstance(a, dict) else a)]
                if account_links:
                    frontier.from_links(url, account_links, att, names=names,
                                       anchor_domains=anchor_domains, exa_ok=exa_ok)
                    for link_url, _t, _s in account_links:
                        link_depth.setdefault(link_url, 2)
                        link_parent.setdefault(link_url, url)
                return {"claims": new_claims, "nodes": new_nodes, "edges": new_edges,
                        "attachment": att, "identity_link": ident}

            if item.action == "username_probe":
                handle = item.args["handle"]
                hits = await deps.usernames.probe(handle)
                new_claims, new_nodes, new_edges = [], [], []
                verify_budget = 8   # fix-round F3: cap page/JSON reads per probe
                for hit in hits:
                    url = hit.get("url") or ""
                    if not url:
                        continue
                    text = ""
                    if verify_budget > 0:
                        verify_budget -= 1
                        if hit.get("platform", "") in _JSON_PROBE_PLATFORMS:
                            body = hit.get("body")
                            text = json.dumps(body) if body else ""
                        else:
                            page = await read_page(url, deps)
                            text = (page or {}).get("text") or ""
                    att, ident = await _attachment(url, text)
                    if att < constants.ATTACH_SKIP:
                        continue
                    snippet = f"username match; same-person test {att:.2f}"
                    tup = [("handle", url, snippet, hit.get("created") or None)]
                    c, n, e = assemble(
                        tup, url=url, text="", cid=cid, rung="site_parser", source_class=classify(url),
                        identity_link=ident, seed=seed, today=date.today(),
                        method="username_probe", attachment=att)
                    new_claims += c
                    new_nodes += n
                    new_edges += e
                return {"claims": new_claims, "nodes": new_nodes, "edges": new_edges}

            if item.action == "github_code":
                q = item.args["q"]
                hits = await deps.github.code_search(q, 6)
                login = (cand.handles.get("github") or "").lower()
                candidates = [h for h in hits
                             if not (login and h.get("repo", "").split("/")[0].lower() == login)]
                new_claims, new_nodes, new_edges = [], [], []
                for hit in candidates[:2]:
                    raw_url = hit.get("raw_url") or ""
                    if not raw_url:
                        continue
                    page = await deps.fetch.get(raw_url)
                    if not page:
                        continue
                    # fix-round F4: raw.githubusercontent.com serves plain text/markdown,
                    # not html — trafilatura's extractor finds no <article> and returns ""
                    # for it, so fall back to the raw fetched body for these files.
                    text = page.get("text") or page.get("html") or ""
                    if not text:
                        continue
                    url = hit.get("html_url") or raw_url
                    att, ident = await _attachment(url, text)
                    if att < constants.ATTACH_SKIP:
                        continue
                    tuples, _links = await extract_prose(text, seed, raw_url, llm)
                    c, n, e = assemble(
                        tuples, url=url, text=text, cid=cid,
                        rung="prose_llm", source_class="code_host", identity_link=ident,
                        seed=seed, today=date.today(), method="github_code", attachment=att)
                    new_claims += c
                    new_nodes += n
                    new_edges += e
                return {"claims": new_claims, "nodes": new_nodes, "edges": new_edges}

            if item.action == "openalex":
                name = item.args["name"]
                author = await deps.openalex.author(name, item.args.get("hints") or [])
                if author is None:
                    return None
                works = await deps.openalex.works(author.get("id"), 5)
                coauthors = (works[0].get("coauthors") or []) if works else []
                text = (f"{author.get('display_name')}; institutions: {', '.join(author.get('institutions') or [])}; "
                        f"works: {'; '.join((w.get('title') or '') + ' ' + str(w.get('venue') or '') for w in works)}; "
                        f"coauthors: {', '.join(coauthors)}")
                url = author.get("id") or ""
                att, ident = await _attachment(url, text)
                if att < constants.ATTACH_SKIP:
                    return None
                new_claims, new_nodes, new_edges = [], [], []

                def _add(tup, *, url: str) -> None:
                    c, n, e = assemble(
                        [tup], url=url, text="", cid=cid, rung="site_parser", source_class="academic",
                        identity_link=ident, seed=seed, today=date.today(),
                        method="openalex", attachment=att)
                    new_claims.extend(c)
                    new_nodes.extend(n)
                    new_edges.extend(e)

                for w in works:
                    title = w.get("title") or ""
                    if not title:
                        continue
                    span = f"{title} ({w.get('year')}, {w.get('venue')})"
                    _add(("publication", title, span, str(w["year"]) if w.get("year") else None),
                         url=w.get("url") or "")
                if works:
                    kept = 0
                    for coauthor in coauthors:
                        if kept >= 3:
                            break
                        if not coauthor or coauthor == author.get("display_name"):
                            continue
                        kept += 1
                        value_raw = f"co_author: {coauthor}"
                        _add(("relationship", value_raw, value_raw, None), url=works[0].get("url") or "")
                orcid = author.get("orcid")
                if orcid:
                    value_raw = f"ORCID {orcid}"
                    _add(("other", value_raw, value_raw, None), url=author.get("id") or "")
                return {"claims": new_claims, "nodes": new_nodes, "edges": new_edges}

            if item.action == "wayback":
                url = item.args["url"]
                snap = await deps.wayback.snapshot(url, item.args.get("year"))
                if not snap or not snap.get("text"):
                    return None
                ts = snap.get("timestamp") or ""
                try:
                    snap_date = date(int(ts[:4]), int(ts[4:6]), int(ts[6:8])) if len(ts) >= 8 else date.today()
                except ValueError:
                    snap_date = date.today()
                owned = item.why == "confirmed candidate page" or _norm(url) in owned_urls
                att, ident = await _attachment(url, snap["text"], owned=owned, depth=link_depth.get(url, 1))
                if att < constants.ATTACH_SKIP:
                    return None
                tuples, _links = await extract_prose(snap["text"], seed, url, llm)
                sc = classify(url, anchor_domains=anchor_domains, names=names)
                new_claims, new_nodes, new_edges = assemble(
                    tuples, url=url, text=snap["text"], cid=cid, rung="prose_llm", source_class=sc,
                    identity_link=ident, seed=seed, today=snap_date,
                    method="wayback", attachment=att)
                return {"claims": new_claims, "nodes": new_nodes, "edges": new_edges,
                        "page": {"url": url, "html": snap.get("html") or ""}, "attachment": att, "identity_link": ident}

            if item.action == "search":
                results = await deps.serper.search(item.args["q"], 8)
                frontier.from_serp(results, names=names, anchor_domains=anchor_domains, exa_ok=exa_ok)
                return None

            if item.action == "verify":
                node_id = item.args.get("node_id", "")
                node_label = item.args.get("label") or (graph.nodes[node_id].label if node_id in graph.nodes else "")
                cur = graph.attachment(node_id)
                fetchable = None
                if node_id.startswith("account:") and node_id.count(":") >= 2:
                    fetchable = node_id.split(":", 2)[2]
                elif node_id.startswith("company:"):
                    dom = node_id.split(":", 1)[1]
                    if "." in dom and " " not in dom:
                        fetchable = f"https://{dom}"
                if fetchable:
                    page = await read_page(fetchable, deps)
                    text = (page or {}).get("text") or ""
                    new_att, _ = await _attachment(fetchable, text)
                else:
                    results = await deps.serper.search(f'"{label}" "{node_label}"', 5)
                    if results:
                        new_att = anchors.score(" ".join((r.get("title") or "") + " " + (r.get("snippet") or "")
                                                          for r in results[:5]), url="")[0]
                    else:
                        new_att = min(cur, 0.3)
                graph.set_attachment(node_id, new_att)
                if deps.trace:
                    deps.trace.emit(Reinforce(event_id=uuid.uuid4().hex[:16], node_id=node_id,
                                              descendants=graph.descendants(node_id), attachment=new_att))
                for c in claims:
                    if any(_evidence_on_node(e, node_id) for e in c.evidence):
                        c.attachment_confidence = new_att
                return None

            return None
        except Exception:  # noqa: BLE001 — a ToolCall event already recorded the failure
            return None

    stop_reason: str | None = None
    empty_batches = 0
    batch_count = 0
    barren_streak = 0
    while True:
        frontier.reinforce(graph)
        ranked = frontier.rank(slots)
        # fix-round F1: pivots are never on the ranked frontier at all — pull up to 2
        # straight from the queue so they cannot be starved by the relevance/cost formula.
        pivot_batch = [pending_pivots.popleft() for _ in range(min(2, len(pending_pivots)))]

        if not ranked and not pivot_batch:
            stop_reason = "S1" if slots.all_closed() else "S_frontier_empty"
            break

        if ranked:
            budget = {"tool_calls_left": max(0, cap - int(deps.counters.get("tool_calls", 0) - start_calls))}
            out = await plan(ranked=ranked, slots=slots, graph=graph, last_claims=last_batch_claims,
                             conflicts=conflicts, budget=budget, llm=llm, deps=deps, frontier=frontier,
                             pivots=pivot_batch)
            if out.stop and not pivot_batch:
                stop_reason = "S5_planner"
                break

            item_by_id = {item.id: item for item, _ in ranked}
            chosen = [item_by_id[i] for i in out.picks if i in item_by_id]
            # plan() already normalized args and registered survivors via frontier.add —
            # look them up by the same key so `chosen` uses the frontier's own item (real,
            # deduped id) rather than a parallel ad-hoc one.
            for a in out.new_actions:
                new_item = frontier.items.get(frontier.key(a.get("tool"), a.get("args") or {}))
                if new_item is not None:
                    chosen.append(new_item)
            chosen_ids = {c.id for c in chosen}
            forced = [it for it in frontier.forced() if it.id not in chosen_ids]
            # pivots first: forced, ahead of the planner's own picks (F1).
            chosen = pivot_batch + forced + chosen
            chosen_ids = {c.id for c in chosen}
            frontier.skipped([item.id for item, _ in ranked
                              if item.origin == "reinforce" and item.id not in chosen_ids])
            chosen = chosen[: constants.PLANNER_MAX_PICKS]

            for name in out.close_slots:
                slot = slots.slots.get(name)
                if slot is not None:
                    slot.closed = True
        else:
            # frontier is empty but pivots remain: run them without spending a planner call.
            chosen = pivot_batch
            if deps.trace:
                deps.trace.emit(PlannerDecision(
                    event_id=uuid.uuid4().hex[:16], phase="expand", note="frontier empty; forced pivot batch",
                    formula_top=[],
                    chosen=[{"id": it.id, "action": it.action, "args": it.args, "origin": "pivot"}
                            for it in pivot_batch],
                    new_actions=[]))

        if not chosen:
            empty_batches += 1
            if empty_batches >= 2:
                stop_reason = "S5_planner"
                break
            continue
        empty_batches = 0
        batch_count += 1

        if deps.trace:
            deps.trace.emit(FrontierUpdate(event_id=uuid.uuid4().hex[:16], added=len(frontier.items),
                                           top=[{"id": it.id, "action": it.action, "score": sc}
                                                for it, sc in ranked[:4]]))

        results = await asyncio.gather(*(run_action(it) for it in chosen), return_exceptions=True)

        prev_ids = {c.id for c in claims}
        batch_new: list[Claim] = []
        for item, result in zip(chosen, results):
            if isinstance(result, BaseException):
                result = None
            new = result.get("claims", []) if result else []
            assert all(e.candidate_id == cid for c in new for e in c.evidence)
            claims.extend(new)
            batch_new.extend(new)
            if result:
                for n in result.get("nodes", []):
                    graph.add_node(n)
                for e in result.get("edges", []):
                    graph.add_edge(e)
            frontier.note_result(item, len(new))
            page = result.get("page") if result else None
            if page and page.get("html"):
                page_url = page["url"]
                links = extract_links_html(page["html"], page_url)
                attach = result.get("attachment", 0.0)
                cur_depth = link_depth.get(page_url, 1)
                if cur_depth < constants.DEPTH_CAP:
                    frontier.from_links(page_url, links, attach, names=names,
                                       anchor_domains=anchor_domains, exa_ok=exa_ok)
                    for link_url, _t, _s in links:
                        link_depth.setdefault(link_url, cur_depth + 1)
                        link_parent.setdefault(link_url, page_url)
                page_sc = classify(page_url, anchor_domains=anchor_domains, names=names)
                if page_sc in ("personal_site", "code_host", "professional_network") and \
                        attach >= constants.ATTACH_TRUSTED:
                    # a page that IS the confirmed candidate's own: harvest a handle
                    # claim straight from its identity-bearing social/professional_network
                    # links instead of ever enqueueing them as frontier fetch/verify noise.
                    # Hygiene: drop a link whose handle is really the page's own domain label
                    # or a UI path (the YC page / Behance footer polluted handles this way),
                    # and a LinkedIn /in/ slug with no name token (a relationship, not his handle).
                    page_label = registrable_domain(host_of(page_url)).split(".")[0].lower()
                    handle_tuples = []
                    for link_url, _t, _s in links:
                        if classify(link_url, anchor_domains=anchor_domains, names=names) \
                                not in ("social", "professional_network"):
                            continue
                        ik = identity_key(link_url, names=names)
                        if ik is None:
                            continue
                        h = handle_of(link_url)
                        if not h or h.lower() == page_label or h.lower() in _HANDLE_RESERVED:
                            continue
                        if ik[0] == "linkedin" and not _slug_has_name_token(h, names):
                            continue
                        handle_tuples.append(("handle", link_url, link_url, None))
                    if handle_tuples:
                        ident = result.get("identity_link", "graph_path:1")
                        h_claims, h_nodes, h_edges = assemble(
                            handle_tuples, url=page_url, text="", cid=cid, rung="site_parser",
                            source_class=page_sc, identity_link=ident,
                            seed=seed, today=date.today(), method="link", attachment=attach)
                        claims.extend(h_claims)
                        batch_new.extend(h_claims)
                        for n in h_nodes:
                            graph.add_node(n)
                        for e in h_edges:
                            graph.add_edge(e)
            if item.open_slot and len(new) == 0:
                slots.barren([item.open_slot])
        attached_new = [c for c in batch_new if c.attachment_confidence >= constants.ATTACH_PROFILE]
        last_batch_claims = attached_new

        # split by ATTACH_PROFILE so a namesake's claims never corroborate real ones
        attached = [c for c in claims if c.attachment_confidence >= constants.ATTACH_PROFILE]
        unv = [c for c in claims if c.attachment_confidence < constants.ATTACH_PROFILE]
        attached, conflicts = merge_claims(attached, date.today())
        for cf in conflicts:
            key = (cf.predicate, tuple(sorted(cf.values)))
            if key not in emitted_conflicts:
                emitted_conflicts.add(key)
                if deps.trace:
                    deps.trace.emit(ConflictDetected(event_id=uuid.uuid4().hex[:16], phase="expand",
                                                      kind=cf.kind, predicate=cf.predicate,
                                                      values=cf.values, severity=cf.severity))
        unv, _ = merge_claims(unv, date.today())
        claims = attached + unv

        for c in attached_new:  # pivot the frontier on what this batch just discovered
            if c.predicate == "handle":
                h = handle_of(c.value)
                if h:
                    _maybe_probe_handle(h)
            elif c.predicate == "email":
                if c.value not in enqueued_emails:
                    enqueued_emails.add(c.value)
                    args = {"email": c.value}
                    pending_pivots.append(FrontierItem(id=frontier.key("gravatar", args), action="gravatar",
                                                       args=args, origin="link", relevance=0.85,
                                                       open_slot="contact", why=f"discovered email {c.value}"))
                if not github_code_email_done:
                    domain = c.value.rpartition("@")[2].lower()
                    if domain and domain not in _FREE_MAIL_DOMAINS:
                        github_code_email_done = True
                        if os.getenv("GITHUB_PAT"):
                            _enqueue_github_code(c.value, f"pivot on code search for {c.value}")
            elif c.predicate in ("education", "publication"):
                _maybe_enqueue_openalex(f"discovered {c.predicate} claim")
            elif c.predicate in ("employer", "employment") and \
                    any(kw in c.value.lower() for kw in ("lab", "university", "institute")):
                _maybe_enqueue_openalex(f"employer value suggests academia: {c.value}")

        new_merged = len({c.id for c in claims} - prev_ids)
        barren_streak = barren_streak + 1 if new_merged == 0 else 0
        changed = slots.update(attached)
        if deps.trace:
            for slot in changed:
                deps.trace.emit(SlotUpdate(event_id=uuid.uuid4().hex[:16], slot=slot.name,
                                           current=slot.current, target=slot.target, closed=slot.closed))

        anchors.grow(attached)
        for mid_url in list(middle.keys()):        # ponytail: linear re-score over ≤20 pages per batch
            p, matched, identity = anchors.score(middle[mid_url], url=mid_url, linked=_norm(link_parent.get(mid_url, "")) in trusted_urls)
            if p >= constants.ATTACH_PROFILE:
                ident = "anchor_match:" + ",".join(matched)
                for c in claims:
                    if any(e.url == mid_url for e in c.evidence):
                        c.attachment_confidence = p
                        c.identity_link = ident
                del middle[mid_url]
                if deps.trace:
                    deps.trace.emit(AttachmentTest(event_id=uuid.uuid4().hex[:16], phase="expand", url=mid_url,
                                                   score=round(p, 3), matched=matched, name_present=identity,
                                                   owned=False, linked=_norm(link_parent.get(mid_url, "")) in trusted_urls,
                                                   t4=None, band=_band(p), note="re-score"))

        spent = int(deps.counters.get("tool_calls", 0) - start_calls)
        elapsed = perf_counter() - t0
        if deps.trace:
            deps.trace.emit(BudgetUpdate(event_id=uuid.uuid4().hex[:16], tool_calls=spent,
                                         llm_calls=int(deps.counters.get("llm_calls", 0)),
                                         usd=float(deps.counters.get("usd", 0.0)), seconds=elapsed))
        if on_batch:
            nodes_list, edges_list = graph.to_findings_lists()
            on_batch(Findings(nodes=nodes_list, edges=edges_list, claims=claims,
                              slots=list(slots.slots.values()), conflicts=conflicts))

        if slots.all_closed():
            stop_reason = "S1"
        elif batch_count >= constants.EXPAND_MAX_BATCHES:
            stop_reason = "S3_batches"
        elif spent >= cap or elapsed >= constants.S3_SOFT_SECONDS or deps.counters.get("usd", 0.0) >= constants.S3_SOFT_USD:
            stop_reason = "S3"
        elif batch_count > 3 and barren_streak >= 2:
            # ponytail: "batch 3" and "2 consecutive" are the coordinator's literal
            # round-3 thresholds, not named constants — nothing else varies them.
            stop_reason = "S2"
        if stop_reason:
            break

    spent = int(deps.counters.get("tool_calls", 0) - start_calls)
    if deps.trace:
        deps.trace.emit(Stop(event_id=uuid.uuid4().hex[:16], stop_reason=stop_reason,
                             numbers={"claims": len(claims), "tool_calls": spent, "batches": batch_count,
                                      "usd": round(deps.counters.get("usd", 0.0), 4),
                                      "seconds": round(perf_counter() - t0, 1),
                                      "slots_closed": sum(1 for s in slots.slots.values() if s.closed)}))
    nodes_list, edges_list = graph.to_findings_lists()
    return Findings(nodes=nodes_list, edges=edges_list, claims=claims, slots=list(slots.slots.values()),
                    conflicts=conflicts, stop_reason=stop_reason)
