"""Single source of truth for every weight, cap, threshold, and slug.

Derivation tags: (judgment) subjective; (census) US Census; (reasoned) from call
structure; (standard) common practice; (verified) checked against a live API.
See plan/design-decisions.md and plan/reference-*.md for rationale.
"""
from __future__ import annotations

import math

# ─────────────────────────── identity log-odds ───────────────────────────
LOGODDS_PRIOR = -1.5            # (judgment) p≈0.18 unsupported, name regimes
HARD_ID_PRIOR = 0.0             # (judgment) email/url inputs start neutral

IDENTITY_HARD_KEYS = {          # (judgment) near-unique identifiers
    "seed_url_resolves": 3.5,
    "seed_email_on_page": 3.5,
    "gravatar_match": 3.0,
    "github_commit_email": 3.0,
    "reciprocal_link": 3.0,
}
ANCHORED_ONE_WAY = 1.5          # (judgment, C21) fetched official/self-pub page → unfetchable profile
PLAIN_ONE_WAY = 0.5             # (judgment)
UNIQUENESS_BONUS = 0.8          # (judgment, A2) sole candidate with anchor weight ≥ UNIQUENESS_MIN_ANCHOR
UNIQUENESS_MIN_ANCHOR = 1.2     # (judgment, A2) computed on enumeration-time (snippet) evidence only
DOMINANT_CLUSTER_BONUS = 2.0    # (judgment, A5) one cluster holds most SERP urls (public figure)
DOMINANT_CLUSTER_SHARE = 0.6
DOMINANT_CLUSTER_MIN_URLS = 8

# identity anchor tier by source class — plan/reference-tables (B2)
IDENTITY_TIER = {               # (judgment)
    "company_site": 2.5,        # anchor org's own site
    "government_registry": 2.5,
    "academic": 2.5,
    "company_site_other": 1.0,
    "personal_site": 2.0,
    "code_host": 2.0,
    "professional_network": 1.2,
    "social": 1.2,
    "press": 1.0,
    "unknown": 0.8,
    "aggregator": 0.5,
    "seed": 0.0,
}
ATTR_FACTORS = {                # (judgment) attribute discriminating power
    "employer": 1.0,
    "title": 0.5,
    "education": 0.7,
    "location": 0.4,
}
CORROBORATION_PER_SOURCE = 0.3  # (judgment) per extra independent source, per anchor
CORROBORATION_CAP = 0.6

# surname rarity — (census) US 2010 surnames, occurrences per 100k people
SURNAME_RARITY = {
    "rare": 2.0,                # < SURNAME_RARE_MAX
    "uncommon": 1.0,
    "common": 0.2,              # ≥ SURNAME_COMMON_MIN (Smith … Wang, Chen, Patel)
    "not_found": 1.0,           # absent from a 160k-name table → fewer than 100 US bearers, or non-US
}
SURNAME_RARE_MAX = 2.0          # (census) ≈ rank > 4,000
SURNAME_COMMON_MIN = 20.0       # (census) ≈ rank ≤ 300; Wang 48, Chen 32, Patel 53

NAME_FORM = {                   # (judgment, C2)
    "exact": 0.0,
    "diacritic_stripped": 0.0,
    "order_swap": -0.2,
    "nickname": -0.4,
    "initials": -0.9,
    "partial": -0.9,
}
NAME_MISMATCH = -2.0            # (judgment) matcher says the page is about a differently-named person

# negatives — (judgment)
CONTRADICT_PAGE_MULT = 0.6      # −(tier × 0.6) when the contradicting source is a fetched page
CONTRADICT_SNIPPET = -0.5
TENSE_CONTRADICTION = -1.5      # (C3) fetched page with context date only
HARD_TIMELINE_CONFLICT = -2.5
GEOGRAPHIC_IMPOSSIBILITY = -2.0

T4_CATEGORY_MULT = {            # (judgment) matcher category → multiplier on tier×attr
    "exact_match": 1.0,
    "matches_former": 1.0,      # seed tense is past and source shows that past role
    "partial": 0.5,
    "unrelated": 0.0,
    # "contradicts" → negative rows above
}

# ───────────────────────────── the gate ──────────────────────────────────
GATE_P_THRESHOLD = 0.85         # (judgment)
GATE_MARGIN = 0.30              # (judgment)
GATE_LOGODDS_THRESHOLD = math.log(GATE_P_THRESHOLD / (1 - GATE_P_THRESHOLD))  # ≈1.735
GATE_MAX_CYCLES = 2             # (Gate-loop′)
GATE_PROMPT_CANDIDATES = 3

