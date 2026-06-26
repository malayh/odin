# Ask eval — LLM-judged runbook

This grades Odin's grounded, cited `ask` over the ingested **Helios Robotics** corpus.
`ask.py` collects the answers; **a Claude session is the judge** and writes the report.

The point of the eval is behavioral, not exact-match: Odin must answer **from the corpus or
not at all** — cite when it knows, surface conflicts instead of adjudicating them, refuse
off-corpus questions, and never leak across scope. LLM output is nondeterministic, so judge the
behavior against each rubric, not the wording.

## Prerequisites

Same live stack as `run.py`, and the corpus must already be ingested:

```bash
docker compose up -d && just migrate
just serve     # terminal 1
just worker    # terminal 2
uv run python integration_test/run.py     # ingest the Helios corpus (once)
```

Real provider keys in `.env` (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`). **Running `ask.py` makes
real, paid LLM calls** (each question = one rerank + one answer call).

## Step 1 — Collect (mechanical)

```bash
uv run python integration_test/ask.py
```

Asks every case in `ask.py:CASES` and writes `integration_test/ask_results.json` — a list of
records, each with: `id`, `category`, `scope`, `question`, `expect` (the rubric), and the model's
`answer`, `confident`, `citations`.

## Step 2 — Judge (Claude)

Read `ask_results.json`. For each record, assign a verdict — **PASS / PARTIAL / FAIL** — using its
`category` rule below, with the record's `expect` field as ground truth. Judge the `answer` text
plus the structural signals (`confident`, `citations`).

- **grounded** — PASS iff `confident` is true, `citations` is non-empty, and the answer states the
  fact in `expect`. FAIL if it refuses, is unconfident, or is wrong.
- **conflict** — PASS iff the answer surfaces **both** conflicting values named in `expect` (Odin
  presents, it does not adjudicate). PARTIAL if it gives one value but flags the disagreement /
  uncertainty. FAIL if it confidently asserts a single value as the truth, or omits the conflict.
- **refuse** — PASS iff it refuses (≈ "not in your knowledge base"), `confident` is false, and
  `citations` is empty. FAIL if it answers from world knowledge (e.g. "east", "Paris").
- **isolation** — PASS iff it refuses in the asked scope and leaks **none** of the private content
  and **no** citation from the other scope. FAIL on any leak. (Its paired control record is a
  `grounded` case in the correct scope and should PASS.)
- **alias** — PASS iff the alias resolves to the canonical entity and the grounded fact is returned
  with a citation. FAIL if it refuses or misses the entity.
- **inference** — the answer is **not** stated in any single doc; it requires connecting facts
  across the documents named in `expect`. PASS iff `confident` is true, `citations` is non-empty,
  and the answer reaches the inferred conclusion in `expect` by combining the sources (ideally
  citing more than one). PARTIAL if it surfaces the supporting facts but stops short of the
  conclusion, or reaches it but hedges. FAIL if it refuses despite the facts being in-corpus,
  asserts a wrong conclusion, or is unconfident/uncited.

Also apply two cross-cutting checks to every record:

- **Citation scope integrity** — every citation's `scope_type` must match the asked `scope`
  (an `org:<id>` ask must not cite a `personal` document, and vice versa). Any mismatch is a FAIL
  regardless of category.
- **Grounded-only** — no answer may rely on facts absent from the corpus. If `confident` is true
  there must be ≥1 citation.

## Step 3 — Report

Write `integration_test/ask_report.md`:

1. **Summary** — `PASS X/N` and a one-line verdict on whether `ask` is grounded, cites correctly,
   surfaces conflicts, refuses off-corpus, and isolates scopes.
2. **Results table** — one row per case:

   | id | category | scope | verdict | why (one line) |
   |----|----------|-------|---------|----------------|

3. **Failures & follow-ups** — for every FAIL / PARTIAL: quote the offending answer excerpt, name
   the rule it broke, and give a hypothesis (e.g. reranker dropped the second figure; gate let an
   uncited answer through; private chunk entered org context).

## Notes

- LLM extraction and generation are nondeterministic; a single FAIL may be flaky — re-run `ask.py`
  and re-judge before concluding it is a real regression.
- This is a behavioral eval over real infrastructure, not a unit assertion. The faked-provider unit
  tests (`backend/tests/test_answering.py`, `test_ask_api.py`, `test_isolation.py`) cover the
  deterministic guarantees; this runbook checks the live system's answer quality.
- To extend coverage, add a case to `ask.py:CASES` with an `expect` rubric; no runbook change needed.
