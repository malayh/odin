# Integration test — end-to-end ingestion

Ingests a deliberately connected "CEO notes" corpus (`corpus/`) through the real
`odin` CLI against a live stack, then observes the knowledge graph it produced.
This is the end-to-end proof that ingestion works against real infrastructure and
real LLM/embedding providers — not the fakes used by the unit tests.

## Corpus

Fictional company **Helios Robotics** (CEO: Mara Vance), ~14 cross-referenced docs:

- `corpus/org/` — shared company docs (board deck, roadmap, wiki, press, sales/eng updates).
- `corpus/personal/` — Mara's candid private notes (1:1s, investor jottings, todos).

It is seeded with:

- **Alias variants** (entity resolution): `Helios Robotics` / `Helios` / `Helios Inc.`;
  `Northwind Capital` / `Northwind`; `Dana Okafor` / `Dana`.
- **Contradictions** (all in org scope, so `CONTRADICTS` can link them): Dana's title
  (CTO vs VP Engineering), Project Atlas ship date (Q2 vs Q3), Series B amount ($40M vs $45M),
  Vertex Dynamics (competitor vs potential partner).
- **A personal/org scope split** to exercise retrieval isolation.

## Prerequisites

From the repo root:

```bash
docker compose up -d          # Postgres (:25000) + MinIO (:25001)
just migrate                  # alembic upgrade head
just serve                    # terminal 1 — API at :8000
just worker                   # terminal 2 — job worker
```

Real provider keys must be set in `.env` (used by the server + worker):

```
OPENAI_API_KEY=...            # embeddings (text-embedding-3-small)
OPENROUTER_API_KEY=...        # extraction LLM (answer_model)
```

Start from a clean graph for a tidy report (a fresh DB, or clear the `odin` graph /
truncate `documents`).

## Run

```bash
uv run python integration_test/run.py
```

What it does:

1. Seeds the initial admin (`mara@helios.test`) and logs the CLI in (writes an isolated
   config to `integration_test/.odin_config.yaml` via `ODIN_CONFIG`).
2. Creates the `Helios Robotics` org (the creator is auto-enrolled as admin).
3. `odin ingest -d corpus/personal --scope personal` and `-d corpus/org --scope org:<id>`,
   polling each job to completion against the real worker.
4. Observes via the datastore + AGE graph and prints a report: documents by state/scope,
   chunk count, entities, relationships, contradictions, resolved aliases, sample searches,
   and a scope-isolation spot-check.

Capture the report for the design doc:

```bash
uv run python integration_test/run.py | tee /tmp/odin_run.txt
```

## Notes

- Re-running is safe: unchanged files dedup (reported as `deduped`); the org is reused.
- To exercise the idempotent graph replace, edit one doc and re-run — its contributions are
  replaced, not duplicated.
- LLM extraction is nondeterministic, so the exact entities/edges vary run to run; the harness
  reports rather than asserts.
