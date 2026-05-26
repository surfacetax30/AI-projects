# 2节点MVP 编码规格 — 极简跑通版

> 交付对象：Trae Solo Code
> 目标：最快能跑通、能演示的核心闭环
> 范围：③ 报告解析 + ④ 资料完整性检查
> 预计代码量：~500 行

---

## 一、数据流（一次请求走完整条链）

```
POST /api/parts        → 创建 Part + ApprovalTask(state=CREATED)
POST /api/tasks/{id}/reports  → 上传 PDF/图片/Excel → 存储到 MinIO
                         → 发布 report.received 事件
后台消费                → 解析 Agent 调 DeepSeek → 提取字段+置信度
                         → 写入 ParsedReport
                         → 发布 report.parsed 事件
后台消费                → 资料 Agent 查清单模板 → 逐项核对
                         → 写入 ApprovalTask.missing_docs
                         → 发布 completeness.pass 或 completeness.fail
GET /api/tasks/{id}    → 返回：任务状态 + 解析结果 + 缺失项
```

---

## 二、待实现的文件（仅 5 个新文件 + 2 个修改）

### 2.1 新建文件

| # | 文件 | 核心内容 | 行数估算 |
|---|------|---------|:--:|
| F1 | `app/schemas/tasks.py` | Pydantic 请求/响应模型 | ~80 |
| F2 | `app/api/parts.py` | 零件 CRUD + 自动创建任务 | ~60 |
| F3 | `app/api/tasks.py` | 任务查询 + 报告上传 + 详情 | ~70 |
| F4 | `app/agents/parser.py` | 解析 Agent：下载MinIO文件→调LLM→提取字段→入库 | ~120 |
| F5 | `app/agents/data_checker.py` | 资料 Agent：查清单→核对→标记缺失 | ~80 |

### 2.2 修改已有文件

| # | 文件 | 改动 |
|---|------|------|
| M1 | `app/main.py` | 注册 router，lifespan 中启动 Agent |
| M2 | `app/db/models.py` | 新增 ChecklistTemplate 表 |

**不动的文件：** `events/bus.py`, `events/types.py`, `services/llm.py`, `config.py`, `db/session.py` — 全部直接复用。

---

## 三、逐文件实现规格

### F1 — `app/schemas/tasks.py`

```python
from pydantic import BaseModel, Field
from datetime import datetime

# ── 请求 ──
class PartCreate(BaseModel):
    part_no: str
    part_name: str
    part_type: str                # "金属支架" | "域控制器" | "塑料件"
    supplier: str
    project_code: str
    is_new: bool = True

# ── 响应 ──
class PartOut(BaseModel):
    id: str
    part_no: str
    part_name: str
    part_type: str
    supplier: str
    project_code: str
    is_new: bool
    created_at: datetime

class TaskOut(BaseModel):
    id: str
    part_id: str
    state: str
    overall_confidence: float | None
    missing_docs: list | None
    created_at: datetime
    updated_at: datetime

class ParsedReportOut(BaseModel):
    id: str
    task_id: str
    test_type: str
    test_date: str
    lab_name: str
    fields: dict                  # 解析出的所有字段
    confidence_per_field: dict
    overall_confidence: float
    created_at: datetime

class TaskDetail(BaseModel):
    task: TaskOut
    part: PartOut
    reports: list[ParsedReportOut]
    missing_items: list[dict]     # [{item_code, item_name, required}]
```

### F2 — `app/api/parts.py`

```
POST /api/parts
    body: PartCreate
    → 1. 创建 Part 记录
    → 2. 创建 ApprovalTask(state=CREATED)
    → 3. 返回 {part, task}

GET /api/parts
    → 分页查询 Part 列表（可选 query params: page, size）
```

**关键逻辑：**
```python
@router.post("/api/parts", response_model=dict)
async def create_part(body: PartCreate, db = Depends(get_db)):
    part = Part(**body.model_dump())
    db.add(part)
    await db.flush()
    
    task = ApprovalTask(part_id=part.id, state="CREATED")
    db.add(task)
    await db.commit()
    
    return {"part": part, "task": task}
```

### F3 — `app/api/tasks.py`

