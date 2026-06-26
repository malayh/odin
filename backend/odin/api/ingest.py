"""Ingest routes (async; returns a job id; pollable status)."""

from typing import Annotated

from fastapi import APIRouter, Form, UploadFile, status

from odin.api.deps import PrincipalDep, SessionDep
from odin.schemas import IngestOut
from odin.services import ingest as ingest_service

router = APIRouter()


@router.post("", response_model=IngestOut, status_code=status.HTTP_201_CREATED)
async def ingest(
    principal: PrincipalDep,
    session: SessionDep,
    file: UploadFile,
    key: Annotated[str, Form()],
) -> IngestOut:
    data = await file.read()
    doc, job, deduped = await ingest_service.intake(session, principal.id, key, data)
    return IngestOut(document_id=doc.id, job_id=job.id if job else None, deduped=deduped)
