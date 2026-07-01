"""Sleep-cycle run schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from odin.models import SleepState


class SleepRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    state: SleepState
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    stats: dict[str, Any] | None
    error: str | None


class SleepStatusOut(BaseModel):
    run: SleepRunOut | None
    waiting_behind: str | None = None
