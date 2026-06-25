# 002 — L3 Graph Hardening + Finish the Slice

Living tracker for the work that takes L3 from "write-path implemented" to "meets its own exit
criterion" — a **provenance-rich, self-consistent graph** — and then finishes the deferred L3
surface (graph expansion in retrieval; graph API + CLI).

Follows [001](001_end_to_end_ingestion.md), which **proved** ingestion end-to-end and recorded the
graph-quality findings this doc acts on.

## Why this phase

L3's stated exit criterion (implementation.md) is *"ingestion builds a provenance-rich,
**self-consistent** graph with canonical entities and scoped edges."* The 001 real run proved it is
**not** self-consistent:

- **Entity resolution is a no-op across documents.** `helios` / `helios inc.` / `helios robotics`
  stayed 3 nodes; Atlas split across 4 type/name nodes. Only 1 multi-surface node ever formed.
- **Contradiction detection over-fires** (197 `CONTRADICTS` edges, almost all false).

Everything downstream consumes this graph (3.8 expansion traverses it; L4 Ask grounds cited answers
on it). Fix the foundation before building on it.

## Root-cause analysis (confirmed in code)

| Symptom | Root cause | Location |
| --- | --- | --- |
| Aliases never merge across docs | `resolve()` only sees **one doc's** extracted entities; there is **no cross-document resolution pass**. Each doc resolves in isolation, so two spellings in two docs never meet. | `services/resolution.py:37`, `worker/handlers.py:69` |
| Same entity forks by type | Same-doc merge requires `types[i]==types[j]` (skips cross-type), and `key = type:name` so `product:atlas` ≠ `project:atlas` even post-merge. | `services/resolution.py:66`, `services/ontology.py:28` |
| Contradictions over-fire | `detect_and_link_contradictions` flags **any** `(subject, predicate)` with ≥2 distinct objects — wrong for multi-valued predicates (`BUILDS`, `RELATED_TO`, `HAS_A`, `USES`). Amplified by unmerged aliases manufacturing fake distinct objects. | `services/graph.py:223` |

## Decisions

| Decision | Choice |
| --- | --- |
| Resolution fix | **Cross-document (scope-global) resolution.** Fold entities already in the scope's graph into the candidate pool; relax the same-type guard so type drift can merge. Keystone — needed regardless of the contradiction path. |
| Keying across type drift | Keep `key = type:name` as the storage key, but route a new mention to an **existing** canonical key when resolution says they co-refer. Canonical node keeps one type; mentions still record what the LLM said. (No key-scheme migration.) |
| Contradictions | **Removed entirely** (user decision). Odin does not detect or adjudicate conflicts. It stores every asserted fact with provenance; conflicting facts (Dana CTO vs VP, Atlas Q2/Q3, …) simply coexist as edges and surface together at query time — the user interprets. Whether two values conflict or are both true (someone works at two places) is the user's call, not the KB's. spec §7.7 rewritten accordingly. |
| Scope of this phase | Harden resolution (A1) + remove contradictions (A2) + finish the deferred L3 surface (B: 3.8 retrieval expansion, 3.9 graph API/CLI). No L4. Surgical; keep all existing tests green. |

### Query-time principle (carries into B1 + L4)

