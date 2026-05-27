import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.session import Base


@pytest_asyncio.fixture
async def client():
    from app.db.session import engine
    from app.main import app

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


class TestTasksAPI:
    @pytest.mark.asyncio
    async def test_get_task_detail(self, client):
        create_resp = await client.post("/api/parts", json={
            "part_no": "OTS-2026-010",
            "part_name": "前副车架",
            "part_type": "金属支架",
            "supplier": "XX精工",
            "project_code": "P2026",
        })
        task_id = create_resp.json()["task"]["id"]

        response = await client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["task"]["state"] == "CREATED"
        assert data["part"]["part_no"] == "OTS-2026-010"

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, client):
        response = await client.get("/api/tasks/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_webhook_mail(self, client):
        create_resp = await client.post("/api/parts", json={
            "part_no": "OTS-2026-011",
            "part_name": "后副车架",
            "part_type": "金属支架",
            "supplier": "YY精工",
            "project_code": "P2026",
        })
        task_id = create_resp.json()["task"]["id"]

        response = await client.post("/api/webhooks/mail", json={
            "mail_from": "vendor1@example.com",
            "mail_subject": "OTS-2026-011 OTS认可测试报告",
            "part_no": "OTS-2026-011",
            "attachments": ["ots-reports/ots2026011/report.pdf"],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["task_id"] == task_id

    @pytest.mark.asyncio
    async def test_webhook_mail_part_not_found(self, client):
        response = await client.post("/api/webhooks/mail", json={
            "mail_from": "vendor1@example.com",
            "mail_subject": "OTS-XXXX OTS认可测试报告",
            "part_no": "OTS-XXXX",
        })
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_report_upload(self, client):
        create_resp = await client.post("/api/parts", json={
            "part_no": "OTS-2026-012",
            "part_name": "线束总成",
            "part_type": "电子零件",
            "supplier": "ZZ电子",
            "project_code": "P2026",
        })
        task_id = create_resp.json()["task"]["id"]

        test_file_content = b"%PDF-1.4 mock report content"
        files = {"file": ("test_report.pdf", test_file_content, "application/pdf")}

        response = await client.post(
            f"/api/tasks/{task_id}/reports",
            files=files,
        )
        assert response.status_code == 200
        data = response.json()
        assert "storage_path" in data
        assert "filename" in data
        assert data["filename"] == "test_report.pdf"

    @pytest.mark.asyncio
    async def test_report_upload_task_not_found(self, client):
        files = {"file": ("test.pdf", b"content", "application/pdf")}
        response = await client.post("/api/tasks/nonexistent/reports", files=files)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_upload_without_file_returns_error(self, client):
        create_resp = await client.post("/api/parts", json={
            "part_no": "OTS-2026-014",
            "part_name": "无文件测试",
            "part_type": "金属支架",
            "supplier": "测试",
            "project_code": "P2026",
        })
        task_id = create_resp.json()["task"]["id"]
        response = await client.post(f"/api/tasks/{task_id}/reports")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_upload_task_id_overflow(self, client):
        short_id = ""
        response = await client.post(f"/api/tasks/{short_id}/reports")
        assert response.status_code in (404, 405)
        long_id = "x" * 256
        response = await client.post(f"/api/tasks/{long_id}/reports")
        assert response.status_code in (404, 422)

    @pytest.mark.asyncio
    async def test_upload_triggers_event(self, client):
        create_resp = await client.post("/api/parts", json={
            "part_no": "OTS-2026-013",
            "part_name": "域控制器",
            "part_type": "电子零件",
            "supplier": "AA科技",
            "project_code": "P2026",
        })
        task_id = create_resp.json()["task"]["id"]

        files = {"file": ("report.pdf", b"mock pdf content", "application/pdf")}
        response = await client.post(f"/api/tasks/{task_id}/reports", files=files)
        assert response.status_code == 200

        task_resp = await client.get(f"/api/tasks/{task_id}")
        data = task_resp.json()
        assert len(data["timeline"]) >= 1
        assert data["timeline"][0]["event"] == "report.received"