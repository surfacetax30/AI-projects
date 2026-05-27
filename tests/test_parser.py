import pytest
import json
from unittest.mock import MagicMock, patch, AsyncMock


MOCK_LLM_RESPONSE = json.dumps({
    "part_no": "OTS-2026-001",
    "test_type": "DV",
    "test_date": "2026-05-15",
    "test_result": "PASS",
    "lab_name": "国家汽车零部件检测中心",
    "standard": "GB/T 1234.5-2023",
    "field_confidence": {
        "part_no": 0.95,
        "test_type": 0.88,
        "test_date": 0.92,
        "test_result": 0.97,
        "lab_name": 0.75,
        "standard": 0.91,
    },
})


MOCK_LLM_RESPONSE_LOW_CONFIDENCE = json.dumps({
    "part_no": "OTS-2026-002",
    "test_type": "EMC",
    "test_date": "unknown",
    "test_result": "PASS",
    "lab_name": "unknown",
    "field_confidence": {
        "part_no": 0.70,
        "test_type": 0.82,
        "test_date": 0.30,
        "test_result": 0.65,
        "lab_name": 0.25,
    },
})


MOCK_LLM_RESPONSE_INVALID = "这不是一个JSON，解析失败"


class TestParserExtraction:
    @pytest.fixture
    def parser(self):
        from app.agents.parser import ReportParser

        return ReportParser()

    def test_parse_json_response(self, parser):
        result = parser._parse_llm_response(MOCK_LLM_RESPONSE)
        assert result["part_no"] == "OTS-2026-001"
        assert result["test_type"] == "DV"
        assert result["field_confidence"]["part_no"] == 0.95

    def test_parse_invalid_response_returns_none(self, parser):
        result = parser._parse_llm_response(MOCK_LLM_RESPONSE_INVALID)
        assert result is None

    def test_compute_overall_confidence(self, parser):
        confidences = {"part_no": 0.95, "test_type": 0.88, "test_date": 0.92}
        overall = parser._compute_overall_confidence(confidences)
        assert 0.85 < overall < 1.0

    def test_overall_above_threshold_auto(self, parser):
        assert parser._is_auto_approve(0.92) is True

    def test_overall_below_threshold_human_pending(self, parser):
        assert parser._is_auto_approve(0.70) is False

    def test_confidence_at_threshold_boundary(self, parser):
        assert parser._is_auto_approve(0.85) is True
        assert parser._is_auto_approve(0.849) is False

    def test_apply_corrections(self, parser):
        raw = {"part_no": " ots-2026-001 ", "test_type": "Dv"}
        corrected = parser._apply_corrections(raw)
        assert corrected["part_no"] == "OTS-2026-001"
        assert corrected["test_type"] == "DV"

    def test_field_level_anomaly_detected(self, parser):
        confidences = {"part_no": 0.35, "test_type": 0.88}
        anomalies = parser._find_low_confidence_fields(confidences)
        assert "part_no" in anomalies

    def test_no_anomaly_when_all_high(self, parser):
        confidences = {"part_no": 0.95, "test_type": 0.92}
        anomalies = parser._find_low_confidence_fields(confidences)
        assert len(anomalies) == 0

    @pytest.mark.asyncio
    async def test_process_high_confidence(self, parser):
        with patch.object(parser, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = MOCK_LLM_RESPONSE
            result = await parser.process({
                "task_id": "task001",
                "part_no": "OTS-2026-001",
                "filename": "report.pdf",
                "storage_path": "ots-reports/task001/report.pdf",
            })
        assert result["status"] == "ok"
        assert result["parsed"]["part_no"] == "OTS-2026-001"
        assert result["parsed"]["overall_confidence"] > 0.85

    @pytest.mark.asyncio
    async def test_process_low_confidence(self, parser):
        with patch.object(parser, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = MOCK_LLM_RESPONSE_LOW_CONFIDENCE
            result = await parser.process({
                "task_id": "task002",
                "part_no": "OTS-2026-002",
                "filename": "report_bad.pdf",
                "storage_path": "ots-reports/task002/report_bad.pdf",
            })
        assert result["status"] == "pending_human"
        assert result["parsed"]["overall_confidence"] < 0.85

    @pytest.mark.asyncio
    async def test_process_llm_failure(self, parser):
        with patch.object(parser, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = MOCK_LLM_RESPONSE_INVALID
            result = await parser.process({
                "task_id": "task003",
                "part_no": "OTS-2026-003",
                "filename": "broken.pdf",
                "storage_path": "ots-reports/task003/broken.pdf",
            })
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_process_with_empty_llm_response(self, parser):
        with patch.object(parser, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = ""
            result = await parser.process({
                "task_id": "task004",
                "part_no": "OTS-2026-004",
                "filename": "empty.pdf",
                "storage_path": "ots-reports/task004/empty.pdf",
            })
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_process_missing_field_confidence(self, parser):
        with patch.object(parser, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = json.dumps({
                "part_no": "OTS-2026-005",
                "test_type": "DV",
                "test_date": "2026-05-15",
                "test_result": "PASS",
                "lab_name": "某实验室",
                "standard": "GB/T 1234",
            })
            result = await parser.process({
                "task_id": "task005",
                "part_no": "OTS-2026-005",
                "filename": "no_conf.pdf",
                "storage_path": "ots-reports/task005/no_conf.pdf",
            })
        assert result["status"] == "pending_human"
        assert result["parsed"]["overall_confidence"] == 0.0