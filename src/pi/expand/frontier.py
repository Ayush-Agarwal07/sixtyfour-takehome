"""The frontier — a plain, ranked list of candidate next actions (Frontier′).

Builds items from three sources (a candidate's own seed pages, links found on
a fetched page, SERP results) plus reinforce triggers from the graph, then
gives the planner (Task 4b) a cheap pre-sorted top-N. No I/O, no cost/score
beyond the formula below.
"""
from __future__ import annotations

from .. import constants
from ..score.claim_score import _sigmoid
from ..sources import classify, host_of, identity_tier, is_unfetchable, registrable_domain
from ..types import Candidate, FrontierItem, Seed
from .assemble import _sha16
from .extract import LinkT
from .slots import Slots


def _action_for(url: str, cls: str, exa_ok: bool) -> str | None:
    """None means skip: aggregator, or unfetchable with no Exa available."""
    if cls == "aggregator":
        return None
    if is_unfetchable(url):
        return "exa_contents" if exa_ok else None
    return "fetch"


def _domain_of(item: FrontierItem) -> str | None:
    url = item.args.get("url", "")
    return registrable_domain(host_of(url)) if url else None


def _class_of(item: FrontierItem) -> str:
    if item.action in ("github", "username_probe", "github_code"):
        return "code_host"          # ponytail: these actions lack a url whose class is knowable
    if item.action == "openalex":
        return "academic"
    return classify(item.args.get("url", ""))


