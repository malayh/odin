# 003 — Consolidation & Insight (the "sleep cycle")

Design for L5, reframed. Where `implementation.md` L5 was an **on-demand** `odin insight "X"`
synthesizer, this builds the thing spec §7.4 parked as the post-MVP **proactive miner**: an
autonomous, budgeted background job that periodically **reorganizes the knowledge graph** — the way
sleep restructures a brain after a day of learning. It consolidates memories, prunes conservatively,
and dreams up a small number of new connections, all anchored on the user's **objectives**.

Follows [002](002_l3_graph_hardening.md), which left the graph self-consistent on the *write path* but
proved consolidation is still incomplete (LLM-judged resolution is nondeterministic on borderline
identities; existing↔existing merges only fire by luck of ingest order). This phase makes
consolidation a deliberate, evidence-rich, scheduled act instead of an ingest-time side effect.

## The metaphor, mapped

Sleep does not learn new facts — it **restructures** what was learned. The mapping that drives this doc:

| Sleep function | Graph operation | Status going in |
| --- | --- | --- |
| **Consolidation** (integrate, strengthen) | Re-canonicalize entities with rich cross-doc context; high-bar auto-merge | `resolution.consolidate()` exists (`resolution.py:151`), naive, harness-only |
| **Synaptic pruning** (downscale weak) | Retract soft-deleted docs' facts; drop true orphans — **conservatively** | `graph.delete_document_contributions` exists; never run as cleanup |
| **Replay** (reactivate the day) | Process the *working set* — entities touched since last sleep | the `graph_mutations` log is the ready-made experience journal |
| **REM creativity** (distant association) | Find new connections; synthesize a *bounded* number of insight docs | not built — the core new work |
| **Schema integration** | Re-type / abstract communities | **deferred** (explicit non-goal this phase) |

## Decisions (locked in design review)

| Decision | Choice |
| --- | --- |
| **Whose mind sleeps** | **Single global brain.** One sleep process over the whole graph — not per-tenant shards. Legal only because of spec §4.3: it operates on entity *existence* (shareable) and writes every artifact back **scoped to its evidence**. Isolation stays a write-time-scoping + query-time-filter property, never weakened by the global pass. See [Isolation under a global brain](#isolation-under-a-single-global-brain). |
| **How changes land** | **Consolidation auto-applies** (high bar, reversible-by-design); **insights are `proposed`** (confirm/reject). The brain reorganizes memory on its own, but a *dreamed* idea is a hypothesis a human signs off on. Matches Odin's "store facts, let the user decide" spine. |
| **Consolidation bar** | A new **`deep_consolidate`** that judges on an *evidence dossier* (contexts, neighborhoods, co-occurring entities, doc topics), not bare name + 3 facts — with a **high bar** (majority-vote judge). Plus a **user-asserted "same-as" API** that forces a merge and re-consolidates the neighborhood. |
| **Pruning stance** | **Very conservative.** Only retract facts from **soft-deleted** documents and drop **true orphans** (zero edges, zero support). Never prune for age or low centrality. |
| **Objectives** | A new first-class **`Objective`** node — the *organizing force*. Sourced three ways: **explicit declaration**, **inferred from ingested notes**, **promoted from graph communities**. Objectives are the **anchors** REM creativity and pruning orient around. |
| **Insight discovery** | Three engines combined: **community detection**, **bridge/surprising paths**, **LLM synthesis over a scoped subgraph**. |
| **Work set & wake** | **Working set = the day's delta** (entities behind mutations since the last watermark) + a **rare random far-jump** into a distant region (the dream's distant-association). Scheduled + manual trigger; **on/off toggle** (default off); a hard **token budget** on dreaming. |
| **Insights produced/cycle** | Config **`insights_per_cycle` (0–1)** — deliberately scarce. Quality over volume. |

