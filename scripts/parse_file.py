#!/usr/bin/env python3
"""终端文件解析测试工具 — 指定文件，自动提取文本 + DeepSeek V4 解析。

用法:
    python3 scripts/parse_file.py 资料/xxx.pdf
    python3 scripts/parse_file.py 资料/xxx.xlsx
    python3 scripts/parse_file.py test_report.txt      # 纯文本也支持
"""

import json, os, re, sys, time, httpx, asyncio

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def extract_file_text(filepath: str) -> tuple[str, str]:
    """提取文件文本。返回 (text, source_label)"""
    sys.path.insert(0, PROJ)
    from app.services.extractor import extract_text

    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        file_bytes = f.read()

    text = extract_text(filename, file_bytes)
    return text, filename

# ═══════════════════════════════════════════════════════════
C_GREEN  = "\033[32m"
C_RED    = "\033[31m"
C_YELLOW = "\033[33m"
C_CYAN   = "\033[36m"
C_BOLD   = "\033[1m"
C_RESET  = "\033[0m"


async def main():
    if len(sys.argv) < 2:
        print(f"用法: python3 scripts/parse_file.py <文件路径>")
        print(f"示例: python3 scripts/parse_file.py 资料/xxx.xlsx")
        print(f"      python3 scripts/parse_file.py report.pdf")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"{C_RED}❌ 文件不存在: {filepath}{C_RESET}")
        sys.exit(1)

    load_env()

    # 读取 System Prompt
    prompt_path = os.path.join(PROJ, "sp", "parser.txt")
    with open(prompt_path) as f:
        prompt = f.read()

    # 提取文本
    print(f"{C_CYAN}📄 文件: {filepath}{C_RESET}")
    file_size = os.path.getsize(filepath)
    print(f"{C_CYAN}   大小: {file_size:,} 字节{C_RESET}")

    text, filename = extract_file_text(filepath)
    print(f"{C_CYAN}   提取文本: {len(text)} 字符{C_RESET}")

    # 打印提取的文本（前 500 字）
    preview = text[:500].replace("\n", "\n    ")
    print(f"\n{C_BOLD}── 提取的文本预览 (前500字) ──{C_RESET}")
    print(f"    {preview}")
    if len(text) > 500:
        print(f"    ... (共 {len(text)} 字符)")

    # 调 DeepSeek V4
    api_key = os.environ["DEEPSEEK_API_KEY"]
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-reasoner")

    print(f"\n{C_YELLOW}⏳ 调用 {model} 解析中...{C_RESET}")

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
                    {"role": "user", "content": f"## 输入报告文本\n\n{text[:4000]}"},
                ],
                "temperature": 0.1,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        elapsed = time.time() - t0

    # ═══ 原始响应 ═══
    print(f"\n{C_BOLD}{'═'*60}{C_RESET}")
    print(f"{C_BOLD}  LLM 原始响应 ({len(raw)} 字符, {elapsed:.1f}s){C_RESET}")
    print(f"{C_BOLD}{'═'*60}{C_RESET}")
    print(raw)

    # ═══ 提取 JSON ═══
    json_match = re.search(r"```json\s*([\s\S]*?)```", raw)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        m = re.search(r"\{[\s\S]*\}", raw)
        json_str = m.group(0) if m else None

    if not json_str:
        print(f"\n{C_RED}❌ 未找到 JSON 输出{C_RESET}")
        return

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError:
        print(f"\n{C_RED}❌ JSON 解析失败: {json_str[:300]}{C_RESET}")
        return

    # ═══ 结构化展示 ═══
    print(f"\n{C_BOLD}{'═'*60}{C_RESET}")
    print(f"{C_BOLD}  解析结果{C_RESET}")
    print(f"{C_BOLD}{'═'*60}{C_RESET}")

    fields = ["part_no", "part_name", "test_type", "test_date", "test_result",
              "lab_name", "standard", "material", "material_spec",
              "tensile_strength", "hardness", "coating"]
    for f in fields:
        v = parsed.get(f)
        if v and v != "unknown" and v is not None:
            print(f"  {C_GREEN}{f:20s}{C_RESET} {v}")
        elif v == "unknown":
            print(f"  {C_RED}{f:20s}{C_RESET} unknown")
        else:
            print(f"  {f:20s} (null)")

    overall = parsed.get("overall_confidence")
    notes = parsed.get("notes", "")
    print(f"\n  {C_BOLD}overall_confidence:{C_RESET} {overall}")
    if notes:
        print(f"  {C_BOLD}notes:{C_RESET} {notes}")

    # ═══ 置信度柱状图 ═══
    conf = parsed.get("field_confidence", {})
    if conf:
        print(f"\n{C_BOLD}{'═'*60}{C_RESET}")
        print(f"{C_BOLD}  逐字段置信度{C_RESET}")
        print(f"{C_BOLD}{'═'*60}{C_RESET}")
        for k, v in conf.items():
            bar = C_GREEN + "█" * int(v * 20) + C_RESET + "░" * (20 - int(v * 20))
            color = C_RED if v < 0.5 else (C_YELLOW if v < 0.85 else C_GREEN)
            print(f"  {color}{k:20s} {bar} {v:.2f}{C_RESET}")

    # ═══ 诊断 ═══
    print(f"\n{C_BOLD}{'═'*60}{C_RESET}")
    if overall is not None:
        if overall >= 0.85:
            print(f"  {C_GREEN}✅ 整体置信度高 — 建议自动通过{C_RESET}")
        elif overall >= 0.5:
            print(f"  {C_YELLOW}⚠️  整体置信度中等 — 建议人工复核{C_RESET}")
        elif overall > 0:
            print(f"  {C_RED}❌ 整体置信度低 — 需要人工介入{C_RESET}")
        else:
            print(f"  {C_YELLOW}ℹ️  overall=0.0 — 非测试报告或无法识别{C_RESET}")


if __name__ == "__main__":
    asyncio.run(main())
