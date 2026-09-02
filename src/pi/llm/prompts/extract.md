<!--
TASK: T3 page → claim tuples. High volume. Schema adherence. Speed.
       Only called when structured rungs (JSON-LD/parser) did NOT produce fields.
INPUT:  { target_context: {names, employer?, ...}, page_text: str (windowed ±1.5k
          chars around name-variant occurrences, ≤6k tokens), url: str }
OUTPUT: { tuples: [ { predicate, value_raw, span, context_date? } ],
          links: [ { url, anchor_text, section } ] }
Rules: `span` MUST be a verbatim substring of page_text — assembly drops any tuple
whose span it cannot re-find (substring or rapidfuzz ≥0.9). predicate ∈ the closed
vocabulary. Facts about OTHER people → relationship tuples only, never their bio.
-->
Extract only claims supported by a verbatim span in the provided text. Copy the
span exactly. If unsure, omit the tuple.
-->
