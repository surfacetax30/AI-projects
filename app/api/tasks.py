"""OTS Approval Helping Agent — Tasks API (query, upload, webhook, mail batch)."""

import uuid
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.db.models import Part, ApprovalTask, ParsedReport, EventLog, PendingMail
from app.events.bus import event_bus
from app.events.types import EventType, Event
from app.services.extractor import extract_text
from app.agents.mail_gateway import mail_gateway
from app.schemas.tasks import (
    TaskResponse,
    PartResponse,
    ParsedReportResponse,
    TimelineEntry,
    TaskDetailResponse,
    WebhookMailPayload,
    ReportUploadResponse,
    MailClassificationResult,
    MailBatchReport,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
webhook_router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
mail_router = APIRouter(prefix="/api/mail", tags=["mail"])


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


# ── Webhook：邮件到达 → 写入 pending_mails 队列，等待每日批处理 ──


@webhook_router.post("/mail", response_model=dict)
async def webhook_mail(body: WebhookMailPayload, db: AsyncSession = Depends(_get_db)):
    """接收邮件 webhook，写入 pending_mails 队列。

    不再直接触发 REPORT_RECEIVED，而是等 daily batch process 统一过滤。
    """
    mail = PendingMail(
        mail_from=body.mail_from,
        mail_subject=body.mail_subject,
        mail_body_preview=body.mail_body_preview or "",
        attachments=body.attachments or [],
        status="pending",
    )
    db.add(mail)
    await db.commit()
    await db.refresh(mail)

    return {
        "status": "queued",
        "mail_id": mail.id,
        "mail_from": body.mail_from,
        "note": "邮件已入队，将在下一次批处理中分类",
    }


# ── 每日批处理 ──


@mail_router.post("/batch-process", response_model=dict)
async def batch_process_mail(db: AsyncSession = Depends(_get_db)):
    """手动触发每日邮件批处理。

    1. 读取 status='pending' 的邮件
    2. 规则引擎 + LLM 分类
    3. auto_accepted → 创建 task + 发布 REPORT_RECEIVED
    4. auto_rejected → 记录日志
    5. pending_human → 标记等待人工审核
    """
    # 读取待处理邮件
    result = await db.execute(
        select(PendingMail)
        .where(PendingMail.status == "pending")
        .order_by(PendingMail.received_at.asc())
    )
    pending = result.scalars().all()

    if not pending:
        return {
            "batch_id": "none",
            "total": 0, "auto_accepted": 0, "auto_rejected": 0, "pending_human": 0,
            "results": [],
            "message": "没有待处理的邮件",
        }

    # 转换为 batch_process 所需格式
    mail_dicts = [
        {
            "id": m.id,
            "mail_from": m.mail_from,
            "mail_subject": m.mail_subject,
            "mail_body_preview": m.mail_body_preview,
            "attachments": m.attachments,
        }
        for m in pending
    ]

    # 调用 MailGateway 批处理
    batch_result = await mail_gateway.batch_process(mail_dicts)

    # 写回 DB + 触发后续动作
    mail_map = {m.id: m for m in pending}
    classified_results = []

    for r in batch_result["results"]:
        mail_id = r.get("id", "")
        db_mail = mail_map.get(mail_id)
        if not db_mail:
            continue

        final_status = r["final_status"]
        now = datetime.utcnow()

        db_mail.status = final_status
        db_mail.classification = r.get("classification")
        db_mail.confidence = r.get("confidence")
        db_mail.reason = r.get("reason")
        db_mail.classified_by = r.get("classified_by")
        db_mail.classified_at = now
        db_mail.batch_id = batch_result["batch_id"]
        db_mail.part_no = r.get("part_no")

        if final_status == "auto_accepted":
            # 查找或创建 Part & Task
            part_no = r.get("part_no") or "UNKNOWN"
            part_result = await db.execute(select(Part).where(Part.part_no == part_no))
            part = part_result.scalar_one_or_none()

            if not part:
                part = Part(
                    part_no=part_no,
                    part_name=f"自动创建-{part_no}",
                    part_type="电子零件",
                    supplier=db_mail.mail_from,
                    project_code="mail",
                )
                db.add(part)
                await db.flush()

            # 创建 ApprovalTask
            task = ApprovalTask(part_id=part.id, state="CREATED")
            db.add(task)
            await db.flush()
            db_mail.task_id = task.id

            # 发布 REPORT_RECEIVED → Parser → DataChecker
            await event_bus.publish(Event(
                type=EventType.REPORT_RECEIVED,
                task_id=task.id,
                source="mail_gateway",
                payload={
                    "task_id": task.id,
                    "part_id": part.id,
                    "part_no": part_no,
                    "mail_from": db_mail.mail_from,
                    "mail_subject": db_mail.mail_subject,
                    "filename": db_mail.mail_subject or "mail_report",
                    "storage_path": f"ots-reports/{task.id}/mail_{db_mail.id}",
                    "report_text": db_mail.mail_body_preview or "",
                },
            ))

        elif final_status == "auto_rejected":
            # 记录拒收日志
            pass  # EventLog 在下面统一记录

        # 记录事件
        event_type = EventType.MAIL_CLASSIFIED
        if final_status == "pending_human":
            event_type = EventType.MAIL_HUMAN_NEEDED
        elif final_status == "auto_rejected":
            event_type = EventType.MAIL_REJECTED

        task_id_val = db_mail.task_id or "__none__"
        event_log = EventLog(
            task_id=task_id_val,
            event_type=event_type,
            source="mail_gateway",
            payload={
                "mail_id": db_mail.id,
                "classification": db_mail.classification,
                "confidence": db_mail.confidence,
                "reason": db_mail.reason,
                "classified_by": db_mail.classified_by,
            },
        )
        db.add(event_log)

        classified_results.append(MailClassificationResult(
            mail_id=db_mail.id,
            mail_from=db_mail.mail_from,
            mail_subject=db_mail.mail_subject,
            status=final_status,
            classification=db_mail.classification,
            part_no=db_mail.part_no,
            confidence=db_mail.confidence,
            reason=db_mail.reason,
            classified_by=db_mail.classified_by,
        ).model_dump(mode="json"))

    await db.commit()

    return MailBatchReport(
        batch_id=batch_result["batch_id"],
        total=batch_result["total"],
        auto_accepted=batch_result["auto_accepted"],
        auto_rejected=batch_result["auto_rejected"],
        pending_human=batch_result["pending_human"],
        results=[MailClassificationResult(**r) for r in classified_results],
    ).model_dump(mode="json")


# ── 查询待审核邮件 ──


@mail_router.get("/pending", response_model=dict)
async def list_pending_mail(db: AsyncSession = Depends(_get_db)):
    """列出所有 status='pending_human' 的邮件，供前端审核列表使用。"""
    result = await db.execute(
        select(PendingMail)
        .where(PendingMail.status == "pending_human")
        .order_by(PendingMail.received_at.desc())
    )
    pending = result.scalars().all()

    return {
        "total": len(pending),
        "mails": [
            {
                "id": m.id,
                "mail_from": m.mail_from,
                "mail_subject": m.mail_subject,
                "mail_body_preview": m.mail_body_preview,
                "attachments": m.attachments,
                "status": m.status,
                "classification": m.classification,
                "confidence": m.confidence,
                "reason": m.reason,
                "classified_by": m.classified_by,
                "received_at": m.received_at.isoformat() if m.received_at else None,
            }
            for m in pending
        ],
    }


# ── 人工审核邮件 ──


@mail_router.post("/{mail_id}/review", response_model=dict)
async def review_mail(
    mail_id: str,
    action: str,  # "accept" | "reject"
    db: AsyncSession = Depends(_get_db),
):
    """人工审核邮件：accept（进入管线）或 reject（拒绝）。"""
    result = await db.execute(select(PendingMail).where(PendingMail.id == mail_id))
    mail = result.scalar_one_or_none()
    if not mail:
        raise HTTPException(status_code=404, detail="Mail not found")

    if action == "accept":
        mail.status = "auto_accepted"
        mail.classified_by = "human"

        # 查找/创建 Part & Task，发布 REPORT_RECEIVED
        part_no = mail.part_no or "UNKNOWN"
        part_result = await db.execute(select(Part).where(Part.part_no == part_no))
        part = part_result.scalar_one_or_none()
        if not part:
            part = Part(part_no=part_no, part_name=f"人工审核-{part_no}", part_type="电子零件", supplier=mail.mail_from, project_code="mail")
            db.add(part)
            await db.flush()

        task = ApprovalTask(part_id=part.id, state="CREATED")
        db.add(task)
        await db.flush()
        mail.task_id = task.id

        await event_bus.publish(Event(
            type=EventType.REPORT_RECEIVED,
            task_id=task.id,
            source="mail_human_review",
            payload={
                "task_id": task.id,
                "part_id": part.id,
                "part_no": part_no,
                "mail_from": mail.mail_from,
                "mail_subject": mail.mail_subject,
                "filename": mail.mail_subject or "mail_report",
                "storage_path": f"ots-reports/{task.id}/mail_{mail.id}",
                "report_text": mail.mail_body_preview or "",
            },
        ))

        event_log = EventLog(
            task_id=task.id,
            event_type=EventType.MAIL_CLASSIFIED,
            source="mail_human_review",
            payload={"mail_id": mail.id, "action": "accepted"},
        )
        db.add(event_log)

    elif action == "reject":
        mail.status = "auto_rejected"
        mail.classified_by = "human"
        event_log = EventLog(
            task_id="__none__",
            event_type=EventType.MAIL_REJECTED,
            source="mail_human_review",
            payload={"mail_id": mail.id, "action": "rejected"},
        )
        db.add(event_log)

    else:
        raise HTTPException(status_code=400, detail="action must be 'accept' or 'reject'")

    await db.commit()
    return {"mail_id": mail.id, "status": mail.status, "action": action}
