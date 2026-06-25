# Odin — Implementation Plan

> Companion to [`spec.md`](./spec.md). The spec says **what** Odin is; this says **in what
> order we build it** and **how we know each piece works**. Read top-to-bottom: each layer
> assumes everything above it exists.

## How this plan is structured

We build **substrate first, then vertical feature slices**:

```
L0  Substrate      infra · config · db · auth/tenancy · worker runtime
L1  Ingest         intake → blob → convert → chunk            (service → api → cli)
L2  Search         embed → vector retrieval                   (service → api → cli)
L3  Graph          extract → resolve → graph upsert + expand  (service → api → cli)
L4  Ask            rerank → grounded, cited generation        (service → api → cli)
L5  Insight        derive docs → reasoning subgraph + trust   (service → api → cli)
```

- **L0** is horizontal: it is built once, completely, and every later slice stands on it.
- **L1–L5** are vertical: each cuts service → API → CLI and ends in a **demoable capability**.
- Slice order is the **RAG spine first** — ingest and search are usable before the graph
  exists; the graph, then grounded ask, then derived insights layer on top.

Each slice **extends the ingestion pipeline** (`worker/handlers.py`) by inserting its stage,
rather than rewriting it. The pipeline grows one stage per layer:

```
L1:  intake → convert → chunk → finalize(chunked)
L2:  intake → convert → chunk → embed → finalize(indexed)
L3:  intake → convert → chunk → embed → extract → graph-upsert → finalize(indexed)
```

### Migrations: incremental per layer

Each layer owns the Alembic migration that creates the tables it introduces. Numbering:

| Migration            | Layer | Adds                                                        |
| -------------------- | ----- | ----------------------------------------------------------- |
| `0001_core`          | L0    | `users`, `orgs`, `memberships`, `access_tokens`, `documents`|
| `0002_ingest`        | L1    | `chunks`, `jobs`                                            |
| `0003_embeddings`    | L2    | `embedding_models`, `embeddings` (pgvector + HNSW)         |
| `0004_graph`         | L3    | `graph_mutations`                                          |
| `0005_derived`       | L5    | derived-doc / proposed-fact trust columns + state          |

The AGE graph itself is bootstrapped in `docker/postgres/init.sql`; node/edge labels are
created lazily by the graph service (L3). L4 (Ask) introduces no new tables.

### Step format

Every step is written as:

- **Goal** — the one thing this step makes true.
- **Deliverables** — the files/artifacts it produces (all are currently stubs).
- **Acceptance** — the observable check that says "done."
- **Tests** — the tests written *with* this step (per the locked test-rigor decision).
- **Depends on** — prerequisite steps.

### Standing invariants (verified at every layer that can violate them)

1. **Tenancy isolation** — no caller may retrieve, traverse, or cite content outside their
   scope set, at *any* retrieval stage (vector, graph, rerank, citation). Each of L2/L3/L4/L5
   adds a case to a growing **isolation test suite** (`tests/test_isolation.py`).
2. **Provenance on everything** — every graph node/edge carries origin, source doc id(s),
   method/model, confidence, timestamps (from L3 on).
3. **Idempotent, retryable jobs** — re-running a job (same content hash / job id) is a no-op
   or a clean retry, never a duplicate.
4. **Secrets stay server-side** — provider keys + datastore creds live in server env only;
   the CLI ever only holds its personal access token.

### Testing approach (applies throughout)

- **Unit** — pure logic (chunking, scope resolution, token hashing, ontology validation)
  with no I/O.
- **Integration** — against **ephemeral Postgres (pgvector + AGE) + MinIO** from
  `docker-compose.yml`; async via `pytest-asyncio`; each test runs in a rolled-back
  transaction or a freshly-migrated throwaway schema. Provider calls (Claude / embedder /
  reranker) are **faked** behind the service interfaces by default; a `--live` opt-in marker
  runs the real-provider smoke tests.
- Shared fixtures live in `backend/tests/conftest.py`: app client, db session, seeded
  principal/org, MinIO bucket, fake-provider doubles.

---

## Layer 0 — Substrate

**Outcome:** the server boots, a user can `odin login`, an admin can create an org and invite
a user, the worker process runs idle, and tenancy is enforceable — all behind migrations and
tests. No ingestion, search, graph, or AI yet.

### Step 0.1 — Test harness & dev loop
- **Goal:** a runnable test suite wired to ephemeral infra before any logic exists.
- **Deliverables:** `backend/tests/conftest.py` (async db session, app client, MinIO bucket,
  fake-provider fixtures), `backend/pyproject.toml` test config (already has pytest/asyncio),
  a `make test` / `uv run pytest` entry, CI-less local loop documented.
