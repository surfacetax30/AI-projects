# 规格转让书 — 零件 OTS 认可 AI Agent MVP

> 交付对象：Trae Solo Code（编码实现）
> 产品设计方：Trae Solo（本会话）
> 版本：V2.0 MVP
> 日期：2026-05-27

---

## 〇、编码前置原则（来自 Superpowers 方法论）

1. **brainstorming** 已完成 → PRD + 架构图已产出，设计已确认
2. **writing-plans**（本文档）→ 任务拆分到 2-5 分钟粒度
3. **test-driven-development** → 先写测试，看到失败，再写最小实现
4. **subagent-driven-development** → 每个任务用独立 subagent，两轮审查（spec 合规 + 代码质量）
5. **YAGNI** → MVP 不做的坚决不写

---

## 一、MVP 目标

**1 个月内，1 人（+AI），交付可演示的 OTS 认可自动化流水线：**

- PE 通过 Web 表单录入零件 → 自动创建认可任务
- 系统持续监听邮箱 → 自动下载测试报告附件
- LLM 自动解析 PDF/图片/Excel → 提取结构化字段
- 自动核对资料完整性 → 缺失提醒
- PE 在 Web 工作台确认低置信度节点
- 全流程状态可追踪

---

## 二、编码任务清单（共 8 个 Phase，22 个 Task）

### Phase 0：基础设施（必须先完成）

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| T01 | **创建 .env 文件** | `.env` | 所有必需变量完整，values 用占位符 |
| T02 | **完善 docker-compose** | `docker-compose.yml` | `docker compose up -d` 能启动 PG + MinIO + pgvector |
| T03 | **Alembic 初始化 + 首次迁移** | `alembic/` + `alembic.ini` | `alembic upgrade head` 创建全部表 |

### Phase 1：核心基础设施

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| T04 | **补充 ORM 模型** | `app/db/models.py` | 新增 TestApplication / ReworkRecord / NotificationLog / ChecklistTemplate / AnomalyLog 五张表 |
| T05 | **实现状态机** | `app/agents/orchestrator.py` | 8 状态 + 路由决策表，`transition(task, event) → (new_state, actions)`，不调 LLM |
| T06 | **事件总线订阅绑定** | `app/agents/orchestrator.py` + `app/main.py` | 编排 Agent 订阅全部 13 种事件，状态变更触发通知 |
| T07 | **通知消费者协程** | `app/agents/notifier.py` | 消费 notify.send 事件，调用邮件 + IM 发送 (MVP 只打 log) |

### Phase 2：邮件网关 Agent

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| T08 | **IMAP 监听 + 规则过滤** | `app/agents/mail_gateway.py` | IDLE 模式监听，按发件人/主题/附件名过滤，下载附件到 MinIO |
| T09 | **附件下载 + 文件校验** | `app/agents/mail_gateway.py` | 支持 .pdf/.docx/.xlsx/.jpg/.png，MD5 校验，发布 report.received 事件 |

### Phase 3：解析 Agent

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| T10 | **多模态文件解析** | `app/agents/parser.py` | 调用 DeepSeek API 解析 PDF/图片/Excel，输出结构化字段 |
| T11 | **LLM 输出解析 + 置信度评分** | `app/agents/parser.py` | 按 Python dataclass 解析 JSON，逐字段置信度，≥0.85 自动过 |
| T12 | **三层纠错机制** | `app/agents/parser.py` | L1 格式修复(2次) → L2 语义修复(1次) → L3 降级标记 |

### Phase 4：资料 Agent

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| T13 | **动态清单模板** | `app/agents/data_checker.py` | 按零件类型返回检查项列表（JSON 配置，MVP 至少支持 3 种零件类型） |
| T14 | **规则引擎核对** | `app/agents/data_checker.py` | 逐项判有/无，生成缺失项清单 |
| T15 | **LLM 语义等价检查** | `app/agents/data_checker.py` | 材料牌号等效判定、版本关系判定（异步，不阻塞主核对） |
| T16 | **缺失提醒 + 超时升级** | `app/agents/data_checker.py` | 缺失时发布 completeness.fail，3 天超时发布 supplement.reminder |

