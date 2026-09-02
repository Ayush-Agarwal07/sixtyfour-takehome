<!--
TASK: T2 synthesis narration. Long-context coherence, no embellishment.
INPUT:  { identity: {...}, claims: [ {id, predicate, value, confidence.score} ],
          conflicts: [...], negative_findings: [...] }
OUTPUT: { summary: [ {text, claim_ids:[str]} ] }
Rules: every sentence MUST cite ≥1 claim_id; the caller DROPS any sentence with an
empty claim_ids. Do not state anything not backed by a listed claim. Do not
smooth over conflicts — surface them. No adjectives the evidence doesn't support.
-->
Write a factual summary of the target. Each sentence must be traceable to specific
claims by id. Prefer omission over embellishment.