```
GET  /api/tasks/{task_id}
    → 返回 TaskDetail：任务 + 零件 + 解析报告列表 + 缺失项
    → 按创建时间倒序排列报告

POST /api/tasks/{task_id}/reports
    → multipart/form-data, field: "file"
    → 1. 上传文件到 MinIO (bucket: ots-reports, path: {task_id}/{filename})
    → 2. 通过事件关联 task_id (从上传文件名或元数据匹配)
    → 3. 发布 report.received 事件
    → 4. 返回 {storage_path, task_id}
    
    联task_id方式：上传时附带 task_id form field
```

**MinIO 上传实现提示：**
```python
from minio import Minio
mc = Minio(endpoint, access_key, secret_key, secure=False)
mc.put_object(bucket, f"{task_id}/{filename}", file_obj, length)
```

### F4 — `app/agents/parser.py`

这是整个 MVP 最核心、最复杂的文件。

**类结构：**
```python
class ParserAgent(BaseAgent):
    """
    订阅: report.received
    发布: report.parsed | report.parse_failed
    
    流程:
    1. 收到 report.received → 根据 storage_path 从 MinIO 下载文件
    2. 读文件内容 → 转成 base64/文本 → 构造 system prompt + user message
    3. 调 DeepSeek API (复用 app/services/llm.py 的 LLMClient)
    4. 解析 LLM 返回的 JSON → 提取 fields + confidence_per_field
    5. 写入 ParsedReport 表
    6. 发布 report.parsed 事件
    """
```

**System Prompt 关键内容：**
```
你是一个汽车零部件测试报告解析专家。请从测试报告中提取以下字段，并对每个字段给出0-1的置信度评分。

必须提取的字段：
- part_no: 零件号
- material: 材料牌号
- material_spec: 材料标准
- test_type: 测试类型 (EMC/DV/PV/HIL/盐雾/振动)
- test_date: 测试日期
- lab_name: 实验室名称
- tensile_strength: 抗拉强度(MPa), 如无则为 null
- hardness: 硬度, 如无则为 null
- coating: 表面处理, 如无则为 null
- test_result: 测试结论 (PASS/FAIL/条件通过)

返回严格 JSON 格式：
{"fields": {...}, "confidence_per_field": {...}, "overall_confidence": 0.xx}
```

**三层纠错（简化版）：**
```python
async def _parse_with_retry(self, file_content, file_type):
    for attempt in range(3):
        try:
            raw = await llm.chat(SYSTEM_PROMPT, user_msg)
            result = json.loads(raw)  # L1: 格式校验
            self._validate_semantic(result)  # L2: 语义校验
            return result
        except json.JSONDecodeError:
            if attempt < 2: continue  # 重试
        except SemanticError:
            if attempt < 1: continue  # L2 只重试一次
    # L3: 降级
    return {"fields": {}, "confidence_per_field": {}, "overall_confidence": 0.0, "fallback": True}
```

**文件类型处理：**
- `.pdf` → 用 `pypdf` 或 `pdfplumber` 提取文本
- `.png/.jpg` → base64 编码后走多模态 API
- `.xlsx` → 用 `openpyxl` 读取，转成 markdown 表格

### F5 — `app/agents/data_checker.py`

```python
class DataCheckerAgent(BaseAgent):
    """
    订阅: report.parsed
    发布: completeness.pass | completeness.fail
    
    流程:
    1. 收到 report.parsed → 根据 task.part.type 查询 ChecklistTemplate
    2. 从 ParsedReport.fields 中逐项核对
    3. 生成 missing_items 列表
    4. 更新 ApprovalTask (missing_docs, 状态 → CHECKED)
    5. 发布 completeness.pass 或 completeness.fail
    """
```

