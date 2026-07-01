"""Generic embedding store: one pgvector per (object_type, object_id, field)."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from odin.db import Base

EMBEDDING_DIM = 1536


def _hnsw(name: str, object_type: str) -> Index:
    return Index(
        name,
        "vector",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"vector": "vector_cosine_ops"},
        postgresql_where=text(f"object_type = '{object_type}'"),
    )


class ObjectEmbedding(Base):
    __tablename__ = "object_embeddings"
    __table_args__ = (
        _hnsw("ix_object_embeddings_chunk_hnsw", "chunk"),
        _hnsw("ix_object_embeddings_entity_hnsw", "entity"),
    )

    object_type: Mapped[str] = mapped_column(String, primary_key=True)
    object_id: Mapped[str] = mapped_column(String, primary_key=True)
    field: Mapped[str] = mapped_column(String, primary_key=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    vector: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
