"""Job status routes: GET /jobs (list) and GET /jobs/{id}."""

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from odin.api.deps import PrincipalDep, SessionDep
from odin.errors import NotFoundError
from odin.models import Document, Job, JobState
from odin.schemas import JobOut

router = APIRouter()


@router.get("", response_model=list[JobOut])
async def list_jobs(
    principal: PrincipalDep,
    session: SessionDep,
    state: JobState | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[JobOut]:
    stmt = (
        select(Job)
        .join(Document, Document.id == Job.document_id)
        .where(Document.owner_user_id == principal.id)
    )
    if state is not None:
        stmt = stmt.where(Job.state == state)
    stmt = stmt.order_by(Job.created_at.desc()).limit(limit).offset(offset)
    jobs = (await session.scalars(stmt)).all()
    return [JobOut.model_validate(j) for j in jobs]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> JobOut:
    job = await session.get(Job, job_id)
    if job is None:
        raise NotFoundError("job not found")
    doc = await session.get(Document, job.document_id)
    if doc is None or doc.owner_user_id != principal.id:
        raise NotFoundError("job not found")
    return JobOut.model_validate(job)
