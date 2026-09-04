<!--
TASK: T3 page → claim tuples. Only when structured rungs (JSON-LD/parser) produced nothing.
INPUT:  target context (name variants, employer, title), url, page text (windowed around name occurrences).
Predicates: employer, title, employment, education, location, email, phone, website, handle, repo,
publication, talk, award, funding_event, board_or_advisor, founded, relationship, other.
-->
Extract facts about the TARGET person only, each backed by a verbatim span copied from the page text.

Rules:
1. `span` must be an exact substring of the page text, copied verbatim.
2. Facts about other people: emit only a `relationship` tuple whose value is exactly `<relationship kind>: <Full Name>` — the colon is required (e.g. `co_founder: Jane Doe`). Never their employer, contact, or bio.
3. If the page is not about the target, return no tuples.
4. `context_date`: the date the page states for the fact (a posting date, "as of", a date range). Null if none.
5. Prefer omission over inference. Do not normalize values; copy them as written.
6. For `employment`, `value` is the organization name; `context_date` is the date range as written (e.g. `2019 – Present`). Emit a separate `title` tuple with the same `context_date` for the role.
7. Use `other` only for one fact about the target that fits no predicate above; never instead of `employer`, `title`, or another listed predicate.
