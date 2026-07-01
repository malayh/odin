"""Documents: owner-scoped listing, retrieval, and soft-delete."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from odin.errors import NotFoundError
from odin.models import DocState, DocType, Document


async def list_for_owner(
    session: AsyncSession,
    owner: uuid.UUID,
    *,
    state: DocState | None = None,
    doc_type: DocType | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Document]:
    stmt = select(Document).where(Document.owner_user_id == owner)
    if state is not None:
        stmt = stmt.where(Document.state == state)
    if doc_type is not None:
        stmt = stmt.where(Document.doc_type == doc_type)
    stmt = stmt.order_by(Document.created_at.desc()).limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())


async def get_for_owner(session: AsyncSession, owner: uuid.UUID, doc_id: uuid.UUID) -> Document:
    doc = await session.get(Document, doc_id)
    if doc is None or doc.owner_user_id != owner:
        raise NotFoundError("document not found")
    return doc


async def soft_delete(
    session: AsyncSession, owner: uuid.UUID, doc_id: uuid.UUID, *, dry_run: bool = False
) -> dict[str, Any]:
    doc = await get_for_owner(session, owner, doc_id)
    if dry_run:
        return {"applied": False, "summary": f"would soft-delete document {doc_id}"}
    doc.state = DocState.soft_deleted
    await session.commit()
    return {"applied": True, "summary": f"soft-deleted document {doc_id}", "id": str(doc_id)}
