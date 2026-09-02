<!--
TASK: T5 role resolution for DEFINITE_DESC ("the CTO of Ariglad" — role, no name).
INPUT:  { role: str, company: str,
          candidates: [ {name, source, snippet, section} ] (from team/about page,
          Wayback if the role is described as past, LinkedIn SERP) }
OUTPUT: { holder: str|null, confidence_note: str, competing: [str] }
Rules: pick the CURRENT holder of the named role at the named company. If ≥2
official sources name different current holders → holder=null and list them in
`competing` (the run returns `ambiguous`). Then the seed is rewritten with the
resolved name and re-enters as NAME_STRONG.
-->
Identify who currently holds the named role at the named company from the provided
sources. If sources genuinely disagree, say so rather than guessing.
