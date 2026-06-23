"""Ingest request/response schemas."""

import uuid

from pydantic import BaseModel


class IngestOut(BaseModel):
    document_id: uuid.UUID
    job_id: uuid.UUID | None
    deduped: bool