> This reshapes `implementation.md` L5: the on-demand `odin insight "X"` synthesizer is **replaced** by
> the autonomous cycle; the L5 **trust / confirm-reject loop is retained** and now applies to whatever
> the cycle dreams. Migration renumbers `0005_derived` → **`0006_*`** (`0005` is taken by Procrastinate).

---

## Architecture — the sleep cycle

One Procrastinate task (`worker/tasks.py`, alongside `ingest`), fired by a periodic schedule
(`@app.periodic`) and an admin trigger, `concurrency=1`, gated by a `consolidation_enabled` toggle. A
cycle is **NREM → REM**:

```
wake → select working set → NREM (consolidate + conservative prune) → REM (dream, budgeted) → record watermark
```

### Working set (replay), via the mutation watermark

The `graph_mutations` log (`mutations.py`) is already an append-only, `seq`-ordered journal of every
graph change. A tiny `consolidation_runs` table stores the last processed `seq` (the high-water mark).

- **Working set** = the distinct entity keys appearing in mutations with `seq > watermark`, expanded by
  **1 hop** to their neighborhoods (their edges pull in adjacent entities). This is "consolidate the
  day's experiences," not the whole life — bounded cost that scales with *activity*, not corpus size.
- **Random far-jump (the dream):** with probability `dream_jump_probability` (small), sample a distant
  entity/community **not** reachable from the working set and add it. This is the rare creative leap to
  unrelated territory. (Plain `random` in worker code — no determinism constraint here.)
- After a successful cycle, advance the watermark to the max `seq` seen.

### Phase 1 — NREM / Consolidation

**`deep_consolidate(session, candidates)`** — the evidence-rich successor to `consolidate()`:

1. **Candidate pairs** — gate cheaply by name-embedding cosine within the working set + neighborhoods
   (same recall mechanism as today), so we never run the judge over O(E²).
2. **Evidence dossier** per surviving pair — far more than today's name + 3 facts:
   - aliases + types on each side,
   - their full in-scope edge neighborhoods (who they relate to),
   - **co-occurring entities** (entities sharing a source chunk/doc),
   - the **topics/titles of the documents** that asserted each,
   - (optional, future) a representative mention snippet — needs the extractor to capture offsets
     (002 flagged this lever).
3. **High bar** — a **majority-vote judge**: N independent `_confirm_same`-style calls over the dossier,
   merge only on quorum (e.g. ≥2/3). This damps the run-to-run nondeterminism 002 measured on
   Dana/Dana Okafor — the dossier is exactly the "Dan ↔ engineering context / Dan Okafor ↔ engineering
   head" corroboration the user described.
4. **Apply** via existing `graph.merge_nodes` (re-points `MENTIONS`/`REL`, drops self-loops,
   `DETACH DELETE`s the absorbed node) + `mutations.log(op="node_merge")`. Auto-applied; logged.

