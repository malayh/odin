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


class SubgraphEdge(BaseModel):
    subject_key: str
    predicate: str
    object_key: str


class EntityOut(BaseModel):
    key: str
    name: str
    type: str
    aliases: list[str]
    relationships: list[RelationshipOut]
    subgraph: list[SubgraphEdge] = []


class MutationOut(BaseModel):
    seq: int
    actor: str
    op: str
    payload: dict[str, Any]
    rationale: str | None = None
    confidence: float | None = None
    created_at: datetime


class EntityIn(BaseModel):
    type: str
    name: str


class EntityRenameIn(BaseModel):
    new_name: str


class EdgeIn(BaseModel):
    subject_key: str
    predicate: str
    object_key: str


class ObjectiveIn(BaseModel):
    text: str


class ObjectiveOut(BaseModel):
    id: str
    text: str
    created_at: str | None = None


class MutationResult(BaseModel):
    applied: bool
    summary: str
    id: str | None = None
