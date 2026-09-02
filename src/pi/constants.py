"""Single source of truth for every weight, cap, threshold, and slug.

Derivation tags: (judgment) subjective; (census) US Census; (reasoned) from call
structure; (standard) common practice. See plan/design-decisions.md and the two
plan/reference-*-scoring.md files for the rationale behind each block.
"""
from __future__ import annotations

import math

# ─────────────────────────── identity log-odds ───────────────────────────
# plan/reference-identity-scoring.md
LOGODDS_PRIOR = -1.5            # (judgment) p≈0.18 unsupported, for name regimes
HARD_ID_PRIOR = 0.0            # (judgment) email/url inputs start neutral

IDENTITY_HARD_KEYS = {          # (judgment) near-unique identifiers
    "seed_url_resolves": 3.5,
    "seed_email_on_page": 3.5,
    "gravatar_match": 3.0,
    "github_commit_email": 3.0,
    "reciprocal_link": 3.0,
}
ANCHORED_ONE_WAY = 1.5          # (judgment, C21) fetched page → unfetchable profile
PLAIN_ONE_WAY = 0.5            # (judgment)
UNIQUENESS_BONUS = 0.8         # (judgment, Unique′) sole distinguished candidate

# anchor source tiers (identity) — plan/reference-identity-scoring.md
ANCHOR_TIERS = {                # (judgment)
    "official_org": 2.5,
    "self_published": 2.0,
    "professional_network_snippet": 1.2,
    "press": 1.0,
    "aggregator": 0.5,
}
ANCHOR_MIN_PROF_TIER = 1.2      # (judgment) threshold for the Unique′ "any anchor" clause
ATTR_FACTORS = {                # (judgment) attribute discriminating power
    "employer": 1.0,
    "title": 0.5,
    "education": 0.7,
    "location": 0.4,
}
CORROBORATION_PER_SOURCE = 0.3  # (judgment) per extra independent source, per anchor
CORROBORATION_CAP = 0.6         # (judgment)

# surname rarity — plan/reference-identity-scoring.md
SURNAME_RARITY = {              # (census) US Census occurrences per 100k
    "rare": 2.0,                # <10
    "uncommon": 1.0,            # 10–100
    "common": 0.2,              # >100
    "not_found": 0.5,
}
SURNAME_RARE_MAX = 10.0
SURNAME_UNCOMMON_MAX = 100.0

# name-form penalties — (judgment, C2)
NAME_FORM = {
    "exact": 0.0,
    "diacritic_stripped": 0.0,
    "order_swap": -0.2,
    "nickname": -0.4,
    "initials": -0.9,
}

# negatives — (judgment)
CONTRADICT_FETCHED_MULT = 0.6   # −(tier × 0.6) on a fetched official/self-pub page
CONTRADICT_SNIPPET = -0.5
TENSE_CONTRADICTION = -1.5      # (C3) fetched page with context date only
HARD_TIMELINE_CONFLICT = -2.5   # two full-time ongoing, overlap >60d, fetched
GEOGRAPHIC_IMPOSSIBILITY = -2.0

# T4 attribute-match categories → multiplier on the anchor weight — (judgment)
T4_CATEGORY_MULT = {
    "exact_match": 1.0,
    "matches_former": 1.0,      # only when seed tense is past
    "partial": 0.5,
    "unrelated": 0.0,
    # "contradicts" routes to the negative rows above
}

# ───────────────────────────── the gate ──────────────────────────────────
GATE_P_THRESHOLD = 0.85         # (judgment)
GATE_MARGIN = 0.30             # (judgment)
GATE_LOGODDS_THRESHOLD = math.log(GATE_P_THRESHOLD / (1 - GATE_P_THRESHOLD))  # ≈1.735
GATE_MAX_CYCLES = 2             # (Gate-loop′) disconfirm→rescore→gate loop bound

# ─────────────────────────── claim confidence ────────────────────────────
# plan/reference-confidence-scoring.md
CLAIM_SOURCE_TIERS = {          # (judgment) predicate-dependent in practice
    "official_org": 2.5,
    "self_published": 2.2,
    "reputable_secondary": 1.4,
    "syndicated_aggregator": 0.2,   # never sole support
}
EXTRACTION_RUNG = {             # (judgment)
    "json_ld": 1.0,
    "site_parser": 0.7,
    "html_table": 0.4,
    "prose_llm": 0.0,
}
CORROBORATION_SECOND = 1.2      # (judgment) second independent source
CORROBORATION_DECAY = 0.6       # (judgment) ×0.6 thereafter
RECENCY_DECAY = {               # (judgment) per year, by predicate class
    "immutable": 0.0,
    "current_employer": -0.15,
    "current_title": -0.35,
    "current_location": -0.35,
    "contact": -0.5,
}
NO_CONTEXT_DATE_PENALTY = -0.3  # (judgment) mutable predicate, no context date
CONFLICT_WEIGHTS = {            # (judgment)
    "soft": -0.3,
    "hard": -1.5,
    "identity": -3.0,           # → C6′ quarantine, never route-back
}
TEMPORAL_HARD_CONFLICT_DAYS = 60  # (judgment, C12)

