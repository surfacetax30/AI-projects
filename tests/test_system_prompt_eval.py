"""完整的 System Prompt + 5 个真实场景测试用例 — 直接调用 DeepSeek V4，记录并评测效果。

运行:  python3 tests/test_system_prompt_eval.py
"""

import json, sys, os, asyncio, httpx, re, time
from typing import Optional

# ═══════════════════════════════════════════════════════════════
# 完整 System Prompt（角色 · 指令 · 变量 · Schema · Few-shot）
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """# 角色
你是汽车行业 OTS (Off-Tool Sample) 零部件认可测试报告的解析专家。
你服务于一家整车厂的 SQE (Supplier Quality Engineer) 团队，
负责从供应商提交的各类测试报告（PDF/Word/Excel/扫描件OCR）中提取结构化数据。

# 任务
阅读下方「输入报告文本」，从中提取关键字段，
并以严格的 JSON 格式输出提取结果和逐字段置信度。

# 输入变量
- report_text: 测试报告的纯文本内容（已从原始文件中提取）

# 字段提取规则

| 字段 | 提取规则 | 示例值 |
|------|---------|--------|
| part_no | 零件号，通常格式为字母-数字-数字，如 OTS-2026-001。注意大小写统一为大写 | "OTS-2026-001" |
| part_name | 零件名称描述 | "前副车架焊接总成" |
| test_type | 测试类型，从以下枚举中匹配：DV / EMC / PV / HIL / 盐雾 / 振动 / 材料 / 尺寸 / 功能 / 耐久 | "DV" |
| test_date | 测试日期，统一为 YYYY-MM-DD 格式。如原文只有年月补为 YYYY-MM-01 | "2026-05-15" |
| test_result | 测试结论，只能是 PASS / FAIL / CONDITIONAL。条件通过写 CONDITIONAL | "PASS" |
| lab_name | 执行测试的实验室名称 | "国家汽车零部件质量监督检验中心" |
| standard | 遵循的测试标准编号（GB/ISO/SAE等） | "GB/T 1234.5-2023" |
| material | 主要材料牌号 | "Q345B" |
| material_spec | 材料遵循的标准 | "GB/T 1591-2018" |
| tensile_strength | 抗拉强度数值（含单位），如无则为 null | "520 MPa" |
| hardness | 硬度数值（含单位），如无则为 null | "HB 180" |
| coating | 表面处理方式，如无则为 null | "阴极电泳" |

# 置信度评分指南
对每个字段给出 0.0-1.0 的置信度：
- 1.0: 报告明确写出，格式标准，无歧义
- 0.8-0.9: 能推断但写法不标准（如日期写 "2026年4月"）
- 0.5-0.7: 部分信息缺失或模糊
- 0.0-0.4: 无法确定或不在报告中
- 如果字段完全不适用（如非金属件无 coating），填 null，置信度 1.0

# 输出 Schema（严格 JSON，放在 ```json 代码块内）
```json
{
  "part_no": "字符串",
  "part_name": "字符串",
  "test_type": "字符串",
  "test_date": "YYYY-MM-DD",
  "test_result": "PASS|FAIL|CONDITIONAL",
  "lab_name": "字符串",
  "standard": "字符串或null",
  "material": "字符串或null",
  "material_spec": "字符串或null",
  "tensile_strength": "字符串或null",
  "hardness": "字符串或null",
  "coating": "字符串或null",
  "field_confidence": {
    "part_no": 0.95,
    "part_name": 0.90,
    "test_type": 0.88,
    "test_date": 0.92,
    "test_result": 0.97,
    "lab_name": 0.85,
    "standard": 0.91,
    "material": 0.80,
    "material_spec": 0.75,
    "tensile_strength": 0.70,
    "hardness": 0.65,
    "coating": 0.60
  },
  "overall_confidence": 0.87,
  "notes": "补充说明（可选）"
}
```

# Few-Shot 示例

## 示例 1：标准 OTS 测试报告
输入：
```
OTS 零部件认可测试报告
零件号: OTS-2025-088
零件名称: 后扭力梁总成
测试类型: DV (Design Verification)
测试日期: 2025-11-20
测试结论: PASS
实验室: 中汽研汽车检验中心
标准: GB/T 26780-2024
材料: SAPH440 (GB/T 20887.1-2017)
抗拉强度: 465 MPa
```
输出：
```json
{
  "part_no": "OTS-2025-088",
  "part_name": "后扭力梁总成",
  "test_type": "DV",
  "test_date": "2025-11-20",
  "test_result": "PASS",
  "lab_name": "中汽研汽车检验中心",
  "standard": "GB/T 26780-2024",
  "material": "SAPH440",
  "material_spec": "GB/T 20887.1-2017",
  "tensile_strength": "465 MPa",
  "hardness": null,
  "coating": null,
  "field_confidence": {
    "part_no": 1.0,
    "part_name": 1.0,
    "test_type": 1.0,
    "test_date": 1.0,
    "test_result": 1.0,
    "lab_name": 1.0,
    "standard": 1.0,
    "material": 0.95,
    "material_spec": 0.95,
    "tensile_strength": 1.0,
    "hardness": 1.0,
    "coating": 1.0
  },
  "overall_confidence": 0.99,
  "notes": ""
}
```

## 示例 2：不完整的手写扫描报告
输入：
```
测试报告
件号 ot-303-099
实验 振动耐久
日期 2026.3
结果 合格
实验室 XX检测
材质 45#钢
```
输出：
```json
{
  "part_no": "OT-303-099",
  "part_name": "unknown",
  "test_type": "振动",
  "test_date": "2026-03-01",
  "test_result": "PASS",
  "lab_name": "XX检测",
  "standard": null,
  "material": "45#钢",
  "material_spec": null,
  "tensile_strength": null,
  "hardness": null,
  "coating": null,
  "field_confidence": {
    "part_no": 0.75,
    "part_name": 0.0,
    "test_type": 0.80,
    "test_date": 0.60,
    "test_result": 0.70,
    "lab_name": 0.50,
    "standard": 0.0,
    "material": 0.85,
    "material_spec": 0.0,
    "tensile_strength": 0.0,
    "hardness": 0.0,
    "coating": 0.0
  },
  "overall_confidence": 0.43,
  "notes": "扫描质量差，多个字段无法识别"
}
```

# 重要提醒
- 输出的 JSON 必须放在 ```json ... ``` 代码块中
- 即使某些字段无法提取，也必须包含所有字段（用 null 或 "unknown"）
- 如果报告明显不是测试报告（如工作汇报），所有字段填 "unknown" 或 null，overall_confidence 设为 0.0，notes 注明 "非测试报告"
"""


