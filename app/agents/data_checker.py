"""OTS Approval Helping Agent — Data Checker Agent (checklist-based completeness)."""

from typing import Any

from app.agents.base import BaseAgent

DEFAULT_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "金属支架": [
        {"code": "MAT-01", "name": "材质证明", "required": True},
        {"code": "DIM-01", "name": "尺寸检测报告", "required": True},
        {"code": "DIM-02", "name": "关键尺寸检测记录", "required": False},
        {"code": "WEL-01", "name": "焊接强度测试报告", "required": True},
        {"code": "FUN-01", "name": "功能测试报告", "required": True},
        {"code": "FUN-02", "name": "耐久性测试报告", "required": True},
    ],
    "域控制器": [
        {"code": "EMC-01", "name": "EMC测试报告", "required": True},
        {"code": "FUN-03", "name": "电气性能报告", "required": True},
        {"code": "ENV-01", "name": "环境测试报告", "required": True},
        {"code": "SW-01", "name": "软件版本记录", "required": True},
    ],
    "电子零件": [
        {"code": "EMC-01", "name": "EMC测试报告", "required": True},
        {"code": "FUN-03", "name": "电气性能报告", "required": True},
        {"code": "ENV-01", "name": "环境测试报告", "required": True},
    ],
    "塑料件": [
        {"code": "MAT-02", "name": "塑料材质证明", "required": True},
        {"code": "DIM-01", "name": "尺寸检测报告", "required": True},
        {"code": "ENV-02", "name": "耐候性测试报告", "required": True},
    ],
}

DEFAULT_TEMPLATE = [
    {"code": "MAT-01", "name": "材质证明", "required": True},
    {"code": "DIM-01", "name": "尺寸检测报告", "required": True},
    {"code": "FUN-01", "name": "功能测试报告", "required": True},
]


class DataChecker(BaseAgent):
    name = "data_checker"

    def _get_default_template(self, part_type: str) -> list[dict[str, Any]]:
        return DEFAULT_TEMPLATES.get(part_type, DEFAULT_TEMPLATE)

    def _get_required_items(self, checklist: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [item for item in checklist if item.get("required", True)]

    def _check_required(
        self,
        checklist: list[dict[str, Any]],
        parsed_fields: dict[str, str],
    ) -> list[dict[str, Any]]:
        missing: list[dict[str, Any]] = []
        for item in checklist:
            if item.get("required", True):
                code = item["code"]
                if code not in parsed_fields:
                    missing.append({
                        "code": code,
                        "name": item["name"],
                        "required": True,
                        "status": "missing",
                    })
        return missing

    def _build_result(
        self,
        checklist_name: str,
        checklist_items: list[dict[str, Any]],
        missing: list[dict[str, Any]],
    ) -> dict:
        all_items = []
        for item in checklist_items:
            is_missing = any(m["code"] == item["code"] for m in missing)
            all_items.append({
                "code": item["code"],
                "name": item["name"],
                "required": item.get("required", True),
                "status": "missing" if is_missing else "present",
            })

        overall_result = "pass" if len(missing) == 0 else "fail"
        return {
            "status": "ok",
            "checklist_name": checklist_name,
            "overall_result": overall_result,
            "total_required": len(self._get_required_items(checklist_items)),
            "total_missing": len(missing),
            "missing_items": missing,
            "all_items": all_items,
        }

    async def process(self, payload: dict) -> dict:
        task_id = payload.get("task_id", "")
        part_type = payload.get("part_type", "")
        parsed_fields = payload.get("parsed_fields", {})

        if not part_type:
            return {"status": "error", "task_id": task_id, "error": "part_type is required"}

        checklist = self._get_default_template(part_type)
        missing = self._check_required(checklist, parsed_fields)
        result = self._build_result(
            checklist_name=f"{part_type}检测清单",
            checklist_items=checklist,
            missing=missing,
        )
        result["task_id"] = task_id
        return result