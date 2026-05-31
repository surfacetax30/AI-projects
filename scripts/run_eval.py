#!/usr/bin/env python3
"""OTS SP 评测执行脚本 — 单模型基线

用法:
    python3 scripts/run_eval.py                    # 全量评测（21 cases）
    python3 scripts/run_eval.py --limit 5           # 只跑前 5 条
    python3 scripts/run_eval.py --model deepseek-chat  # 切换模型

输出:
    产品设计文档/评测/评测报告_baseline.md   # 人看
    产品设计文档/评测/评测数据_baseline.json  # 机器读
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)

FIELDS = [
    "part_no", "software_version_F1C1", "software_version_F1C2",
    "software_version_vendor_MCU", "part_name", "test_type", "test_date",
    "test_result", "lab_name", "standard", "material", "material_spec",
    "tensile_strength", "hardness", "coating",
]
CORE_FIELDS = {"part_no", "test_result", "test_type", "test_date"}
VALID_TEST_TYPES = {
    "DV", "EMC", "PV", "HIL", "盐雾", "振动", "材料", "尺寸",
    "功能", "耐久", "软件", "静态电流", "CAN总线", "诊断",
    "总线", "CANDBC", "电性能", "其他",
}

MATERIAL_EQUIV = {
    "45钢": "45#钢", "45号钢": "45#钢", "45#钢": "45#钢",
}


def load_env():
    env_path = os.path.join(PROJ, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def load_sp():
    sp_path = os.path.join(PROJ, "sp", "parser.txt")
    with open(sp_path, encoding="utf-8") as f:
        return f.read()


def extract_json(text: str):
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def call_llm(system_prompt: str, user_message: str, model: str = None):
    import httpx

    api_key = os.environ["DEEPSEEK_API_KEY"]
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-reasoner")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.1,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ═══════════════════════════════════════════════════════
# 字段比对
# ═══════════════════════════════════════════════════════

def normalize_material(val):
    if not isinstance(val, str):
        return val
    return MATERIAL_EQUIV.get(val, val)


def field_match(key, actual, expected):
    if key == "part_no":
        if actual is None and expected is None:
            return True
        if actual is None or expected is None:
            return False
        return str(actual).upper().strip() == str(expected).upper().strip()

    if key in ("test_date",):
        return str(actual).strip() == str(expected).strip()

    if key == "material":
        return normalize_material(actual) == normalize_material(expected)

    if key in ("test_result", "test_type"):
        return str(actual).upper().strip() == str(expected).upper().strip() if actual and expected else actual == expected

    if expected is None:
        return actual is None

    return str(actual).strip() == str(expected).strip()


# ═══════════════════════════════════════════════════════
# MOS 查表
# ═══════════════════════════════════════════════════════

def mos_accuracy(weighted_accuracy):
    if weighted_accuracy >= 0.98: return 5
    if weighted_accuracy >= 0.95: return 4
    if weighted_accuracy >= 0.90: return 3
    if weighted_accuracy >= 0.80: return 2
    return 1


def mos_calibration(conf_deviation, status_accuracy):
    avg = (conf_deviation + (1.0 - status_accuracy)) / 2
    avg = 1.0 - avg
    if avg >= 0.98: return 5
    if avg >= 0.95: return 4
    if avg >= 0.90: return 3
    if avg >= 0.80: return 2
    return 1


def mos_robustness(boundary_pass, non_report_reject):
    combined = boundary_pass * 0.6 + non_report_reject * 0.4
    if combined >= 0.98: return 5
    if combined >= 0.90: return 4
    if combined >= 0.75: return 3
    if combined >= 0.50: return 2
    return 1


def mos_schema(compliance_rate):
    if compliance_rate >= 1.0: return 5
    if compliance_rate >= 0.98: return 4
    if compliance_rate >= 0.95: return 3
    if compliance_rate >= 0.85: return 2
    return 1


# ═══════════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════════

async def main(limit: int = None, model: str = None, cases_file: str = "eval_cases.json"):
    load_env()
    sp = load_sp()
    cases_path = os.path.join(PROJ, "scripts", cases_file)
    with open(cases_path, encoding="utf-8") as f:
        all_cases = json.load(f)

    cases = all_cases[:limit] if limit else all_cases
    output_suffix = Path(cases_file).stem.replace("eval_cases_", "").replace("eval_cases", "baseline")
    print(f"Loaded {len(cases)} cases from {cases_file} (total {len(all_cases)} in file)")

    out_dir = os.path.join(PROJ, "产品设计文档", "评测")
    os.makedirs(out_dir, exist_ok=True)

    results = []
    parse_errors = 0

    for i, case in enumerate(cases):
        cid = case["case_id"]
        print(f"[{i+1}/{len(cases)}] {cid} ...", end=" ", flush=True)

        try:
            raw_resp = await call_llm(sp, f"请解析以下测试报告内容：\n\n{case['input'][:4000]}", model)
        except Exception as e:
            print(f"LLM error: {e}")
            results.append({"case_id": cid, "parse_error": True, "error": str(e)})
            parse_errors += 1
            continue

        actual = extract_json(raw_resp)
        if actual is None:
            print("JSON parse failed")
            results.append({"case_id": cid, "parse_error": True, "actual": {}})
            parse_errors += 1
            continue

        expected = case["expected"]

        # 逐字段比对
        field_hits = {}
        for key in FIELDS:
            field_hits[key] = field_match(key, actual.get(key), expected.get(key))

        # 加权准确率
        weighted_hits = sum(2 if k in CORE_FIELDS else 1 for k in FIELDS if field_hits.get(k))
        weighted_total = sum(2 if k in CORE_FIELDS else 1 for k in FIELDS)
        weighted_accuracy = weighted_hits / weighted_total if weighted_total else 0.0

        core_hits = sum(1 for k in CORE_FIELDS if field_hits.get(k))
        core_total = len(CORE_FIELDS)
        general_hits = sum(1 for k in FIELDS if k not in CORE_FIELDS and field_hits.get(k))
        general_total = len(FIELDS) - core_total

        # field_status 比对
        actual_fs = actual.get("field_status", {})
        expected_fs = expected.get("field_status", {})
        status_hits = sum(
            1 for k in FIELDS
            if actual_fs.get(k) == expected_fs.get(k)
        )
        status_accuracy = status_hits / len(FIELDS) if FIELDS else 0.0

        # 置信度偏差
        actual_fc = actual.get("field_confidence", {})
        expected_fc = expected.get("field_confidence", {})
        deviations = []
        for k in FIELDS:
            if actual_fs.get(k) == "extracted":
                pred_conf = actual_fc.get(k, 0.0)
                correct = 1.0 if field_hits.get(k) else 0.0
                deviations.append(abs(pred_conf - correct))
        conf_deviation = sum(deviations) / len(deviations) if deviations else 0.0

        # overall_confidence
        actual_oc = actual.get("overall_confidence", 0.0)
        expected_oc = expected.get("overall_confidence", 0.0)

        results.append({
            "case_id": cid,
            "type": case.get("type", "unknown"),
            "report_type": case.get("report_type", case.get("source_file", "")),
            "parse_error": False,
            "field_hits": field_hits,
            "weighted_accuracy": round(weighted_accuracy, 4),
            "core_accuracy": round(core_hits / core_total, 4) if core_total else 0.0,
            "general_accuracy": round(general_hits / general_total, 4) if general_total else 0.0,
            "status_accuracy": round(status_accuracy, 4),
            "conf_deviation": round(conf_deviation, 4),
            "actual_oc": actual_oc,
            "expected_oc": expected_oc,
            "actual": actual,
            "expected": expected,
        })

        status = "✅" if weighted_accuracy >= 0.90 else ("⚠️" if weighted_accuracy >= 0.70 else "❌")
        print(f"{status} acc={weighted_accuracy:.2%} dev={conf_deviation:.3f}")

        time.sleep(1)  # API rate limit

    # ═══════════════════════════════════════════════════
    # 评分计算
    # ═══════════════════════════════════════════════════

    valid_results = [r for r in results if not r.get("parse_error")]
    if not valid_results:
        print("No valid results to score!")
        return

    # 维度一：字段提取准确性
    core_acc = sum(r["core_accuracy"] for r in valid_results) / len(valid_results)
    general_acc = sum(r["general_accuracy"] for r in valid_results) / len(valid_results)
    dim1_weighted = (core_acc * 2 + general_acc * 1) / 3
    dim1_mos = mos_accuracy(dim1_weighted)

    # 维度二：置信度校准质量
    avg_deviation = sum(r["conf_deviation"] for r in valid_results) / len(valid_results)
    avg_status = sum(r["status_accuracy"] for r in valid_results) / len(valid_results)

    high_conf_fields = []
    for r in valid_results:
        actual_fc = r["actual"].get("field_confidence", {})
        for k in FIELDS:
            conf = actual_fc.get(k, 0.0)
            if conf >= 0.8:
                hit = r["field_hits"].get(k, False)
                high_conf_fields.append(hit)
    calib_consistency = sum(high_conf_fields) / len(high_conf_fields) if high_conf_fields else 1.0

    false_positives = 0
    total_extracted = 0
    for r in valid_results:
        actual_fs = r["actual"].get("field_status", {})
        for k in FIELDS:
            if actual_fs.get(k) == "extracted":
                total_extracted += 1
                if not r["field_hits"].get(k, False):
                    false_positives += 1
    false_pos_rate = false_positives / total_extracted if total_extracted else 0.0

    dim2_mos = mos_calibration(avg_deviation, avg_status)

    # 维度三：边界场景鲁棒性
    boundary_cases = [r for r in valid_results if r["type"] == "boundary"]
    boundary_pass = sum(1 for r in boundary_cases if r["weighted_accuracy"] >= 0.80) / len(boundary_cases) if boundary_cases else 1.0

    negative_cases = [r for r in valid_results if r["type"] == "negative"]
    non_report_reject = sum(1 for r in negative_cases if r.get("actual_oc", 1.0) <= 0.3) / len(negative_cases) if negative_cases else 1.0

    dim3_mos = mos_robustness(boundary_pass, non_report_reject)

    # 维度四：输出规范性
    schema_checks = 0
    schema_total = 10 * len(valid_results)
    for r in valid_results:
        a = r["actual"]
        schema_checks += 1  # 1. JSON可解析
        schema_checks += int(all(k in a for k in FIELDS))  # 2. 15字段齐全
        fc = a.get("field_confidence", {})
        schema_checks += int(len(fc) == 15 and all(0.0 <= v <= 1.0 for v in fc.values()))  # 3. fc齐全
        fs = a.get("field_status", {})
        schema_checks += int(len(fs) == 15 and all(v in ("extracted", "missing", "not_applicable") for v in fs.values()))  # 4. fs齐全
        schema_checks += int(a.get("overall_confidence") is not None and 0.0 <= a.get("overall_confidence", 999) <= 1.0)  # 5. oc
        schema_checks += int(bool(a.get("notes", "")))  # 6. notes
        tr = a.get("test_result")
        schema_checks += int(tr in (None, "PASS", "FAIL", "CONDITIONAL"))  # 7. test_result
        tt = a.get("test_type")
        schema_checks += int(tt is None or tt in VALID_TEST_TYPES)  # 8. test_type
        td = a.get("test_date", "")
        schema_checks += int(td is None or bool(re.match(r"^\d{4}-\d{2}-\d{2}$", str(td))))  # 9. date格式
        schema_checks += int(len(a) <= 19)  # 10. 无多余字段
    schema_rate = schema_checks / schema_total
    dim4_mos = mos_schema(schema_rate)

    total_score = dim1_mos * 0.35 + dim2_mos * 0.25 + dim3_mos * 0.25 + dim4_mos * 0.15

    grades = [(4.5, "S"), (4.0, "A"), (3.0, "B"), (2.0, "C"), (1.0, "D")]
    grade = "E"
    for threshold, g in grades:
        if total_score >= threshold:
            grade = g
            break

    # ═══════════════════════════════════════════════════
    # 一票否决
    # ═══════════════════════════════════════════════════
    vetoes = []

    # V1: test_result 颠倒
    for r in valid_results:
        exp_tr = r["expected"].get("test_result")
        act_tr = r["actual"].get("test_result")
        if exp_tr == "PASS" and act_tr == "FAIL":
            vetoes.append("V1")
        if exp_tr == "FAIL" and act_tr == "PASS":
            vetoes.append("V1")

    # V2: JSON大面积无法解析
    if parse_errors >= 3:
        vetoes.append("V2")

    # V3: 非报告误判为报告
    for r in valid_results:
        if r["type"] == "negative" and r.get("actual_oc", 0.0) > 0.3:
            vetoes.append("V3")
            break

    # V4: 软件报告缺版本字段（expected中有实际版本值，输出却是占位文本）
    for r in valid_results:
        sv_fields = ["software_version_F1C1", "software_version_F1C2", "software_version_vendor_MCU"]
        has_real_versions = any(
            r["expected"].get(k) and not str(r["expected"].get(k, "")).startswith("非软件")
            for k in sv_fields
        )
        if has_real_versions:
            if all(str(r["actual"].get(k, "")).startswith("非软件") for k in sv_fields):
                vetoes.append("V4")
                break

    # V5: CONDITIONAL 误映射为 PASS（检查所有 case 中 expected=CONDITIONAL 但 actual=PASS）
    for r in valid_results:
        exp_tr = r["expected"].get("test_result")
        act_tr = r["actual"].get("test_result")
        if exp_tr == "CONDITIONAL" and act_tr == "PASS":
            vetoes.append("V5")
            break

    # V6: 置信度虚高
    inflated = 0
    for r in valid_results:
        actual_fc = r["actual"].get("field_confidence", {})
        for k in FIELDS:
            if not r["field_hits"].get(k, False) and actual_fc.get(k, 0.0) > 0.8:
                inflated += 1
    if inflated >= 5:
        vetoes.append("V6")

    # V7: field_status 系统性错误（按 expected field_status 推断场景）
    for r in valid_results:
        actual_fs = r["actual"].get("field_status", {})
        expected_fs = r["expected"].get("field_status", {})

        is_software = any(
            str(expected_fs.get(sv)) == "extracted"
            for sv in ["software_version_F1C1", "software_version_F1C2", "software_version_vendor_MCU"]
        )
        if is_software:
            if actual_fs.get("material") == "extracted":
                vetoes.append("V7")
                break

        is_non_software = all(
            expected_fs.get(sv) == "not_applicable"
            for sv in ["software_version_F1C1", "software_version_F1C2", "software_version_vendor_MCU"]
        )
        if is_non_software:
            if any(
                actual_fs.get(sv) == "extracted"
                for sv in ["software_version_F1C1", "software_version_F1C2", "software_version_vendor_MCU"]
            ):
                vetoes.append("V7")
                break

    vetoes = sorted(set(vetoes))

    # ═══════════════════════════════════════════════════
    # 输出
    # ═══════════════════════════════════════════════════

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    model_display = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-reasoner")

    # ── 终端输出 ──
    print()
    print("=" * 52)
    print(f"  OTS SP v2 评测结果")
    print(f"  模型: DeepSeek V4 ({model_display})")
    print(f"  日期: {now_str}")
    print(f"  数据: {cases_file}")
    print("=" * 52)
    veto_str = " / ".join(vetoes) if vetoes else "无"
    print(f"  总分: {total_score:.2f} / 5.0  → 等级: {grade}")
    print(f"  一票否决: {veto_str}")
    print()
    print(f"  维度一：字段提取准确性  {dim1_mos}/5  (MOS {dim1_mos})  核心准确率 {core_acc:.1%}")
    print(f"  维度二：置信度校准质量  {dim2_mos}/5  (MOS {dim2_mos})  偏差 {avg_deviation:.3f}  status准确率 {avg_status:.1%}")
    print(f"  维度三：边界场景鲁棒性  {dim3_mos}/5  (MOS {dim3_mos})  边界通过率 {boundary_pass:.1%}  拒绝率 {non_report_reject:.1%}")
    print(f"  维度四：输出规范性      {dim4_mos}/5  (MOS {dim4_mos})  Schema合规率 {schema_rate:.1%}")
    print()

    # Case 明细行
    case_line = ""
    for r in valid_results:
        if r["weighted_accuracy"] >= 0.90:
            case_line += f"{r['case_id']} ✅  "
        elif r["weighted_accuracy"] >= 0.70:
            case_line += f"{r['case_id']} ⚠️  "
        else:
            case_line += f"{r['case_id']} ❌  "
    for i in range(0, len(case_line), 60):
        print(f"  {case_line[i:i+60]}")
    print("=" * 52)

    # ── 评测报告 markdown ──
    md_path = os.path.join(out_dir, f"评测报告_{output_suffix}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# OTS SP v2 基线评测报告\n\n")
        f.write(f"> 模型: DeepSeek V4 (`{model_display}`)\n")
        f.write(f"> 日期: {now_str}\n")
        f.write(f"> 用例数: {len(cases)} 条（正向 {sum(1 for c in cases if c['type']=='positive')} / 边界 {sum(1 for c in cases if c['type']=='boundary')} / 负向 {sum(1 for c in cases if c['type']=='negative')}）\n\n")

        f.write(f"## 综合评分\n\n")
        f.write(f"| 维度 | 权重 | MOS | 得分 |\n")
        f.write(f"|------|:---:|:---:|:---:|\n")
        f.write(f"| 字段提取准确性 | 35% | {dim1_mos} | {dim1_mos*0.35:.2f} |\n")
        f.write(f"| 置信度校准质量 | 25% | {dim2_mos} | {dim2_mos*0.25:.2f} |\n")
        f.write(f"| 边界场景鲁棒性 | 25% | {dim3_mos} | {dim3_mos*0.25:.2f} |\n")
        f.write(f"| 输出规范性 | 15% | {dim4_mos} | {dim4_mos*0.15:.2f} |\n")
        f.write(f"| **总分** | | | **{total_score:.2f}** |\n")
        f.write(f"| **等级** | | | **{grade}** |\n\n")

        f.write(f"### 一票否决检查\n\n")
        veto_text = " / ".join(vetoes) if vetoes else "✅ 未触发任何否决项"
        f.write(f"- {veto_text}\n\n")

        f.write(f"### 维度一：字段提取准确性\n\n")
        f.write(f"- 核心字段准确率: {core_acc:.1%}\n")
        f.write(f"- 一般字段准确率: {general_acc:.1%}\n")
        f.write(f"- 加权准确率: {dim1_weighted:.1%}\n\n")

        f.write(f"### 维度二：置信度校准质量\n\n")
        f.write(f"- 置信度偏差: {avg_deviation:.3f}\n")
        f.write(f"- field_status 准确率: {avg_status:.1%}\n")
        f.write(f"- 高置信度字段准确率: {calib_consistency:.1%}\n")
        f.write(f"- 误报率: {false_pos_rate:.1%}\n\n")

        f.write(f"### 维度三：边界场景鲁棒性\n\n")
        f.write(f"- 边界 case 通过率: {boundary_pass:.1%}\n")
        f.write(f"- 非报告拒绝率: {non_report_reject:.1%}\n\n")

        f.write(f"### 维度四：输出规范性\n\n")
        f.write(f"- Schema 合规率: {schema_rate:.1%}\n")
        f.write(f"- JSON 解析失败: {parse_errors}/{len(cases)}\n\n")

        f.write(f"## 逐 Case 明细\n\n")
        f.write(f"| Case | 类型 | 加权准确率 | 置信度偏差 | status准确率 | |\n")
        f.write(f"|------|------|:---:|:---:|:---:|---|\n")
        for r in valid_results:
            icon = "✅" if r["weighted_accuracy"] >= 0.90 else ("⚠️" if r["weighted_accuracy"] >= 0.70 else "❌")
            f.write(f"| {r['case_id']} | {r['type']} | {r['weighted_accuracy']:.1%} | {r['conf_deviation']:.3f} | {r['status_accuracy']:.1%} | {icon} |\n")

        f.write(f"\n### 低分 Case 清单\n\n")
        low_cases = [r for r in valid_results if r["weighted_accuracy"] < 0.70]
        if low_cases:
            for r in low_cases:
                errors = [k for k in FIELDS if not r["field_hits"].get(k)]
                f.write(f"- **{r['case_id']}** ({r['weighted_accuracy']:.1%}): 错误字段 {', '.join(errors[:5])}")
                if len(errors) > 5:
                    f.write(f" ... 等 {len(errors)} 个")
                f.write("\n")
        else:
            f.write("无\n")

    # ── 评测数据 JSON ──
    json_path = os.path.join(out_dir, f"评测数据_{output_suffix}.json")
    eval_data = {
        "meta": {"model": model_display, "date": now_str, "sp_version": "v2"},
        "total_score": round(total_score, 2),
        "grade": grade,
        "veto_flags": vetoes,
        "dimensions": {
            "accuracy": {"score": dim1_mos, "mos": dim1_mos, "core_accuracy": round(core_acc, 4), "general_accuracy": round(general_acc, 4)},
            "calibration": {"score": dim2_mos, "mos": dim2_mos, "deviation": round(avg_deviation, 4), "status_accuracy": round(avg_status, 4), "consistency": round(calib_consistency, 4)},
            "robustness": {"score": dim3_mos, "mos": dim3_mos, "boundary_pass_rate": round(boundary_pass, 4), "reject_rate": round(non_report_reject, 4)},
            "schema": {"score": dim4_mos, "mos": dim4_mos, "compliance_rate": round(schema_rate, 4), "parse_errors": parse_errors},
        },
        "cases": [
            {
                "case_id": r["case_id"],
                "passed": r["weighted_accuracy"] >= 0.90,
                "score": round(r["weighted_accuracy"], 4),
                "errors": [k for k in FIELDS if not r["field_hits"].get(k)],
            }
            for r in valid_results
        ],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(eval_data, f, ensure_ascii=False, indent=2)

    print(f"\n📄 评测报告: {md_path}")
    print(f"📊 评测数据: {json_path}")


if __name__ == "__main__":
    import asyncio
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--cases-file", type=str, default="eval_cases.json")
    args = parser.parse_args()

    asyncio.run(main(limit=args.limit, model=args.model, cases_file=args.cases_file))
