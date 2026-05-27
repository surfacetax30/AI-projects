import pytest


SAMPLE_CHECKLIST = [
    {"code": "MAT-01", "name": "材质证明", "required": True},
    {"code": "DIM-01", "name": "尺寸报告", "required": True},
    {"code": "DIM-02", "name": "关键尺寸检测记录", "required": False},
    {"code": "FUN-01", "name": "功能测试报告", "required": True},
    {"code": "FUN-02", "name": "耐久性测试报告", "required": True},
]


SAMPLE_PARSED_FIELDS_COMPLETE = {
    "MAT-01": "available",
    "DIM-01": "available",
    "DIM-02": "available",
    "FUN-01": "available",
    "FUN-02": "available",
}


SAMPLE_PARSED_FIELDS_INCOMPLETE = {
    "MAT-01": "available",
    "DIM-01": "available",
    "FUN-02": "available",
}


class TestDataChecker:
    @pytest.fixture
    def checker(self):
        from app.agents.data_checker import DataChecker

        return DataChecker()

    def test_get_required_items(self, checker):
        required = checker._get_required_items(SAMPLE_CHECKLIST)
        assert len(required) == 4
        codes = [r["code"] for r in required]
        assert "MAT-01" in codes
        assert "DIM-01" in codes
        assert "DIM-02" not in codes

    def test_check_completeness_all_required_pass(self, checker):
        missing = checker._check_required(
            SAMPLE_CHECKLIST, SAMPLE_PARSED_FIELDS_COMPLETE
        )
        assert len(missing) == 0

    def test_check_completeness_missing_required(self, checker):
        missing = checker._check_required(
            SAMPLE_CHECKLIST, SAMPLE_PARSED_FIELDS_INCOMPLETE
        )
        assert len(missing) == 1
        missing_codes = [m["code"] for m in missing]
        assert "FUN-01" in missing_codes

    def test_check_with_empty_parsed(self, checker):
        missing = checker._check_required(SAMPLE_CHECKLIST, {})
        assert len(missing) == 4

    def test_check_with_empty_checklist(self, checker):
        missing = checker._check_required([], SAMPLE_PARSED_FIELDS_COMPLETE)
        assert len(missing) == 0

    def test_process_complete(self, checker):
        result = checker._build_result(
            checklist_name="金属支架检测清单",
            checklist_items=SAMPLE_CHECKLIST,
            missing=[],
        )
        assert result["status"] == "ok"
        assert result["overall_result"] == "pass"
        assert len(result["missing_items"]) == 0

    def test_process_incomplete(self, checker):
        missing = checker._check_required(
            SAMPLE_CHECKLIST, SAMPLE_PARSED_FIELDS_INCOMPLETE
        )
        result = checker._build_result(
            checklist_name="金属支架检测清单",
            checklist_items=SAMPLE_CHECKLIST,
            missing=missing,
        )
        assert result["overall_result"] == "fail"
        assert len(result["missing_items"]) == 1
        assert result["missing_items"][0]["code"] == "FUN-01"

    def test_load_template_by_part_type(self, checker):
        template = checker._get_default_template("金属支架")
        assert len(template) >= 2
        codes = [t["code"] for t in template]
        assert "MAT-01" in codes

    def test_non_existent_part_type_fallback(self, checker):
        template = checker._get_default_template("未知类型")
        assert len(template) >= 2

    @pytest.mark.asyncio
    async def test_process_pass_scenario(self, checker):
        plastic_fields = {"MAT-02": "available", "DIM-01": "available", "ENV-02": "available"}
        result = await checker.process({
            "task_id": "task001",
            "part_type": "塑料件",
            "parsed_fields": plastic_fields,
        })
        assert result["overall_result"] == "pass"

    @pytest.mark.asyncio
    async def test_process_fail_scenario(self, checker):
        result = await checker.process({
            "task_id": "task002",
            "part_type": "金属支架",
            "parsed_fields": SAMPLE_PARSED_FIELDS_INCOMPLETE,
        })
        assert result["overall_result"] == "fail"
        assert len(result["missing_items"]) >= 1

    @pytest.mark.asyncio
    async def test_process_missing_part_type(self, checker):
        result = await checker.process({
            "task_id": "task003",
            "part_type": "",
            "parsed_fields": {},
        })
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_process_with_none_part_type(self, checker):
        result = await checker.process({
            "task_id": "task004",
            "part_type": None,
            "parsed_fields": {"MAT-01": "available"},
        })
        assert result["status"] in ("error", "ok")