"""Job status routes: GET /jobs/{id}."""

import uuid

from fastapi import APIRouter

from odin.api.deps import PrincipalDep, SessionDep
from odin.errors import NotFoundError
from odin.models import Document, Job
from odin.schemas import JobOut
from odin.tenancy import Scope, can_read, resolve_scope_set

router = APIRouter()


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> JobOut:
    job = await session.get(Job, job_id)
    if job is None:
        raise NotFoundError("job not found")
    doc = await session.get(Document, job.document_id)
    scope_set = await resolve_scope_set(session, principal)
    if doc is None or not can_read(scope_set, Scope(doc.scope_type, doc.scope_id)):
        raise NotFoundError("job not found")
    return JobOut.model_validate(job)