Because Odin never adjudicates, retrieval/answering must **surface all in-scope facts** about an
entity — never dedupe or silently pick among differing values. `graph.read_entity` already returns
every in-scope relationship; B1 graph-expansion and L4 answering must preserve that ("here are the
facts, each cited"), letting the user see the disagreement.

## Phase checklist

- [x] **A1 — Cross-document entity resolution** (keystone). Pool = existing in-scope graph entities
  + this doc's entities; relax type guard; prefer existing node as canonical. New
  `graph.list_scope_entities`. Backward-compatible with current per-doc tests (empty graph → pool of
  one doc → unchanged). Proven by `test_resolve_merges_alias_into_existing_graph_entity`. Perf note:
  embeds all in-scope entity names per doc (O(E·D)) — fine at corpus scale; cache later if needed.
- [x] **A2 — Remove contradictions.** Deleted `detect_and_link_contradictions`, `add_contradiction`,
  the pipeline call, the `CONTRADICTS` cleanup, and the pre-created `CONTRADICTS` AGE label; updated
  spec/implementation/README/harness. Conflicting facts now just coexist as edges; surfacing them is
  the natural default of returning all in-scope edges. Tests updated (idempotency retained;
  contradiction assertions removed).
- [x] **B1 — 3.8 graph expansion in retrieval.** `retrieval.expand`/`search_graph` (1 hop, fanout caps
  `expand_entities_per_doc`/`expand_neighbors_per_entity`) over new scoped graph reads
  `mentioned_entities`/`entity_neighbors`/`docs_for_entities`. Scope-filtered at every hop; never
  dedupes differing facts. `search()`/`/search` contract unchanged. Tests: `test_retrieval_graph.py`
  + `test_graph_expansion_excludes_other_users` in `test_isolation.py`.
- [x] **B2 — 3.9 graph API + `odin graph` CLI.** `api/graph.py`: `GET /graph/entities?q=`,
  `/entities/{key}`, `/entities/{key}/history` (scope-filtered provenance — see history-isolation
  handling below) over `graph.find_entities` + `graph.read_entity` + new `graph.entity_history`.
  Schemas in `schemas/graph.py`. `cli/odin_cli/commands/graph.py`: `find` / `entity` / `history`
  (`--json`) + client methods. Tests: `test_graph_api.py`, `cli/tests/test_cli_graph.py`. History
  isolation solved by filtering `mutations.explain` rows to the caller's scope (payload scope, or the
  source doc's scope) — no fallback needed. Full check green: ruff + mypy clean, 107 passed / 4 skipped.
- [ ] **C — Re-run + record.** Re-run the 001 corpus harness; confirm aliases now merge and
  contradiction count drops to the genuine few; update 001's findings + this doc's observations.

## Phase B — detailed plan (3.8 + 3.9)

Phase A (A1 cross-doc resolution, A2 remove contradictions) is **done + green**. Phase B finishes the
deferred L3 surface. Guiding principle (from A2): **surface all in-scope facts; never dedupe or pick.**

### B1 — Graph expansion in retrieval (3.8)

**Goal:** from the top vector hits, pull connected in-scope graph context (mentioned entities → their
relationships → linked docs), bounded and scope-filtered, without ever crossing scope.

**Design (additive — does not change `/search`'s `{hits}` contract):**
- New `services/retrieval.expand(session, scope_set, seed_document_ids, *, fanout=…) -> Expansion`
  where `Expansion` is a frozen dataclass: `entities: list[EntityRef]`, `relationships:
  list[RelRef]`, `linked_document_ids: list[UUID]`. Depth fixed at **1 hop**:
  seed docs → in-scope `MENTIONS` entities → in-scope `REL` neighbors → docs mentioning those
  entities (in scope). All hops filtered with the existing `graph._scope_clause(scope_set, var)`.
- New graph read helpers in `services/graph.py` (reuse `_scope_clause`, batched, `DISTINCT`):
  - `entities_for_documents(session, scope_set, doc_ids) -> [(key, name, type)]`
  - `expand_entities(session, scope_set, keys, *, fanout) -> {relationships, neighbor_keys, linked_doc_ids}`
- Convenience `retrieval.search_graph(session, scope_set, query, only=…, top_k=…) -> (hits, Expansion)`
  = `search()` then `expand(seed = hit doc ids)`. This is what L4 (Ask) and the graph API will consume.
  `search()` stays as-is for `/search`.

**Decisions to lock here (the "open params" for this step):**
- **Depth = 1** (seed-doc entities + their direct relationships + directly-linked docs). Deeper
  traversal deferred — 1 hop is the spec's "entities in top hits, their relationships, linked docs."
- **Fanout caps** (deterministic, ordered by confidence then key): ≤ `EXPAND_ENTITIES_PER_DOC`
  (default 16) and ≤ `EXPAND_NEIGHBORS_PER_ENTITY` (default 16). Surfaced via config, not hardcoded.
- No dedup of differing facts — return every in-scope relationship (A2 principle).

**Tests:** `tests/test_retrieval_graph.py` — expansion finds the mentioned entities + their in-scope
rels + linked docs; bounded by fanout; deterministic. **Add the graph case to
`tests/test_isolation.py`**: user A expanding from a hit never sees an org edge/neighbor/linked-doc
from an org A is not in (even when the entity node is shared — spec §4.3).

### B2 — Graph API + `odin graph` CLI (3.9)

**Goal:** explore the graph — inspect an entity (+ in-scope relationships + aliases), find an entity
by name, and view its provenance/history — all scope-enforced.

**API (`api/graph.py`, already mounted at `/graph`; `current_principal` → `scope_set`):**
- `GET /graph/entities?q=<name>` → name/alias lookup → `[EntitySummary{key,name,type}]` (bridges the
  UX gap: users know names, keys are `type:name`). New `graph.find_entities(session, scope_set, q)`.
- `GET /graph/entities/{key}` → `graph.read_entity(scope_set, key)` (already exists) →
  `EntityOut{key,name,type,aliases,relationships}` or 404.
- `GET /graph/entities/{key}/history` → provenance/"why". **Isolation-critical** (see risk below).
- `GET /graph/entities/{key}/neighbors` → thin wrapper over `retrieval.expand` for a single entity
  (1 hop). Optional; include if cheap.
- Schemas in `schemas/graph.py`: `EntitySummary`, `EntityOut`, `RelationshipOut`, `MutationOut`.

**CLI (`cli/odin_cli/commands/graph.py`, replace the stub):** a Typer group (mounted via
`add_typer`, like `admin`) — leaf subcommands bind positionals fine (unlike the `search` single-action
gotcha):
- `odin graph find <name>` → list matching `key  name  type`.
- `odin graph entity <key|name>` → inspect; if arg isn't a `type:name` key, resolve via `find` first.
- `odin graph history <key>` → mutation timeline (actor/op/why).
- `--json` on each. New client methods: `find_entities`, `get_entity`, `entity_history`.

**Risk to handle explicitly — history isolation.** The `graph_mutations` log is not uniformly
scope-tagged (some payloads carry `scope_type/scope_id`, e.g. merges; `rel_add` carries
`source_doc_id`). Exposing raw history could leak out-of-scope provenance for a *shared* entity.
**Plan:** `mutations.explain` results are filtered to rows the caller can see — keep a row only if its
payload scope ∈ `scope_set`, or (for ops with only `source_doc_id`) the source document's scope ∈
`scope_set`; drop when undecidable. Add this case to `tests/test_isolation.py`. If filtering proves
fiddly, fall back to exposing only `entity_create`/`merge` existence rows (spec §4.3: entity
*existence* is shareable) and defer edge-level history.

**Tests:** `tests/test_graph_api.py` (inspect/find/history shape + scope enforcement),
`tests/test_cli_graph.py` (CliRunner, client faked — find/entity/history, `--json`).

### Sequencing & verification

1. B1 service + helpers + tests (incl. isolation) → green.
2. B2 API + schemas + tests → green. 3. B2 CLI + client + tests → green.
4. `just check` (ruff + mypy + full suite) green; CLI tests green.
5. **Phase C:** drop the dev graph (clears stale 001 `CONTRADICTS` edges), re-run
   `integration_test/run.py`; confirm aliases now merge into canonical nodes and the graph is
   navigable end-to-end via `odin graph`. Record observations in this doc + refresh 001's findings.

## Test contract to preserve (must stay green)

- `test_resolution.py` — merge-on-confirm, reject-on-LLM-no, no-LLM-for-dissimilar. (Empty graph in
  these tests ⇒ A1 pool == current pool ⇒ unchanged.)
- `test_pipeline_l3.py` — `WORKS_AT` provenance edge; re-ingest idempotency (rel count stable).
- `test_isolation.py` — no cross-scope leakage; B1 adds the graph-expansion case.

## Observations (Phase C)

Re-ran `integration_test/run.py` against the live stack (real OpenAI + OpenRouter) after a full
reset (graph cleared + `documents/jobs/graph_mutations` truncated). 14/14 docs `indexed`, 14 chunks,
isolation holds, **no contradictions** (A2 confirmed end-to-end). B1/B2 verified live: `odin graph
find|entity|history` all work against the real graph.

**Run 1 — surfaced the gate bug.** 0 alias merges. Root cause measured directly: resolution gates
the LLM behind `cosine ≥ 0.85`, but real alias pairs score **0.54–0.81** (Dana/Dana Okafor 0.54,
Helios/Helios Robotics 0.74, Helios Inc./Helios Robotics 0.81), so `_confirm_same` was **never
called**. True negative (Vertex/Helios) = 0.28.

**Fixes applied (resolution).** (1) `_THRESHOLD` 0.85→0.5 so alias pairs reach the LLM arbiter.
(2) `_confirm_same` now gets **type + up to 3 relationship facts** per side (new `graph.scope_entity_facts`
for in-graph entities; current-doc relations for new ones), not bare names. (3) Canonical now keeps
the **fullest name** as display name while anchoring the node **key** to the existing node (no
orphaned edges). All resolution unit tests stay green.

**Run 2 — resolution now fires, but consolidation is incomplete.** Multi-surface nodes 0→**4**
(LLM confirmed Helios Inc.↔Helios Robotics, Beacon↔Project Beacon, Austin↔Austin HQ, …). But the
headline aliases still split: org scope has **both** `org:helios robotics` and `org:helios inc.`
(both now *display* "Helios Robotics"); personal scope has both `person:dana` and `person:dana
okafor`. Only 4 merges fired, all **new→existing**; **zero existing→existing**.

**Root cause (structural, confirmed).** Worker is strictly **sequential** (no concurrency race —
`runner.py` claims one job at a time). Resolution is **incremental** and explicitly **refuses to
merge two already-existing nodes** (`resolution.py`: `if in_graph[i] and in_graph[j]: continue`),
because the write path can only fold *new* entities into a canonical — it cannot re-point an existing
node's `MENTIONS`/`REL` edges. So when two surface forms each become their own node in different docs
(order-dependent), they can never be unified afterward. Irrefutable evidence: **two nodes both named
"Helios Robotics" coexist**, even though the LLM demonstrably merges that exact pair when one side is
new.

**A3 — node-merge built.** Added `graph.merge_nodes` (re-points an absorbed node's `MENTIONS`/`REL`
edges onto the canonical, drops self-loops, `DETACH DELETE`s the absorbed node) and
`resolution.consolidate` (one bounded per-scope O(E²) pass that clusters all scope entities via
cosine+LLM and merges existing↔existing duplicates, logging `node_merge`). Unit-tested
(`test_consolidation.py`); wired into the harness after ingest. Undo of `node_merge` is intentionally
unsupported (`apply_inverse` raises) — re-creating a deleted node's full edge set is out of scope.

**Run 3 (threshold+context+canonical+A3).** Graph is markedly cleaner than run 1: **org scope fully
consolidated** — one `org:helios robotics`, every employee `WORKS_AT` it, Atlas/Beacon/Northwind
collapsed. Multi-surface nodes 4 (helios robotics ['Helios Inc.','Helios Robotics'], northwind,
project atlas, beacon). Isolation holds; no contradictions. **`consolidate` reported 0 merges** this
run — the org cleanup came from per-doc resolution during ingestion (aided by extraction
nondeterminism), leaving no same-scope existing duplicates for the pass to catch.

**Why residual splits remain (diagnosed, not a mechanical bug).** Personal scope still has
`person:dana` vs `person:dana okafor` and `person:mara` vs `person:mara vance`. Probing the judge
directly on the live data: **Dana/Dana Okafor → not same even with bare names** (the LLM won't equate a
first-name-only mention with a full name — defensible caution); **Mara/Mara Vance → merges *with*
context, rejects bare**, and `consolidate` saw 0 — i.e. the judge is **nondeterministic** on these
borderline first-name↔full-name pairs. `merge_nodes`/`consolidate` are correct; the variance is
inherent to LLM-judged resolution on ambiguous identities, and *not* force-merging them aligns with
the project principle (store facts; let the user decide). Run-to-run extraction + judge nondeterminism
also means exact entity/edge counts vary; the harness reports rather than asserts.

**Optional future levers (not built):** majority-vote the judge (3× calls, merge on quorum) to damp
nondeterminism; feed the judge a mention snippet (needs extractor to capture offsets); expose
`consolidate` via an admin endpoint/CLI trigger instead of the harness call.
