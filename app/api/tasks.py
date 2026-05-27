"""OTS Approval Helping Agent — Tasks API (query, upload, webhook)."""

import uuid
import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.db.models import Part, ApprovalTask, ParsedReport, EventLog
from app.events.bus import event_bus
from app.events.types import EventType, Event
from app.services.extractor import extract_text
from app.schemas.tasks import (
    TaskResponse,
    PartResponse,
    ParsedReportResponse,
    TimelineEntry,
    TaskDetailResponse,
    WebhookMailPayload,
    ReportUploadResponse,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
webhook_router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


async def _get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


@router.get("/{task_id}", response_model=dict)
async def get_task(task_id: str, db: AsyncSession = Depends(_get_db)):
    result = await db.execute(select(ApprovalTask).where(ApprovalTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    part_result = await db.execute(select(Part).where(Part.id == task.part_id))
    part = part_result.scalar_one()

    reports_result = await db.execute(
        select(ParsedReport).where(ParsedReport.task_id == task_id).order_by(ParsedReport.created_at.desc())
    )
    reports = reports_result.scalars().all()

    events_result = await db.execute(
        select(EventLog).where(EventLog.task_id == task_id).order_by(EventLog.created_at.asc())
    )
    events = events_result.scalars().all()

    timeline = [
        TimelineEntry(
            event=e.event_type,
            detail=e.source or "",
            time=e.created_at.isoformat() if e.created_at else "",
        )
        for e in events
    ]

    return TaskDetailResponse(
        task=TaskResponse.model_validate(task),
        part=PartResponse.model_validate(part),
        reports=[ParsedReportResponse.model_validate(r) for r in reports],
        timeline=timeline,
    ).model_dump(mode="json")


@router.post("/{task_id}/reports", response_model=dict)
async def upload_report(task_id: str, file: UploadFile = File(...), db: AsyncSession = Depends(_get_db)):
    task_result = await db.execute(select(ApprovalTask).where(ApprovalTask.id == task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    file_content = await file.read()
    filename = file.filename or "report.bin"

    storage_path = f"ots-reports/{task_id}/{uuid.uuid4().hex[:8]}_{filename}"

    report_text = extract_text(filename, file_content)

    event_log = EventLog(
        task_id=task_id,
        event_type=EventType.REPORT_RECEIVED,
        source="tasks_api",
        payload={"filename": filename, "storage_path": storage_path, "size": len(file_content)},
    )
    db.add(event_log)

    await event_bus.publish(Event(
        type=EventType.REPORT_RECEIVED,
        task_id=task_id,
        source="tasks_api",
        payload={
            "task_id": task_id,
            "part_id": task.part_id,
            "filename": filename,
            "storage_path": storage_path,
            "file_size": len(file_content),
            "report_text": report_text,
        },
    ))

    await db.commit()

    return ReportUploadResponse(
        storage_path=storage_path,
        filename=filename,
    ).model_dump(mode="json")


@webhook_router.post("/mail", response_model=dict)
async def webhook_mail(body: WebhookMailPayload, db: AsyncSession = Depends(_get_db)):
    part_result = await db.execute(select(Part).where(Part.part_no == body.part_no))
    part = part_result.scalar_one_or_none()
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")

    task_result = await db.execute(
        select(ApprovalTask).where(ApprovalTask.part_id == part.id).order_by(ApprovalTask.created_at.desc())
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    event = Event(
        type=EventType.REPORT_RECEIVED,
        task_id=task.id,
        source="webhook_mail",
        payload={
            "task_id": task.id,
            "part_id": part.id,
            "part_no": body.part_no,
            "mail_from": body.mail_from,
            "mail_subject": body.mail_subject,
            "attachments": body.attachments,
            "report_text": "[Webhook 触发，无文件内容]",
        },
    )

    event_log = EventLog(
        task_id=task.id,
        event_type=EventType.REPORT_RECEIVED,
        source="webhook_mail",
        payload={"mail_from": body.mail_from, "mail_subject": body.mail_subject},
    )
    db.add(event_log)
    await db.commit()

    await event_bus.publish(event)

    return {"status": "accepted", "task_id": task.id, "part_no": body.part_no}