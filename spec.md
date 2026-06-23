# Odin — The Seeker of Knowledge

> A multi-tenant knowledge index. It ingests information (documents, emails, etc.),
> keeps its own copy, builds a vector index and a knowledge graph over it, and answers
> questions through a command-line client that talks to a central server.

**Status:** DRAFT v1 — coherent end-to-end design captured; concrete params + a few
semantics still open (see §14).
**Last updated:** 2026-06-23

---

## 1. Vision & scope

Odin is a personal + organizational knowledge index. Users feed it documents; Odin
stores a copy, derives entities and relationships into a knowledge graph, embeds the
content into a vector store, and exposes a natural-language + structured query surface
through a CLI (`odin ask`, `odin search`, `odin ingest ...`).

### Core capabilities (target)
- **Ingest** information from files/directories (and later, connectors like email).
- **Store** its own copy of every ingested document.
- **Embed** content into a vector store for semantic search.
- **Extract** entities and relationships into a knowledge graph
  (e.g. `has_a`, `works_at`, `builds`, `talks_about`, `related_to`).
- **Answer** natural-language questions and run searches via a CLI.
- **Isolate** data per user, with org-shared knowledge participating in members' graphs.

---

## 2. Foundational decisions (locked)

| Decision | Choice | Notes |
|---|---|---|
| Implementation language | **Python** | Richest RAG/embedding/LLM/entity-extraction ecosystem. |
| Deployment topology | **Central self-hosted server** | Single server holds all data; CLI is a thin remote client. |
| AI provider stance | **Cloud-only** | Always use hosted APIs (LLM + embeddings). Privacy tradeoff accepted. |
| MVP scope | **Multi-tenant from day one** | Users, orgs, and permissions are in v1, alongside RAG + KG. |
| Datastores | **All-in-Postgres** | `pgvector` (embeddings) + Apache AGE (graph) + relational tables (metadata/tenancy). One system, one backup, RLS-friendly. |
| Auth | **Personal access tokens** | `odin login` issues a bearer token stored in CLI config. Org membership managed server-side. |
| Blob storage | **S3-compatible object store** | MinIO/S3/R2. Odin keeps a content-addressed copy of every original document. |
| Embeddings | **Small hosted model, swappable** | Default `text-embedding-3-small` (1536-d). Schema is model-agnostic to allow switching/re-embedding. |

---

## 3. Architecture

### 3.1 Components
- **`odin` CLI** — thin remote client. Stores server URL + access token in `~/.config/odin/`.
  Talks to the server over HTTP(S) (REST/JSON; streaming for `ask`).
- **API server** — Python (e.g. FastAPI). **API-first**: ingest/ask/search are HTTP
  endpoints; the CLI is one client, and other sources can call the same API. Handles
  AuthN/Z, tenancy enforcement, query orchestration (RAG + graph), ingestion intake.
- **Worker(s)** — async background processing for the heavy ingestion pipeline
  (convert → chunk → embed → entity/relationship extraction → graph upsert). Driven by a
  **Postgres-backed job queue** (`FOR UPDATE SKIP LOCKED`) — no extra broker to operate.
- **Postgres** — system of record: relational metadata + tenancy, `pgvector` embeddings,
  Apache AGE knowledge graph.
- **Object store (S3-compatible)** — content-addressed copies of original documents + extracted text.
- **AI providers (cloud)** — generation LLM (Claude) + embedding model (separate vendor).

### 3.2 Request flow (sketch)
- **Ingest:** CLI uploads file(s) → server stores blob (content hash) + a `documents` row in
  `pending` state → enqueues a job → worker runs the pipeline → document becomes `indexed`.
- **Search:** CLI query → server runs retrieval (vector ± keyword, tenancy-filtered) → ranked hits.
- **Ask:** CLI question → server retrieves context (vector + graph) → calls LLM → streams a
  cited answer back.

### 3.3 Embedding storage (model-agnostic)
pgvector columns are fixed-dimension, so to keep models swappable:
- An `embedding_models` registry (id, provider, model name, dimensions, version, active flag).
- Embeddings are tagged with the `embedding_model_id` that produced them.
- Switching models = register a new model + re-embed (new rows), without dropping old ones,
  so retrieval can cut over atomically. _Exact table layout (per-model tables vs. shared) TBD._

## 4. Multi-tenancy & access control