**Split (secondary):** when a node's dossier splits cleanly into two disjoint context clusters,
`deep_consolidate` may *propose* a split (not auto-apply — splitting re-creates edge sets, which
`apply_inverse` already can't invert). Split is the natural correction for a bad prior merge.

**User-asserted identity** — `POST /graph/entities/{a}/same-as/{b}` (Editor+ on a shared scope): a
human says "these are the same." Highest-trust signal — immediately `merge_nodes` + log, then pulls the
merged neighborhood back through `deep_consolidate` so the assertion ripples outward.

**Conservative pruning** — only:
- retract contributions of **soft-deleted** docs (`graph.delete_document_contributions`, already exists;
  ties to spec §10.3's soft-delete→purge), and
- drop **true orphans** (entities with zero remaining edges and no supporting doc).
Nothing is pruned for being old or peripheral.

### The Objectives layer (the organizing force)

A new node type **`Objective`** — what the user is *trying to do*. Objectives are consolidated and
connected like entities as evidence accrues, and they are the **anchors** for REM.

- **Representation:** a distinct AGE vlabel `Objective` (pre-created in `0006` following the
  `0004_graph.py` `_VLABELS` pattern), plus an edge label `SERVES` (`Entity|Document -[SERVES]-> Objective`)
  and `ABOUT`. Objectives carry scope + provenance like everything else.
- **Sources (all three):**
  1. **Explicit** — `odin objective add "<text>"` / API. `origin=user`, highest signal. The MVP source.
  2. **Inferred from ingested notes** — extend `extraction` to emit candidate objectives when a doc
     states goals/intent (esp. personal notes). Emitted as **`proposed`** objectives for confirm/reject.
  3. **Promoted from communities** — REM's community detection surfaces a recurring, growing cluster as
     a **`proposed`** objective. Fully emergent.
- Objectives anchor salience: a region's relevance to REM = its graph proximity to an objective.

### Phase 2 — REM / Creative (bounded, budgeted, objective-anchored)

Operates on the working set (+ the far-jump), oriented around objectives, under a hard
`dream_token_budget`. Three discovery engines feed candidate insights:

- **Community detection** — cluster the in-scope subgraph (label-propagation / Louvain over the pulled
  edge set); a dense cluster = a latent theme → can name it (LLM) and/or propose an objective.
- **Bridge / surprising paths** — short paths linking entities whose support comes from **different
  documents**, especially paths that connect an objective to working-set entities. The non-obvious
  "A and C are linked via B, asserted in two unrelated docs" connection.
- **LLM synthesis over a subgraph** — feed an objective + its neighborhood to the LLM: "what non-obvious
  insight serves this objective?" → a candidate insight. Most open-ended, most expensive — hence the
  per-cycle cap.

**Output:** ≤ `insights_per_cycle` (0–1) **insight documents** — first-class `DocType.derived`
(`models/enums.py:19`, already exists) docs, with a reasoning subgraph
(`Doc… -[IMPLIES]-> Insight`, `DERIVED_FROM`, `SUPPORTS`) linked to the objective(s) served. Persisted
as **`proposed`** (see trust). Stop when the cap or token budget is hit, whichever first.

---

## Isolation under a single global brain

The load-bearing risk. A global pass that re-canonicalizes everything **must not** become a leakage
path. The guard, in three rules:

1. **Node merges are existence-level.** Spec §4.3: entity *existence* is shareable; merging two entity
   *nodes* changes only existence, never who-can-see-which-edge. Global node consolidation is therefore
   safe by construction.
2. **Edges are never re-scoped.** Every `MENTIONS`/`REL`/reasoning edge keeps the scope of the doc that
   asserted it. Query-time `graph._scope_clause` is untouched; nothing the brain does widens a traversal.
3. **Insights inherit their evidence's scope and only materialize when co-visible.** An insight doc + its
   reasoning edges are scoped to the **union of scopes of the supporting edges**, and are returnable only
   to a caller whose scope-set covers *all* of that evidence. A bridge whose two ends live in disjoint
   scopes that **no single caller can see together is never written down.** The brain may *think* across
   everything; it may only *record* a thought some real viewer could fully substantiate.

Consequence for objectives: an objective inferred from a personal note is personal-scoped; from org docs,
org-scoped. This refines spec §7.4's "insight private to its creator" for a brain with no single creator:
**scoped to evidence; personal-evidence insights are private to that user; cross-scope insights only form
within one user's reachable set and are private to them.**

Every one of these rules gets a case in `tests/test_isolation.py`.

---

## Trust model — proposed / confirmed / rejected

Consolidation **auto-applies** (it restructures existing, already-trusted facts). Everything the cycle
*invents* — insight docs, reasoning edges, inferred objectives — lands as **`proposed`**:

- `confirm`/`reject` API + `odin graph` CLI; each decision logged via `mutations.log`.
- Answering (L4 `services/answering.py`) **prefers confirmed/extracted** facts and flags reliance on
  unconfirmed inferences — the down-weighting hook L4 already anticipated.
- A `proposed` insight is excluded from retrieval grounding until confirmed (or surfaced clearly as
  unconfirmed), so dreams never silently become cited "fact."

---

## Migration `0006`

`down_revision="0005_procrastinate"`. Adds:

- **AGE labels** (pre-created, `0004_graph.py` pattern): vlabel `Objective`; elabels `SERVES`, `ABOUT`,
  `IMPLIES`, `DERIVED_FROM`, `SUPPORTS`.
- **Trust state** — a `TrustState` enum (`proposed | confirmed | rejected`) + column on `documents` for
  insight docs; reasoning/inferred edges carry `trust` as an AGE edge property (schemaless — no DDL).
- **`consolidation_runs`** — `id, started_at, finished_at, watermark_seq, merges, prunes, insights,
  tokens_spent`. The watermark + an audit trail of each sleep.

`DocType.derived` already exists, so no doc-type change is needed.

---

## Phase checklist

- [ ] **A — Objectives layer.** `Objective` ontology type + AGE labels (`0006`); explicit
  API/CLI (`odin objective`); extraction extension to propose objectives from notes; `graph` upsert/read
  for objectives. *(Sources 1+2; source 3 lands with D.)*
- [ ] **B — `deep_consolidate`.** Evidence dossier + majority-vote judge; reuse `merge_nodes` + log;
  propose-split path. Promote consolidation from harness call to a real callable. Unit tests extend
  `test_consolidation.py`.
- [ ] **C — User-asserted same-as.** `POST /graph/entities/{a}/same-as/{b}` → forced merge +
  neighborhood re-consolidation; scope-authorized. `test_graph_api.py`.
- [ ] **D — Sleep job runtime.** Procrastinate periodic task + admin trigger; working-set via mutation
  watermark; random far-jump; conservative pruning; `consolidation_runs`; on/off toggle.
- [ ] **E — REM creative.** Community detection + bridge paths + LLM synthesis, objective-anchored;
  insight docs + reasoning subgraph; `insights_per_cycle` + `dream_token_budget` caps.
- [ ] **F — Trust loop.** `TrustState` + confirm/reject API + `odin graph` CLI; answering prefers
  confirmed/extracted; proposed insights excluded from grounding.
- [ ] **G — Isolation hardening.** The three global-brain rules → cases in `test_isolation.py`.
- [ ] **H — Live run + record.** Run a sleep cycle against the 001/002 corpus on the real stack; confirm
  Dana/Mara finally consolidate under the dossier+vote bar; record observations here (002 Phase-C style).

**Sequencing:** A → B → C (consolidation usable + testable), then D (schedule it), then E → F (dream +
trust), G alongside C/E, H last.

---

## Config / open params (fixed at their step)

| Param | Default (proposed) | Step |
| --- | --- | --- |
| `consolidation_enabled` | `false` (opt-in toggle) | D |
| `consolidation_schedule` (cron) | nightly | D |
| candidate cosine gate | reuse `0.5` (002) | B |
| judge votes / quorum | 3 / 2 | B |
| working-set neighborhood hops | 1 | D |
| `dream_jump_probability` | small (e.g. 0.1) | D |
| `insights_per_cycle` | 1 (0 disables dreaming) | E |
| `dream_token_budget` | a hard ceiling per cycle | E |

---

## Risks / open questions

- **No `node_merge` undo.** `apply_inverse` can't re-create a deleted node's edge set (002), so a bad
  auto-merge isn't cleanly reversible. The **high bar (dossier + vote)** is the primary mitigation; the
  **propose-split path (B)** is the practical correction. Building true merge-undo is a separate lift —
  flagged, not scheduled.
- **Community detection in AGE.** No native Louvain; likely pull the scoped edge set and cluster in
  Python (bounded by the working set). Confirm scale is fine on the small-corpus target.
- **"Inferred from notes" needs a notes signal.** Odin has no notes type today; objective inference
  rides the existing extraction pass keyed on goal/intent language. May be noisy — `proposed` + confirm
  is the safety valve.
- **Schema integration (re-typing, abstraction)** is deliberately out of scope this phase.