# ═══════════════════════════════════════════════════════════════
# 5 个测试用例 — 覆盖不同难度层级
# ═══════════════════════════════════════════════════════════════

TEST_CASES = [
    {
        "id": "TC01",
        "name": "标准 DV 测试报告（完整、结构化）",
        "difficulty": "easy",
        "report_text": """OTS 零部件认可测试报告
================================================================================

零件号: OTS-2026-001
零件名称: 前副车架焊接总成
测试类型: DV (Design Verification)
测试日期: 2026-05-15
测试结论: PASS
实验室: 国家汽车零部件质量监督检验中心
测试标准: GB/T 1234.5-2023

--- 材料分析 ---
基材: Q345B (GB/T 1591-2018)
焊接材料: ER50-6

--- 力学性能 ---
抗拉强度: 520 MPa (标准要求 ≥ 480 MPa)
屈服强度: 355 MPa
延伸率: 22%
硬度: HB 180

--- 尺寸检测 ---
关键尺寸全部合格，详见附表A

--- 无损检测 ---
超声波探伤: 合格
磁粉探伤: 合格

--- 盐雾试验 ---
96小时中性盐雾试验: 无红锈

结论: 所有测试项目均符合设计要求和相关标准。
================================================================================
报告日期: 2026-05-20      报告人: 张三      审核: 李四""",
        "expected": {
            "part_no": "OTS-2026-001",
            "test_type": "DV",
            "test_result": "PASS",
            "material": "Q345B",
            "tensile_strength_contains": "520",
        },
    },
    {
        "id": "TC02",
        "name": "EMC 测试报告（中等格式）",
        "difficulty": "medium",
        "report_text": """EMC 电磁兼容性测试报告

送检单位: XX精工制造有限公司
样品名称: 车身域控制器
样品编号: OTS-2026-055

测试依据标准:
- GB/T 18655-2018 车辆、船和内燃机 无线电骚扰特性
- GB/T 21437.2-2021 道路车辆 沿电源线的电瞬态传导

测试项目及结果:
+---+---------------------+--------+--------+-------+
| # | 项目                | 标准限值| 测量值 | 判定  |
+---+---------------------+--------+--------+-------+
| 1 | 辐射发射 (30MHz-1GHz)| Class 3| PASS   | PASS  |
| 2 | 传导发射 (150k-108M) | Class 3| PASS   | PASS  |
| 3 | 瞬态传导抗扰        | Level A| Level A| PASS  |
| 4 | 静电放电            | ±8kV   | ±8kV   | PASS  |
+---+---------------------+--------+--------+-------+

测试日期: 2026年4月20日 - 2026年4月25日
测试结论: 全部项目 PASS
实验室: 中汽研汽车检验中心（天津）EMC实验室
报告日期: 2026-04-28""",
        "expected": {
            "part_no": "OTS-2026-055",
            "test_type_contains": "EMC",
            "test_result": "PASS",
            "lab_name_contains": "中汽研",
        },
    },
    {
        "id": "TC03",
        "name": "简略手写报告（低质量输入）",
        "difficulty": "hard",
        "report_text": """测试记录
件号 ot-303-099
实验: 振动耐久
日期: 2026.3
结果: 合格
实验室: XX检测中心
材质: 45#钢
硬度: HRC 28-32""",
        "expected": {
            "part_no_contains": "OT-303-099",
            "test_type_contains": "振动",
            "test_result": "PASS",
            "material": "45#钢",
        },
    },
    {
        "id": "TC04",
        "name": "非测试报告——工作汇报（负样本）",
        "difficulty": "negative",
        "report_text": """尊敬的领导：

本周工作汇报如下：

1. 完成了XX项目的方案设计评审
2. 参加了3次跨部门协调会议
3. 处理了2起供应商来料异常
4. 更新了QMS体系文件

下周计划：
1. 继续推进XX项目第二阶段
2. 完成月度质量报告
3. 安排供应商年度审核

此致
敬礼
张三
2026-05-27""",
        "expected": {
            "overall_confidence_max": 0.3,
        },
    },
    {
        "id": "TC05",
        "name": "盐雾试验报告（含表面处理信息）",
        "difficulty": "medium",
        "report_text": """盐雾试验报告
NSS Test Report

委托单位: XX精工制造有限公司
零件号: OTS-2026-033
零件名称: 前保险杠安装支架
材质: DC04 冷轧钢板
表面处理: 阴极电泳 (KTL) + 面漆

试验条件:
- 标准: GB/T 10125-2021 人造气氛腐蚀试验 盐雾试验
- 温度: 35±2°C
- NaCl浓度: 5%
- 试验时间: 480小时

试验结果:
+--------+----------+----------+------------------+
| 时间   | 红锈面积 | 白锈面积 | 判定             |
+--------+----------+----------+------------------+
| 96h    | 0%       | <1%      | 合格             |
| 240h   | 0%       | 3%       | 合格             |
| 480h   | <1%      | 5%       | 合格             |
+--------+----------+----------+------------------+

测试结论: PASS — 满足480h盐雾试验要求
测试日期: 2026-03-10 至 2026-03-30
实验室: SGS-CSTC 通标标准技术服务有限公司
报告编号: SGS-CSTC-2026-0412""",
        "expected": {
            "part_no": "OTS-2026-033",
            "test_type_contains": "盐雾",
            "test_result": "PASS",
            "coating_contains": "电泳",
        },
    },
]


