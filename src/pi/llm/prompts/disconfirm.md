<!--
TASK: T1 disconfirmation. Runs when the gate math PASSES, before the gate decision (C5).
INPUT: seed; the top candidate's matched attributes with their sources; its urls; runner-up summary; budget left.
OUTPUT: {"hypothesis":"...","actions":[{"tool":"search|fetch","args":{"q":"..."}|{"url":"..."}}],
         "expected_if_wrong":"...","reasoning":"..."}   (≤2 actions)
-->
State the single most likely way this identity match is WRONG. Then return the cheapest tool calls that would reveal it.

Rules:
1. Think like an investigator: same name at a different company, a stale profile, an aggregator echoing one source, a namesake in the same city, a title that changed.
2. Prefer a `fetch` of a page the candidate controls (personal site, GitHub) or of the anchor organization's team page. Prefer a `search` that combines the name with a DIFFERENT distinguishing attribute than the one already matched.
3. Never search for the same query that produced the current evidence.
4. `expected_if_wrong` says what the result would show if the match is wrong.
5. At most 2 actions. Args: search → {"q": "..."}; fetch → {"url": "https://..."}.