### Phase 5：API 路由

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| T17 | **零件 CRUD + 任务创建** | `app/api/parts.py` | POST/GET /api/parts, POST /api/parts → 自动创建 ApprovalTask |
| T18 | **任务查询 + 详情** | `app/api/tasks.py` | GET /api/tasks?state=, GET /api/tasks/{id} 含报告/异常/时间线 |
| T19 | **人工确认 + 纠错接口** | `app/api/tasks.py` | POST /api/tasks/{id}/confirm, POST /api/tasks/{id}/correct |
| T20 | **统计接口 + Webhook** | `app/api/stats.py` + `app/api/webhooks.py` | GET /api/stats, POST /api/webhooks/mail (IMAP 备选方案) |

### Phase 6：Web 工作台（MVP 极简版）

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| T21 | **任务看板页面** | `app/static/index.html` | 任务列表 + 状态筛选 + 简易详情弹窗 |
| T22 | **人工确认交互** | `app/static/index.html` | 低置信度字段高亮 + 确认/修正/驳回按钮 |

---

## 三、事件 Payload 精确定义

> 实现时直接用 Python dataclass / TypedDict

### 3.1 report.received（邮件网关 → 事件总线）

```python
{
    "task_id": str,              # ApprovalTask.id
    "part_no": str,              # 从邮件主题提取
    "mail_subject": str,
    "mail_from": str,
    "mail_date": str,            # ISO 8601
    "attachment_ids": [str],     # MinIO object paths
    "attachment_names": [str],   # 原始文件名
}
```

### 3.2 report.parsed（解析 Agent → 编排 Agent）

```python
{
    "task_id": str,
    "part_no": str,
    "test_type": str,            # "EMC" | "DV" | "HIL" | ...
    "test_date": str,
    "lab_name": str,
    "fields": {                  # 提取的所有字段
        "material": str,
        "material_spec": str,
        "tensile_strength": float | None,
        "hardness": str | None,
        "coating": str | None,
        # ... 动态扩展
    },
    "confidence_per_field": {
        "material": 0.95,
        "tensile_strength": 0.72,  # 低于 0.85 → HUMAN_PENDING
    },
    "overall_confidence": float,
    "storage_path": str,         # MinIO 原始文件路径
    "anomalies": [               # 提取阶段检测的异常
        {
            "type": "value_out_of_range",
            "field": "tensile_strength",
            "value": 9999,
            "expected_range": [200, 800],
            "severity": "major",
        }
    ],
}
```

### 3.3 report.parse_failed（解析 Agent → 编排 Agent）

```python
{
    "task_id": str,
    "storage_path": str,
    "error_type": str,           # "format_error" | "empty_document" | "unsupported_format" | "llm_error"
    "error_detail": str,
    "retry_count": int,          # 0-2
    "retry_limit_reached": bool, # True → 等待人工
}
```

### 3.4 completeness.pass / completeness.fail（资料 Agent → 编排 Agent）

```python
{
    "task_id": str,
    "checklist_id": str,         # 使用的清单模板 ID
    "checked_at": str,           # ISO 8601
    "total_items": int,
    "passed_items": int,
    "missing_items": [           # completeness.fail 时有值
        {
            "item_code": str,    # 清单项编码, e.g. "MAT-01"
            "item_name": str,    # "材质证明"
            "required": true,
            "deadline_hours": 72,
        }
    ],
    "conflict_items": [          # 版本冲突 / 语义冲突
        {
            "item_code": str,
            "description": str,
            "expected_from_dwg": str,
            "found_in_report": str,
        }
    ],
    "semantic_check_passed": bool | None,  # LLM 语义等价结果 (可能为 None = 未检查)
}
```

### 3.5 anomaly.detected / anomaly.none（解析/报告 Agent → 编排 Agent）

```python
{
    "task_id": str,
    "source_agent": str,         # "parser" | "data_checker"
    "anomalies": [
        {
            "id": str,
            "type": str,         # "value_out_of_range" | "field_mismatch" | "version_conflict" | ...
            "field": str,
            "severity": str,     # "minor" | "major" | "critical"
            "value": Any,
            "expected": Any,
            "suggestion": str,
        }
    ],
}
```

