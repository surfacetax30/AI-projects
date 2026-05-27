"""OTS Approval Helping Agent — Parts API (CRUD + auto-create task)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.db.models import Part, ApprovalTask
from app.schemas.tasks import PartCreate, PartResponse, TaskResponse

router = APIRouter(prefix="/api/parts", tags=["parts"])


async def _get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


@router.post("", response_model=dict)
async def create_part(body: PartCreate, db: AsyncSession = Depends(_get_db)):
    part = Part(
        part_no=body.part_no,
        part_name=body.part_name,
        part_type=body.part_type,
        supplier=body.supplier,
        project_code=body.project_code,
        is_new=body.is_new,
        parent_part_no=body.parent_part_no,
    )
    db.add(part)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Part {body.part_no} already exists")

    task = ApprovalTask(part_id=part.id, state="CREATED")
    db.add(task)
    await db.commit()
    await db.refresh(part)
    await db.refresh(task)

    return {
        "part": PartResponse.model_validate(part).model_dump(mode="json"),
        "task": TaskResponse.model_validate(task).model_dump(mode="json"),
    }


@router.get("", response_model=list[PartResponse])
async def list_parts(db: AsyncSession = Depends(_get_db)):
    result = await db.execute(select(Part).order_by(Part.created_at.desc()))
    parts = result.scalars().all()
    return [PartResponse.model_validate(p) for p in parts]


@router.get("/{part_id}", response_model=dict)
async def get_part(part_id: str, db: AsyncSession = Depends(_get_db)):
    result = await db.execute(select(Part).where(Part.id == part_id))
    part = result.scalar_one_or_none()
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")

    tasks_result = await db.execute(
        select(ApprovalTask).where(ApprovalTask.part_id == part_id).order_by(ApprovalTask.created_at.desc())
    )
    tasks = tasks_result.scalars().all()

    return {
        **PartResponse.model_validate(part).model_dump(mode="json"),
        "tasks": [TaskResponse.model_validate(t).model_dump(mode="json") for t in tasks],
    }