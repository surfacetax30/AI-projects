"""MailGateway 重构测试 — 覆盖率: 规则引擎(6单元) + 批处理/LLM/降级/审核(4集成)"""

import os
import sys
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="module")
def module_env():
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest_asyncio.fixture
async def app_client(module_env):
    from app.db.session import engine
    from app.db.models import Base
    from app.main import app

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ═══════════════════════════════════════════════════
# 单元测试: 规则引擎 (6 条)
# ═══════════════════════════════════════════════════


class TestRuleEngine:
    @pytest.fixture(scope="class")
    def gateway(self):
        from app.agents.mail_gateway import MailGateway

        return MailGateway()

    def test_1_whitelist_full_match_auto_accepted(self, gateway):
        mails = [{"id": "m1", "mail_from": "vendor1@example.com", "mail_subject": "OTS-2026-0099 DV测试报告", "attachments": ["DV测试报告.pdf"]}]
        results = gateway._rule_engine_classify(mails)
        assert results[0]["rule_status"] == "auto_accepted"
        assert results[0]["rule_reason"] == "whitelist_full_match"

    def test_2_blacklist_subject_auto_rejected(self, gateway):
        mails = [{"id": "m2", "mail_from": "admin@example.com", "mail_subject": "5月团建通知", "attachments": []}]
        results = gateway._rule_engine_classify(mails)
        assert results[0]["rule_status"] == "auto_rejected"
        assert results[0]["rule_reason"] == "blacklist_subject"

    def test_3_blacklist_sender_auto_rejected(self, gateway):
        mails = [{"id": "m3", "mail_from": "noreply@company.com", "mail_subject": "OTS测试报告", "attachments": ["test.pdf"]}]
        results = gateway._rule_engine_classify(mails)
        assert results[0]["rule_status"] == "auto_rejected"
        assert results[0]["rule_reason"] == "blacklist_sender"

    def test_4_known_sender_unclear_subject_to_llm(self, gateway):
        mails = [{"id": "m4", "mail_from": "vendor1@example.com", "mail_subject": "关于上次的测试", "attachments": ["result.docx"]}]
        results = gateway._rule_engine_classify(mails)
        assert results[0]["rule_status"] == "to_llm"
        assert results[0]["rule_reason"] == "known_sender_unclear_subject"

    def test_5_unknown_sender_report_subject_to_llm(self, gateway):
        mails = [{"id": "m5", "mail_from": "new_vendor@xyz.cn", "mail_subject": "OTS-2026-0156 PV测试报告提交", "attachments": ["报告.pdf"]}]
        results = gateway._rule_engine_classify(mails)
        assert results[0]["rule_status"] == "to_llm"
        assert results[0]["rule_reason"] == "unknown_sender_report_subject"

    def test_6_no_rule_match_to_llm(self, gateway):
        mails = [{"id": "m6", "mail_from": "random@qq.com", "mail_subject": "你好", "attachments": []}]
        results = gateway._rule_engine_classify(mails)
        assert results[0]["rule_status"] == "to_llm"
        assert results[0]["rule_reason"] == "no_rule_match"


# ═══════════════════════════════════════════════════
# 辅助: 往 DB 写 test data
# ═══════════════════════════════════════════════════

async def _seed_mail(client, mail_from, mail_subject, mail_body_preview="", attachments=None):
    resp = await client.post("/api/webhooks/mail", json={
        "mail_from": mail_from,
        "mail_subject": mail_subject,
        "mail_body_preview": mail_body_preview,
        "part_no": "",
        "attachments": attachments or [],
    })
    assert resp.status_code == 200
    return resp.json()["mail_id"]


# ═══════════════════════════════════════════════════
# 集成测试: 批处理流程 (4 条)
# ═══════════════════════════════════════════════════


