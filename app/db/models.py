"""OTS Approval Helping Agent — ORM models (part, task, report, event_log, checklist)."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, JSON, Integer, Float, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.session import Base


def _new_id():
    return uuid.uuid4().hex[:12]


class Part(Base):
    __tablename__ = "parts"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    part_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    part_name: Mapped[str] = mapped_column(String(256))
    part_type: Mapped[str] = mapped_column(String(64), index=True)
    supplier: Mapped[str] = mapped_column(String(256))
    project_code: Mapped[str] = mapped_column(String(64))
    is_new: Mapped[bool] = mapped_column(default=True)
    parent_part_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ApprovalTask(Base):
    __tablename__ = "approval_tasks"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    part_id: Mapped[str] = mapped_column(String(12), index=True)
    state: Mapped[str] = mapped_column(String(32), default="CREATED", index=True)
    pending_human_action: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    human_action_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    overall_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    anomalies: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    missing_docs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ParsedReport(Base):
    __tablename__ = "parsed_reports"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    task_id: Mapped[str] = mapped_column(String(12), index=True)
    part_no: Mapped[str] = mapped_column(String(64), index=True)
    test_type: Mapped[str] = mapped_column(String(32), index=True)
    test_date: Mapped[str] = mapped_column(String(32))
    lab_name: Mapped[str] = mapped_column(String(256))
    raw_fields: Mapped[dict] = mapped_column(JSON)
    confidence_per_field: Mapped[dict] = mapped_column(JSON)
    overall_confidence: Mapped[float] = mapped_column(Float)
    storage_path: Mapped[str] = mapped_column(String(512))
    correction_count: Mapped[int] = mapped_column(Integer, default=0)
    correction_log: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(12), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64))
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ChecklistTemplate(Base):
    __tablename__ = "checklist_templates"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    part_type: Mapped[str] = mapped_column(String(64), index=True)
    items: Mapped[list] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PendingMail(Base):
    __tablename__ = "pending_mails"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    mail_from: Mapped[str] = mapped_column(String(256))
    mail_subject: Mapped[str] = mapped_column(String(512))
    mail_body_preview: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    classification: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    classified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    classified_by: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    part_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    batch_id: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
