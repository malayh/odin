"""Search request/response schemas."""

import uuid
from typing import Any

from pydantic import BaseModel


class SearchIn(BaseModel):
    query: str
    top_k: int = 10


class SearchHit(BaseModel):
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    ordinal: int
    text: str
    section_meta: dict[str, Any] | None = None
    char_start: int
    char_end: int
    score: float


class SearchOut(BaseModel):
    hits: list[SearchHit]