# ═══════════════════════════════════════════════════════════════
# 评估引擎
# ═══════════════════════════════════════════════════════════════

C_GREEN  = "\033[32m"
C_RED    = "\033[31m"
C_YELLOW = "\033[33m"
C_CYAN   = "\033[36m"
C_BOLD   = "\033[1m"
C_RESET  = "\033[0m"

def extract_json(response: str) -> Optional[dict]:
    """从 DeepSeek reasoner 的响应中提取 JSON。
    可能被 ``json...`` 包裹，也可能直接裸输出。"""
    # 优先匹配 ```json ... ```
    m = re.search(r"```json\s*([\s\S]*?)```", response)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 尝试匹配裸 { ... }
    m = re.search(r"\{[\s\S]*\}", response)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def evaluate(tc: dict, parsed: dict) -> list[str]:
    """逐项校验 expected 中的断言，返回通过/失败的描述列表。"""
    results = []
    exp = tc["expected"]

    for key, expected in exp.items():
        actual = parsed.get(key, None)

        if key.endswith("_contains"):
            real_key = key.replace("_contains", "")
            actual = parsed.get(real_key, "")
            if expected.lower() in str(actual).lower():
                results.append(f"✓ {real_key} 包含 '{expected}'")
            else:
                results.append(f"✗ {real_key}: 期望包含 '{expected}', 实际 '{actual}'")

        elif key.endswith("_max"):
            real_key = key.replace("_max", "")
            actual_val = float(parsed.get(real_key, 1.0))
            if actual_val <= expected:
                results.append(f"✓ {real_key}={actual_val} ≤ {expected}")
            else:
                results.append(f"✗ {real_key}={actual_val} > {expected}")

        else:
            # 精确匹配
            actual_str = str(actual).strip() if actual is not None else ""
            expected_str = str(expected).strip()
            if actual_str.lower() == expected_str.lower():
                results.append(f"✓ {key} = '{actual_str}'")
            else:
                results.append(f"✗ {key}: 期望 '{expected_str}', 实际 '{actual_str}'")

    return results