- **Acceptance:** `uv run pytest` collects and runs a trivial passing test against a migrated
  throwaway database.
- **Tests:** `tests/test_smoke.py` — `/health` returns 200; db fixture round-trips.
- **Depends on:** docker-compose infra (exists).

### Step 0.2 — Config finalize
- **Goal:** all settings load from env/`.env`, typed and cached.
- **Deliverables:** `backend/odin/config.py` (already stubbed with fields) — confirm every
  field used downstream exists; `Settings` validates required keys lazily.
- **Acceptance:** `get_settings()` parses `.env.example`; missing optional keys don't crash
  boot; provider keys are not required to start the server.
- **Tests:** `tests/test_config.py` — env override, defaults, `lru_cache` identity.
- **Depends on:** —

### Step 0.3 — DB layer + AGE access
- **Goal:** async engine/session and a helper to run AGE cypher.
- **Deliverables:** `backend/odin/db.py` (engine, `SessionLocal`, `get_session`, `Base`);
  an AGE helper (set `search_path`, run a cypher statement, parse `agtype` rows) — co-located
  in `db.py` or a small `odin/graphdb.py` (decide at build; service in L3 consumes it).
- **Acceptance:** a test opens a session, executes SQL and a trivial `cypher(...)` query
  against the `odin` graph, gets rows back.
- **Tests:** `tests/test_db.py` — relational round-trip; AGE `RETURN 1` round-trip.
- **Depends on:** 0.1.

### Step 0.4 — Migration `0001_core`
- **Goal:** the tenancy + document spine exists in Postgres.
- **Deliverables:** `backend/alembic/versions/0001_core.py`; ORM in `backend/odin/models.py`
  for `users`, `orgs`, `memberships(user_id, org_id, role)`, `access_tokens`,
  `documents(id, owner_user_id, scope, doc_type, content_hash, blob_uri, version,
  supersedes_id, state, created_at)`.
- **Acceptance:** `alembic upgrade head` then `downgrade base` is clean; models match tables.
- **Tests:** `tests/test_migrations.py` — upgrade/downgrade round-trip; unique/FK constraints
  (e.g. one membership per (user, org); content_hash index).
- **Depends on:** 0.3.

### Step 0.5 — Logging & unified error model
- **Goal:** structured app logs and one consistent API error shape.
- **Deliverables:** `backend/odin/logging.py` (structured logger, request id);
  `backend/odin/errors.py` (typed app exceptions + a single JSON error envelope);
  exception handlers registered in `backend/odin/main.py`.
- **Acceptance:** an unhandled domain error returns the documented envelope, not a stack trace;
  a request id appears in logs.
- **Tests:** `tests/test_errors.py` — known errors → mapped status + envelope; unknown → 500
  envelope.
- **Depends on:** 0.1.

### Step 0.6 — Security: tokens & bearer auth
- **Goal:** issue/verify personal access tokens; authenticate requests.
- **Deliverables:** `backend/odin/security.py` (token generate, hash-at-rest, verify);
  `backend/odin/api/deps.py` `current_principal` dependency (bearer → user).
- **Acceptance:** a valid token resolves to its user; a bad/expired/missing token → 401 in the
  error envelope; tokens are stored hashed, never plaintext.
- **Tests:** `tests/test_security.py` — issue→verify, hash-not-reversible, wrong token rejected;
  dependency 401 path.
- **Depends on:** 0.4, 0.5.

### Step 0.7 — Tenancy: scope model & isolation predicate
- **Goal:** compute a principal's scope set and the predicate every query filters by.
- **Deliverables:** `backend/odin/tenancy.py` — `Scope` (personal / `org:<id>`), resolve a
  principal's full scope set from memberships, `--scope` narrowing/validation, and the single
  reusable filter (SQL + graph) that enforces the isolation invariant.
- **Acceptance:** scope-set resolution matches memberships; narrowing to an org the user isn't
  in is rejected; the predicate excludes out-of-scope rows.
- **Tests:** `tests/test_tenancy.py` — multi-org membership resolution, narrowing rules,
  predicate correctness; **seeds the growing** `tests/test_isolation.py`.
- **Depends on:** 0.4.

