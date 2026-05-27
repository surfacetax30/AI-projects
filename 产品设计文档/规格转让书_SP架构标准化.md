# 规格转让书 — SP 架构标准化

> **交付对象**：Code（Trae Solo Code）
> **设计者**：Solo（Trae Solo）
> **日期**：2026-05-28
> **优先级**：P0（阻塞当前 Parser SP 迭代）

---

## 一、问题陈述

### 1.1 当前架构的问题

```
┌──────────────────────────────┐      ┌──────────────────────────────┐
│  parser.py (API 管线)        │      │  parse_file.py (CLI 测试)     │
│                              │      │                              │
│  SYSTEM_PROMPT = """..."""  │      │  read("system_prompt.txt")   │
│  模块级常量（import 时加载）   │      │  每次调用前从文件读取           │
└──────────────────────────────┘      └──────────────────────────────┘
         ↑ 手工同步 ？                         ↑ Solo 直接编辑
    ┌─────────────────────────────────────────────┐
    │  system_prompt.txt  (Solo 的真相关件)         │
    │  当前版本：field_status 三态 + 加权置信度      │
    └─────────────────────────────────────────────┘
```

**存在两个致命问题**：

1. **知识漂移**：Solo 在 `system_prompt.txt` 中迭代 SP 后，`parser.py` 中的 `SYSTEM_PROMPT` 常量不会自动更新。当前 `system_prompt.txt` 已包含 `field_status` + 加权置信度计算，但 `parser.py` 还是旧版本——**API 管线实际跑的是过期 SP**。

2. **SP 散落各处**：SP 文件（`system_prompt.txt`、可能的 `sp/data_checker.txt`）散落在项目根目录，没有统一的组织方式。

### 1.2 目标架构

```
sp/                         ← 新建目录，SP 的单一真相源
├── parser.txt              ← 从 system_prompt.txt 迁移
└── (data_checker.txt)      ← 预留，DataChecker LLM 化时需要

app/services/sp_loader.py   ← 新建，SP 加载工具（缓存 + 校验）
app/agents/parser.py        ← 改造：删除 SYSTEM_PROMPT 常量，改为从 sp_loader 加载
scripts/parse_file.py       ← 改造：改为从 sp/parser.txt 读取
```

**核心原则**：
- **文件即真相**：改 SP 就是改 `sp/*.txt`，不需要改代码
- **一处读取**：所有组件通过 `sp_loader` 读同一个文件
- **评测一致**：CLI 工具和 API 管线跑的是同一个 SP

---

## 二、改动清单

### 2.1 新建 `sp/` 目录和 SP 文件

**操作**：
```
mkdir sp/
mv system_prompt.txt sp/parser.txt
```

> 旧文件 `system_prompt.txt` 是否保留由 Solo 决定（建议删除或加 deprecation 注释，避免后续混淆）。

---

### 2.2 新建 `app/services/sp_loader.py`

**用途**：所有 Agent 读取 SP 的统一入口。支持缓存（避免每次调用读磁盘）和校验（确保不是空文件）。

**完整代码**：

```python
"""SP loader — single source of truth for all agent system prompts."""

import os
from typing import Optional

# sp/ 目录的绝对路径（相对于项目根目录）
_SP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "sp")

_cache: dict[str, str] = {}


def load_sp(name: str, use_cache: bool = True) -> str:
    """Load a system prompt file from sp/ directory.

    Args:
        name: SP 文件名（不含 .txt 后缀），如 "parser" 对应 sp/parser.txt
        use_cache: 是否使用缓存（默认 True，进程生命周期内只读一次文件）

    Returns:
        SP 文本内容

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 文件内容为空
    """
    if use_cache and name in _cache:
        return _cache[name]

    filepath = os.path.join(_SP_DIR, f"{name}.txt")
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"SP file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.strip():
        raise ValueError(f"SP file is empty: {filepath}")

    _cache[name] = content
    return content


def reload_sp(name: str) -> str:
    """强制重新加载 SP（跳过缓存）。"""
    _cache.pop(name, None)
    return load_sp(name, use_cache=False)


def get_sp_dir() -> str:
    """返回 sp/ 目录的绝对路径。"""
    return _SP_DIR


def list_sp_files() -> list[str]:
    """列出 sp/ 目录下所有 .txt 文件（不含扩展名）。"""
    if not os.path.isdir(_SP_DIR):
        return []
    return [
        f.replace(".txt", "")
        for f in os.listdir(_SP_DIR)
        if f.endswith(".txt")
    ]
```

