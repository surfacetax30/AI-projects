import pytest


class TestMailGatewayFiltering:
    @pytest.fixture
    def gateway(self):
        from app.agents.mail_gateway import MailGateway

        return MailGateway()

    def test_valid_sender_passes(self, gateway):
        assert "vendor1@example.com" in gateway.VALID_SENDERS

    def test_unknown_sender_rejected(self, gateway):
        assert "hacker@evil.com" not in gateway.VALID_SENDERS

    def test_valid_subject_matches(self, gateway):
        assert gateway._subject_matches("OTS-2026-001 OTS认可测试报告") is True

    def test_spam_subject_rejected(self, gateway):
        assert gateway._subject_matches("理财产品推荐") is False

    def test_pdf_attachment_allowed(self, gateway):
        assert gateway._attachment_valid("report.pdf") is True

    def test_exe_attachment_rejected(self, gateway):
        assert gateway._attachment_valid("virus.exe") is False

    def test_empty_subject_rejected(self, gateway):
        assert gateway._subject_matches("") is False

    def test_should_accept_valid_mail(self, gateway):
        result = gateway._should_accept(
            sender="vendor1@example.com",
            subject="OTS-2026-001 测试报告",
            attachments=["report.pdf"],
        )
        assert result is True

    def test_should_reject_unknown_sender(self, gateway):
        result = gateway._should_accept(
            sender="spam@evil.com",
            subject="OTS-2026-001 测试报告",
            attachments=["report.pdf"],
        )
        assert result is False

    def test_should_reject_bad_subject(self, gateway):
        result = gateway._should_accept(
            sender="vendor1@example.com",
            subject="广告推广",
            attachments=["report.pdf"],
        )
        assert result is False

    def test_can_accept_without_attachments(self, gateway):
        result = gateway._should_accept(
            sender="vendor1@example.com",
            subject="OTS认可测试通知",
            attachments=[],
        )
        assert result is True

    def test_partial_subject_match_works(self, gateway):
        assert gateway._subject_matches("关于OTS认可测试报告的提交事宜") is True

    def test_extract_part_no_from_subject(self, gateway):
        part_no = gateway._extract_part_no("OTS-2026-001 OTS认可测试报告")
        assert part_no == "OTS-2026-001"

    def test_extract_part_no_not_found(self, gateway):
        part_no = gateway._extract_part_no("广告推广")
        assert part_no is None

    def test_subject_matches_with_none(self, gateway):
        result = gateway._subject_matches(None)
        assert result is False