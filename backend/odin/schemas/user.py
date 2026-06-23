"""User request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    is_initial_admin: bool
    created_at: datetime


class CreateUserIn(BaseModel):
    email: str
    display_name: str | None = None