**接口说明**：

| 函数 | 用途 | 调用者 |
|------|------|--------|
| `load_sp("parser")` | 加载 parser 的 SP（默认缓存） | `parser.py`, `parse_file.py` |
| `load_sp("data_checker")` | 加载 data_checker 的 SP | `data_checker.py`（未来） |
| `reload_sp("parser")` | 强制重新加载（用于热更新/测试） | 未来管理 API |
| `list_sp_files()` | 列出所有 SP 文件 | 健康检查/管理 API |
| `get_sp_dir()` | 获取 sp/ 目录路径 | 工具脚本 |

**缓存策略**：
- 默认 `use_cache=True`：进程生命周期内只读一次文件，减少磁盘 I/O
- `reload_sp()` 清缓存后重新加载：用于管理 API 的热更新场景
- 缓存是模块级 dict，线程安全（Python GIL 保证），async 安全（纯内存读取）

---

### 2.3 改造 `app/agents/parser.py`

**改动点**：删除模块级 `SYSTEM_PROMPT` 常量，改为从 `sp_loader` 加载。

**具体操作**：

1. **删除** 第 9 行到最后一个 Few-Shot 示例结束的 `SYSTEM_PROMPT = """..."""` 常量定义块（约 310 行）

2. **新增** import 和加载逻辑。在文件顶部 import 区添加：

```python
from app.services.sp_loader import load_sp
```

3. 在 `ReportParser` 类的 `__init__` 方法（或类属性）中加载 SP：

当前 `parser.py` 的 `__init__` 可能不存在，需要新增。SP 在 init 时加载一次，存入 `self._system_prompt`。

**改造后的 `ReportParser` 类框架**：

```python
class ReportParser(BaseAgent):
    name = "parser"

    def __init__(self):
        # 进程启动时加载一次 SP，后续所有请求复用
        self._system_prompt = load_sp("parser")

    async def process(self, payload: dict) -> dict:
        # ... 原有逻辑不变 ...
        # 唯一改动：把 llm.chat(system_prompt=SYSTEM_PROMPT, ...) 
        #          改为 llm.chat(system_prompt=self._system_prompt, ...)
```

4. 把第 321 行的 `system_prompt=SYSTEM_PROMPT` 改为 `system_prompt=self._system_prompt`

**关键约束**：
- `load_sp("parser")` 在 `__init__` 中只调用**一次**（进程启动时），不是每次 `process()` 调用时读取
- 如果文件不存在/为空，`load_sp` 会抛异常 → 导致 `ReportParser()` 初始化失败 → 服务启动失败（fail-fast 原则，比运行中静默错误好）

---

### 2.4 改造 `scripts/parse_file.py`

**改动点**：读取路径从 `system_prompt.txt` 改为 `sp/parser.txt`。

**具体操作**：

当前代码（约第 63 行）：
```python
prompt_path = os.path.join(PROJ, "system_prompt.txt")
```

改为：
```python
prompt_path = os.path.join(PROJ, "sp", "parser.txt")
```

> 如果 `parse_file.py` 未来想要更规范，可以直接 import `sp_loader`：
> ```python
> sys.path.insert(0, PROJ)
> from app.services.sp_loader import load_sp
> prompt = load_sp("parser")
> ```
> 但当前先保持最小改动即可。

---

### 2.5 可选改造：`test_system_prompt_eval.py` 和 `test_prompt.py`

如果这两个测试脚本中也硬编码了 SP 路径，同样改为 `sp/parser.txt`。Code 自行 grep 搜索 `system_prompt.txt` 引用，逐一改为新路径。

---

### 2.6 可选改造：`BaseAgent` 增加 SP 加载能力

如果未来多个 Agent 都需要 SP，可以在 `BaseAgent` 中加一个 util：

