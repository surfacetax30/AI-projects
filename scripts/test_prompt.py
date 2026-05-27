#!/usr/bin/env python3
"""手动 Prompt 测试工具 — 读取 sp/parser.txt + test_report.txt，调 DeepSeek V4。

用法:
  1. 编辑 sp/parser.txt ← 你的 Prompt
  2. 编辑 test_report.txt   ← 测试报告文本
  3. python3 scripts/test_prompt.py
"""

import json, os, re, httpx, asyncio, time, sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 加载 .env ──
env_path = os.path.join(PROJ, ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

# ── 读取 ──
prompt_path = os.path.join(PROJ, "sp", "parser.txt")
report_path = os.path.join(PROJ, "test_report.txt")

if not os.path.exists(prompt_path):
    print(f"❌ 找不到 {prompt_path}，请创建 sp/parser.txt")
    sys.exit(1)
if not os.path.exists(report_path):
    print(f"❌ 找不到 {report_path}，请创建 test_report.txt")
    sys.exit(1)

with open(prompt_path) as f:
    prompt = f.read()
with open(report_path) as f:
    report = f.read()

api_key = os.environ["DEEPSEEK_API_KEY"]
base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
model = os.environ.get("DEEPSEEK_MODEL", "deepseek-reasoner")

# ═══════════════════════════════════════════════
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_CYAN = "\033[36m"
C_BOLD = "\033[1m"
C_RESET = "\033[0m"


async def main():
    print(f"{C_BOLD}模型: {model}{C_RESET}")
    print(f"{C_BOLD}Prompt: {len(prompt)} 字符 | 报告: {len(report)} 字符{C_RESET}")
    print()

    t0 = time.time()

    async with httpx.AsyncClient(
        base_url=base,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=90.0,
    ) as client:
        resp = await client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"## 输入报告文本\n\n{report[:4000]}"},
                ],
                "temperature": 0.1,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        elapsed = time.time() - t0

    # ═══ 1. 原始响应 ═══
    print(f"{C_BOLD}{'═'*60}{C_RESET}")
    print(f"{C_BOLD}  原始响应 ({len(raw)} 字符, {elapsed:.1f}s){C_RESET}")
    print(f"{C_BOLD}{'═'*60}{C_RESET}")
    print(raw)
    print()

    # ═══ 2. 提取 JSON ═══
    json_match = re.search(r"```json\s*([\s\S]*?)```", raw)
    if json_match:
        json_str = json_match.group(1).strip()
        print(f"{C_BOLD}{'═'*60}{C_RESET}")
        print(f"{C_BOLD}  解析出的 JSON{C_RESET}")
        print(f"{C_BOLD}{'═'*60}{C_RESET}")
    else:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            json_str = m.group(0)
            print(f"{C_BOLD}{'═'*60}{C_RESET}")
            print(f"{C_BOLD}  解析出的 JSON（裸输出）{C_RESET}")
            print(f"{C_BOLD}{'═'*60}{C_RESET}")
        else:
            print(f"{C_RED}❌ 未找到 JSON，请检查 Prompt 是否要求 ```json 代码块输出{C_RESET}")
            return

    try:
        parsed = json.loads(json_str)
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print(f"{C_RED}❌ JSON 解析失败，原始内容:{C_RESET}")
        print(json_str[:500])
        return

    # ═══ 3. 置信度可视化 ═══
    conf = parsed.get("field_confidence", {})
    overall = parsed.get("overall_confidence", None)
    print(f"\n{C_BOLD}{'═'*60}{C_RESET}")
    print(f"{C_BOLD}  置信度总览 (overall={overall}){C_RESET}")
    print(f"{C_BOLD}{'═'*60}{C_RESET}")
    if conf:
        for k, v in conf.items():
            bar = C_GREEN + "█" * int(v * 20) + C_RESET + "░" * (20 - int(v * 20))
            color = C_RED if v < 0.5 else (C_YELLOW if v < 0.85 else C_GREEN)
            print(f"  {color}{k:20s} {bar} {v:.2f}{C_RESET}")
    else:
        print("  （无 field_confidence）")

    # ═══ 4. 快速诊断 ═══
    print(f"\n{C_BOLD}{'═'*60}{C_RESET}")
    print(f"{C_BOLD}  快速诊断{C_RESET}")
    print(f"{C_BOLD}{'═'*60}{C_RESET}")
    if conf:
        high = sum(1 for v in conf.values() if v >= 0.85)
        mid = sum(1 for v in conf.values() if 0.5 <= v < 0.85)
        low = sum(1 for v in conf.values() if v < 0.5)
        print(f"  高置信(≥0.85): {high}  中置信(0.5-0.84): {mid}  低置信(<0.5): {low}")
    notes = parsed.get("notes", "")
    if notes:
        print(f"  LLM 备注: {notes}")
    if isinstance(overall, (int, float)):
        if overall >= 0.85:
            print(f"  {C_GREEN}✅ 整体置信度高 — 建议自动通过{C_RESET}")
        elif overall >= 0.5:
            print(f"  {C_YELLOW}⚠️  整体置信度中等 — 建议人工复核{C_RESET}")
        else:
            print(f"  {C_RED}❌ 整体置信度低 — 需要人工介入{C_RESET}")

    print(f"\n{C_CYAN}修改 sp/parser.txt 后重新运行即可迭代测试。{C_RESET}")


if __name__ == "__main__":
    asyncio.run(main())
