"""Document ORM model."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from odin.db import Base
from odin.models.enums import DocState, DocType, ScopeType


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_content_hash", "content_hash"),
        Index("ix_documents_scope_state", "scope_type", "scope_id", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    scope_type: Mapped[ScopeType] = mapped_column(Enum(ScopeType, name="scope_type"))
    scope_id: Mapped[uuid.UUID] = mapped_column()
    doc_type: Mapped[DocType] = mapped_column(
        Enum(DocType, name="doc_type"), default=DocType.source
    )
    content_hash: Mapped[str] = mapped_column(String)
    blob_uri: Mapped[str | None] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    state: Mapped[DocState] = mapped_column(
        Enum(DocState, name="doc_state"), default=DocState.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
