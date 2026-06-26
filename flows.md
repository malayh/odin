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
- Insert a `Job(state=pending)`, then `ingest_task.configure(connection=<session's psycopg3 conn>).defer_async(job_id=…)` defers the Procrastinate task **on the session's own connection**, then commit — `Document` + `Job` row + `procrastinate_jobs` row all in one transaction (atomic enqueue, one driver).
- Response `IngestOut{document_id, job_id, deduped}`.

### 3. Executor (Procrastinate) — `worker/app.py`, `worker/tasks.py`, `worker/__main__.py`

- **Queue = Procrastinate's `procrastinate_jobs`** (Postgres, `SKIP LOCKED`, installed by migration `0005`); safe for **N concurrent workers**. The app's `jobs` table is the status of record, kept in sync by the task.
- **Worker = `python -m odin.worker`** → `app.run_worker_async(concurrency=1)` inside `app.open_async()`. Procrastinate owns claiming, the run loop, retry scheduling, and graceful shutdown; `import_paths=["odin.worker.tasks"]` registers the task on boot.
- The `ingest` task is keyed by `job_id`. `_begin` flips the `Job` to `running` and `attempts += 1`; success → `_finish` (`Job.done`); exception → `_fail` records `error` and, if `attempts >= worker_max_attempts` (5) → `Job.failed` + `Document.failed`, else `Job.pending`, then re-raises so Procrastinate reschedules (`retry=worker_max_attempts - 1` keeps both counters terminal on the same attempt).

### 4. Ingest pipeline — `worker/tasks.py:_pipeline`

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

- **Document** (`DocState`): `pending` → `indexed` (task success) | `failed` (job exhausted retries). `soft_deleted` out of band.
- **Job** (`JobState`): `pending` → `running` → `done`; on error `running` → `pending` (retry) → … → `failed` at `worker_max_attempts`.

### Status surface

`GET /jobs/{id}` (`api/jobs.py`) returns the `Job` row, scope-checked via its `Document`. The CLI poll and any UI read job state from here — the `jobs` table is the **status of record**; Procrastinate's `procrastinate_jobs` is the internal queue.
