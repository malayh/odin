"""Whoami schema."""

from pydantic import BaseModel

from odin.schemas.user import UserOut


class WhoamiOut(BaseModel):
    user: UserOut
