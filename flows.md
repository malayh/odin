# Flows

Internal flow documentation. One section per flow; describes what the code does today.

## Ingest

Push a file → durable blob + vector embeddings + knowledge-graph contributions, tracked by a job.

### 1. CLI submit — `cli/odin_cli/commands/ingest.py`

- `odin ingest -d <dir> [--scope] [--json]` walks `<dir>` with `rglob`, keeps `.txt/.md/.markdown/.html/.htm`, sorts.
- Per file: `key = path.relative_to(dir)` (retains subdirectory structure), then `client.ingest(path, key, scope)` → `POST /ingest`.
- Submission is **serial**: each file is polled to a terminal state before the next is sent.
- `_poll` hits `GET /jobs/{id}` every 2s up to 300s → `done` / `failed: <err>` / `timeout`. A deduped response (no `job_id`) short-circuits to `deduped`.

### 2. API intake — `api/ingest.py` → `services/ingest.py:intake`

- Auth principal; multipart `file` + `key` + `scope` (default `personal`). `resolve_scope_set`, `Scope.parse`.
- `can_write(scope_set, scope)` else 403; `converters.format_for_key(key)` validates the extension.
- `content_hash(data)`; look up the **active** doc for `(scope_type, scope_id, key)` where `supersedes_id IS NULL`.
- **Dedup**: active exists and same hash → return `(active, job=None, deduped=True)`. No blob write, no job.
- **New / new version**: `blobs.put(data)` → `blob_uri`; mint `doc_id`; if an active doc exists set its `supersedes_id = doc_id` (version chain, `version += 1`); insert `Document(state=pending)`.
- `queue.enqueue(doc.id, "ingest")` inserts a `Job(state=pending)` **in the same transaction**, then commit (transactional enqueue — doc + job are atomic).
- Response `IngestOut{document_id, job_id, deduped}`.

### 3. Queue + worker (executor) — `worker/queue.py`, `worker/runner.py`

- **Queue = the `jobs` table.** `queue.claim` runs `SELECT … WHERE state=pending ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED`, flips `running`, `attempts += 1`. `SKIP LOCKED` makes it safe for **N concurrent workers** (each claims a distinct row).
- **Worker = `python -m odin.worker`** → `runner._run` loop: `claim` → `_dispatch` → `complete`/`fail`. Empty queue → sleep `worker_poll_interval_seconds`. SIGTERM/SIGINT set a stop event for graceful drain.
- `_dispatch` looks up `HANDLERS[job["type"]]` (only `"ingest"`). Unknown type → logged, treated as a no-op success.
- Success → `queue.complete` (`Job.done`). Exception → `queue.fail`: record `error`; if `attempts >= worker_max_attempts` (5) → `Job.failed` + `Document.failed`; else back to `pending` (retry).

### 4. Ingest handler pipeline — `worker/handlers.py:ingest_handler`

One DB session/transaction per job:

- Load `Document`; require `blob_uri` else `NotFoundError`.
- `blobs.get` → bytes → `converters.convert(data, key)` → text.
- `chunking.chunk(text, …)` → chunks. Delete existing `Chunk` rows for the doc (re-ingest idempotency), insert new ones, flush.
- `embedding.embed_chunks` → OpenAI embeddings → pgvector.
- `extraction.extract` → entities/relationships (OpenRouter LLM).
- `resolution.resolve` → entity resolution / merges within the doc's scope.
- `graph.delete_document_contributions` then `graph.upsert` → Apache AGE nodes/edges (scoped).
- `doc.state = indexed`; commit.

### State machines

- **Document** (`DocState`): `pending` → `indexed` (handler success) | `failed` (job exhausted retries). `soft_deleted` out of band.
- **Job** (`JobState`): `pending` → `running` → `done`; on error `running` → `pending` (retry) → … → `failed` at `worker_max_attempts`.

### Status surface

`GET /jobs/{id}` (`api/jobs.py`) returns the `Job` row, scope-checked via its `Document`. The CLI poll and any UI read job state from here — the `jobs` table is both the **queue** and the **status of record**.