### 4.1 Principals
- **User** — an individual identity (authenticates via personal access token).
- **Org** — a tenant grouping. A user belongs to **one or more** orgs, each with a role
  (see §4.4).
- **Document scope** — every document is either **personal** (owned by one user) or
  **org-owned** (belongs to an org; visible to its members).

### 4.2 Default query scope: unified
- By default, `ask`/`search` span the user's **personal docs + all orgs they belong to**,
  merged into a single retrieval + graph view.
- A `--scope` flag narrows to `personal`, a specific `org:<name>`, or a subset.
- **Isolation invariant:** a user can never retrieve, traverse, or cite content they don't
  have access to — enforced at the storage/query layer, not just the UI.

### 4.3 Cross-scope knowledge: canonical node, scoped edges
The same real-world entity may appear in personal and org documents. Odin stores **one
canonical entity node**, but **every edge (MENTIONS / relationship) carries the scope of
the document that asserted it**. Query-time traversal only follows edges the caller can
access, so:
- A user gets a unified picture of an entity across everything they can see.
- Org relationships never leak into another user's personal view, and vice versa.
- **Leakage rule:** entity *existence* may be shared, but no edge, mention, document, or
  attribute is traversable/returnable unless the caller's scope set includes its origin scope.

### 4.4 Org roles
Per-org role (a user can have different roles in different orgs):
- **Admin** — manages membership (add/remove users), assigns roles/permissions, and has
  Editor rights. Can delete org docs.
- **Editor** — can ingest/contribute and edit org documents; read access.
- **Viewer** — read-only access to org documents/graph.

**Doc contribution & scope changes:** Editors/Admins contribute docs to orgs they belong
to. A user may **promote a personal doc into an org** (creates an org-scoped copy/link).
The doc's owner or an org Admin can delete it. (Exact "copy vs link" semantics — TBD.)

### 4.5 Onboarding (invite-only)
No open self-serve signup in v1. An **initial admin** (seeded via CLI/env at install)
creates users and orgs and **invites** members. Fits a controlled, self-hosted deployment
and matches the personal-access-token auth model.

## 5. Ingestion pipeline

### 5.1 API-first intake
Ingestion is an **HTTP API**. `odin ingest -d <dir>` simply walks local files and POSTs
them; other producers (future connectors, scripts, services) hit the same endpoint. Each
ingest call carries the target **scope** (personal or `org:<id>`) and metadata.

### 5.2 Converters (pluggable)
- The core pipeline operates on **normalized text**. Native support: text / Markdown / HTML.
- Any other format is handled by a **pluggable converter** that (a) extracts text and
  (b) hands back the original bytes to be stored as the canonical blob. PDF/Office/email/
  OCR/transcription are all just converters added later — the core doesn't special-case them.

### 5.3 Content addressing, dedup & versioning
- Every original is stored content-addressed (hash) in the object store; metadata in Postgres.
- **Dedup:** identical content (same hash) is not re-processed.
- **Versioning:** a changed document (same logical source, new content) creates a **new
  version** that supersedes the prior one; embeddings and graph facts are updated, old
  versions retained for history/lineage.

### 5.4 Pipeline stages (per document, async)
1. **Intake** — store blob, create `documents` row in `pending`, enqueue job.
2. **Convert/normalize** — to text (native or via converter).
3. **Chunk** — split into retrieval units (strategy TBD).
4. **Embed** — via the active embedding model; write vectors tagged with `embedding_model_id`.
5. **Extract** — a **single structured LLM pass** per chunk/doc emits entities + typed
   relationships (with confidence) against the curated-core ontology; then resolve/merge
   entities (embedding + LLM canonicalization).
6. **Graph upsert** — write nodes/edges with full provenance; append to the mutation log.
7. **Finalize** — mark `indexed` (or `failed` with error; jobs are retryable + idempotent).

## 6. Vector index & retrieval

### 6.1 Vector index
- Embeddings in `pgvector` (HNSW index), each row tagged with `embedding_model_id` so
  models are swappable and re-embedding is additive.
- **Chunking: structure-aware + token-bounded.** Split on document structure
  (headings/paragraphs) into token-bounded chunks with overlap; retain section + character
  offsets as metadata so citations can point precisely back into the original.

