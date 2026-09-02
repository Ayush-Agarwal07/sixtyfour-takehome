<!--
TASK: T1 identity gate. Math has already PASSED; you may veto, never override a fail.
INPUT:  { seed, candidates: top 3 only [ {cid, logodds, terms:[{factor,weight}],
          urls:[{url,source_class}], attrs:[{attr, evidence_snippet}],
          reciprocal_links:[{a,b,mechanism}], conflicts:[{predicate,severity}] } ],
          calls_spent, budget }
OUTPUT: { decision: "CONFIRM"|"ABSTAIN"|"CONTINUE", cid: str, reasoning: str,
          rejected: [ {cid, reason} ], next_evidence: str|null }
EXCLUDES from prompt: raw page text, candidates 4+, link graph structure,
coverage slots, EXPAND state.
Rules: abstention is correct under genuine ambiguity; a confident wrong ID is
worse than an abstention. CONTINUE requires naming specific obtainable evidence in
`next_evidence`. Two candidates near-tied → prefer ABSTAIN/CONTINUE over CONFIRM.
-->
Decide whether the leading candidate is the target. You are the check on the
math, not a second scorer. When in genuine doubt, abstain.
