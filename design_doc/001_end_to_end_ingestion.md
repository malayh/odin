# 001 — End-to-End Ingestion: Prove It, Build the CLI, Run a Real Corpus

Living tracker for the work that takes Odin's ingestion pipeline from "code-complete, fake-tested"
to "proven against real infrastructure with a real corpus."

## Goals

1. **Finish ingestion** — prove the existing pipeline works end-to-end against real Postgres/AGE/
   MinIO + real OpenAI/OpenRouter. Fix only genuine bugs that surface. No new ingest features.
2. **Build the CLI** — the missing human driver: `login`, `admin`, `ingest`, `search`.
3. **Manufacture a corpus** — a big, connected "CEO notes" corpus under `integration_test/corpus/`.
4. **Run it and observe** — a standalone harness that ingests the corpus and reports what the
   knowledge graph actually becomes.

## Decisions

| Decision | Choice |
| --- | --- |
| "Finish ingestion" | Prove it, don't extend. md/txt/html only; no delete/soft-delete; fix real bugs only. |
| CLI scope | Ingest + observe slice: `client`/`config`/`output` + `login`, `admin`, `ingest`, `search`. `ask`/`graph` stay stubs (no backend yet). |
| Run harness | Standalone script + observation report. Tolerant of LLM nondeterminism. |
| Corpus | Synthetic, big and connected — "CEO notes" theme. Plant shared entities, contradictions, mixed formats, personal+org scopes. |

## Phase checklist

- [x] **P0 — Design doc** (this file).
- [x] **P1 — CLI foundation**: `config.py`, `client.py`, `output.py`.
- [x] **P2 — CLI commands**: `login`, `admin`, `ingest`, `search`.
- [x] **P3 — Corpus**: `integration_test/corpus/{personal,org}/*` (14 docs).
- [x] **P4 — Run harness**: `integration_test/run.py` + `README.md`.
- [x] **P5 — Run for real + record observations** (below).

## Reused infrastructure (don't rebuild)

- **Bootstrap:** `just seed-admin <email>` (`backend/odin/seed.py`) mints the first admin + a
  one-time token. No `/auth/login` endpoint exists; the CLI `login` just stores a token.
- **API surface** (router prefixes): `GET /health`; `GET /auth/whoami`; `POST /admin/users`,
  `POST /admin/users/{id}/tokens`, `POST /admin/orgs`, `POST /admin/orgs/{id}/members`;
  `POST /ingest` (multipart `file`,`key`,`scope`); `GET /jobs/{id}`; `POST /search`.
- **Auth:** `Authorization: Bearer odin_pat_…`. **Error envelope:** `{"error":{"type","message"}}`.
- **Scope wire format:** `personal` or `org:<uuid>` (`tenancy.Scope`). **Role:** `admin|editor|viewer`.
- **Observation:** `odin.db.SessionLocal` + ORM (`Document`/`Chunk`/`Job`) + `graphdb.cypher`.

## Corpus design — "Helios Robotics" CEO notes

Narrator: **Mara Vance**, CEO of fictional **Helios Robotics**. ~12–16 cross-referenced docs.

**Cast (recurs across docs):**
- People: Mara Vance (CEO), Dana Okafor, Sam Ortiz (Head of Sales), Priya Nair (CFO), Leo Zhang (lead eng).
- Orgs: Helios Robotics; Northwind Capital (investor); Vertex Dynamics (rival); Acme Logistics (customer); Quanta Labs (acquisition target).
- Projects: Project Atlas (flagship), Project Beacon, Project Orion.
- Places: Austin HQ, Berlin office.

**Planted alias variants (exercise entity resolution):**
- `Helios Robotics` / `Helios` / `Helios Inc.`
- `Northwind Capital` / `Northwind`
- `Dana Okafor` / `Dana`

**Planted contradictions (exercise CONTRADICTS):**
- Dana's title: **CTO** vs **VP Engineering**.
- Project Atlas ship date: **Q2** vs **Q3**.
- Northwind Series B amount: **$40M** vs **$45M**.
- Vertex Dynamics framing: **competitor** vs **potential partner**.

**Formats:** `.md` (board/strategy/roadmap/1:1), `.txt` (quick jottings, investor call), `.html` (wiki, press release).

**Scopes:**
- `corpus/org/` — shared company docs (board deck, roadmap, wiki, press).
- `corpus/personal/` — Mara's candid private notes (1:1 impressions, personal todos). The split is
  what the isolation spot-check exercises.

## Run procedure (P4 harness)

Prereqs: `docker compose up -d`, `just migrate`, `just serve` + `just worker` running,
`OPENAI_API_KEY` + `OPENROUTER_API_KEY` set.

1. Check `/health`; fail fast with instructions if missing.
2. `just seed-admin mara@helios.test` → admin token; `odin login --token …`.
3. `odin admin create-org --name "Helios Robotics"` → `org_id`; `odin admin add-member` to give
   Mara `admin` on the org (user id from `whoami --json`).
4. `odin ingest -d corpus/personal --scope personal` and `… -d corpus/org --scope org:<org_id>`
   (drives the real worker; polls to `done`).
