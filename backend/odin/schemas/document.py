"""Document schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from odin.models import DocState, DocType


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    doc_type: DocType
    state: DocState
    version: int
    content_hash: str
    created_at: datetime
