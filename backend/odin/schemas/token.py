"""Access token schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str | None
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None


class TokenCreated(TokenOut):
    token: str


class CreateTokenIn(BaseModel):
    name: str | None = None
    expires_at: datetime | None = None