### 3.6 human.confirmed / human.corrected / human.rejected（Web → 编排 Agent）

```python
{
    "task_id": str,
    "node_id": str,              # "H1" ~ "H10"
    "confirmed_by": str,         # PE 姓名 / ID
    "confirmed_at": str,         # ISO 8601
    # human.confirmed 专用
    "decision": str,             # "approve" | "rework"
    "comment": str,
    # human.corrected 专用
    "corrections": [
        {"field": str, "original": Any, "corrected": Any}
    ],
    # human.rejected 专用
    "reason": str,
}
```

### 3.7 task.state_changed（编排 Agent → 通知消费者）

```python
{
    "task_id": str,
    "part_no": str,
    "from_state": str,
    "to_state": str,
    "trigger_event": str,        # 触发此次变更的事件类型
    "timestamp": str,
}
```

### 3.8 rework.triggered（编排 Agent → 通知消费者）

```python
{
    "task_id": str,
    "part_no": str,
    "severity": str,             # "minor" | "major" | "critical"
    "reason": str,
    "suggested_scope": str,      # LLM 建议的返工范围
    "supplier": str,
    "triggered_at": str,
}
```

### 3.9 notify.send（任一方 → 通知消费者协程）

```python
{
    "task_id": str,
    "channel": str,              # "email" | "im" | “both”
    "template_key": str,         # 模板标识，如 "supplement_reminder", "approval_needed"
    "recipients": [
        {"name": str, "email": str, "im_id": str | None}
    ],
    "context": {                 # 模板变量
        "part_no": str,
        "deadline": str | None,
        "missing_count": int | None,
        "message": str,
    },
    "priority": str,             # "normal" | "urgent"
}
```

---

## 四、数据库补充模型

> 追加到现有 `app/db/models.py`，与已有 Part / ApprovalTask / ParsedReport / EventLog 共存。

```python
# ── 测试申请记录 (节点②) ──
class TestApplication(Base):
    __tablename__ = "test_applications"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    task_id: Mapped[str] = mapped_column(String(12), index=True)
    test_types: Mapped[list] = mapped_column(JSON)          # ["EMC", "DV"]
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(16))       # "normal" | "urgent"
    mail_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    mail_message_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ── 检查清单模板 ──
class ChecklistTemplate(Base):
    __tablename__ = "checklist_templates"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    part_type: Mapped[str] = mapped_column(String(64), index=True)  # "域控制器" / "金属支架" / "塑料件"
    items: Mapped[list] = mapped_column(JSON)                       # [{"code":"MAT-01","name":"材质证明","required":true}]
    version: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ── 异常记录 ──
class AnomalyLog(Base):
    __tablename__ = "anomaly_logs"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    task_id: Mapped[str] = mapped_column(String(12), index=True)
    source_agent: Mapped[str] = mapped_column(String(32))           # "parser" | "data_checker"
    anomaly_type: Mapped[str] = mapped_column(String(32))           # "value_out_of_range" | "field_mismatch" | ...
    field_name: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))               # "minor" | "major" | "critical"
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved: Mapped[bool] = mapped_column(default=False)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ── 返工记录 ──
class ReworkRecord(Base):
    __tablename__ = "rework_records"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    task_id: Mapped[str] = mapped_column(String(12), index=True)
    trigger_anomaly_id: Mapped[str | None] = mapped_column(String(12), nullable=True)
    severity: Mapped[str] = mapped_column(String(16))               # "minor" | "major" | "critical"
    reason: Mapped[str] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)  # LLM 建议的返工范围
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # PENDING → CONFIRMED → COMPLETED
    confirmed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supplier_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ── 通知发送记录 ──
class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(12), index=True)
    channel: Mapped[str] = mapped_column(String(16))                # "email" | "im"
    template_key: Mapped[str] = mapped_column(String(32))
    recipients: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))                 # "sent" | "failed"
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

---

## 五、API 路由精确定义

### 5.1 零件 & 任务

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/parts` | 创建零件 + 自动创建任务 |
| `GET` | `/api/parts` | 零件列表 `?page=&size=&q=` |
| `GET` | `/api/parts/{part_id}` | 零件详情 + 关联任务 |
| `GET` | `/api/tasks` | 任务列表 `?state=&part_no=&page=` |
| `GET` | `/api/tasks/{task_id}` | 任务详情：基本信息 + 报告列表 + 异常列表 + 事件时间线 |
| `POST` | `/api/tasks/{task_id}/confirm` | PE 确认（body: `{node_id, decision, comment}`） |
| `POST` | `/api/tasks/{task_id}/correct` | PE 纠错（body: `{corrections: [{field, original, corrected}]}`） |
| `POST` | `/api/tasks/{task_id}/reject` | PE 驳回（body: `{node_id, reason}`） |
| `GET` | `/api/tasks/{task_id}/reports` | 该任务的解析报告列表 |
| `GET` | `/api/tasks/{task_id}/anomalies` | 该任务的异常列表 |
| `GET` | `/api/tasks/{task_id}/timeline` | 事件时间线 |

