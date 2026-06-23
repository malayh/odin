"""Job status schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from odin.models import JobState


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    type: str
    state: JobState
    attempts: int
    error: str | None
    created_at: datetime