# ═══════════════════════════════════════════════════════════════
# 主测试入口
# ═══════════════════════════════════════════════════════════════

async def run_one(httpx_client, tc: dict) -> dict:
    """调用 DeepSeek V4，返回原始响应 + 解析结果。"""
    print(f"\n{C_BOLD}── {tc['id']} {tc['name']} ──{C_RESET}")
    print(f"{C_CYAN}难度: {tc['difficulty']}{C_RESET}")
    print(f"{C_CYAN}输入 ({len(tc['report_text'])} 字符):{C_RESET}")
    print(tc['report_text'][:200] + ("..." if len(tc['report_text']) > 200 else ""))

    t0 = time.time()
    resp = await httpx_client.post(
        "/chat/completions",
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"## 输入报告文本\n\n{tc['report_text'][:4000]}"},
            ],
            "temperature": 0.1,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    raw = data["choices"][0]["message"]["content"]
    elapsed = time.time() - t0

    print(f"\n{C_BOLD}原始响应 ({len(raw)} 字符, {elapsed:.1f}s):{C_RESET}")
    # 只打印 JSON 部分 + 前后文
    json_match = re.search(r"```json([\s\S]*?)```", raw)
    if json_match:
        json_part = json_match.group(1).strip()
        before = raw[:json_match.start()].strip()
        after = raw[json_match.end():].strip()
        if before:
            print(f"  [{C_YELLOW}思考/前置{C_RESET}] {before[:120]}...")
        try:
            parsed_json = json.loads(json_part)
            print(f"  {C_GREEN}JSON:{C_RESET}")
            print(json.dumps(parsed_json, indent=2, ensure_ascii=False))
        except json.JSONDecodeError:
            print(f"  [{C_RED}JSON解析失败{C_RESET}] {json_part[:200]}")
        if after:
            print(f"  [{C_YELLOW}后置{C_RESET}] {after[:120]}...")
    else:
        print(raw[:600])

    parsed = extract_json(raw)

    if parsed is None:
        print(f"\n{C_RED}⨯ JSON 解析失败{C_RESET}")
        return {"tc": tc, "raw": raw, "parsed": None, "elapsed": elapsed, "results": ["JSON_PARSE_FAILED"]}

    # 评估
    eval_results = evaluate(tc, parsed)
    passed = sum(1 for r in eval_results if r.startswith("✓"))
    failed = sum(1 for r in eval_results if r.startswith("✗"))

    print(f"\n{C_BOLD}评估: {passed}/{passed+failed} 通过{C_RESET}")
    for r in eval_results:
        color = C_GREEN if r.startswith("✓") else C_RED
        print(f"  {color}{r}{C_RESET}")

    # 汇总字段
    conf = parsed.get("field_confidence", {})
    print(f"\n{C_BOLD}置信度总览:{C_RESET} overall={parsed.get('overall_confidence','?')}")
    for k, v in conf.items():
        bar = "█" * int(v * 20) + "░" * (20 - int(v * 20))
        color = C_GREEN if v >= 0.85 else (C_YELLOW if v >= 0.5 else C_RED)
        print(f"  {k:20s} {color}{bar} {v:.2f}{C_RESET}")

    return {
        "tc": tc,
        "raw": raw,
        "parsed": parsed,
        "elapsed": elapsed,
        "results": eval_results,
    }


