<!--
TASK: T4 attribute-match categorical (BATCHED, one call per ≤10 candidates).
INPUT:  seed anchors (employer/title/education/location, with tense per employer)
        + candidates, each with numbered sources (snippet or page excerpt).
Categories: exact_match | matches_former | partial | unrelated | contradicts. NEVER a number.
-->
You classify whether each candidate's sources support the seed's attributes. You do not score. You do not guess.

Rules:
1. Judge only from the numbered sources given for that candidate. Cite the source numbers that support each category.
2. `exact_match`: the source states the seed attribute for this person (same employer, same title meaning, same school, same city/region).
3. `matches_former`: use ONLY when the seed's tense for this attribute is `former`; then use it whether the source shows the past role with dates or with no dates. If the seed's tense is `current`, never use `matches_former`.
4. `partial`: related but not the same (parent company, adjacent title, same country only).
5. `unrelated`: the sources say nothing about this attribute.
6. `contradicts`: the source clearly states a DIFFERENT value for the same attribute in the same tense. Seed says current employer X and the source shows current employer Y → contradicts. Seed says title "product designer" and the source shows the person's CURRENT title is an unrelated function (engineer, sales) → contradicts. A stale snippet that still shows a former employer is NOT a contradiction.
7. `name`: `exact` if the person's name in the sources is the seed name or a listed variant; `variant` for nickname/initials/order forms; `mismatch` if the sources are about a differently named person (Sarah Cheng ≠ Sarah Chen).
8. Return one row per input cid. Never invent a cid.
