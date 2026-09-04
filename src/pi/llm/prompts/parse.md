<!--
TASK: T5 input parse. One call/run. Handle odd phrasings.
INPUT:  {input: str}  (hard-ID regex already ran separately)
-->
Extract structured fields from a freeform people-search target.

Rules:
1. Return only entities literally present in the input. Never add a first name, surname, employer, or title that is not stated.
2. Instruction words ("do deep research on", "find", "look up") are not entities.
3. `names`: the person's name as written. Do not expand initials.
4. `orgs`: organizations the person works or worked for. A university, lab, or institute belongs here only when the input frames it as work ("researcher at", "professor at", "postdoc", "lab member", "works at").
5. `schools`: universities or colleges the person studied at ("studied", "student", "alum", "PhD from", a degree). A university with no framing at all goes in `schools`, not `orgs`.
6. `titles`: job titles or roles ("product designer", "CTO").
7. `role_description`: set ONLY when the input names a role at an organization but gives NO person name ("the CTO of Ariglad"). Otherwise null.
8. `tense`: for each org, "former" if the input marks it as past ("ex-", "former", "previously", "was at"), else "current". Keys are the org names in lowercase. Use exactly the string `former` or `current` for each value.