### 5.2 统计 & 回调

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats` | 仪表盘数据：各状态任务数、本周处理量、平均周期 |
| `POST` | `/api/webhooks/mail` | 邮件 Webhook（IMAP 备选方案） |

### 5.3 请求/响应 Schema 示例

```python
# POST /api/parts
{
    "part_no": "ABC-12345-67",
    "part_name": "前保险杠支架",
    "part_type": "金属支架",
    "supplier": "XX汽车零部件有限公司",
    "project_code": "P2026-001",
    "is_new": true
}

# Response
{
    "part": {
        "id": "a1b2c3d4e5f6",
        "part_no": "ABC-12345-67",
        "part_name": "前保险杠支架",
        "part_type": "金属支架",
        "supplier": "XX汽车零部件有限公司",
        "project_code": "P2026-001",
        "is_new": true,
        "created_at": "2026-05-27T10:00:00"
    },
    "task": {
        "id": "f6e5d4c3b2a1",
        "state": "CREATED",
        "created_at": "2026-05-27T10:00:00"
    }
}

# GET /api/tasks/{task_id}
{
    "task": { "id": "...", "state": "REPORT_COLLECTING", "part_no": "...", ... },
    "reports": [ /* ParsedReport list */ ],
    "anomalies": [ /* AnomalyLog list */ ],
    "timeline": [
        {"event": "task.state_changed", "detail": "CREATED → TEST_APPLYING", "time": "..."},
        ...
    ]
}
```

---

## 六、状态机路由决策表

> 实现为一个纯函数：`def decide_next(event_type: str, current_state: str, context: dict) -> tuple[str, list[str]]`
> 返回 `(next_state, [actions])`。actions 是字符串："publish_rework_triggered", "publish_notify", "set_human_pending_flag" 等。

| 当前状态 | 触发事件 | 下一状态 | 动作 |
|---------|---------|---------|------|
| CREATED | (API 触发) | TEST_APPLYING | 发布 task.state_changed |
| TEST_APPLYING | (PE 确认) | TESTING | 发布 task.state_changed |
| TESTING | (PE/定时 触发) | REPORT_COLLECTING | 发布 task.state_changed |
| REPORT_COLLECTING | report.received | REPORT_COLLECTING | 触发解析 Agent |
| REPORT_COLLECTING | report.parsed | DATA_ORGANIZING | 触发资料 Agent，置信度 <0.85 → HUMAN_PENDING flag |
| REPORT_COLLECTING | report.parse_failed (未超限) | REPORT_COLLECTING | 重试 |
| REPORT_COLLECTING | report.parse_failed (超限) | REPORT_COLLECTING | HUMAN_PENDING flag，通知 PE |
| DATA_ORGANIZING | completeness.pass | SIGNING | 发布 task.state_changed |
| DATA_ORGANIZING | completeness.fail | DATA_ORGANIZING | 发布 supplement.reminder，3天后升级 |
| DATA_ORGANIZING | anomaly.detected (critical) | (不变) | 发布 rework.triggered |
| DATA_ORGANIZING | human.confirmed (approve) | SIGNING | 清除 HUMAN_PENDING flag |
| DATA_ORGANIZING | human.confirmed (rework) | (不变) | 发布 rework.triggered |
| SIGNING | human.confirmed (approve) | CLOSED | 结案归档 |
| SIGNING | human.rejected | DATA_ORGANIZING | 驳回 |
| 任意 | rework.triggered | REWORKING | HUMAN_PENDING flag |
| REWORKING | (返工完成) | REPORT_COLLECTING | 回到收报告节点 |

---

## 七、.env 模板

```bash
# ── App ──
APP_ENV=development
LOG_LEVEL=DEBUG

