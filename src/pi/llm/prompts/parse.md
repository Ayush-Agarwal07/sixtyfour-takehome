<!--
TASK: T5 input parse. One call/run. Handle odd phrasings.
INPUT:  {input: str}  (hard-ID regex already ran separately)
OUTPUT: {"names":[...],"orgs":[...],"titles":[...],"schools":[...],"locations":[...],
         "role_description":"...|null","tense":{"<org lowercase>":"current|former"},"reasoning":"..."}
-->
Extract structured fields from a freeform people-search target.

Rules:
1. Return only entities literally present in the input. Never add a first name, surname, employer, or title that is not stated.
2. Instruction words ("do deep research on", "find", "look up") are not entities.
3. `names`: the person's name as written. Do not expand initials.
4. `orgs`: companies, universities, or organizations named as an anchor. `schools` also lists universities.
5. `titles`: job titles or roles ("product designer", "CTO").
6. `role_description`: set ONLY when the input names a role at an organization but gives NO person name ("the CTO of Ariglad"). Otherwise null.
7. `tense`: for each org, "former" if the input marks it as past ("ex-", "former", "previously", "was at"), else "current". Keys are the org names in lowercase.
