"""Ask request/response schemas."""

import uuid

from pydantic import BaseModel


class AskTurn(BaseModel):
    role: str
    content: str


class AskIn(BaseModel):
    question: str
    history: list[AskTurn] | None = None


class AskCitation(BaseModel):
    document_id: uuid.UUID


class AskOut(BaseModel):
    answer: str
    confident: bool
    citations: list[AskCitation]
