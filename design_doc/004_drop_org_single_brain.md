# 004 — Drop Org: One Brain Per User

Living tracker for removing multi-tenancy. Odin stops being multi-tenant: **every user is a single
isolated brain.** Orgs, memberships, roles, and the whole personal-vs-org scope model are deleted.
Isolation collapses to one fact — **you see only what you own** (`documents.owner_user_id == you`).

This reverses spec §2's "Multi-tenant from day one" and deletes spec §4 wholesale. It is a deliberate
product decision (not a regression): the knowledge graph's value and the upcoming "sleep cycle"
([003](003_consolidation_and_insight.md)) are about *one mind reorganizing itself*. Orgs forced a
shared-canonical-node + scoped-edge model (spec §4.3) whose only real consumer was cross-tenant sharing;
removing it makes consolidation and global dreaming trivial — no scope inheritance, no leakage rules.

## Why now

003 (dreaming) kept colliding with §4.3: a global consolidation pass over shared entity nodes can't stay
inside a tenant, and dreamed insights needed scope-inheritance gymnastics to avoid leaking. Cutting orgs
removes the collision at the root. After this, a brain = a user, the graph is that user's, and "global
dreaming" just means *over everything the brain owns*.

## What collapses

| Concept | Before | After |
| --- | --- | --- |
| Tenancy unit | personal scope + N org scopes per user | **one brain = one user** |
| Document ownership | `owner_user_id` + `scope_type`/`scope_id` | `owner_user_id` only |
| Graph edge scope | `scope_type` + `scope_id` on every MENTIONS/REL | single `owner` property |
| Isolation predicate | `scope_filter`/`_scope_clause` (personal OR org-set) | `owner_user_id == caller` / `e.owner = $uid` |
| Roles | Admin/Editor/Viewer (`Role`) | gone — you own or you don't |
| `--scope` flag | narrow to personal / `org:<id>` | gone |
| Cross-doc resolution pool | per-scope | per-owner |

## Deleted entirely

- **Models:** `Org`, `Membership`; enums `Role`, `ScopeType`.
- **Services:** `services/orgs.py` org/membership funcs (`create_user` kept, moved to `services/users.py`).
- **Tenancy:** `Scope`, `ScopeSet`, `narrow`, `can_read`, `can_write`, `resolve_scope_set`,
  `scope_filter` → `tenancy.py` shrinks to a single `owner_filter(owner_id)`.
- **API:** `admin` org/member/role routes (user + token routes kept); `--scope`/scope params on
  ingest/search/ask; `WhoamiOut.scopes`.
- **Schemas:** `schemas/org.py`; `ScopeOut`; scope fields on `SearchHit`/`SearchIn`/`AskCitation`.
- **CLI:** `create-org`/`add-member`; `--scope` on ingest/search/ask/login; `default_scope` in config.

## Migration strategy: edit `0001_core`, recreate the DB

This is **dev-only with a re-ingestable corpus** — no production data, no forward migration needed.
So instead of a new down-migration, we **edit `0001_core` in place** to remove `orgs`, `memberships`,
the `role`/`scope_type` PG enums, and the `documents.scope_type`/`scope_id` columns + scope indexes,
then **drop and recreate the dev DB** and re-run `alembic upgrade head`. The AGE graph is wiped with it;
re-ingest rebuilds edges carrying the new `owner` property. `0002`–`0005` are unaffected (they never
referenced scope). No graph-property data migration — the hardest piece — is needed because we re-ingest.

## Checklist

- [ ] **Models** — delete `org.py`; drop `Role`/`ScopeType` from `enums.py`; `Document` loses scope cols,
  indexes become owner-based; `models/__init__` cleaned.
- [ ] **Migration `0001_core`** — remove orgs/memberships/role/scope_type + doc scope cols/indexes.
- [ ] **Tenancy** — `tenancy.py` → just `owner_filter(owner_id)`.
- [ ] **Graph** — edges carry `owner` not `scope_type/scope_id`; `_owner_clause`; read helpers take
  `owner: uuid.UUID`; `merge_nodes`/`apply_inverse`/`entity_history` updated.
- [ ] **Services** — `ingest.intake(session, owner_id, key, data)`; `resolution.resolve/consolidate` keyed
  by `owner`; `retrieval`/`answering` drop scope (Hit/Citation lose scope fields); `orgs.py`→`users.py`.
- [ ] **API** — ingest/search/ask/graph/jobs derive owner from `principal.id`; `admin` stripped to
  user/token; `whoami` returns just the user.
- [ ] **Schemas** — delete org; drop scope fields.
- [ ] **CLI** — client + commands drop org/scope; config drops default_scope.
- [ ] **Tests** — drop `test_admin_api` org cases, rewrite `test_tenancy`/`test_isolation` to cross-user,
  strip scope from every seed/call. `integration_test/` corpus de-scoped (separate, not in `just check`).
- [ ] **Docs** — spec §2/§4, implementation L0, README, flows.md, CLAUDE.md header (follow-up).
- [ ] **Verify** — drop DB, `just migrate`, `just check` green.

## Notes / out of scope

- `integration_test/corpus/{org,personal}` and `run.py` use scopes — de-scoping the harness is tracked
  but **not** part of `just check`; handled alongside the 003 live run.
- Spec/README/CLAUDE.md prose edits are a documentation follow-up, not load-bearing for green tests.
- Entity nodes remain global/shared in AGE (existence is not owner-tagged); **edges** carry `owner`.
  A single user owning everything means this is moot today, but it keeps the door open if multi-user
  returns as "separate brains that can share by reference" (the 003 attribution idea).
