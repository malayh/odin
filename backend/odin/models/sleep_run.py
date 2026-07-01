"""SleepRun ORM model: tracks consolidate/dream sleep-cycle runs (single-flight per type)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from odin.db import Base
from odin.models.enums import SleepState


class SleepRun(Base):
    __tablename__ = "sleep_runs"
    __table_args__ = (
        Index(
            "uq_sleep_runs_active",
            "owner_user_id",
            "type",
            unique=True,
            postgresql_where=text("state IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String)
    state: Mapped[SleepState] = mapped_column(
        Enum(SleepState, name="sleep_state"), default=SleepState.queued
    )
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
