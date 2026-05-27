"""OTS Approval Helping Agent — Report Parser Agent (DeepSeek V4 + confidence)."""

import json
from typing import Optional

from app.agents.base import BaseAgent
from app.services.llm import llm
from app.services.sp_loader import load_sp


class ReportParser(BaseAgent):
    name = "parser"
    CONFIDENCE_THRESHOLD_AUTO = 0.85
    CONFIDENCE_THRESHOLD_LOW = 0.75

    def __init__(self):
        self._system_prompt = load_sp("parser")

    def _parse_llm_response(self, raw: str) -> Optional[dict]:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _compute_overall_confidence(self, confidences: dict[str, float]) -> float:
        if not confidences:
            return 0.0
        return sum(confidences.values()) / len(confidences)

    def _is_auto_approve(self, overall: float) -> bool:
        return overall >= self.CONFIDENCE_THRESHOLD_AUTO

    def _find_low_confidence_fields(self, confidences: dict[str, float]) -> dict[str, float]:
        return {k: v for k, v in confidences.items() if v < self.CONFIDENCE_THRESHOLD_LOW}

    def _apply_corrections(self, raw: dict) -> dict:
        corrected = {}
        for key, value in raw.items():
            if key == "field_confidence":
                continue
            if isinstance(value, str):
                value = value.strip()
                if key == "part_no":
                    value = value.upper()
                if key == "test_type":
                    value = value.upper()
                if key == "test_date":
                    value = value.strip()
            corrected[key] = value
        return corrected

    async def _call_llm(self, text_content: str) -> str:
        return await llm.chat(
            system_prompt=self._system_prompt,
            user_message=f"请解析以下测试报告内容：\n\n{text_content[:4000]}",
            temperature=0.1,
        )

    async def process(self, payload: dict) -> dict:
        task_id = payload.get("task_id", "")
        part_no = payload.get("part_no", "")
        filename = payload.get("filename", "")
        storage_path = payload.get("storage_path", "")

        report_text = payload.get("report_text", f"[Mock content for {filename}]")

        try:
            raw_response = await self._call_llm(report_text)
        except Exception as e:
            return {"status": "error", "task_id": task_id, "error": str(e)}

        parsed = self._parse_llm_response(raw_response)
        if parsed is None:
            return {"status": "error", "task_id": task_id, "error": "LLM returned non-JSON"}

        field_conf = parsed.pop("field_confidence", {})
        overall = self._compute_overall_confidence(field_conf)
        low_fields = self._find_low_confidence_fields(field_conf)

        corrected = self._apply_corrections(parsed)

        result = {
            "part_no": corrected.get("part_no", part_no),
            "software_version_F1C1": corrected.get("software_version_F1C1", "非软件测试报告，无软件版本信息"),
            "software_version_F1C2": corrected.get("software_version_F1C2", "非软件测试报告，无软件版本信息"),
            "software_version_vendor_MCU": corrected.get("software_version_vendor_MCU", "非软件测试报告，无软件版本信息"),
            "part_name": corrected.get("part_name", "unknown"),
            "test_type": corrected.get("test_type", "unknown"),
            "test_date": corrected.get("test_date", "unknown"),
            "test_result": corrected.get("test_result", "unknown"),
            "lab_name": corrected.get("lab_name", "unknown"),
            "standard": corrected.get("standard"),
            "material": corrected.get("material"),
            "material_spec": corrected.get("material_spec"),
            "tensile_strength": corrected.get("tensile_strength"),
            "hardness": corrected.get("hardness"),
            "coating": corrected.get("coating"),
            "notes": corrected.get("notes", ""),
            "raw_fields": parsed,
            "confidence_per_field": field_conf,
            "overall_confidence": round(overall, 4),
            "low_confidence_fields": low_fields,
        }

        status = "ok" if self._is_auto_approve(overall) else "pending_human"

        return {
            "status": status,
            "task_id": task_id,
            "storage_path": storage_path,
            "parsed": result,
        }