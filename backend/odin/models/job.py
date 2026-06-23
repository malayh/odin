"""Job ORM model: the worker queue."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from odin.db import Base
from odin.models.enums import JobState


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_state_created", "state", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String)
    state: Mapped[JobState] = mapped_column(
        Enum(JobState, name="job_state"), default=JobState.pending
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
