import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.sql import text

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


class TestPartsAPI:
    @pytest.mark.asyncio
    async def test_create_part_creates_task(self, client):
        response = await client.post("/api/parts", json={
            "part_no": "OTS-2026-001",
            "part_name": "前副车架焊接总成",
            "part_type": "金属支架",
            "supplier": "XX精工制造有限公司",
            "project_code": "P2026-SUV",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["part"]["part_no"] == "OTS-2026-001"
        assert data["part"]["is_new"] is True
        assert "task" in data
        assert data["task"]["state"] == "CREATED"

    @pytest.mark.asyncio
    async def test_create_part_strips_whitespace(self, client):
        response = await client.post("/api/parts", json={
            "part_no": " OTS-2026-002 ",
            "part_name": "测试零件",
            "part_type": "域控制器",
            "supplier": "测试供应商",
            "project_code": "P2026-002",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["part"]["part_no"] == "OTS-2026-002"

    @pytest.mark.asyncio
    async def test_list_parts(self, client):
        await client.post("/api/parts", json={
            "part_no": "OTS-2026-003",
            "part_name": "零件A",
            "part_type": "金属支架",
            "supplier": "供应商A",
            "project_code": "P2026-003",
        })
        await client.post("/api/parts", json={
            "part_no": "OTS-2026-004",
            "part_name": "零件B",
            "part_type": "域控制器",
            "supplier": "供应商B",
            "project_code": "P2026-004",
        })

        response = await client.get("/api/parts")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_get_part_detail(self, client):
        create_resp = await client.post("/api/parts", json={
            "part_no": "OTS-2026-005",
            "part_name": "零件C",
            "part_type": "塑料件",
            "supplier": "供应商C",
            "project_code": "P2026-005",
        })
        part_id = create_resp.json()["part"]["id"]

        response = await client.get(f"/api/parts/{part_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["part_no"] == "OTS-2026-005"
        assert len(data["tasks"]) == 1

    @pytest.mark.asyncio
    async def test_get_part_not_found(self, client):
        response = await client.get("/api/parts/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_duplicate_part_no_returns_error(self, client):
        await client.post("/api/parts", json={
            "part_no": "OTS-2026-DUP",
            "part_name": "零件A",
            "part_type": "金属支架",
            "supplier": "供应商A",
            "project_code": "P2026-DUP",
        })
        response = await client.post("/api/parts", json={
            "part_no": "OTS-2026-DUP",
            "part_name": "零件B",
            "part_type": "域控制器",
            "supplier": "供应商B",
            "project_code": "P2026-DUP",
        })
        assert response.status_code in (400, 409, 422)