async def main():
    PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 加载 .env
    env_path = os.path.join(PROJ, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    api_key = os.environ["DEEPSEEK_API_KEY"]
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    global DEEPSEEK_MODEL
    DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-reasoner")

    print(f"{C_BOLD}{'='*70}{C_RESET}")
    print(f"{C_BOLD}  OTS Parser · System Prompt 评测{C_RESET}")
    print(f"{C_BOLD}  模型: {DEEPSEEK_MODEL} | API: {base}{C_RESET}")
    print(f"{C_BOLD}  用例数: {len(TEST_CASES)}{C_RESET}")
    print(f"{C_BOLD}{'='*70}{C_RESET}")

    async with httpx.AsyncClient(
        base_url=base,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=90.0,
    ) as client:
        all_results = []
        for tc in TEST_CASES:
            r = await run_one(client, tc)
            all_results.append(r)

        # ═══════════════════ 总结 ═══════════════════
        print(f"\n\n{C_BOLD}{'='*70}{C_RESET}")
        print(f"{C_BOLD}  总结{C_RESET}")
        print(f"{C_BOLD}{'='*70}{C_RESET}")

        total_checks = 0
        total_passed = 0
        total_time = 0
        for r in all_results:
            res = r["results"]
            if res == ["JSON_PARSE_FAILED"]:
                total_checks += 1
            else:
                passed = sum(1 for x in res if x.startswith("✓"))
                failed = sum(1 for x in res if x.startswith("✗"))
                total_checks += passed + failed
                total_passed += passed
            total_time += r["elapsed"]

            verdict = "✓" if r["parsed"] else "✗"
            conf = r["parsed"]["overall_confidence"] if r["parsed"] else 0
            tc = r["tc"]
            print(f"  {verdict} {tc['id']} {tc['name'][:30]:30s}  {conf:.2f}  {r['elapsed']:.1f}s  {tc['difficulty']}")

        print(f"\n{C_BOLD}总检查项: {total_passed}/{total_checks} 通过 ({total_passed/max(total_checks,1)*100:.0f}%){C_RESET}")
        print(f"{C_BOLD}总耗时: {total_time:.1f}s 平均: {total_time/len(TEST_CASES):.1f}s{C_RESET}")

        # 效果标注
        print(f"\n{C_BOLD}效果结论:{C_RESET}")
        for r in all_results:
            tc = r["tc"]
            if r["parsed"] is None:
                print(f"  {C_RED}✗ {tc['id']} 严重失败 — JSON解析失败{C_RESET}")
                continue
            res = r["results"]
            if res == ["JSON_PARSE_FAILED"]:
                print(f"  {C_RED}✗ {tc['id']} 严重失败 — JSON解析失败{C_RESET}")
                continue
            passed = sum(1 for x in res if x.startswith("✓"))
            failed = sum(1 for x in res if x.startswith("✗"))
            ratio = passed / max(passed + failed, 1)
            conf = r["parsed"]["overall_confidence"]
            if ratio == 1.0 and conf >= 0.8:
                print(f"  {C_GREEN}★ {tc['id']} 优秀 — 全对, 置信度合理 ({conf*100:.0f}%){C_RESET}")
            elif ratio >= 0.7:
                print(f"  {C_YELLOW}△ {tc['id']} 良好 — {passed}/{passed+failed} 通过, 置信度={conf:.2f}{C_RESET}")
            elif ratio >= 0.4:
                print(f"  {C_RED}○ {tc['id']} 需要改进 — {passed}/{passed+failed} 通过{C_RESET}")
            else:
                print(f"  {C_RED}✗ {tc['id']} 差 — {passed}/{passed+failed} 通过{C_RESET}")


if __name__ == "__main__":
    asyncio.run(main())
