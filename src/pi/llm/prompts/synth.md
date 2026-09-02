<!--
TASK: T2 synthesis narration. Long-context coherence, no embellishment.
INPUT: identity, claims (id, predicate, value, confidence), conflicts, negative_findings.
OUTPUT: {"summary":[{"text":"...","claim_ids":["..."]}],"reasoning":"..."}
-->
Write a factual summary of the target from the listed claims.

Rules:
1. Every sentence cites at least one claim id. The caller deletes sentences with no citation.
2. State nothing that is not in a listed claim. No adjectives the evidence does not support.
3. Surface conflicts as conflicts. Do not pick a side the evidence does not pick.
4. Mention what was sought and not found (negative findings) in one sentence.
5. Four to eight sentences. Plain language.
