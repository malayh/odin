"""Ownership: a caller is one brain and sees only documents they own."""

import uuid

from sqlalchemy import ColumnElement

from odin.models import Document


def owner_filter(owner_id: uuid.UUID) -> ColumnElement[bool]:
    return Document.owner_user_id == owner_id
