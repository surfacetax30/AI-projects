"""OTS Approval Helping Agent — Pydantic request/response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class PartCreate(BaseModel):
    part_no: str
    part_name: str
    part_type: str
    supplier: str
    project_code: str
    is_new: bool = True
    parent_part_no: Optional[str] = None

    @field_validator("part_no")
    @classmethod
    def strip_part_no(cls, v: str) -> str:
        return v.strip()


class PartResponse(BaseModel):
    id: str
    part_no: str
    part_name: str
    part_type: str
    supplier: str
    project_code: str
    is_new: bool
    parent_part_no: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskResponse(BaseModel):
    id: str
    part_id: str
    state: str
    pending_human_action: Optional[str] = None
    human_action_deadline: Optional[datetime] = None
    overall_confidence: Optional[float] = None
    anomalies: Optional[dict] = None
    missing_docs: Optional[list] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ParsedReportResponse(BaseModel):
    id: str
    task_id: str
    part_no: str
    test_type: str
    test_date: str
    lab_name: str
    raw_fields: dict
    confidence_per_field: dict
    overall_confidence: float
    storage_path: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TimelineEntry(BaseModel):
    event: str
    detail: str
    time: str


class TaskDetailResponse(BaseModel):
    task: TaskResponse
    part: PartResponse
    reports: list[ParsedReportResponse]
    timeline: list[TimelineEntry]


class WebhookMailPayload(BaseModel):
    mail_from: str
    mail_subject: str
    mail_body_preview: str = ""
    part_no: str
    attachments: list[str] = []


class ReportUploadResponse(BaseModel):
    storage_path: str
    filename: str


class MailClassificationResult(BaseModel):
    mail_id: str
    mail_from: str
    mail_subject: str
    status: str
    classification: Optional[str] = None
    part_no: Optional[str] = None
    confidence: Optional[float] = None
    reason: Optional[str] = None
    classified_by: Optional[str] = None


class MailBatchReport(BaseModel):
    batch_id: str
    total: int
    auto_accepted: int
    auto_rejected: int
    pending_human: int
    results: list[MailClassificationResult]