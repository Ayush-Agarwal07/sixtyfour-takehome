<!--
TASK: T4 attribute-match categorical (BATCHED, one call per ≤10 candidates).
INPUT:  { seed_anchors: {employer?, title?, education?, location?, tense},
          candidates: [ { cid, attrs: {employer?, title?, education?, location?} } ] }
OUTPUT: { results: [ { cid, employer?, title?, education?, location? } ] }
        where each attribute value ∈ {exact_match, matches_former, partial,
        unrelated, contradicts}. matches_former only when seed tense is past.
Rules: NEVER emit a number. Only the categorical. Return a row for every input
cid; the caller validates the returned cids against the batch.
-->
For each candidate, classify how each attribute relates to the seed. Use
`matches_former` only when the seed says the person formerly held it.