### Step 0.8 — Auth & org services + endpoints + seed
- **Goal:** real login and org/membership administration; invite-only onboarding.
- **Deliverables:** `services/auth.py`, `services/orgs.py`; `api/auth.py` (login / token),
  `api/admin.py` (create org, invite/remove user, set role, manage tokens); an **initial-admin
  seed** (CLI/env at install per spec §4.5); CLI `commands/login.py` + `commands/admin.py`,
  `cli/odin_cli/client.py`, `cli/odin_cli/config.py` (`~/.odin/config.yaml`).
- **Acceptance:** `odin login` stores token+context; an admin creates an org, invites a user,
  assigns Admin/Editor/Viewer; a Viewer is refused write ops; non-admins can't administer.
- **Tests:** `tests/test_auth_api.py`, `tests/test_admin_api.py` — login flow, role
  enforcement (Admin/Editor/Viewer matrix), invite-only (no open signup), seed idempotency.
- **Depends on:** 0.6, 0.7.

### Step 0.9 — Worker runtime skeleton
- **Goal:** a runnable worker process and a handler-registry loop — with no real jobs yet.
- **Deliverables:** `worker/runner.py` (poll loop, graceful shutdown, backoff),
  `worker/handlers.py` (handler registry; empty), `worker/__main__.py` (`python -m odin.worker`).
  *(The `jobs` table + the real `FOR UPDATE SKIP LOCKED` claim land in L1, step 1.3.)*
- **Acceptance:** `uv run python -m odin.worker` starts, logs that it's idle, and shuts down
  cleanly on SIGTERM.
- **Tests:** `tests/test_worker_runtime.py` — registry dispatch with a fake handler; clean
  startup/shutdown.
- **Depends on:** 0.2, 0.5.

**Layer 0 exit criteria:** server boots with `/health` + `/docs`; `odin login` + full
`odin admin` membership flow work end-to-end; worker runs idle; tenancy resolver and
role matrix are tested; migrations up/down clean.

---

## Layer 1 — Ingest slice

**Outcome:** `odin ingest -d <dir>` pushes text/md/html through the API; originals are stored
content-addressed (dedup + versioning), documents are chunked, jobs are pollable. Pipeline
terminal state: `chunked`. (Embedding arrives in L2.)

### Migration `0002_ingest`
- `chunks(id, document_id, ordinal, text, section_meta, char_range)`;
- `jobs(id, document_id, type, state, attempts, error, created_at)`.

### Step 1.1 — Blob store client
- **Goal:** content-addressed put/get against the S3-compatible store.
- **Deliverables:** `services/blobs.py` — hash bytes, `put(blob) → uri`, `get(uri)`,
  existence check; uses boto3 with env creds + `S3_ENDPOINT_URL`/`S3_BUCKET`.
- **Acceptance:** same bytes → same uri (idempotent); store + retrieve round-trips against
  MinIO; original bytes preserved exactly.
- **Tests:** `tests/test_blobs.py` (integration, MinIO) — round-trip, content addressing,
  re-put is a no-op.
- **Depends on:** L0.

### Step 1.2 — Job queue (claim/complete)
- **Goal:** durable Postgres-backed queue with concurrency-safe claim.
- **Deliverables:** `worker/queue.py` — `enqueue`, `claim` (`SELECT … FOR UPDATE SKIP LOCKED`),
  `complete`, `fail` (attempts/backoff/retry); wire into `worker/runner.py`.
- **Acceptance:** two workers never claim the same job; failed jobs retry up to N then go
  `failed` with error; claim is idempotent under restart.
- **Tests:** `tests/test_queue.py` (integration) — concurrent claim exclusivity, retry/backoff,
  terminal `failed`.
- **Depends on:** `0002_ingest`, 0.9.

### Step 1.3 — Converters (native text/md/html)
- **Goal:** normalize supported formats to text; define the converter contract for later
  pluggable formats.
- **Deliverables:** `services/converters.py` — a converter signature `(bytes, mime) →
  (text, original_bytes)`, a registry, and native implementations for text/Markdown/HTML.
  Unknown formats raise a clear "no converter" error (PDF/Office/email come later as plugins).
- **Acceptance:** md/html/text convert to expected normalized text; original bytes returned
  unchanged for storage; unsupported mime is a clean, typed error.
- **Tests:** `tests/test_converters.py` — md/html/text normalization, registry dispatch,
  unsupported-format error.
- **Depends on:** L0.

### Step 1.4 — Chunking
- **Goal:** structure-aware, token-bounded chunks with citation metadata.
- **Deliverables:** `services/chunking.py` — split on structure (headings/paragraphs) into
  token-bounded chunks with overlap; emit `ordinal`, `section_meta`, `char_range`.
  *(Concrete size/overlap params chosen here — see Open params.)*
