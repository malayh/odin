"""ingest: chunks + jobs

Revision ID: 0002_ingest
Revises: 0001_core
Create Date: 2026-06-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0002_ingest"
down_revision = "0001_core"
branch_labels = None
depends_on = None

job_state = pg.ENUM("pending", "running", "done", "failed", name="job_state", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    job_state.create(bind, checkfirst=True)

    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("section_meta", pg.JSONB(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_chunk_doc_ordinal"),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("state", job_state, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_jobs_state_created", "jobs", ["state", "created_at"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("chunks")
    bind = op.get_bind()
    pg.ENUM(name="job_state").drop(bind, checkfirst=True)
