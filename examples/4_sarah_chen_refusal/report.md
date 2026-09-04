# sarah chen

**ABSTAINED** · NAME_STRONG · identity 0.000 ░░░░░

> Input: `sarah chen, product designer, ex-figma`

The agent did not confirm an identity. See **Identity resolution** below for the candidates and what would settle it.

## How it connects

_No graph nodes._

## Identity resolution

- gate math not met after evidence cycles

| Candidate | Score | Terms |
|---|---|---|
| `c3` | 0.426 | prior -1.5; anchor:title:personal_site +1.0; surname:common +0.2 |
| `c1` | 0.269 | prior -1.5; anchor:title:professional_network +0.3; surname:common +0.2 |
| `c6` | 0.214 | prior -1.5; surname:common +0.2 |
| `c9` | 0.214 | prior -1.5; surname:common +0.2 |
| `c10` | 0.214 | prior -1.5; surname:common +0.2 |

- **rejected `c3`** — Personal site describes a Product Designer in Tech Consulting, SF bay area - no mention of Figma employment.
- **rejected `c1`** — LinkedIn profile shows a UX design student/certificate holder in Columbia, SC - no Figma or senior product designer history.
- **rejected `c6`** — No matched evidence shown beyond common surname; cannot verify any connection to Figma or product design role.
- **rejected below the gate margin** — `c9`, `c10`, `c11`, `c14`, `c15`, `c13`, `c2`, `c4`, `c12`, `c5`, `c8`, `c7`

**What would settle it:**

- LinkedIn or portfolio URL explicitly listing Figma as past employer
- Dates of employment at Figma
- City/region where seed's Sarah Chen worked
- Current employer or title after leaving Figma

## Run

| job | tool calls | cache hits | LLM calls | cost | seconds | stop |
|---|---|---|---|---|---|---|
| `sarah-chen-8` | 9 | 0 | 14 | $0.066 | 95.8 | no_expand:abstained |

_Confidence is ordinal, not frequency-calibrated: 0.9 is more reliable than 0.6, it does not mean 90% correct._
