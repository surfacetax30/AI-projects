#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# OTS-AHA 端到端测试 — 真实 DeepSeek V4 全链路
# 
# 用法:
#   chmod +x scripts/test_e2e_real.sh
#   ./scripts/test_e2e_real.sh
#
# 前置条件:
#   - DeepSeek V4 API Key 已配置在 .env
#   - uvicorn app.main:app 已启动在 localhost:8000
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

BASE="http://localhost:8000"
PASS=0
FAIL=0

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
cyan()  { echo -e "\033[36m$1\033[0m"; }
dim()   { echo -e "\033[2m$1\033[0m"; }

check() {
    local desc="$1"
    local expected="$2"
    local actual="$3"
    if echo "$actual" | grep -q "$expected"; then
        green "  ✓ $desc"
        PASS=$((PASS + 1))
    else
        red "  ✗ $desc (expected: $expected)"
        dim "    actual: $actual"
        FAIL=$((FAIL + 1))
    fi
}

check_status() {
    local desc="$1"
    local expected_code="$2"
    local resp="$3"
    local code
    code=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "parse_error")
    if [ "$code" = "$expected_code" ]; then
        green "  ✓ $desc"
        PASS=$((PASS + 1))
    else
        red "  ✗ $desc (expected status=$expected_code, got=$code)"
        FAIL=$((FAIL + 1))
    fi
}

echo ""
cyan "═══════════════════════════════════════════════════════"
cyan "  OTS-AHA 端到端测试 · DeepSeek V4"
cyan "═══════════════════════════════════════════════════════"
echo ""

# ── Test 0: Health check ──
echo "── 健康检查 ──"
RESP=$(curl -s "$BASE/health")
echo "$RESP" | python3 -m json.tool 2>/dev/null || echo "$RESP"
check "服务可达" "ok" "$RESP"
echo ""

# ── Test 1: Create part ──
echo "── 测试1: 创建零件 ──"
RESP=$(curl -s -X POST "$BASE/api/parts" \
    -H "Content-Type: application/json" \
    -d '{
        "part_no": "OTS-2026-001",
        "part_name": "前副车架焊接总成",
        "part_type": "金属支架",
        "supplier": "XX精工制造有限公司",
        "project_code": "P2026-SUV"
    }')
echo "$RESP" | python3 -m json.tool 2>/dev/null || echo "$RESP"

PART_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['part']['id'])" 2>/dev/null)
TASK_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['task']['id'])" 2>/dev/null)

check "返回 part.id" "[a-f0-9]" "$PART_ID"
check "返回 task.id" "[a-f0-9]" "$TASK_ID"
check "任务状态=CREATED" "CREATED" "$RESP"
echo ""

# ── Test 2: Upload report ──
echo "── 测试2: 上传测试报告 ──"

# Create a realistic test report PDF-like text
REPORT_TEXT=$(cat <<'EOF'
OTS 零部件认可测试报告
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
报告日期: 2026-05-20      报告人: 张三      审核: 李四
EOF
)

# Also create a garbage "report" for negative testing
GARBAGE_TEXT="尊敬的领导：本周工作汇报如下：1. 完成了XX项目的方案设计 2. 参加了部门会议。下周计划：继续推进XX项目。"

# Upload clean report
RESP=$(curl -s -X POST "$BASE/api/tasks/$TASK_ID/reports" \
    -F "file=@<(echo '$REPORT_TEXT');filename=ots_test_report.txt" \
    -F "task_id=$TASK_ID")
echo "$RESP" | python3 -m json.tool 2>/dev/null || echo "$RESP"
STORAGE=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('storage_path',''))" 2>/dev/null)
check "上传成功，返回 storage_path" "ots-reports" "$RESP"
echo ""

# ── Test 3: Trigger webhook (simulates email arriving) ──
echo "── 测试3: Webhook 触发解析管线 ──"
RESP=$(curl -s -X POST "$BASE/api/webhooks/mail" \
    -H "Content-Type: application/json" \
    -d "{
        \"mail_from\": \"vendor1@example.com\",
        \"mail_subject\": \"RE: OTS-2026-001 前副车架OTS认可测试报告\",
        \"part_no\": \"OTS-2026-001\",
        \"attachments\": [\"$STORAGE\"]
    }")
echo "$RESP" | python3 -m json.tool 2>/dev/null || echo "$RESP"
check "Webhook 接受" "accepted" "$RESP"
echo ""

# ── Test 4: Get task detail (after ~15s for LLM to process) ──
echo "── 测试4: 查询任务详情（等待 DeepSeek V4 解析...）──"
for i in $(seq 1 20); do
    RESP=$(curl -s "$BASE/api/tasks/$TASK_ID")
    TIMELINE_COUNT=$(echo "$RESP" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('timeline',[])))" 2>/dev/null || echo "0")
    if [ "$TIMELINE_COUNT" -ge 2 ] 2>/dev/null; then
        dim "  事件数=$TIMELINE_COUNT，解析已完成"
        break
    fi
    dim "  等待中... ($i/20)"
    sleep 3
done

RESP=$(curl -s "$BASE/api/tasks/$TASK_ID")
echo "$RESP" | python3 -m json.tool 2>/dev/null || echo "$RESP"

# Validate response structure
check "任务ID正确" "$TASK_ID" "$RESP"
check "包含零件信息" "OTS-2026-001" "$RESP"
check "有时间线" "timeline" "$RESP"
check "有报告列表" "reports" "$RESP"

TIMELINE=$(echo "$RESP" | python3 -c "import sys,json; t=json.load(sys.stdin)['timeline']; [print(e['event']) for e in t]" 2>/dev/null)
echo ""
dim "时间线事件:"
echo "$TIMELINE" | while read event; do dim "  - $event"; done
echo ""

# ── Test 5: List parts ──
echo "── 测试5: 零件列表 ──"
RESP=$(curl -s "$BASE/api/parts")
COUNT=$(echo "$RESP" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
check "零件列表非空" "[1-9]" "$COUNT"
echo ""

# ── Summary ──
echo ""
cyan "═══════════════════════════════════════════════════════"
cyan "  结果: $PASS 通过 / $FAIL 失败"
cyan "═══════════════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
    red "存在失败用例，请检查上方 ✗ 标记。"
    exit 1
else
    green "全部通过！DeepSeek V4 全链路运行正常。"
fi