- **Acceptance:** a 10k-token doc yields a stable, deterministic chunk set; char ranges map
  back into the source exactly; overlap honored; re-running is identical.
- **Tests:** `tests/test_chunking.py` — sizing/overlap, stable ordinals, char-range fidelity,
  edge cases (tiny doc, no headings).
- **Depends on:** 1.3.

### Step 1.5 — Ingest intake service + endpoint
- **Goal:** accept documents over HTTP, dedup/version, persist, enqueue.
- **Deliverables:** `services/ingest.py`, `api/ingest.py` — accept upload(s) + scope +
  metadata; content-hash dedup (skip reprocessing identical content); versioning
  (`supersedes_id` for changed logical source); create `documents` row (`pending`); enqueue
  job; return job/doc id immediately. Scope authorization enforced (Editor/Admin for org).
- **Acceptance:** identical content is deduped (no new job); changed content creates a new
  version superseding the old; response carries a pollable id; ingesting to an org you can't
  write to is refused.
- **Tests:** `tests/test_ingest_api.py` — dedup, versioning/supersession, scope auth,
  immediate-id contract.
- **Depends on:** 1.1, 1.2, 0.7/0.8.

### Step 1.6 — Ingest pipeline handler (L1 stages)
- **Goal:** the worker runs intake → convert → chunk → finalize.
- **Deliverables:** an `ingest` handler in `worker/handlers.py` chaining blobs → converters →
  chunking → persist chunks → mark `chunked`; failures mark `failed` with error; idempotent
  on retry.
- **Acceptance:** enqueued doc ends `chunked` with persisted chunks + stored blob; a forced
  mid-stage failure retries cleanly and is idempotent; dedup short-circuits.
- **Tests:** `tests/test_pipeline_l1.py` (integration) — full happy path, retry idempotency,
  failure → `failed`.
- **Depends on:** 1.1–1.5.

### Step 1.7 — Jobs status endpoint
- **Goal:** clients poll ingestion progress.
- **Deliverables:** `api/jobs.py` — `GET /v1/jobs/{id}` → state (`pending → chunked | failed`),
  scope-checked (only the owner sees it).
- **Acceptance:** status transitions are observable; another user can't read someone's job.
- **Tests:** `tests/test_jobs_api.py` — state polling, scope check.
- **Depends on:** 1.6.

### Step 1.8 — CLI `odin ingest`
- **Goal:** push local files/dirs to the API and report status.
- **Deliverables:** `cli/odin_cli/commands/ingest.py`, `cli/odin_cli/output.py` — walk
  `-d <dir>` / single `<file>`, POST with `--scope`, poll job(s), human + `--json` output.
- **Acceptance:** `odin ingest -d ./docs --scope personal` ingests a tree, prints per-file
  job ids/status; `--json` is machine-parseable.
- **Tests:** `tests/test_cli_ingest.py` — dir walk → N POSTs, scope flag, json output (API faked).
- **Depends on:** 1.5, 1.7.

**Layer 1 exit criteria:** ingest a directory of md/txt/html → blobs stored (dedup +
versioning), documents reach `chunked`, chunks persisted with citation metadata, jobs
pollable, everything scope-tagged and scope-authorized.

---

## Layer 2 — Search slice

**Outcome:** `odin search <query>` returns scope-correct, ranked chunk hits with precise
citations. Pipeline extends to `embed`; terminal state becomes `indexed`. Embedding model is
swappable via a registry, re-embedding is additive.

### Migration `0003_embeddings`
- `embedding_models(id, provider, model, dimensions, version, active)`;
- `embeddings(chunk_id, embedding_model_id, vector)` — pgvector, **HNSW** index. *(Shared-table
  layout for the swappable-dim concern resolved here — see Open params / spec §14.)*

### Step 2.1 — Embedding model registry
- **Goal:** register embedding models and mark one active; vectors are tagged by model.
- **Deliverables:** registry logic in `services/embedding.py` + seed from
  `EMBEDDING_MODEL`/`EMBEDDING_DIMENSIONS`.
- **Acceptance:** exactly one active model; a new model can be registered without dropping old
  vectors; switching active model is a single atomic flip.
- **Tests:** `tests/test_embedding_registry.py` — single-active invariant, additive registration.
- **Depends on:** `0003_embeddings`.

### Step 2.2 — Embedding service
- **Goal:** embed chunk text via the hosted model, tagged with `embedding_model_id`.
- **Deliverables:** `services/embedding.py` — batched calls to the active model (OpenAI
  `text-embedding-3-small` default), write `embeddings` rows; provider faked in tests.