# ───────────────────────────── regimes ───────────────────────────────────
# plan/reference-identity-scoring.md
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
# Regime′: resolvable company → NAME_STRONG unless the org is on this stoplist.
HUGE_COMPANY_STOPLIST = {       # (judgment) names too big to disambiguate a person
    "google", "alphabet", "meta", "facebook", "amazon", "apple", "microsoft",
    "netflix", "ibm", "oracle", "intel", "walmart", "jpmorgan", "accenture",
}

# ─────────────────────────── budget & stops ──────────────────────────────
# plan/reference-contracts.md §10
RESOLVE_BUDGET_BASE = 4         # (reasoned) resolve_company + enumeration
RESOLVE_BUDGET_PER_CANDIDATE = 2  # (reasoned)
ENUMERATION_MAX_QUERIES = 8     # (judgment) one Serper batch
VARIANTS_MAX = 3                # (judgment) cap on variants fanned into enumeration

EXPAND_CAP = 40                 # (judgment) capped further by min(40, 60−resolve_spent)
S3_TOTAL_TOOL_CALLS = 60        # (judgment + $100 key)
S3_SOFT_SECONDS = 180
S3_HARD_SECONDS = 300
S3_HARD_USD = 0.75
S3_SOFT_USD = 0.50              # soft ceiling: stop expanding, spend rest on synthesis
S2_YIELD_THRESHOLD = 0.25       # (judgment) confirmed claims/call over trailing window
S2_WINDOW = 8
S2_MIN_EXPAND_CALLS = 16        # only evaluate S2 after this many EXPAND calls
# ponytail (Frontier′): no cost formula. The planner ranks; the frontier only
# filters off-target items and does a one-line pre-sort. SECTION_MULT below is the
# cheap on-target signal that survives.
FRONTIER_RELEVANCE_FLOOR = 0.2  # (judgment) drop items below this before the planner sees them

# EXPAND frontier — plan/stage-3-expand.md
SECTION_MULT = {                # (judgment) Case B relevance (Frontier′)
    "prose": 1.0,
    "sidebar": 0.6,
    "nav": 0.2,
    "footer": 0.2,
}
REINFORCE_MIN_DESCENDANTS = 3   # (judgment, C7)
REINFORCE_MAX_ATTACHMENT = 0.6
REINFORCE_FALLBACK_FRACTION = 0.20
DOMAIN_EARLY_STOP_FETCHES = 3   # (judgment) no new claims → stop the domain
DEPTH_CAP = 2                   # (judgment) exception to 3 for reciprocal verification
SLOT_BARREN_LIMIT = 3           # consecutive barren fetches → close a slot

DOMAIN_CLASSES = [              # (judgment) 9 classes; powers yield_prior, slots, cost
    "code_host", "professional_network", "social", "personal_site",
    "company_site", "academic", "government_registry", "press", "aggregator",
]
UNFETCHABLE_HOSTS = {           # (C21) never spend a fetch; SERP/Exa contents only
    "linkedin.com", "x.com", "twitter.com", "facebook.com",
    "instagram.com", "crunchbase.com", "threads.net",
}

# ───────────────────────── infra & concurrency ───────────────────────────
# plan/reference-contracts.md §9
SEMAPHORES = {                  # (judgment) process-wide provider limits
    "serper": 5, "exa": 3, "firecrawl": 2, "openrouter": 8, "fetch": 10,
}
TIMEOUTS_S = {                  # (judgment)
    "fetch": 8, "firecrawl": 20, "wayback": 15, "llm": 60,
}
MAX_RUNNING_JOBS = 3            # (judgment, Concurrency′) semaphore; queue beyond
MAX_INFLIGHT_DEFAULT = 10      # (judgment) 429 past running+queued this many

CACHE_TTL_S = {                 # (judgment) by source class; None = no expiry
    "structured_api": 6 * 3600,
    "official_org": 7 * 86400,
    "self_published": 7 * 86400,
    "press": 30 * 86400,
    "aggregator": 1 * 86400,
    "wayback": None,
    "edgar": None,
}
TRACKING_PARAMS = {             # (standard) blocklist for url normalization
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "ref", "source", "_ga",
}

# ───────────────────────────── model routing ─────────────────────────────
# plan/reference-contracts.md §8 — slugs/prices VERIFIED IN STAGE 1.
TEMPERATURE = 0                 # (standard) T2–T5; T1 uses reasoning, no temp param
# T1 (the identity gate) is the make-or-break decision — it must read a profile and
# veto a mismatch, which gpt-4o-mini confabulates. It runs on a capable model. Every
# other tier stays cheap. (~$0.005 per gate call; the gate fires 1–2× per run.)
_CHEAP_MODEL = "openai/gpt-4o-mini"
_GATE_MODEL = "openai/gpt-4o"
TASK_MODELS = {                 # tier -> (primary_slug, secondary_slug)
    "T1": (_GATE_MODEL, _CHEAP_MODEL),
    "T2": (_CHEAP_MODEL, None),
    "T3": (_CHEAP_MODEL, None),
    "T4": (_CHEAP_MODEL, None),
    "T5": (_CHEAP_MODEL, None),
}
# prices (USD per 1M tokens) filled in Stage 1 from OpenRouter; used for $ tracking
MODEL_PRICES = {}               # slug -> {"in": float, "out": float}

RETRIES = {"validation": 3, "rate_limit": 2, "refusal": 0}  # (judgment, §10)
