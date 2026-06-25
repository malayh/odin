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
- [ ] **B1 — 3.8 graph expansion in retrieval.** From top vector hits → in-scope mentioned entities
  → in-scope relationships → linked docs; bounded depth/fanout; merged into candidates. Scope-filter
  at every hop. Adds the graph case to `tests/test_isolation.py`.
- [ ] **B2 — 3.9 graph API + `odin graph` CLI.** `api/graph.py` (inspect entity, traverse,
  mutation history/explain) over the existing `graph.read_entity` + `mutations.explain`;
  `cli/odin_cli/commands/graph.py` real implementation.
- [ ] **C — Re-run + record.** Re-run the 001 corpus harness; confirm aliases now merge and
  contradiction count drops to the genuine few; update 001's findings + this doc's observations.

## Test contract to preserve (must stay green)

- `test_resolution.py` — merge-on-confirm, reject-on-LLM-no, no-LLM-for-dissimilar. (Empty graph in
  these tests ⇒ A1 pool == current pool ⇒ unchanged.)
- `test_pipeline_l3.py` — `WORKS_AT` provenance edge; re-ingest idempotency (rel count stable).
- `test_isolation.py` — no cross-scope leakage; B1 adds the graph-expansion case.

## Observations

_(filled in Phase C)_