class Frontier:
    def __init__(self) -> None:
        self.items: dict[str, FrontierItem] = {}
        self.done: set[str] = set()
        self.domain_fetches: dict[str, tuple[int, int]] = {}   # domain -> (fetches, claims)
        self.skips: dict[str, int] = {}

    def key(self, action: str, args: dict) -> str:
        payload = action + "".join(f"|{k}={args[k]}" for k in sorted(args))
        return _sha16(payload)

    def _make(self, action: str, args: dict, *, origin: str, relevance: float, why: str,
              open_slot: str | None = None) -> FrontierItem:
        return FrontierItem(id=self.key(action, args), action=action, args=args, origin=origin,
                            open_slot=open_slot, relevance=relevance, why=why)

    def add(self, item: FrontierItem) -> None:
        if item.id in self.items or item.id in self.done:
            return
        self.items[item.id] = item

    # ───────────────────────────── builders ───────────────────────────────
    def seed(self, cand: Candidate, seed: Seed, *, exa_ok: bool, github_ok: bool,
             anchor_domains: set[str]) -> None:
        names = [v.form for v in seed.names]
        org = seed.orgs[0] if seed.orgs else ""
        name = names[0] if names else seed.input

        for url in cand.urls:
            cls = classify(url, anchor_domains=anchor_domains, names=names)
            action = _action_for(url, cls, exa_ok)
            if action is None:
                continue
            predicted = constants.CLASS_SLOTS.get(cls, [])
            self.add(self._make(action, {"url": url}, origin="link", relevance=0.95,
                                why="confirmed candidate page", open_slot=predicted[0] if predicted else None))

        gh = cand.handles.get("github")
        if gh and github_ok:
            predicted = constants.CLASS_SLOTS.get("code_host", [])
            self.add(self._make("github", {"login": gh}, origin="link", relevance=0.95,
                                why="confirmed candidate page", open_slot=predicted[0] if predicted else None))

        email = seed.hard_ids.get("email")
        if email:
            self.add(self._make("gravatar", {"email": email}, origin="link", relevance=0.95,
                                why="confirmed candidate page", open_slot="contact"))

        company_slots = constants.CLASS_SLOTS.get("company_site", [])
        for domain in sorted(anchor_domains or ()):
            url = f"https://{domain}"
            open_slot = company_slots[0] if company_slots else None
            self.add(self._make("fetch", {"url": url}, origin="link", relevance=0.95,
                                why="anchor org page / historical team page", open_slot=open_slot))
            self.add(self._make("wayback", {"url": url}, origin="link", relevance=0.95,
                                why="anchor org page / historical team page", open_slot=open_slot))

        templates: list[tuple[str, str]] = []
        if org:
            templates.append((f'"{name}" "{org}"', "notable_artifacts"))
        templates.append((f'"{name}" interview OR podcast OR talk', "public_output"))
        if not gh:
            templates.append((f'"{name}" site:github.com', "public_output"))
        if exa_ok and not any(k.startswith("linkedin:") for k in cand.identity_keys):
            # LinkedIn is the employment-history source; when RESOLVE confirmed on another
            # key alone, one SERP finds the profile for exa_contents to read.
            templates.append((f'"{name}" site:linkedin.com/in', "employment_history"))
        if org:
            templates.append((f'"{name}" "{org}" founder OR cofounder', "social_graph"))
        for q, slot_name in templates:
            self.add(self._make("search", {"q": q}, origin="slot_template", relevance=0.6,
                                why=f'slot template targeting {slot_name}', open_slot=slot_name))

    def from_links(self, page_url: str, links: list[LinkT], parent_attachment: float, *,
                   names: list[str], anchor_domains: set[str] | None, exa_ok: bool) -> None:
        page_domain = registrable_domain(host_of(page_url))
        same_domain_seen = 0
        for url, _anchor_text, section in links:
            if not url or url.startswith(("mailto:", "javascript:", "#")):
                continue
            cls = classify(url, anchor_domains=anchor_domains, names=names)
            if cls in ("aggregator", "social"):
                # social profile/post links are near-never worth a fetch and clog the
                # frontier (LinkedIn posts, X profiles); the expander harvests a handle
                # claim for identity-bearing ones directly instead (see run_action).
                continue
            if registrable_domain(host_of(url)) == page_domain:
                same_domain_seen += 1
                if same_domain_seen > 2:
                    continue
            relevance = parent_attachment * constants.SECTION_MULT.get(section, 1.0)
            if relevance < constants.FRONTIER_RELEVANCE_FLOOR:
                continue
            action = _action_for(url, cls, exa_ok)
            if action is None:
                continue
            predicted = constants.CLASS_SLOTS.get(cls, [])
            why = f"linked from {host_of(page_url)} ({section})"
            self.add(self._make(action, {"url": url}, origin="link", relevance=relevance, why=why,
                                open_slot=predicted[0] if predicted else None))

    def from_serp(self, results: list[dict], *, names: list[str], anchor_domains: set[str] | None,
                  exa_ok: bool) -> None:
        org_tokens = {registrable_domain(d).split(".")[0] for d in (anchor_domains or ())}
        for r in results:
            url = r.get("url") or ""
            if not url:
                continue
            cls = classify(url, anchor_domains=anchor_domains, names=names)
            action = _action_for(url, cls, exa_ok)
            if action is None:
                continue
            text = f"{r.get('title', '')} {r.get('snippet', '')}".lower()
            tier = identity_tier(cls)
            total = 0.0
            if org_tokens and any(tok and tok in text for tok in org_tokens):
                total += tier * constants.ATTR_FACTORS["employer"]
            # ponytail: no title-anchor plumbed to the frontier (this module is pure and
            # only receives names/anchor_domains, never seed.titles) — employer-anchor
            # term only. Upgrade: thread a title token through when the planner needs it.
            if names and any(n and n.lower() in text for n in names):
                total += 1.0
            relevance = _sigmoid(total - 2.0)
            if relevance < constants.FRONTIER_RELEVANCE_FLOOR:
                continue
            predicted = constants.CLASS_SLOTS.get(cls, [])
            self.add(self._make(action, {"url": url}, origin="link", relevance=relevance,
                                why=f"serp: {r.get('query', '')}", open_slot=predicted[0] if predicted else None))

    def reinforce(self, graph) -> None:
        for node in graph.reinforce_candidates():
            args = {"node_id": node.id, "label": node.label}
            self.add(FrontierItem(id=self.key("verify", args), action="verify", args=args, origin="reinforce",
                                  open_slot=None, relevance=1.0, why="load-bearing node with weak attachment"))

    # ───────────────────────────── ranking ────────────────────────────────
    def rank(self, slots: Slots) -> list[tuple[FrontierItem, float]]:
        scored: list[tuple[FrontierItem, float]] = []
        for item in self.items.values():
            dom = _domain_of(item)
            if dom is not None:
                fetches, claims = self.domain_fetches.get(dom, (0, 0))
                if fetches >= constants.DOMAIN_EARLY_STOP_FETCHES and claims == 0:
                    continue
            if item.origin == "reinforce":
                slot_gap, class_prior = 1.0, 1.0
            else:
                # ponytail: FrontierItem carries only the single first predicted slot
                # (types.py contract), so slot_gap sums over that one slot, not a list.
                slot_gap = slots.gap(item.open_slot) if item.open_slot else 0.0
                if slot_gap <= 0.0:
                    slot_gap = 0.05     # never exactly zero — planner should still see it
                class_prior = constants.CLASS_PRIOR.get(_class_of(item), constants.CLASS_PRIOR["unknown"])
            est_s, est_usd = constants.ACTION_COST.get(item.action, (1.0, 0.0))
            denom = est_s + constants.COST_LAMBDA * est_usd
            score = (item.relevance * slot_gap * class_prior / denom) if denom else 0.0
            scored.append((item, score))
        scored.sort(key=lambda pair: (pair[0].origin != "reinforce", -pair[1]))
        return scored[: constants.FRONTIER_TOP_N]

    # ───────────────────────────── bookkeeping ────────────────────────────
    def note_result(self, item: FrontierItem, n_new_claims: int) -> None:
        self.done.add(item.id)
        self.items.pop(item.id, None)
        if item.origin == "reinforce":
            return
        dom = _domain_of(item)
        if dom is None:
            return
        fetches, claims = self.domain_fetches.get(dom, (0, 0))
        self.domain_fetches[dom] = (fetches + 1, claims + n_new_claims)

    def skipped(self, item_ids: list[str]) -> None:
        for iid in item_ids:
            item = self.items.get(iid)
            if item is not None and item.origin == "reinforce":
                self.skips[iid] = self.skips.get(iid, 0) + 1

    def forced(self) -> list[FrontierItem]:
        return [item for item in self.items.values()
                if item.origin == "reinforce" and self.skips.get(item.id, 0) >= constants.REINFORCE_FORCE_AFTER_SKIPS]
