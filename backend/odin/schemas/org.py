"""Org and membership schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from odin.models import Role


class OrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime


class CreateOrgIn(BaseModel):
    name: str


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    org_id: uuid.UUID
    role: Role
    created_at: datetime


class AddMemberIn(BaseModel):
    user_id: uuid.UUID
    role: Role


class SetRoleIn(BaseModel):
    role: Role