5. Observe via DB + graph: docs by state/scope, chunk counts, entities, `REL` edges (with
   provenance), `CONTRADICTS` edges, captured aliases, `/search` samples, isolation spot-check.

## Observations (first real run — 2026-06-25)

Ran `integration_test/run.py` against the live stack (Postgres+AGE+MinIO) with **real** OpenAI
embeddings + OpenRouter (`z-ai/glm-5.2`) extraction. **End-to-end ingestion is proven.**

### What works ✅

| Signal | Result |
| --- | --- |
| Documents indexed | **14 / 14** (8 org, 6 personal) — every doc reached `indexed` |
| Chunks | 14 |
| Graph | **52 entities**, **166 REL edges**, scope + provenance on every edge |
| Provider calls | OpenAI embeddings + OpenRouter extraction, all `200 OK`, zero worker errors |
| **Scope isolation** | **PASS** — org query → 100% org hits; personal query → 100% personal hits; no cross-scope leakage |
| **Idempotency (dedup)** | **PASS** — re-run ingested 0, deduped 14/14; no duplicate documents |
| Search quality | Good — "Atlas ship date" → roadmap; "Series B" → $45M press release; "candid take" → personal team-assessment |

The pipeline works for real: intake → blob (dedup) → chunk → **real embeddings** → **real LLM
extraction** → resolution → AGE graph (entities/MENTIONS/REL/CONTRADICTS) → `indexed`, scope-isolated
end to end.

### Bug found and fixed

- **CLI `search` couldn't parse its query argument.** `search` was mounted as a Typer sub-group
  (`add_typer`) with a positional `QUERY`; a Click *group* reserves the first positional for a
  subcommand name, so the argument never bound (`Missing argument 'QUERY'`). Fixed by registering
  `search` as a real root command (`app.command("search")(search.search)`). Option-only commands
  (`login`, `ingest`) were unaffected and stayed as groups.

### Findings to address in a follow-up (L3 quality — out of scope for "prove it, don't extend")

The run did its job: it exposed real graph-quality issues. These are **not** blockers to the
end-to-end proof, and per the "prove it, don't extend" directive they are recorded here rather than
fixed in this pass.

1. **Entity resolution is effectively a no-op on alias variants.** The graph kept *separate*
   canonical nodes for the same real-world entity: `org:helios` / `org:helios inc.` /
   `org:helios robotics`; `org:northwind` / `org:northwind capital`; `person:dana` /
   `person:dana okafor`; `person:mara` / `person:mara vance`; `place:austin` / `place:austin hq`;
   `place:berlin` / `place:berlin office`; and Atlas split across **types** as
   `product:atlas` / `product:project atlas` / `project:atlas` / `project:project atlas`. Only **1**
   multi-surface node formed (a case difference). Likely causes: (a) `key = type:name`, so when the
   LLM assigns different *types* to the same thing (Atlas as Product vs Project) the keys never
   collide and exact-merge misses; (b) the fuzzy clusterer in `services/resolution.py` (3.6) isn't
   firing across the scope. *Fix direction:* reconcile entity type before keying / merge across
   types; verify the fuzzy pass actually runs and its threshold.

2. **Contradiction detection massively over-fires (197 `CONTRADICTS` edges).** The heuristic
   (`same (subject, predicate)` with ≥2 distinct objects → contradiction) is wrong for **multi-valued
   predicates**: `helios BUILDS atlas <> beacon`, `mara RELATED_TO <everything>`,
   `leo WORKS_AT atlas-team <> helios` are all legitimate, not conflicts. It's compounded by finding
   (1): unmerged aliases manufacture fake "distinct objects" (`WORKS_AT helios inc. <> helios
   robotics`; `BUILDS product:project atlas <> project:project atlas`). The genuinely-planted
   conflicts mostly drowned in the noise — Atlas Q2/Q3 *did* surface (`product:atlas RELATED_TO
   topic:q2 <> topic:q3`), but Dana's title and the $40M/$45M Series B did not form clean
   contradiction edges. *Fix direction:* restrict contradiction detection to single-valued predicates
   (or value-typed objects: dates/amounts/titles); canonicalize object aliases before grouping.

3. **LLM type/predicate inconsistency.** The same thing gets different ontology types across chunks
   (Atlas = Product and Project; "Helios platform" vs "Helios control platform"). Ontology
   normalization isn't constraining the type assignment, which feeds (1) and (2).

4. **Per-source-doc edge duplication** (by design — one edge per assertion per source doc) inflates
   edge/contradiction counts. Accepted residue, but it amplifies (2).

### Not yet exercised

- The **graph-replace-on-new-version** path (`delete_document_contributions`): re-ingest deduped at
  intake (content unchanged), so the replace-and-reindex path wasn't hit. To exercise it, edit one
  doc's content and re-run; confirm its old contributions are replaced, not duplicated.

### Recommendation

The end-to-end ingestion milestone is **met**. The natural next pass is a focused **L3 graph-quality
hardening** (resolution merging across types + contradiction precision), which would make the graph
faithful enough to ground L4 (Ask). The full run report is in the run output;
re-run with `uv run python integration_test/run.py`.