- **Acceptance:** chunks → vectors of the registry's dimensions, tagged with the active model;
  batching + retry on transient provider errors.
- **Tests:** `tests/test_embedding.py` — batching, dimension/tag correctness, retry (fake provider).
- **Depends on:** 2.1.

### Step 2.3 — Extend pipeline with `embed`
- **Goal:** ingestion now embeds and reaches `indexed`.
- **Deliverables:** insert `embed` stage after `chunk` in `worker/handlers.py`; terminal state
  `indexed`; a **re-embed** path (new active model → embed missing vectors additively).
- **Acceptance:** newly ingested docs reach `indexed` with vectors; switching models + re-embed
  produces a complete new vector set without touching old rows.
- **Tests:** `tests/test_pipeline_l2.py` — embed stage, `indexed` terminal, re-embed additivity.
- **Depends on:** 2.2.

### Step 2.4 — Vector retrieval (stage 1)
- **Goal:** scope-filtered ANN search over chunks.
- **Deliverables:** `services/retrieval.py` — embed query → pgvector ANN (active model),
  **scope-filtered at the query** (tenancy predicate from 0.7), top-K with chunk text +
  citation metadata (doc id, section, char range, scope).
- **Acceptance:** relevant chunks rank correctly; **no out-of-scope chunk** can appear; results
  carry precise citations; top-K honored. *(top-K chosen here — see Open params.)*