class TestBatchProcess:
    @pytest_asyncio.fixture
    async def client(self, app_client):
        return app_client

    @pytest.mark.asyncio
    async def test_7_rule_engine_e2e_direct_pipeline(self, client):
        _ = await _seed_mail(client, "vendor1@example.com", "OTS-2026-0099 DV测试报告", "", ["DV测试报告.pdf"])
        _ = await _seed_mail(client, "vendor1@example.com", "OTS-2026-0100 认可测试报告", "", ["report.pdf"])
        _ = await _seed_mail(client, "admin@example.com", "5月团建通知", "")

        resp = await client.post("/api/mail/batch-process")
        assert resp.status_code == 200
        data = resp.json()

        assert data["total"] == 3
        assert data["auto_accepted"] == 2
        assert data["auto_rejected"] == 1
        assert data["pending_human"] == 0

        for r in data["results"]:
            assert r["status"] in ("auto_accepted", "auto_rejected")

    @pytest.mark.asyncio
    @pytest.mark.skipif("DEEPSEEK_API_KEY" not in os.environ, reason="需要 DeepSeek API Key")
    async def test_8_e2e_with_llm_classification(self, client):
        """真实 LLM 调用 — 仅在有 Key 时运行"""
        mail_id = await _seed_mail(
            client,
            "new_vendor@xyz.cn",
            "OTS-2026-0156 PV测试报告提交",
            "附件为前副车架焊接总成的 PV 生产验证测试报告，测试日期 2026-04-20，结论 PASS。",
            ["PV测试报告.pdf"],
        )

        resp = await client.post("/api/mail/batch-process")
        assert resp.status_code == 200
        data = resp.json()

        matched = [r for r in data["results"] if r["mail_id"] == mail_id]
        assert len(matched) == 1
        assert matched[0]["classified_by"] == "llm"

    @pytest.mark.asyncio
    async def test_9_llm_failure_degradation(self, client):
        from unittest.mock import AsyncMock, patch

        mail_id = await _seed_mail(
            client,
            "new_vendor@xyz.cn",
            "OTS-2026-0156 PV测试报告提交",
            "测试报告正文",
            ["PV测试报告.pdf"],
        )

        async def _mock_chat_fail(*args, **kwargs):
            raise Exception("Mocked LLM timeout")

        with patch("app.services.llm.llm.chat", side_effect=_mock_chat_fail):
            resp = await client.post("/api/mail/batch-process")
            assert resp.status_code == 200
            data = resp.json()

            matched = [r for r in data["results"] if r["mail_id"] == mail_id]
            assert len(matched) == 1
            assert matched[0]["status"] == "pending_human"

    @pytest.mark.asyncio
    async def test_10_human_review_loop(self, client):
        from app.events.types import EventType

        mail_id = await _seed_mail(
            client,
            "new_vendor@xyz.cn",
            "OTS-2026-0200 测试报告",
            "附件为后扭力梁总成 DV 测试报告",
            ["DV测试报告.pdf"],
        )

        # Step1: batch-process → pending_human（因为非白名单，要靠 LLM；但 LLM 可能失败 → pending_human）
        # 强制设为 pending_human 状态
        from app.db.session import async_session
        from sqlalchemy import select, update
        from app.db.models import PendingMail

        async with async_session() as db:
            result = await db.execute(select(PendingMail).where(PendingMail.id == mail_id))
            mail = result.scalar_one()
            mail.status = "pending_human"
            mail.classification = "不确定"
            mail.reason = "LLM 无法判定"
            mail.classified_by = "llm"
            await db.commit()

        # Step2: GET /api/mail/pending → 返回该邮件
        resp = await client.get("/api/mail/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        pending_ids = [m["id"] for m in data["mails"]]
        assert mail_id in pending_ids

        # Step3: accept
        resp = await client.post(f"/api/mail/{mail_id}/review?action=accept")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "auto_accepted"
        assert data["action"] == "accept"

        # Step4: 验证 Part + Task 已创建
        from app.db.session import async_session
        from sqlalchemy import select, update
        from app.db.models import PendingMail, ApprovalTask

        async with async_session() as db:
            result = await db.execute(select(PendingMail).where(PendingMail.id == mail_id))
            mail = result.scalar_one()
            assert mail.classified_by == "human"
            assert mail.task_id is not None

            task_result = await db.execute(select(ApprovalTask).where(ApprovalTask.id == mail.task_id))
            task = task_result.scalar_one()
            assert task.state == "CREATED"

        # Step5: 创建另一封 pending_human 邮件并 reject
        mail_id_2 = await _seed_mail(
            client,
            "spam@test.cn",
            "广告推广邮件",
            "这不是测试报告",
        )
        async with async_session() as db:
            result = await db.execute(select(PendingMail).where(PendingMail.id == mail_id_2))
            mail2 = result.scalar_one()
            mail2.status = "pending_human"
            await db.commit()

        resp = await client.post(f"/api/mail/{mail_id_2}/review?action=reject")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "auto_rejected"

        # Step6: GET /api/mail/pending → 之前 pending_human 的都处理完了
        resp = await client.get("/api/mail/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert mail_id not in [m["id"] for m in data["mails"]]
        assert mail_id_2 not in [m["id"] for m in data["mails"]]

        # Step7: 验证 reject 的事件日志
        from app.db.models import EventLog
        async with async_session() as db:
            result = await db.execute(
                select(EventLog).where(
                    EventLog.event_type == EventType.MAIL_REJECTED,
                    EventLog.payload["mail_id"].as_string() == mail_id_2,
                )
            )
            event = result.scalar_one_or_none()
            assert event is not None
