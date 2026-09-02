# Stage 5 — Examples, eval, docs

**Owner:** you. **~3–4h — protect this time; it is what gets graded.**
**Prereqs:** Stage 4 green. **Builds against:** everything.

The deliverables live here: the three example runs, the eval table, and the three
docs. Spend any leftover slack here, **not** on Stage 6.

## Scope

### Workstream A — examples (the graded artifact)

Run the three PDF inputs end to end; tune prompts/weights **only** via
`constants.py` (no scattered edits). Commit under `examples/`:

```
examples/1_henry_wang/{input.txt, output.json, trace.jsonl, trace.md}
examples/2_cto_ariglad/{input.txt, output.json, trace.jsonl, trace.md}
examples/3_andrew_goering/{input.txt, output.json, trace.jsonl, trace.md}
```

- **1_henry_wang must show a rejected candidate** in `identity_resolution` (a plausible wrong Henry Wang, rejected with a reason). If the live run doesn't surface one, note why rather than fabricating.
- **2_cto_ariglad must show a `role_resolution` event** (company → role-holder → NAME_STRONG) then confirmed.
- **3_andrew_goering** shows the HARD_ID_EMAIL path and ideally a commit-email→employer specialization payoff.
- **(Example′, optional)** `4_sarah_chen` showing `ambiguous` + disambiguation table — the correct-refusal showcase — if slack remains.

### Workstream B — eval + replay

```
eval/{targets.json, run_eval.py}
```

- `targets.json` — the 3 PDF inputs + 2–3 verifiable targets incl. **one common name**.
- `run_eval.py` — 2 runs each with `PI_NO_CACHE=1`; prints per-target **identity correct / abstain / wrong**, claim count, cost, seconds, and **planner-vs-formula query yield**. Output form: "6 targets, 3 runs each, identity correct 17/18."
- Replay mode (`PI_OFFLINE=1`) if time: run against the content cache, network off — isolates code changes from web drift ("better or just different").

### Workstream C — docs

- **DESIGN.md** — the weights + derivation table, budget rules, gate, output schema, such that **a reader can predict the output without reading code**. Include the DESIGN′ honesty note (uniqueness term trivially satisfied in single-candidate HARD_ID runs). State the **calibration scope**: ordinally calibrated, not frequency-calibrated; method for real calibration documented but data out of scope.
- **README.md** — setup, keys, run, example `curl`, the calibration scope statement, edge-case behavior.
- **SCALING.md** — three sections: what breaks at **100 concurrent runs**, at **10k stored entities**, when **the same person is investigated twice**. Include the C9 resume design and the C6′ contested-identity handling as architectural-judgment notes.

## Checkpoints (binary)

- [ ] Fresh clone + `.env` → `uv run pi investigate "Henry wang, sixtyfour ai"` produces valid output in **< 5 min**.
- [ ] All three `examples/*/` committed with `input.txt`, `output.json`, `trace.jsonl`, `trace.md`.
- [ ] `1_henry_wang` output contains a **rejected candidate with a reason**; `2_cto_ariglad` trace contains a `role_resolution` event.
- [ ] For each example, a reader of `trace.md` alone can follow: every tool call with args + latency, every planner choice vs formula rank, the disconfirmation action, the gate terms, and the stop reason **with numbers**.
- [ ] `run_eval.py` prints the table; **repeat-run variance reported** (e.g., "identity correct N/M").
- [ ] `DESIGN.md` lets a reader predict output shape + a confidence value's arithmetic without opening code.
- [ ] `SCALING.md` has all three sections.

## Degrade / cut behavior

Cut order within this stage: 6-target eval → 3×1; SCALING.md → a README section;
`4_sarah_chen` example dropped. **Never cut:** the three PDF examples with
readable traces, the calibration-scope statement, the "rejected candidate"
showcase in example 1.
