"""object_embeddings: generic pgvector store (chunk + entity), partial HNSW per type

Revision ID: 0008_object_embeddings
Revises: 0007_sleep_runs
Create Date: 2026-07-01

Unifies chunk embeddings and (new) entity embeddings into one table keyed by
(object_type, object_id, field). Partial HNSW indexes per object_type keep filtered
ANN fast. The vector column is fixed at 1536 dims.
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0008_object_embeddings"
down_revision = "0007_sleep_runs"
branch_labels = None
depends_on = None


def _hnsw(name: str, object_type: str) -> None:
    op.create_index(
        name,
        "object_embeddings",
        ["vector"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"vector": "vector_cosine_ops"},
        postgresql_where=sa.text(f"object_type = '{object_type}'"),
    )


def upgrade() -> None:
    op.create_table(
        "object_embeddings",
        sa.Column("object_type", sa.String(), primary_key=True),
        sa.Column("object_id", sa.String(), primary_key=True),
        sa.Column("field", sa.String(), primary_key=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("vector", Vector(1536), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_object_embeddings_owner", "object_embeddings", ["owner_user_id"]
    )
    _hnsw("ix_object_embeddings_chunk_hnsw", "chunk")
    _hnsw("ix_object_embeddings_entity_hnsw", "entity")
    op.execute(
        """
        INSERT INTO object_embeddings
            (object_type, object_id, field, owner_user_id, vector, updated_at)
        SELECT 'chunk', e.chunk_id::text, 'text', d.owner_user_id, e.vector, e.created_at
        FROM embeddings e
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        """
    )
    op.drop_table("embeddings")


def downgrade() -> None:
    op.create_table(
        "embeddings",
        sa.Column(
            "chunk_id",
            sa.Uuid(),
            sa.ForeignKey("chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("vector", Vector(1536), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_embeddings_vector_hnsw",
        "embeddings",
        ["vector"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"vector": "vector_cosine_ops"},
    )
    op.execute(
        """
        INSERT INTO embeddings (chunk_id, vector, created_at)
        SELECT object_id::uuid, vector, updated_at
        FROM object_embeddings
        WHERE object_type = 'chunk'
        """
    )
    op.drop_table("object_embeddings")
