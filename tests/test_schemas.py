import pytest
from datetime import datetime


class TestPartSchemas:
    def test_part_create_valid(self):
        from app.schemas.tasks import PartCreate

        data = PartCreate(
            part_no="OTS-2026-001",
            part_name="前副车架焊接总成",
            part_type="金属支架",
            supplier="XX精工制造有限公司",
            project_code="P2026-SUV",
        )
        assert data.part_no == "OTS-2026-001"
        assert data.is_new is True

    def test_part_create_strips_whitespace(self):
        from app.schemas.tasks import PartCreate

        data = PartCreate(
            part_no=" OTS-2026-001 ",
            part_name="前副车架焊接总成",
            part_type="金属支架",
            supplier="XX精工制造有限公司",
            project_code="P2026-SUV",
        )
        assert data.part_no == "OTS-2026-001"

    def test_part_response_serialization(self):
        from app.schemas.tasks import PartResponse

        resp = PartResponse(
            id="a1b2c3d4e5f6",
            part_no="OTS-2026-001",
            part_name="前副车架",
            part_type="金属支架",
            supplier="XX精工",
            project_code="P2026-SUV",
            is_new=True,
            created_at=datetime(2026, 5, 27, 10, 0, 0),
        )
        d = resp.model_dump(mode="json")
        assert d["id"] == "a1b2c3d4e5f6"
        assert d["is_new"] is True


class TestTaskSchemas:
    def test_task_response_state_default(self):
        from app.schemas.tasks import TaskResponse

        resp = TaskResponse(
            id="task001",
            part_id="part001",
            state="CREATED",
            created_at=datetime(2026, 5, 27, 10, 0, 0),
        )
        assert resp.state == "CREATED"
        assert resp.pending_human_action is None

    def test_task_detail_response(self):
        from app.schemas.tasks import TaskResponse, TaskDetailResponse, PartResponse

        part = PartResponse(
            id="part001",
            part_no="OTS-001",
            part_name="前副车架",
            part_type="金属支架",
            supplier="XX",
            project_code="P2026",
            is_new=True,
            created_at=datetime(2026, 5, 27, 10, 0, 0),
        )
        task = TaskResponse(
            id="task001",
            part_id="part001",
            state="DATA_ORGANIZING",
            pending_human_action="H1",
            created_at=datetime(2026, 5, 27, 10, 0, 0),
        )
        detail = TaskDetailResponse(
            task=task,
            part=part,
            reports=[],
            timeline=[],
        )
        d = detail.model_dump(mode="json")
        assert d["task"]["state"] == "DATA_ORGANIZING"
        assert d["reports"] == []


class TestWebhookSchema:
    def test_webhook_mail_payload(self):
        from app.schemas.tasks import WebhookMailPayload

        data = WebhookMailPayload(
            mail_from="vendor1@example.com",
            mail_subject="OTS-2026-001 OTS认可测试报告",
            part_no="OTS-2026-001",
            attachments=["ots-reports/task001/report.pdf"],
        )
        assert data.part_no == "OTS-2026-001"
        assert len(data.attachments) == 1

    def test_webhook_mail_attachments_optional(self):
        from app.schemas.tasks import WebhookMailPayload

        data = WebhookMailPayload(
            mail_from="vendor1@example.com",
            mail_subject="OTS认可测试报告",
            part_no="OTS-2026-001",
        )
        assert data.attachments == []


class TestReportUploadSchema:
    def test_report_upload_response(self):
        from app.schemas.tasks import ReportUploadResponse

        resp = ReportUploadResponse(
            storage_path="ots-reports/task001/report.pdf",
            filename="report.pdf",
        )
        d = resp.model_dump(mode="json")
        assert d["filename"] == "report.pdf"