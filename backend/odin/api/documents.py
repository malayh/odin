"""Document routes: list, inspect, and soft-delete owner documents."""

import uuid

from fastapi import APIRouter

from odin.api.deps import PrincipalDep, SessionDep
from odin.models import DocState, DocType
from odin.schemas import DocumentOut, MutationResult
from odin.services import documents

router = APIRouter()


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    principal: PrincipalDep,
    session: SessionDep,
    state: DocState | None = None,
    doc_type: DocType | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[DocumentOut]:
    docs = await documents.list_for_owner(
        session, principal.id, state=state, doc_type=doc_type, limit=limit, offset=offset
    )
    return [DocumentOut.model_validate(d) for d in docs]


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> DocumentOut:
    doc = await documents.get_for_owner(session, principal.id, doc_id)
    return DocumentOut.model_validate(doc)


@router.delete("/{doc_id}", response_model=MutationResult)
async def delete_document(
    doc_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, dry_run: bool = False
) -> MutationResult:
    result = await documents.soft_delete(session, principal.id, doc_id, dry_run=dry_run)
    return MutationResult(**result)
