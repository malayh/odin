"""graph: mutation log + pre-created AGE labels

Revision ID: 0004_graph
Revises: 0003_embeddings
Create Date: 2026-06-24

The materialized knowledge graph lives in Apache AGE (the `odin` graph from init.sql);
this migration adds the relational `graph_mutations` audit log and pre-creates the AGE
vertex/edge labels so runtime cypher only ever inserts rows (never issues label DDL).
AGE label tables live in the `odin` schema, not `public`; downgrade drops only the
relational table and leaves the (empty, idempotently-created) labels in place.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0004_graph"
down_revision = "0003_embeddings"
branch_labels = None
depends_on = None

_VLABELS = ("Entity", "Document")
_ELABELS = ("MENTIONS", "REL", "CONTRADICTS")


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


def upgrade() -> None:
    op.create_table(
        "graph_mutations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("op", sa.String(), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_graph_mutations_seq", "graph_mutations", ["seq"])

    op.execute("LOAD 'age'")
    for name in _VLABELS:
        op.execute(_create_label("v", name))
    for name in _ELABELS:
        op.execute(_create_label("e", name))


def downgrade() -> None:
    op.drop_table("graph_mutations")