### 6.2 Retrieval = vector + graph (GraphRAG)
- **Stage 1 — vector recall:** semantic similarity over chunks, **scope-filtered** (only
  chunks the caller can access).
- **Stage 2 — graph expansion:** pull connected context from the knowledge graph
  (entities mentioned in top hits, their relationships, linked/derived documents), again
  traversing only edges in the caller's scope set.
- **Stage 3 — rerank:** re-score the merged candidate set with a **hosted reranker**
  (cross-encoder/rerank API or LLM pass) to maximize precision of the final context.
- (Keyword/full-text was deferred; vector + graph is the v1 signal mix. Postgres FTS can
  be added later for exact-term recall.)

### 6.3 Tenancy in retrieval
Scope filtering is applied at **every** stage (vector, graph, rerank, citation). Nothing
outside the caller's scope set can enter the candidate set, the context window, or a citation.

## 7. Knowledge graph

### 7.1 Node types
- **Document nodes**, with a `doc_type`:
  - `source` — an ingested document (file/email/etc.). Odin keeps the original blob.
  - `derived` (a.k.a. `insight`) — a document Odin **generates** by reasoning over the
    corpus/graph. Persisted like any document, but marked as derived and linked to its sources.
  - (room for more: `note`, `summary`, …)
- **Entity nodes** — extracted/inferred real-world things (Person, Org, Project, Place,
  Topic, …). Carry an **`origin`** field: `extracted` | `inferred` (LLM-invented) |
  `merged` | `user`. Carry aliases (for entity resolution).

### 7.2 Edge types
- **Extraction edges** (asserted by a source doc): `Document -[MENTIONS]-> Entity`,
  `Entity -[WORKS_AT|BUILDS|HAS_A|RELATED_TO|…]-> Entity`.
- **Inference edges** (reasoned by Odin): e.g. `Doc1, Doc2 -[IMPLIES]-> Insight`,
  `SUPPORTS`, `CONTRADICTS`, `DERIVED_FROM`. These connect documents (and entities) through
  Odin's synthesis, not direct extraction.
- **Full provenance on every node and edge:** `origin`
  (`extracted`/`inferred`/`merged`/`user`), source document id(s), extraction
  method/model, **confidence score**, and timestamps. This powers citations, trust
  weighting (down-weighting shaky/LLM-inferred facts), and audit.

### 7.3 Ontology: curated core + open extension
- Ship a curated set of entity types and relation types for consistency + queryability.
- The LLM may **propose new types** and, crucially, may **revise its own model over time**:
  invent entities, then later **merge** them (changing the connected graph), split, or
  re-type them. The `origin` field records how each entity/edge came to exist.
- Because the graph self-revises, mutations must be **auditable/reversible** _(round 4)_.

### 7.4 Derived knowledge / "insights"
Example: `odin ask "find insights about XYZ"` → traverse the knowledge base → synthesize
an `insight` document → materialize a reasoning subgraph
(`Doc1, Doc2 -[IMPLIES]-> InsightDoc`). Insights are **persisted as first-class derived
documents** and reusable later.

Two generation modes:
- **On-demand** — user triggers synthesis (`odin insight` / certain `ask` queries).
- **Proactive (later phase — not in MVP)** — a background process periodically mines the
  corpus/graph for new insights, contradictions, and emerging connections, and proposes
  them. When added, it runs scheduled + budgeted with an on/off toggle. **MVP ships
  on-demand insights only.**

**Scope/ownership:** an insight is **private to the user who generated it** by default,
even when synthesized from mixed personal+org sources. It records all source docs and
their scopes, and can be **explicitly shared** to an org. This prevents personal context
from leaking into an org via an insight.

**Trust (tiered + confirmable):** extracted facts carry higher trust; **inferred facts and
insights carry lower confidence and are surfaced as "proposed"** until a user
confirms/rejects them (each decision logged to the mutation log). Answering prefers
confirmed/extracted facts and clearly marks reliance on unconfirmed inferences.

### 7.6 Graph mutation log (audit & reversibility)
Because the graph self-revises, Odin keeps the **current materialized graph + an
append-only mutation log**. Every mutation (create/merge/split/re-type/edge add/remove)
records actor (which process/model), inputs, rationale, confidence, and timestamp. This
enables **explain** ("why is X linked to Y?"), **undo** (revert a bad merge), and
**replay**. Trades extra storage + write complexity for full accountability.