**清单模板（硬编码 3 种类型，MVP 阶段）：**
```python
CHECKLISTS = {
    "金属支架": [
        {"code": "MAT-01", "name": "材质证明", "field": "material"},
        {"code": "MAT-02", "name": "材料标准", "field": "material_spec"},
        {"code": "MEC-01", "name": "抗拉强度", "field": "tensile_strength"},
        {"code": "MEC-02", "name": "硬度", "field": "hardness"},
        {"code": "SUR-01", "name": "表面处理", "field": "coating"},
    ],
    "域控制器": [
        {"code": "EMC-01", "name": "EMC测试报告", "field": "test_type"},
        {"code": "ENV-01", "name": "环境测试报告", "field": "test_type"},
        {"code": "FUN-01", "name": "功能测试报告", "field": "test_type"},
        {"code": "MAT-01", "name": "PCB材质", "field": "material"},
    ],
    "塑料件": [
        {"code": "MAT-01", "name": "材质证明", "field": "material"},
        {"code": "MAT-03", "name": "阻燃等级", "field": "flammability"},
        {"code": "ENV-02", "name": "耐候测试", "field": "weathering"},
        {"code": "DIM-01", "name": "尺寸报告", "field": "dimensions"},
    ],
}
```

**核对逻辑：**
```python
def _check(self, fields: dict, checklist: list) -> tuple[list, list]:
    passed, missing = [], []
    for item in checklist:
        value = fields.get(item["field"])
        if value is not None and value != "":
            passed.append(item)
        else:
            missing.append(item)
    return passed, missing
```

### M1 — 修改 `app/main.py`

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.api.parts import router as parts_router
from app.api.tasks import router as tasks_router
from app.agents.parser import ParserAgent
from app.agents.data_checker import DataCheckerAgent

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await event_bus.start()
    
    # 启动两个 Agent
    parser = ParserAgent()
    checker = DataCheckerAgent()
    await parser.start()
    await checker.start()
    
    yield
    
    await checker.stop()
    await parser.stop()
    await event_bus.stop()

app = FastAPI(title="OTS-AHA MVP", version="0.1.0", lifespan=lifespan)
app.include_router(parts_router)
app.include_router(tasks_router)

# 可选：托管静态文件用于文件上传测试
# app.mount("/static", StaticFiles(directory="app/static"), name="static")
```

### M2 — 修改 `app/db/models.py`

追加一行 ChecklistTemplate 表（可选 — 也可以先硬编码在 data_checker.py 里）。

**如果要查数据库：**
```python
class ChecklistTemplate(Base):
    __tablename__ = "checklist_templates"
    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    part_type: Mapped[str] = mapped_column(String(64), index=True)
    items: Mapped[list] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(default=True)
```

---

## 四、install_deps 补充

```bash
pip install python-multipart openpyxl pypdf pdfplumber --break-system-packages
```

已有依赖全部可用（fastapi, uvicorn, sqlalchemy, asyncpg, minio, httpx, pydantic）。

---

## 五、状态流转（3 状态）

```
CREATED ──(上传报告)──→ PARSING ──(解析完成)──→ CHECKED
                             │
                             └──(解析失败)──→ 保持 PARSING
```

不做完整状态机，直接在 Agent 里更新 `ApprovalTask.state`。

---

## 六、验收标准

| # | 操作 | 预期结果 |
|---|------|---------|
| 1 | `POST /api/parts` 创建一个零件 | 返回 part + task(state=CREATED) |
| 2 | `POST /api/tasks/{id}/reports` 上传一个 PDF | 文件存到 MinIO，返回 storage_path |
| 3 | 等待 5-30 秒（LLM 解析） | `GET /api/tasks/{id}` 返回 parsed report + fields + confidence |
| 4 | 字段缺失（如无硬度值） | missing_items 列表包含对应项 |
| 5 | 所有字段齐全 | missing_items 为空，state=CHECKED |

---

## 七、启动命令

```bash
# 1. 启动基础设施
docker compose up -d

# 2. 初始化 MinIO bucket
docker exec ots-minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker exec ots-minio mc mb local/ots-reports --ignore-existing

# 3. 启动应用
uvicorn app.main:app --reload --port 8000

# 4. 测试
curl -X POST http://localhost:8000/api/parts \
  -H "Content-Type: application/json" \
  -d '{"part_no":"TEST-001","part_name":"前保险杠支架","part_type":"金属支架","supplier":"XX公司","project_code":"P2026","is_new":true}'

curl -X POST http://localhost:8000/api/tasks/{task_id}/reports \
  -F "file=@test_report.pdf" \
  -F "task_id={task_id}"

curl http://localhost:8000/api/tasks/{task_id}
```

---

*此规格仅涵盖2个核心AI节点，其余功能（邮件监听、通知、Web工作台、返工、会签）均不在此范围。*
