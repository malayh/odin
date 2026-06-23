"""Auth and whoami schemas."""

import uuid

from pydantic import BaseModel

from odin.models import Role
from odin.schemas.user import UserOut


class ScopeOut(BaseModel):
    type: str
    id: uuid.UUID
    role: Role | None


class WhoamiOut(BaseModel):
    user: UserOut
    scopes: list[ScopeOut]
