"""sleep_runs: consolidate/dream sleep-cycle run tracking

Revision ID: 0007_sleep_runs
Revises: 0006_objectives
Create Date: 2026-07-01

design_doc/003 Phase D: a per-user, single-flight record for the sleep verbs.
The partial unique index on (owner_user_id, type) WHERE state IN ('queued','running')
enforces "at most one of each type in flight" at the database level.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0007_sleep_runs"
down_revision = "0006_objectives"
branch_labels = None
depends_on = None

sleep_state = pg.ENUM(
    "queued", "running", "succeeded", "failed", name="sleep_state", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    sleep_state.create(bind, checkfirst=True)

    op.create_table(
        "sleep_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("state", sleep_state, nullable=False),
        sa.Column(
            "queued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stats", pg.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "uq_sleep_runs_active",
        "sleep_runs",
        ["owner_user_id", "type"],
        unique=True,
        postgresql_where=sa.text("state IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_sleep_runs_active", table_name="sleep_runs")
    op.drop_table("sleep_runs")
    bind = op.get_bind()
    pg.ENUM(name="sleep_state").drop(bind, checkfirst=True)