### 7.7 Contradictions
When two documents assert conflicting facts, Odin **keeps both** (each with its provenance
+ confidence) and links them with a **`CONTRADICTS`** edge. Answers surface the conflict
("sources disagree…") rather than silently picking a winner — honest and auditable.

### 7.5 Entity resolution
Embedding + LLM canonicalization: cluster mentions by name + embedding similarity, LLM
confirms merges into a canonical entity with aliases. Merges are graph mutations (audited).

## 8. Query / answering (RAG)

### 8.1 `ask` flow
retrieve (vector + graph, §6) → rerank → assemble scope-filtered context → LLM (Claude)
generates a **grounded, cited** answer → stream back to the client.

### 8.2 Grounding & trust ("cite + admit ignorance")
- Every answer **cites the source documents** it used, including which **scope** each came
  from (personal vs which org).
- When retrieval is thin / evidence is weak, Odin says **"I don't know"** or flags low
  confidence rather than guessing. Trust-first behavior.

### 8.3 Conversation model (stateless, LLM-API style)
- The server is **stateless**: each `ask` is self-contained.
- The client may include **prior turns / context** in the request (like the messages array
  of an LLM API) to support follow-ups, without the server holding session state.
- Optional **server-persisted sessions** (a convenience to store/replay threads) may be
  added later; not required for the model to work.

## 9. API & CLI

### 9.1 API is the product
The HTTP API is the primary interface and system contract. The CLI is a **thin wrapper**
(one UI among possible future ones — web, connectors, scripts). Design effort centers on
the API; CLI commands map 1:1 onto endpoints.

### 9.2 CLI command surface
Top-level verbs (each `admin`/`graph` has subcommands):
- `odin login` — authenticate; stores token + context in `~/.odin/`.
- `odin ingest [-d <dir> | <file>] [--scope ...]` — push documents to the ingest API.
- `odin search <query> [--scope ...]` — retrieval results.
- `odin ask <question> [--scope ...] [--stream]` — grounded, cited answer.
- `odin admin <subcmd>` — org + membership management: create org, invite/remove users,
  set roles (Admin/Editor/Viewer), manage tokens, scope settings.
- `odin graph <subcmd>` — explore/operate the knowledge graph: inspect entities, traverse
  relationships, run/list insights, confirm/reject proposed facts, view mutation history.

### 9.3 CLI conventions
- **Output:** human-readable by default; `--json` on every command for scripting.
- **Streaming:** **off by default** (print the full answer); `--stream` opts into live
  token/chunk streaming for `ask`.
- **Config:** `~/.odin/config.yaml` (+ supporting files) holds server URL(s), token(s),
  and default scope. (Multiple contexts/profiles — TBD.)

### 9.4 API shape (working assumptions, to refine)
- REST/JSON, versioned (`/v1/...`), bearer-token auth, scope passed per request.
- **Async ingest:** ingest returns a **job/document id** immediately; clients poll
  `GET /v1/jobs/{id}` for state (`pending → indexed | failed`). Universal, no inbound
  networking to producers. (Webhook callbacks are a possible later add.)
- Pagination, idempotency keys for ingest, and a consistent error model — TBD.

## 10. Security & privacy

### 10.1 Encryption (MVP: pragmatic)
- **TLS in transit** for all client↔server and server↔provider traffic.
- **At rest:** rely on host/disk-level encryption (no app-level field/blob encryption in
  MVP). Per-tenant envelope encryption is a possible later upgrade.

### 10.2 AI provider data handling
- Cloud-only is an accepted tradeoff: chunk text + extraction prompts are sent to providers
  **as-is** (no redaction/scrubbing layer in MVP). Revisit if a privacy mode is needed.

### 10.3 Deletion = soft-delete + periodic purge
- A delete first **soft-deletes** the document (excluded from retrieval/answers immediately).
- A **periodic cleanup job** then performs the hard cascade: purge blob + chunks +
  embeddings, **retract** the graph facts the doc asserted (re-evaluate entities that lose
  all support), and leave a **tombstone** in the mutation log for lineage.

### 10.4 Logging
- **No dedicated audit log in MVP** — application-level logs suffice for now. (A structured
  access/admin/AI-call audit trail is a later addition if compliance needs arise.)