# ─────────────────────────── claim confidence ────────────────────────────
CLAIM_TIER = {                  # (judgment) plan/reference-tables (B2)
    "company_site": 2.5,
    "government_registry": 2.5,
    "academic": 2.5,
    "personal_site": 2.2,
    "code_host": 2.2,
    "company_site_other": 1.4,
    "professional_network": 1.4,
    "social": 1.4,
    "press": 1.4,
    "unknown": 0.8,
    "aggregator": 0.2,          # never sole support
    "seed": 1.5,                # user-supplied hard id (email domain); not a page
}
EXTRACTION_RUNG = {             # (judgment)
    "json_ld": 1.0,
    "site_parser": 0.7,
    "html_table": 0.4,
    "prose_llm": 0.0,
    "none": 0.0,
}
CORROBORATION_SECOND = 1.2
CORROBORATION_DECAY = 0.6
RECENCY_DECAY = {               # (judgment) per year, by predicate class
    "immutable": 0.0,
    "current_employer": -0.15,
    "current_title": -0.35,
    "current_location": -0.35,
    "contact": -0.5,
}
NO_CONTEXT_DATE_PENALTY = -0.3
CONFLICT_WEIGHTS = {"soft": -0.3, "hard": -1.5, "identity": -3.0}
TEMPORAL_HARD_CONFLICT_DAYS = 60

# ───────────────────────────── regimes ───────────────────────────────────
REGIME_PRIORS = {
    "HARD_ID_URL": HARD_ID_PRIOR,
    "HARD_ID_EMAIL": HARD_ID_PRIOR,
    "NAME_STRONG": LOGODDS_PRIOR,
    "DEFINITE_DESC": LOGODDS_PRIOR,
    "NAME_WEAK": LOGODDS_PRIOR,
    "BARE_NAME": LOGODDS_PRIOR,
}
REGIME_CAPS = {                 # (judgment, C10) RESOLVE tool round trips
    "HARD_ID_URL": 12,
    "HARD_ID_EMAIL": 12,
    "NAME_STRONG": 20,
    "DEFINITE_DESC": 24,
    "NAME_WEAK": 30,
    "BARE_NAME": 10,
}
HUGE_COMPANY_STOPLIST = {       # (judgment, Regime′)
    "google", "alphabet", "meta", "facebook", "amazon", "apple", "microsoft",
    "netflix", "ibm", "oracle", "intel", "walmart", "jpmorgan", "accenture",
}
DEFINITE_ROLES = {              # (judgment) roles unique enough for DEFINITE_DESC
    "ceo", "cto", "cfo", "coo", "cmo", "cpo", "cro", "ciso", "cio",
    "president", "founder", "cofounder", "co-founder", "chair", "chairman",
    "chairwoman", "chief", "head", "vp", "vice president", "director",
    "managing director", "general counsel", "principal", "partner",
}

# ─────────────────────────── budget & stops ──────────────────────────────
RESOLVE_BUDGET_BASE = 4         # (reasoned) resolve_budget = min(enum_spent + 4 + 2n, cap)
RESOLVE_BUDGET_PER_CANDIDATE = 2
ENUMERATION_MAX_QUERIES = 5     # (judgment; free-tier keys) plan says ≤8
VARIANTS_MAX = 3
DISCONFIRM_MAX_ACTIONS = 2
FETCH_K = 2                     # RESOLVE verification fetches per cycle

EXPAND_CAP = 40
S3_TOTAL_TOOL_CALLS = 60
S3_SOFT_SECONDS = 180
S3_HARD_SECONDS = 300
S3_HARD_USD = 0.75
S3_SOFT_USD = 0.50
S2_YIELD_THRESHOLD = 0.25
S2_WINDOW = 8
S2_MIN_EXPAND_CALLS = 16
FRONTIER_RELEVANCE_FLOOR = 0.2

SECTION_MULT = {"prose": 1.0, "sidebar": 0.6, "nav": 0.2, "footer": 0.2, "nav_footer": 0.2}
REINFORCE_MIN_DESCENDANTS = 3
REINFORCE_MAX_ATTACHMENT = 0.6
DOMAIN_EARLY_STOP_FETCHES = 3
DEPTH_CAP = 2
SLOT_BARREN_LIMIT = 3

