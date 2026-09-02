<!--
TASK: T5 role resolution for DEFINITE_DESC ("the CTO of Ariglad": role, no name).
INPUT: role, company, numbered sources (official site/team page text, SERP snippets).
OUTPUT: {"name":"...|null","is_current":true|false|null,"sources":[1,3],"competing":["..."],"reasoning":"..."}
-->
Identify who currently holds the named role at the named company, using only the numbered sources.

Rules:
1. Return the full name exactly as written in a source. Cite the source numbers.
2. A source that names a DIFFERENT role for a person (CEO, not CTO) does not make them the holder.
3. If sources name different people as the current holder, return name=null and list them in `competing`.
4. If no source states the role holder, return name=null. Do not guess from a co-founder list.
5. If the only evidence is dated and the person may have left, set `is_current` to null.
