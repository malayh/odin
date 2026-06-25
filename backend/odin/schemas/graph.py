"""Graph exploration schemas: entity summaries, full entity views, mutation history."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class EntitySummary(BaseModel):
    key: str
    name: str
    type: str


class RelationshipOut(BaseModel):
    predicate: str
    object_key: str
    source_doc_id: str | None = None


class EntityOut(BaseModel):
    key: str
    name: str
    type: str
    aliases: list[str]
    relationships: list[RelationshipOut]


class MutationOut(BaseModel):
    seq: int
    actor: str
    op: str
    payload: dict[str, Any]
    rationale: str | None = None
    confidence: float | None = None
    created_at: datetime