### 10.5 Secrets
- Provider API keys and DB/object-store credentials are server-side config (env/secret
  store), never exposed to clients. CLI only ever holds its personal access token.

## 11. Operations & scale

### 11.1 Scale target (v1)
- **Small self-host:** ~1–50 users, up to low-millions of chunks. Single Postgres
  (pgvector HNSW + AGE) + a few workers, vertical scaling. Sharding/replicas/partitioning
  are explicitly out of scope for v1.

### 11.2 Dev / local setup
- **Docker Compose** brings up infra dependencies: **Postgres** (with pgvector + AGE) and
  **MinIO** (S3-compatible).
- The **API server + workers run locally** via **uv / venv** during development.
- Production deployment is **out of scope** for now (no k8s/Helm/CD work yet).

### 11.3 Observability
- Application-level structured logs for now (no separate audit/metrics stack required for v1).

## 12. Phased roadmap

**Phase 0 — Skeleton & infra**
Docker Compose (Postgres + pgvector + AGE, MinIO); FastAPI app + Postgres-backed worker;
auth (personal access tokens), users/orgs/roles, scope model; `odin login`. Initial-admin seed.

**Phase 1 — Ingest → search (the RAG spine)**
API-first ingest (text/md/html), blob storage + content-hash dedup/versioning, chunking,
embeddings (swappable model registry), vector retrieval, `odin ingest` / `odin search`.
Pollable job status.

**Phase 2 — Knowledge graph**
Single-pass LLM extraction → entities + relationships with full provenance; entity
resolution (canonical node + scoped edges); mutation log; `odin graph` explore.

**Phase 3 — Ask (grounded answering)**
Vector + graph retrieval, hosted reranker, Claude generation, citations + "admit
ignorance", stateless ask with client-supplied context; `odin ask`.

**Phase 4 — Derived knowledge (on-demand)**
`odin insight` / insight-style asks → persisted derived docs + reasoning subgraph
(`IMPLIES`/`DERIVED_FROM`); tiered trust + confirm/reject of proposed facts; `CONTRADICTS`.

**Later (post-MVP)**
Proactive insight miner (scheduled + budgeted); pluggable format converters (PDF/Office/
email/OCR); watched dirs + source connectors; keyword/FTS hybrid; webhooks; per-tenant
encryption; audit log; deployment/HA.

---

## 13. Data model sketch (working, to refine)

_Relational (Postgres):_
- `users`, `orgs`, `memberships(user_id, org_id, role)`, `access_tokens`.
- `documents(id, owner_user_id, scope, doc_type[source|derived], content_hash,
  blob_uri, version, supersedes_id, state[pending|indexed|failed|soft_deleted], created_at)`.
- `chunks(id, document_id, ordinal, text, section_meta, char_range)`.
- `embedding_models(id, provider, model, dimensions, version, active)`.
- `embeddings(chunk_id, embedding_model_id, vector)` — pgvector; layout (shared vs
  per-model table) TBD given fixed-dim columns.
- `jobs(id, document_id, type, state, attempts, error, created_at)` — `FOR UPDATE SKIP LOCKED`.
- `graph_mutations(id, actor, op, payload, rationale, confidence, created_at)` — append-only log.

_Graph (Apache AGE):_
- Nodes: `Document`, `Entity{origin, aliases, type, confidence}`.
- Edges: `MENTIONS`, relationship types (`WORKS_AT`/`BUILDS`/`HAS_A`/`RELATED_TO`/…),
  inference edges (`IMPLIES`/`SUPPORTS`/`CONTRADICTS`/`DERIVED_FROM`) — **all carry
  `scope` + provenance + confidence**.

_Object store (S3/MinIO):_ content-addressed original blobs + extracted text.

---

## 14. Open questions / to refine
- Embedding storage layout: one shared table vs per-model tables (pgvector fixed-dim columns).
- "Promote personal doc to org": copy vs link semantics + re-scoping of derived facts.
- Curated-core ontology: finalize the entity/relationship type list (and normalization rules).
- Concrete params: chunk size/overlap, top-K, reranker vendor, Claude model id(s).
- CLI multi-context/profile support (kubectl-style) — in or out for v1.
- API specifics: pagination, idempotency keys for ingest, unified error model, rate limits.
- Insight review/noise UX (esp. once the proactive miner lands).
- Soft-delete → purge cleanup cadence + how entities re-evaluate when they lose all support.