# ── Database ──
DATABASE_URL=postgresql+asyncpg://ots_user:ots2026@localhost:5432/ots

# ── DeepSeek (LLM) ──
DEEPSEEK_API_KEY=sk-your-api-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat

# ── MinIO (Object Storage) ──
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=ots-reports

# ── Mail ──
MAIL_IMAP_HOST=imap.example.com
MAIL_IMAP_PORT=993
MAIL_IMAP_USER=ots-bot@example.com
MAIL_IMAP_PASSWORD=your-password
MAIL_SMTP_HOST=smtp.example.com
MAIL_SMTP_PORT=587
MAIL_SMTP_USER=ots-bot@example.com
MAIL_SMTP_PASSWORD=your-password
MAIL_FILTER_SENDERS=vendor1@example.com,vendor2@example.com
MAIL_FILTER_SUBJECT_KEYWORDS=OTS,PPAP,认可,样件,测试报告

# ── IM (飞书/企微) ──
IM_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/your-hook
```

---

## 八、docker-compose 完善版

> 在现有基础上追加 pgvector

```yaml
version: "3.9"

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: ots-pg
    environment:
      POSTGRES_USER: ots_user
      POSTGRES_PASSWORD: ots2026
      POSTGRES_DB: ots
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data

  minio:
    image: minio/minio:latest
    container_name: ots-minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data

volumes:
  pg_data:
  minio_data:
```

---

## 九、编码约定

| 约定 | 说明 |
|------|------|
| Agent 命名 | 放在 `app/agents/` 下，每个 Agent 一个文件：`orchestrator.py`, `mail_gateway.py`, `parser.py`, `data_checker.py`, `notifier.py` |
| Agent 基类 | 继承 `app/agents/base.py` 的 `BaseAgent`，统一 `start() / stop() / handle_event()` 接口 |
| 事件发布 | 统一通过 `event_bus.publish(Event(...))` |
| 数据库操作 | 使用 `async_session` 依赖注入，不在 Agent 内直接创建 session |
| 日志 | `logging.getLogger(__name__)`，关键路径打印 DEBUG，异常打印 ERROR |
| 类型 | TypedDict 定义事件 payload，Pydantic 定义 API Schema |
| 测试 | 每个 Agent 有对应的 `tests/test_*.py`，先写测试 |

---

## 十、验收检查清单

- [ ] `docker compose up -d` 一次成功
- [ ] `alembic upgrade head` 创建所有表
- [ ] `POST /api/parts` 创建零件 → 自动创建任务 → 状态 CREATED
- [ ] 启动邮件网关 → IDLE 监听 → 收到 OTS 邮件 → 附件下载到 MinIO
- [ ] 解析 Agent 消费附件 → DeepSeek 解析 → `report.parsed` 事件发布
- [ ] 字段置信度 <0.85 → `HUMAN_PENDING` flag 置为 true
- [ ] 资料 Agent 清单核对 → 缺失项识别 → `completeness.fail` 事件
- [ ] `POST /api/tasks/{id}/confirm` → 状态前进
- [ ] 全流程走通：CREATED → TEST_APPLYING → TESTING → REPORT_COLLECTING → DATA_ORGANIZING → SIGNING → CLOSED
- [ ] Web 工作台可查看任务列表和详情

---

*本文档基于 PRD V2.0 + 三张架构图 + 现有代码骨架生成，所有数值、阈值、状态名、事件名均与设计文档一致。*