```python
# app/agents/base.py

class BaseAgent(ABC):
    name: str

    @staticmethod
    def load_sp(name: str) -> str:
        """便捷方法：加载 sp/{name}.txt"""
        from app.services.sp_loader import load_sp
        return load_sp(name)
```

这样所有子类可以直接 `prompt = self.load_sp("parser")`，不需要每个 agent 单独 import `sp_loader`。

**此项为可选，Code 自行判断是否值得做。**

---

## 三、改动影响范围评估

| 改动 | 影响文件数 | 风险等级 | 说明 |
|------|:---:|:---:|------|
| 新建 `sp/` + 移动文件 | 1 个目录 + 1 次 mv | 🟢 无风险 | 纯文件操作 |
| 新建 `sp_loader.py` | 1 个新文件 | 🟢 无风险 | 独立模块，不依赖其他改动 |
| 改造 `parser.py` | 1 个文件 | 🟡 低风险 | 删除 ~310 行常量，新增 ~3 行。逻辑不变 |
| 改造 `parse_file.py` | 1 个文件 | 🟢 无风险 | 改 1 行路径 |
| 改造测试脚本 | 0-2 个文件 | 🟢 无风险 | 路径替换 |

> 改动的核心是**删除** `parser.py` 中的硬编码常量，改为读文件。Parser 的 `process()` 方法逻辑完全不变。

---

## 四、校验清单（Code 完成开发后自检）

| # | 检查项 | 验证方式 |
|---|--------|---------|
| 1 | `sp/parser.txt` 存在且内容与旧 `system_prompt.txt` 一致 | `diff sp/parser.txt system_prompt.txt`（如果旧文件还在） |
| 2 | `parser.py` 中不再包含 `SYSTEM_PROMPT = """` | `grep "SYSTEM_PROMPT" app/agents/parser.py` 无结果 |
| 3 | 服务启动成功（SP 文件存在） | `python -m uvicorn app.main:app` 无报错 |
| 4 | 服务启动失败（SP 文件不存在） | 临时 `mv sp/parser.txt sp/parser.txt.bak`，启动应抛 `FileNotFoundError` |
| 5 | `parse_file.py` 能正常读取 SP | `python3 scripts/parse_file.py "real_OTS_data/五菱E260S低规项目 89 【V40021】版本测试报告_20250209.docx"` 跑通 |
| 6 | 上传报告 API 返回正确的解析结果 | `curl` 或前端上传一份报告，返回的 JSON 包含 `field_status` |
| 7 | `sp_loader.load_sp("parser")` 两次调用返回同一对象（缓存生效） | `assert load_sp("parser") is load_sp("parser")` |

---

## 五、未来扩展指引（不在此次改动中实现）

以下内容仅作为设计预留，Code 无需在本次开发中实现：

1. **管理 API**：`GET /api/admin/sp/reload?name=parser` → 调用 `reload_sp("parser")`，实现不重启服务更新 SP
2. **健康检查**：`GET /health` 中增加 SP 校验：`list_sp_files()` 确认所有必需 SP 存在
3. **DataChecker LLM 化**：新建 `sp/data_checker.txt`，`DataChecker.__init__` 调用 `load_sp("data_checker")`，`process()` 中调用 LLM
4. **MailGateway SP**：如果未来升级为 LLM 做意图识别，新建 `sp/mail_gateway.txt`

---

## 六、实施步骤总结

```
Step 1: mkdir sp/
Step 2: cp system_prompt.txt sp/parser.txt   （复制，保留旧文件作为过渡）
Step 3: 创建 app/services/sp_loader.py       （按 2.2 代码）
Step 4: 改造 app/agents/parser.py
        - 删除 SYSTEM_PROMPT 常量
        - 新增 import + __init__ 加载
        - 修改 llm.chat() 调用参数
Step 5: 改造 scripts/parse_file.py           （改 1 行路径）
Step 6: 全局搜索 "system_prompt.txt"，替换所有引用
Step 7: 启动服务 + 跑 parse_file.py 验证
Step 8: 确认无误后删除旧 system_prompt.txt
```
