"""objectives: Objective vlabel + objective edges, and backfill entity owner

Revision ID: 0006_objectives
Revises: 0005_procrastinate
Create Date: 2026-06-27

Phase A of design_doc/003: objectives are distinct `Objective` nodes (full graph
participants), so this pre-creates the vlabel plus the objectives-layer edge labels
SERVES/ABOUT (the 0004_graph label pattern). It also backfills `owner` onto existing
Entity nodes from their MENTIONS edge owner so the node-owner model (003 A+I) applies
to the existing corpus without re-ingest.
"""

from alembic import op
from sqlalchemy.util import await_only

revision = "0006_objectives"
down_revision = "0005_procrastinate"
branch_labels = None
depends_on = None

_VLABELS = ("Objective",)
_ELABELS = ("SERVES", "ABOUT")

_BACKFILL = (
    "SELECT * FROM ag_catalog.cypher('odin', $cy$ "
    "MATCH (:Document)-[m:MENTIONS]->(e:Entity) SET e.owner = m.owner "
    "$cy$) AS (v agtype)"
)


def _create_label(kind: str, name: str) -> str:
    fn = "create_vlabel" if kind == "v" else "create_elabel"
    return (
        f"DO $$ BEGIN "
        f"IF NOT EXISTS ("
        f"SELECT 1 FROM ag_catalog.ag_label l "
        f"JOIN ag_catalog.ag_graph g ON l.graph = g.graphid "
        f"WHERE g.name = 'odin' AND l.name = '{name}') THEN "
        f"PERFORM ag_catalog.{fn}('odin', '{name}'); "
        f"END IF; END $$;"
    )


def _run(sql: str) -> None:
    raw = op.get_bind().connection.driver_connection
    await_only(raw.execute(sql))


def upgrade() -> None:
    op.execute("LOAD 'age'")
    for name in _VLABELS:
        op.execute(_create_label("v", name))
    for name in _ELABELS:
        op.execute(_create_label("e", name))
    _run(_BACKFILL)


def downgrade() -> None:
    pass
