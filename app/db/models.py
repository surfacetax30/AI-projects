"""OTS Approval Helping Agent — ORM models (part, task, report, event_log)."""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, JSON, Integer, Float, Text, Enum as SAEnum
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
    part_type: Mapped[str] = mapped_column(String(64), index=True)         # e.g. 域控制器, 金属支架
    supplier: Mapped[str] = mapped_column(String(256))
    project_code: Mapped[str] = mapped_column(String(64))
    is_new: Mapped[bool] = mapped_column(default=True)                     # True=新零件, False=改款
    parent_part_no: Mapped[str] = mapped_column(String(64), nullable=True) # 改款来源
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ApprovalTask(Base):
    __tablename__ = "approval_tasks"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    part_id: Mapped[str] = mapped_column(String(12), index=True)
    state: Mapped[str] = mapped_column(String(32), default="CREATED", index=True)
    # CREATED → TEST_APPLYING → TESTING → REPORT_COLLECTING → DATA_ORGANIZING → SIGNING → CLOSED
    pending_human_action: Mapped[str | None] = mapped_column(String(64), nullable=True)  # flag, not state
    human_action_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    anomalies: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    missing_docs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ParsedReport(Base):
    __tablename__ = "parsed_reports"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    task_id: Mapped[str] = mapped_column(String(12), index=True)
    part_no: Mapped[str] = mapped_column(String(64), index=True)
    test_type: Mapped[str] = mapped_column(String(32), index=True)       # EMC/DV/HIL/...
    test_date: Mapped[str] = mapped_column(String(32))
    lab_name: Mapped[str] = mapped_column(String(256))
    raw_fields: Mapped[dict] = mapped_column(JSON)                       # all extracted fields
    confidence_per_field: Mapped[dict] = mapped_column(JSON)
    overall_confidence: Mapped[float] = mapped_column(Float)
    storage_path: Mapped[str] = mapped_column(String(512))               # MinIO object path
    correction_count: Mapped[int] = mapped_column(Integer, default=0)    # PE correction history count
    correction_log: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(12), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
