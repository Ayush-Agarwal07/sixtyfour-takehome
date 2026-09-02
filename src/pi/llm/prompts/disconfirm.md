<!--
TASK: T1 disconfirmation. Executable, not decorative (C5).
INPUT:  { seed, top_candidate: {cid, terms, urls, attrs}, budget_left }
OUTPUT: { hypothesis: str, actions: [ { tool, args } ] (≤2), reasoning: str }
Rules: name what would FALSIFY this match, then return ≤2 concrete tool calls that
would surface that falsifying evidence (e.g. fetch a personal site, github_emails
on a repo). The caller runs them and rescores before the gate.
-->
Given the leading candidate, state the single most likely way this identity match
is wrong, and return the cheapest tool calls that would reveal it.