- **Tests:** `tests/test_retrieval_vector.py` — ranking sanity, top-K; **adds the vector case to
  `tests/test_isolation.py`** (user A's query never returns user B / unjoined-org chunks).
- **Depends on:** 2.3, 0.7.

### Step 2.5 — Search endpoint + CLI
- **Goal:** expose retrieval over HTTP and the CLI.
- **Deliverables:** `api/search.py` (`GET/POST /v1/search`, `--scope`),
  `cli/odin_cli/commands/search.py` (human + `--json`).
- **Acceptance:** `odin search "<q>" --scope personal` returns ranked hits with citations;
  `--scope org:<id>` narrows; isolation holds end-to-end.
- **Tests:** `tests/test_search_api.py`, `tests/test_cli_search.py` — scope narrowing, citation
  shape, json output.
- **Depends on:** 2.4.

**Layer 2 exit criteria:** ingest → search works end-to-end; ranked chunk hits with precise,
scope-tagged citations; model swap = register + re-embed with atomic cutover; vector-stage
tenancy isolation proven.

---

## Layer 3 — Graph slice

**Outcome:** ingestion builds a provenance-rich knowledge graph (canonical entities, scoped
edges, mutation log); retrieval gains graph expansion; `odin graph` explores it. Pipeline
extends to `extract → graph-upsert`.

### Migration `0004_graph`
- `graph_mutations(id, actor, op, payload, rationale, confidence, created_at)` — append-only.
- AGE node/edge labels (`Document`, `Entity`, `MENTIONS`, relation types, inference types) are
  created lazily by the graph service against the `odin` graph from `init.sql`.

### Step 3.1 — LLM client
- **Goal:** a Claude wrapper for structured extraction and (later) generation.
- **Deliverables:** `services/llm.py` — call Claude (`ANSWER_MODEL`), structured/JSON output,
  retries/timeouts; faked in tests.
- **Acceptance:** returns validated structured output; transient errors retried; key absent →
  clear config error, not a crash at import.
- **Tests:** `tests/test_llm.py` — structured parse, retry, schema-violation handling (fake).
- **Depends on:** L0 config.

### Step 3.2 — Graph access layer
- **Goal:** typed node/edge upsert + scope-filtered traversal over AGE.
- **Deliverables:** `services/graph.py` — upsert Document/Entity nodes and edges **with
  provenance (origin, source doc ids, method/model, confidence, timestamps) and scope on every
  edge**; canonical-node lookups; scope-filtered traversal helpers (only follow edges in the
  caller's scope set).
- **Acceptance:** nodes/edges persist with full provenance; a traversal **never returns an edge
  whose scope is outside the caller's set** even when the entity node is shared (spec §4.3).
- **Tests:** `tests/test_graph_access.py` — upsert+read-back provenance; **canonical-node /
  scoped-edge leakage test → `tests/test_isolation.py`**.
- **Depends on:** `0004_graph`, 0.3.

### Step 3.3 — Ontology
- **Goal:** the curated-core entity/relation type set + open-extension rules.
- **Deliverables:** an ontology module (entity types: Person/Org/Project/Place/Topic/…;
  relations: WORKS_AT/BUILDS/HAS_A/RELATED_TO/…), validation, and handling for LLM-proposed
  new types. *(Final type list fixed here — spec §14.)*
- **Acceptance:** known types validate; a proposed new type is accepted + recorded (not
  silently dropped); normalization is deterministic.
- **Tests:** `tests/test_ontology.py` — validation, proposal handling, normalization.
- **Depends on:** —

### Step 3.4 — Extraction
- **Goal:** one structured LLM pass per chunk/doc → entities + typed relationships + confidence.
- **Deliverables:** `services/extraction.py` — prompt + structured output against the ontology;
  attach confidence + source provenance to each candidate.
- **Acceptance:** a known fixture doc yields the expected entities/relations with confidence and
  provenance; output validates against the ontology.
- **Tests:** `tests/test_extraction.py` — fixture-doc extraction shape, ontology conformance,
  confidence present (fake LLM).
- **Depends on:** 3.1, 3.3.

### Step 3.5 — Mutation log service
- **Goal:** record every graph mutation, reversibly.
- **Deliverables:** `services/mutations.py` — append create/merge/split/re-type/edge add|remove
  with actor, inputs, rationale, confidence, timestamp; provide replay/undo primitives.
- **Acceptance:** every graph write produces a mutation row; an "explain" can reconstruct why a
  node/edge exists; a merge can be undone via the log.
- **Tests:** `tests/test_mutations.py` — log-on-write, undo-a-merge, replay determinism.
- **Depends on:** 3.2.

### Step 3.6 — Entity resolution
- **Goal:** merge co-referent mentions into canonical entities with aliases.
- **Deliverables:** `services/resolution.py` — cluster by name + embedding similarity, LLM
  confirms merges → canonical node + aliases + `origin=merged`; each merge is a logged mutation.
- **Acceptance:** duplicate mentions of the same real-world entity resolve to one canonical
  node; merges appear in the mutation log; a bad merge is reversible.
- **Tests:** `tests/test_resolution.py` — clustering, LLM-confirmed merge, alias capture,
  mutation logged (fake LLM + real embeddings/db).
- **Depends on:** 3.4, 3.5, 2.2.

### Step 3.7 — Extend pipeline with `extract → graph-upsert`
- **Goal:** ingestion writes the graph with provenance and resolves entities across documents
  into canonical nodes; documents asserting different facts simply both persist (no contradiction
  adjudication at ingest — spec §7.7).
- **Deliverables:** insert `extract` then `graph-upsert` stages after `embed` in
  `worker/handlers.py`; upsert via 3.2, resolve via 3.6 (cross-document, scope-global), log via 3.5.
- **Acceptance:** ingesting a corpus builds canonical entities + scoped, provenance-rich edges;
  documents asserting different facts both persist with their provenance; pipeline reaches `indexed`.
- **Tests:** `tests/test_pipeline_l3.py` (integration) — end-to-end graph build, re-ingest
  idempotency, provenance completeness.
- **Depends on:** 3.2–3.6.

### Step 3.8 — Graph expansion in retrieval (stage 2)
- **Goal:** retrieval pulls connected graph context, scope-filtered.
- **Deliverables:** extend `services/retrieval.py` — from top vector hits, expand to mentioned
  entities → their relationships → linked/derived docs, traversing **only in-scope edges**;
  merge into the candidate set.
- **Acceptance:** graph-connected context appears in results; **expansion never crosses scope**;
  expansion is bounded (depth/fanout) and deterministic.
- **Tests:** `tests/test_retrieval_graph.py` — expansion correctness/bounds; **graph case →
  `tests/test_isolation.py`**.
- **Depends on:** 3.7, 2.4.

### Step 3.9 — Graph endpoints + CLI
- **Goal:** explore the graph.
- **Deliverables:** `api/graph.py` + `cli/odin_cli/commands/graph.py` — inspect entity,
  traverse relationships, view mutation history / "why is X linked to Y". *(Confirm/reject of
  proposed facts arrives with trust in L5.)*
- **Acceptance:** `odin graph` inspects an entity and its in-scope relationships, and shows
  provenance/mutation history; out-of-scope edges never shown.
- **Tests:** `tests/test_graph_api.py`, `tests/test_cli_graph.py` — inspect/traverse, history,
  scope enforcement.
- **Depends on:** 3.2, 3.5.

**Layer 3 exit criteria:** ingestion builds a provenance-rich, self-consistent graph with
canonical entities and scoped edges; retrieval expands through it without leakage; every
mutation is logged and reversible; conflicting facts are stored side by side with their
provenance and surfaced at query time, not adjudicated at ingest.

---

## Layer 4 — Ask slice

**Outcome:** `odin ask <question>` returns a grounded, cited answer (with per-citation scope),
admits ignorance on thin evidence, is stateless with client-supplied context, and can stream.
No new migration (reranker is an external service; sessions deferred).

### Step 4.1 — Reranker client (retrieval stage 3)
- **Goal:** re-score the merged vector+graph candidate set for precision.
- **Deliverables:** `services/reranker.py` — hosted rerank API (cross-encoder or LLM pass);
  wired as stage 3 of `services/retrieval.py`. *(Vendor chosen here — spec §14.)*
- **Acceptance:** reranking improves ordering on a labeled fixture set; **scope filter still
  applied** (rerank can't introduce out-of-scope items); graceful fallback if reranker is down.
- **Tests:** `tests/test_reranker.py` — ordering improvement on fixtures, scope preserved,
  fallback (fake provider).
- **Depends on:** 3.8.

### Step 4.2 — Context assembly
- **Goal:** turn ranked candidates into a scope-filtered, trust-weighted context bundle.
- **Deliverables:** assembly in `services/retrieval.py`/`services/answering.py` — pack
  reranked chunks + graph facts within a budget, each carrying source doc + scope + confidence;
  down-weight low-confidence/inferred facts (spec §7.2/§8.2).
- **Acceptance:** the bundle stays within budget, every item is in-scope and citation-ready,
  trust weighting is applied.
- **Tests:** `tests/test_context_assembly.py` — budget bounds, citation/scope completeness,
  trust ordering.
- **Depends on:** 4.1.

### Step 4.3 — Answering
- **Goal:** generate a grounded, cited answer that admits ignorance.
- **Deliverables:** `services/answering.py` — Claude generation over the context; **cite source
  docs with their scope**; on weak/thin evidence say "I don't know" / flag low confidence;
  stateless with optional client-supplied prior turns; optional token streaming.
- **Acceptance:** answers cite the docs used (with scope); thin retrieval → honest "I don't
  know"; identical request is reproducible modulo model nondeterminism; **no citation outside
  the caller's scope**.
- **Tests:** `tests/test_answering.py` — citation presence+scope, admit-ignorance path,
  client-context follow-up, isolation (fake LLM); **ask case → `tests/test_isolation.py`**.
- **Depends on:** 4.2, 3.1.

### Step 4.4 — Ask endpoint + CLI
- **Goal:** expose ask, streaming off by default.
- **Deliverables:** `api/ask.py` (`POST /v1/ask`, `--scope`, optional stream),
  `cli/odin_cli/commands/ask.py` (full answer by default; `--stream` opt-in; `--json`).
- **Acceptance:** `odin ask "<q>"` prints a cited answer; `--stream` streams tokens; `--json`
  returns answer + citations; follow-ups via client-supplied context work.
- **Tests:** `tests/test_ask_api.py`, `tests/test_cli_ask.py` — non-stream default, stream path,
  citation/json shape.
- **Depends on:** 4.3.

**Layer 4 exit criteria:** `odin ask` returns grounded, cited answers with per-citation scope;
admits ignorance on weak evidence; stateless multi-turn via client context; streaming opt-in;
no citation ever crosses scope.

---

## Layer 5 — Insight slice

**Outcome:** `odin insight` / insight-style `ask` synthesize persisted **derived documents** +
a reasoning subgraph (`IMPLIES`/`DERIVED_FROM`/`SUPPORTS`); inferred facts/insights are surfaced
as **proposed** with a confirm/reject loop; insights are private-by-default and explicitly
shareable.

### Migration `0005_derived`
- Derived-doc support (reuse `documents.doc_type = derived`) + proposed-fact **trust state**
  (`proposed | confirmed | rejected`) and confirm/reject decisions (logged via `graph_mutations`).

### Step 5.1 — Insight synthesis (on-demand)
- **Goal:** synthesize a derived `insight` document by reasoning over the corpus/graph.
- **Deliverables:** `services/insights.py` — traverse in-scope corpus/graph → Claude synthesis
  → persist a first-class **derived document** → materialize a reasoning subgraph
  (`Doc1, Doc2 -[IMPLIES]-> InsightDoc`, `DERIVED_FROM`, `SUPPORTS`) with provenance; record all
  source docs + their scopes.
- **Acceptance:** an insight is persisted as a derived doc, reusable later, linked to its
  sources with inference edges carrying provenance + confidence.
- **Tests:** `tests/test_insights.py` — derived-doc persistence, reasoning-subgraph shape,
  source provenance (fake LLM).
- **Depends on:** L3, L4.

### Step 5.2 — Insight scope & sharing
- **Goal:** insights are private to their creator even from mixed personal+org sources, and
  explicitly shareable to an org.
- **Deliverables:** scope logic in `services/insights.py` — default-private insight; explicit
  `share` to an org; **prevent personal context from leaking into an org via an insight**.
- **Acceptance:** a creator-only insight is invisible to others; sharing exposes the insight
  (not its private personal sources beyond what's permitted); leakage test passes.
- **Tests:** `tests/test_insight_scope.py` — private default, explicit share, **no-personal-leak
  → `tests/test_isolation.py`**.
- **Depends on:** 5.1, 0.7.

### Step 5.3 — Tiered trust & confirm/reject
- **Goal:** inferred facts/insights are "proposed"; users confirm/reject; answering prefers
  confirmed/extracted.
- **Deliverables:** trust state on inferred edges/insights; confirm/reject endpoints + service
  (each decision logged to the mutation log); answering (4.3) prefers confirmed/extracted and
  clearly marks reliance on unconfirmed inferences.
- **Acceptance:** a fresh inference is `proposed`; confirm/reject updates state + logs a
  mutation; answers down-rank/flag unconfirmed facts.
- **Tests:** `tests/test_trust.py` — proposed default, confirm/reject transitions + logging,
  answering preference for confirmed facts.
- **Depends on:** 5.1, 4.3, 3.5.

### Step 5.4 — Insight endpoints + graph CLI additions
- **Goal:** trigger insights and operate proposed facts from the CLI.
- **Deliverables:** insight endpoints (run/list) + `ask` integration for insight-style queries;
  `cli/odin_cli/commands/graph.py` additions — run/list insights, confirm/reject proposed facts,
  view their provenance.
- **Acceptance:** `odin ask "find insights about X"` (and/or `odin insight`) produces a
  persisted insight + subgraph; `odin graph` lists insights and confirms/rejects proposed facts.
- **Tests:** `tests/test_insight_api.py`, `tests/test_cli_insight.py` — run/list, confirm/reject
  flow, json output.
- **Depends on:** 5.1–5.3.

**Layer 5 exit criteria:** on-demand insights produce persisted derived docs + provenance-rich
reasoning subgraphs; proposed facts have a working confirm/reject loop that answering respects;
insights are private-by-default with no personal→org leakage.

---

## Cross-cutting: what's deliberately deferred (post-MVP)

Tracked in spec §12 "Later"; **not** scheduled in L0–L5:

- Proactive insight miner (scheduled + budgeted).
- Pluggable converters beyond text/md/html (PDF/Office/email/OCR) — the converter contract
  (1.3) is built; the plugins are not.
- Keyword/FTS hybrid retrieval; watched dirs / source connectors; webhook callbacks.
- Per-tenant encryption; dedicated audit log (app logs only in MVP); server-persisted ask
  sessions; CLI multi-context/profiles.
- Deployment / HA / k8s.

## Open params to fix during their layer

These were left `TBD` in spec §14; each is decided at the step that first needs it, not up front:

| Param                                   | Decided in step |
| --------------------------------------- | --------------- |
| Chunk size / overlap                    | 1.4             |
| Embedding table layout (shared vs per-model) | `0003` / 2.1 |
| Vector top-K                            | 2.4             |
| Curated ontology type list              | 3.3             |
| Graph expansion depth / fanout          | 3.8             |
| Reranker vendor                         | 4.1             |
| Context budget / trust weights          | 4.2             |
| Promote personal→org copy-vs-link semantics | revisit at 5.2 |

## Layer → spec → artifacts map

| Layer | Spec §            | Migration       | Enables                          |
| ----- | ----------------- | --------------- | -------------------------------- |
| L0    | 3, 4, 10, 11      | `0001_core`     | `odin login`, `odin admin`       |
| L1    | 5                 | `0002_ingest`   | `odin ingest`                    |
| L2    | 3.3, 6            | `0003_embeddings`| `odin search`                   |
| L3    | 7                 | `0004_graph`    | `odin graph`                     |
| L4    | 8                 | —               | `odin ask`                       |
| L5    | 7.4              | `0005_derived`  | `odin insight`, confirm/reject   |
