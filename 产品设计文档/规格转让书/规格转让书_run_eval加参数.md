# 规格转让书 — run_eval.py 加 --cases-file 参数

> **交付对象**：Code（Trae Solo Code）
> **日期**：2026-06-04
> **优先级**：P0（阻塞真实报告评测）

---

## 需求

给 `run_eval.py` 加 `--cases-file` 参数，支持指定评测数据文件。

### 改动前

```bash
python3 scripts/run_eval.py              # 只读 scripts/eval_cases.json
python3 scripts/run_eval.py --limit 5    # 只能跑前 5 条
```

### 改动后

```bash
python3 scripts/run_eval.py                                    # 默认读 eval_cases.json（21条）
python3 scripts/run_eval.py --cases-file eval_cases_real.json  # 读指定文件（5条真实报告）
```

---

## 实现要点

1. 新增 `--cases-file`，默认值 `eval_cases.json`
2. 文件路径相对于 `scripts/` 目录解析
3. 输入格式与现有 `eval_cases.json` 完全一致，无需改解析逻辑
4. 终端输出中标注用的是哪个数据文件（如 `Cases: eval_cases_real.json`）
5. 输出文件名也带后缀区分：`评测报告_real.md` / `评测数据_real.json`（取 cases-file 的 basename 去掉 `.json` 做后缀）

---

## 校验

```bash
python3 scripts/run_eval.py --cases-file eval_cases_real.json
# 应输出: Loaded 5 cases from eval_cases_real.json
# 输出文件: 评测/评测报告_real.md + 评测/评测数据_real.json
```
