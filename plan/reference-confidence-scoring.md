# Reference — claim confidence & temporal

Per-claim confidence is deterministic log-odds, prior −1.5 (p≈0.18 unsupported).
Every input is a fact about the evidence or a constrained model categorical —
**never a model-emitted float.** Every claim ships its arithmetic.

`tests/test_claim_spread.py` asserts the three spread rows produce 0.96 / 0.85 /
0.12. A system that cannot produce numbers **under 0.3** has meaningless high ones.

---

## Term groups

**Source tier (predicate-dependent** — org page authoritative for employment,
personal site for contact):

| Tier | Weight |
|---|---|
| official_org | +2.5 |
| self_published primary | +2.2 |
| reputable_secondary | +1.4 |
| syndicated_aggregator | +0.2 (never sole support) |

(Breach-derived and model-inference tiers **removed** — C13. Every claim needs a
page span; synthesis inferences live unscored in `inferences[]`.)

**Extraction rung:** structured API/JSON-LD +1.0 · site parser +0.7 · HTML table
+0.4 · prose LLM 0. (VLM removed.)

**Corroboration:** +1.2 for a second independent source, ×0.6 decay thereafter.
Independence key = `(source_class, registrable_domain)`; aggregator ∧ aggregator
collapses to one key regardless of domain. Known accepted error: two outlets
running the same press release count as independent.

**Recency by predicate class:** immutable 0 · current employer −0.15/yr · current
title/location −0.35/yr · contact −0.5/yr. Mutable predicate with **no context
date** → −0.3.

**Conflicts:** soft −0.3 · hard −1.5 and flag · identity −3.0 (→ C6′ quarantine).

---

## Spread check (test fixtures)

| Scenario | Terms | logodds → P |
|---|---|---|
| Official page + site parser + fresh + single source | 2.5 + 0.7 − 1.5 | 1.7 → **0.85** |
| Two independent primaries + JSON-LD | 2.5 + 1.0 + 1.2 − 1.5 (+ decay) ≈ 3.2 | 3.2 → **0.96** |
| One aggregator + prose LLM + 2yr-stale title | 0.2 + 0 − 0.70 − 1.5 ≈ −2.0 | −2.0 → **0.12** |

The 0.12 is the point.

Example claim block shipped in output:
```json
"confidence": {"score":0.91,"logodds":2.31,"terms":[
  {"factor":"source_tier:official_org","weight":2.5},
  {"factor":"extraction:json_ld","weight":1.0},
  {"factor":"corroboration:1_independent","weight":1.2},
  {"factor":"recency:current_title_1.2yr","weight":-0.42},
  {"factor":"prior","weight":-1.5}]}
```

**Scope (state in README):** ordinally calibrated, not frequency-calibrated. A
0.9 is more reliable than a 0.6; it does not mean 90% correct.

---

## Temporal rules

```python
class Temporal(BaseModel):
    start: date | None
    end: date | None
    end_state: Literal["ongoing","unknown","ended"]  # default "unknown"
    precision: Literal["year","month","day"]
    context_date: date | None
```

- **Precision derives from string shape in assembly, never from the model.**
  Year → `[YYYY-01-01, YYYY-12-31]`.
- Relative expressions ("currently", "since 2 years ago") resolve against
  `context_date`; missing `context_date` → drop the date, keep the claim.
- **Hard conflict only when:** both `ongoing`, definite overlap, exceeding 60
  days, **and** both are full-time employment (C12). Founder+advisor, exec+board
  are soft. Everything else soft. `unknown` **never** produces a hard conflict —
  treating it as `ongoing` generates false conflicts that cause wrong ABSTAINs.
- Identity conflict = contradiction on an **immutable** predicate only
  (hard-key mismatch, birth year, degree year).

`tests/test_temporal.py`: year-shape → full-year range; relative w/o context_date
→ date dropped, claim kept; `unknown` vs `ongoing` → no hard conflict; two
full-time ongoing overlapping 90d → hard conflict.