# ───────────────────────── source classification ─────────────────────────
# plan/reference-tables (B1). First match wins; see pi.sources.classify.
DOMAIN_CLASSES = [
    "code_host", "professional_network", "social", "personal_site", "company_site",
    "company_site_other", "academic", "government_registry", "press", "aggregator", "unknown",
]
CODE_HOSTS = {"github.com", "gitlab.com", "bitbucket.org"}
PROFESSIONAL_NETWORK_HOSTS = {"linkedin.com"}
SOCIAL_HOSTS = {
    "x.com", "twitter.com", "facebook.com", "instagram.com", "threads.net",
    "bsky.app", "youtube.com", "tiktok.com", "mastodon.social",
}
ACADEMIC_HOSTS = {
    "openalex.org", "orcid.org", "scholar.google.com", "researchgate.net",
    "arxiv.org", "semanticscholar.org", "dblp.org",
}
GOVERNMENT_HOSTS = {"sec.gov", "companieshouse.gov.uk", "opencorporates.com"}
AGGREGATOR_HOSTS = {
    "zoominfo.com", "rocketreach.co", "apollo.io", "signalhire.com", "contactout.com",
    "lusha.com", "theorg.com", "crunchbase.com", "pitchbook.com", "craft.co", "owler.com",
    "clay.com", "hunter.io", "spokeo.com", "whitepages.com", "radaris.com", "mylife.com",
    "beenverified.com", "intelius.com", "idcrawl.com", "seedtable.com", "wiza.co",
    "peopledatalabs.com", "fastpeoplesearch.com", "truepeoplesearch.com", "ancestry.com",
    "wikipedia.org", "wellfound.com", "angel.co", "cbinsights.com", "tracxn.com",
    "golden.com", "leadiq.com", "kendoemailapp.com", "clearbit.com",
}
PRESS_HOSTS = {
    "techcrunch.com", "forbes.com", "bloomberg.com", "reuters.com", "nytimes.com",
    "wsj.com", "ft.com", "theinformation.com", "businessinsider.com", "wired.com",
    "theverge.com", "axios.com", "venturebeat.com", "fortune.com", "cnbc.com",
    "theguardian.com", "bbc.com", "bbc.co.uk", "prnewswire.com", "businesswire.com",
    "globenewswire.com", "medium.com", "substack.com", "news.ycombinator.com",
    "ycombinator.com",              # YC's own founder directory: reputable secondary, not an aggregator
}
PERSONAL_PLATFORM_HOSTS = {     # self-published platforms; personal_site when path/subdomain is the person's
    "github.io", "about.me", "carrd.co", "notion.site", "vercel.app", "netlify.app",
    "wordpress.com", "squarespace.com", "wixsite.com", "substack.com", "medium.com",
    "dev.to", "hashnode.dev", "bearblog.dev", "read.cv", "linktr.ee",
}
UNFETCHABLE_HOSTS = {           # (C21) never spend an httpx fetch; SERP snippet + Exa contents only
    "linkedin.com", "x.com", "twitter.com", "facebook.com", "instagram.com",
    "crunchbase.com", "threads.net",
}
RARE_HANDLE_MIN_LEN = 6         # (judgment, C17)
COMMON_HANDLE_WORDS = {"admin", "info", "hello", "contact", "team", "official", "profile", "user"}

# ───────────────────────── infra & concurrency ───────────────────────────
SEMAPHORES = {"serper": 5, "exa": 3, "firecrawl": 2, "openrouter": 8, "fetch": 10}
TIMEOUTS_S = {"fetch": 8, "firecrawl": 20, "wayback": 15, "llm": 60, "serper": 15, "exa": 30}
MAX_RUNNING_JOBS = 3
MAX_INFLIGHT_DEFAULT = 10

CACHE_TTL_S = {                 # (judgment) by source class; None = no expiry
    "structured_api": 6 * 3600,
    "search": 24 * 3600,
    "company_site": 7 * 86400,
    "personal_site": 7 * 86400,
    "code_host": 6 * 3600,
    "professional_network": 7 * 86400,
    "press": 30 * 86400,
    "aggregator": 1 * 86400,
    "unknown": 3 * 86400,
    "wayback": None,
}
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "ref", "source", "_ga",
}

# ───────────────────────────── model routing ─────────────────────────────
# (verified 2026-09-02 against GET https://openrouter.ai/api/v1/models)
TEMPERATURE = 0                 # (standard) T2–T5; reasoning tiers send no temperature
_T1 = "anthropic/claude-sonnet-5"
_T1_SECONDARY = "anthropic/claude-sonnet-4.6"
_CHEAP = "google/gemini-3.8-flash"
TASK_MODELS = {                 # tier -> (primary_slug, secondary_slug)
    "T1": (_T1, _T1_SECONDARY),  # gate, disconfirmation, planner — do not economize
    "T2": (_T1, _T1_SECONDARY),  # synthesis
    "T3": (_CHEAP, None),        # page → claims
    "T4": (_CHEAP, None),        # attribute-match categorical
    "T5": (_CHEAP, None),        # parse, role_resolve
}
REASONING_TIERS = {"T1", "T2"}
REASONING_EFFORT = "medium"
JSON_MODE_PREFIXES = ("openai/", "google/")   # models that accept response_format=json_object
MODEL_PRICES = {                # USD per 1M tokens (verified 2026-09-02); fallback when usage.cost is absent
    "anthropic/claude-sonnet-5": {"in": 2.0, "out": 10.0},
    "anthropic/claude-sonnet-4.6": {"in": 3.0, "out": 15.0},
    "google/gemini-3.8-flash": {"in": 0.75, "out": 3.75},
}
RETRIES = {"validation": 3, "rate_limit": 2, "refusal": 0}
