"""core tenancy + document spine

Revision ID: 0001_core
Revises:
Create Date: 2026-06-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None

role = pg.ENUM("admin", "editor", "viewer", name="role", create_type=False)
scope_type = pg.ENUM("personal", "org", name="scope_type", create_type=False)
doc_type = pg.ENUM("source", "derived", name="doc_type", create_type=False)
doc_state = pg.ENUM(
    "pending", "indexed", "failed", "soft_deleted", name="doc_state", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    for e in (role, scope_type, doc_type, doc_state):
        e.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("is_initial_admin", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "orgs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("name", name="uq_orgs_name"),
    )

    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "org_id", sa.Uuid(), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", role, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "org_id", name="uq_membership_user_org"),
    )

    op.create_table(
        "access_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_access_tokens_token_hash", "access_tokens", ["token_hash"], unique=True)

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("scope_type", scope_type, nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("doc_type", doc_type, nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("blob_uri", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("state", doc_state, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])
    op.create_index("ix_documents_scope_state", "documents", ["scope_type", "scope_id", "state"])
    op.create_index(
        "ix_documents_active_key",
        "documents",
        ["scope_type", "scope_id", "key"],
        unique=True,
        postgresql_where=sa.text("supersedes_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("documents")
    op.drop_table("access_tokens")
    op.drop_table("memberships")
    op.drop_table("orgs")
    op.drop_table("users")
    bind = op.get_bind()
    for name in ("doc_state", "doc_type", "scope_type", "role"):
        pg.ENUM(name=name).drop(bind, checkfirst=True)
