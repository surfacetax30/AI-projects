# 3节点MVP 编码规格 — 含邮件网关版

> 交付对象：Trae Solo Code
> 目标：最快跑通全链路——邮件到达 → 自动解析 → 完整性检查 → 查结果
> 范围：邮件网关 + 报告解析 + 资料检查
> 预计代码量：~650 行

---

## 一、数据流（邮件网关 + 2 核心 AI 节点）

```
┌─ 真实邮箱 ─┐          ┌─ 测试用 ─┐
│ IMAP监听   │          │ Webhook  │
│ IDLE模式   │          │ 手动灌入 │
└─────┬──────┘          └────┬─────┘
      │                      │
      ▼                      ▼
┌──────────────────────────────────────┐
│   📧 邮件网关 Agent                   │
│   规则过滤 → 提取零件号 → 下载附件    │
│   → MinIO 存储 → 发布 report.received │
└─────────────────┬────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────┐
│   🔍 解析 Agent                       │
│   下载文件 → 调 DeepSeek → 提取字段   │
│   → 入库 ParsedReport → report.parsed │
└─────────────────┬────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────┐
│   📋 资料 Agent                       │
│   查清单 → 逐项核对 → 标记缺失        │
│   → completeness.pass / fail          │
└──────────────────────────────────────┘

GET /api/tasks/{id}  →  查看全部结果
```

---

## 二、待实现的文件（6 个新文件 + 2 个修改）

### 2.1 新建文件

| # | 文件 | 核心内容 | 行数 |
|---|------|---------|:--:|
| F1 | `app/schemas/tasks.py` | Pydantic 请求/响应模型 | ~80 |
| F2 | `app/api/parts.py` | 零件 CRUD + 自动创建任务 | ~60 |
| F3 | `app/api/tasks.py` | 任务查询 + 报告上传 + 详情 + webhook | ~90 |
| F4 | **`app/agents/mail_gateway.py`** | 🆕 IMAP 监听 + 规则过滤 + 附件下载 | ~100 |
| F5 | `app/agents/parser.py` | 解析 Agent | ~120 |
| F6 | `app/agents/data_checker.py` | 资料 Agent | ~80 |

### 2.2 修改已有文件

| # | 文件 | 改动 |
|---|------|------|
| M1 | `app/main.py` | 注册所有 router，lifespan 中启动 3 个 Agent |
| M2 | `app/db/models.py` | 新增 ChecklistTemplate |

---

## 三、邮件网关 Agent 规格（F4 — 新增核心）

### 两种触发方式

| 方式 | 适用场景 | 如何触发 |
|------|---------|---------|
| **IMAP 监听** | 生产环境 | 后台 IDLE 模式持续监听 |
| **Webhook** | 测试 / 无 IMAP | `POST /api/webhooks/mail` 手动灌入 |

**两种方式走同一条下游链路：** 附件 → MinIO → `report.received` 事件 → 解析 Agent → 资料 Agent。

### 类结构

```python
class MailGatewayAgent(BaseAgent):
    """
    订阅: 无（主动从 IMAP 拉取或被动接 Webhook）
    发布: report.received

    两种工作模式:
    1. IMAP IDLE — 后台协程，持续监听新邮件
    2. Webhook  — API 端点 POST /api/webhooks/mail

    规则过滤（满足 ALL 才通过）:
    - 发件人域名在 MAIL_FILTER_SENDERS 白名单中
    - 主题包含任一 MAIL_FILTER_SUBJECT_KEYWORDS
    - 有附件，且扩展名在允许列表内 (.pdf/.docx/.xlsx/.jpg/.png)
    """
```

### IMAP 监听实现

```python
async def _listen_loop(self):
    """后台协程：IMAP IDLE 循环"""
    import imaplib, email, ssl
    from email.header import decode_header
    
    while self._running:
        try:
            # 1. 连接 + 登录
            imap = imaplib.IMAP4_SSL(MAIL_IMAP_HOST, MAIL_IMAP_PORT)
            imap.login(MAIL_IMAP_USER, MAIL_IMAP_PASSWORD)
            imap.select("INBOX")
            
            while self._running:
                # 2. IDLE 等待新邮件
                imap.idle()
                response = imap.fetch(b"1:*", "(FLAGS)")
                # 有 UNSEEN → 退出 IDLE
                imap.noop()  # 退出 IDLE
                
                # 3. 搜索未读邮件
                _, data = imap.search(None, "UNSEEN")
                for num in data[0].split():
                    await self._process_mail(imap, num)
        except Exception:
            logger.exception("IMAP error, reconnect in 30s")
            await asyncio.sleep(30)

async def _process_mail(self, imap, mail_num):
    """处理单封邮件"""
    _, data = imap.fetch(mail_num, "(RFC822)")
    msg = email.message_from_bytes(data[0][1])
    
    # 规则过滤
    if not self._pass_filter(msg):
        return
    
    # 提取零件号（从主题中匹配已知 part_no 列表）
    part_no = self._extract_part_no(msg["Subject"])
    if not part_no:
        return
    
    # 找到对应的 task
    task = await self._find_task_by_part_no(part_no)
    if not task:
        return
    
    # 下载附件到 MinIO
    attachment_ids = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        if filename and self._is_allowed_attachment(filename):
            obj_path = await self._save_to_minio(task.id, filename, part)
            attachment_ids.append(obj_path)
    
    if attachment_ids:
        # 发布事件 → 触发解析管线
        await event_bus.publish(Event(
            type=EventType.REPORT_RECEIVED,
            task_id=task.id,
            source="mail_gateway",
            payload={
                "task_id": task.id,
                "part_no": part_no,
                "mail_subject": msg["Subject"],
                "mail_from": msg["From"],
                "attachment_ids": attachment_ids,
                "attachment_names": [...],
            }
        ))
```

### 过滤规则实现

```python
def _pass_filter(self, msg) -> bool:
    from_addr = msg["From"] or ""
    subject = msg["Subject"] or ""
    
    # 发送人白名单
    allowed = MAIL_FILTER_SENDERS.split(",")
    if not any(s.strip().lower() in from_addr.lower() for s in allowed):
        logger.debug(f"Skipped: sender {from_addr} not in whitelist")
        return False
    
    # 主题关键词
    keywords = MAIL_FILTER_SUBJECT_KEYWORDS.split(",")
    if not any(kw.strip().lower() in subject.lower() for kw in keywords):
        logger.debug(f"Skipped: subject '{subject[:50]}' no keywords match")
        return False
    
    return True

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".jpg", ".jpeg", ".png"}

def _is_allowed_attachment(self, filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS
```

### 零件号提取 + 任务匹配

```python
def _extract_part_no(self, subject: str) -> str | None:
    """从邮件主题中提取零件号。
    
    策略：
    1. 遍历数据库中所有 active 任务的 part_no
    2. 检查是否出现在主题中
    3. 返回匹配到的 part_no
    
    MVP 阶段不做复杂正则，直接查数据库做子串匹配。
    """
    # 在 agent 内部实现，从 DB 查所有活跃 part_no 然后匹配
    ...

async def _find_task_by_part_no(self, part_no: str) -> ApprovalTask | None:
    """找到该零件的活跃任务（非 CLOSED 状态）"""
    async with async_session() as db:
        result = await db.execute(
            select(ApprovalTask)
            .join(Part)
            .where(Part.part_no == part_no)
            .where(ApprovalTask.state != "CLOSED")
            .order_by(ApprovalTask.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
```

### Webhook 端点（测试用）

```python
# 在 app/api/tasks.py 或 app/api/webhooks.py 中

class WebhookMailPayload(BaseModel):
    """模拟一封邮件"""
    mail_from: str
    mail_subject: str
    part_no: str                # 必须指定，IMAP 是自动提取的
    attachments: list[str] = [] # MinIO 中已上传的文件路径（先上传再发 webhook）

@router.post("/api/webhooks/mail")
async def webhook_mail(body: WebhookMailPayload):
    """手动触发邮件处理管线（测试用）"""
    task = await _find_task_by_part_no(body.part_no)
    if not task:
        raise HTTPException(404, f"No active task for part_no: {body.part_no}")
    
    await event_bus.publish(Event(
        type=EventType.REPORT_RECEIVED,
        task_id=task.id,
        source="webhook",
        payload={
            "task_id": task.id,
            "part_no": body.part_no,
            "mail_subject": body.mail_subject,
            "mail_from": body.mail_from,
            "attachment_ids": body.attachments,
            "attachment_names": [p.split("/")[-1] for p in body.attachments],
        }
    ))
    return {"status": "accepted", "task_id": task.id}
```

---

## 四、状态流转（4 状态）

```
CREATED ──(邮件到达/上传)──→ REPORT_RECEIVED
                                   │
                                   ▼
                               PARSING ──(解析完成)──→ CHECKED
                                   │
                                   └──(解析失败)──→ 保持 PARSING
```

---

## 五、两个新增 API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| `POST` | `/api/webhooks/mail` | **测试用**：模拟一封邮件，触发完整解析管线 |
| `POST` | `/api/tasks/{id}/reports` | **备用**：手动上传文件触发解析 |

两个端点都发布 `report.received` 事件，走同一条下游链路。

---

## 六、install_deps 补充

```bash
pip install python-multipart openpyxl pypdf pdfplumber --break-system-packages
```

`imaplib` / `email` 是 Python 标准库，不需要额外安装。`IMAPClient` 是可选的，`imaplib` 够用。

---

## 七、测试指南

### 7.1 测试策略总览

> **LLM 统一使用 DeepSeek V4 API（API Key 已配置在 `.env`），所有测试直接走真实调用。**

| 测试层级 | 测什么 | 依赖 | 工具 |
|---------|--------|------|------|
| **单元测试** | 私有方法（JSON解析、置信度计算、过滤规则、清单核对） | 无外部依赖 | pytest |
| **集成测试** | Agent process() 方法 + 事件总线 | 真实 DeepSeek V4 API, 真实 PG | pytest + pytest-asyncio |
| **端到端** | Webhook → 解析 → 检查 全链路 | 真实 DeepSeek V4 API, 真实 MinIO + PG | curl / httpie |
| **邮件测试** | IMAP 监听 | 真实邮箱 + 真实 DeepSeek V4 | 手动 / 测试邮箱 |

### 7.2 单元测试 — 每个文件的测试点

#### `tests/test_mail_gateway.py`

```python
import pytest
from app.agents.mail_gateway import MailGatewayAgent

async def test_filter_sender_whitelist():
    """发件人不在白名单 → 过滤掉"""
    agent = MailGatewayAgent()
    msg = _make_mock_email(from_="unknown@spam.com", subject="OTS测试报告")
    assert agent._pass_filter(msg) is False

async def test_filter_subject_keywords():
    """主题不含关键词 → 过滤掉"""
    agent = MailGatewayAgent()
    msg = _make_mock_email(from_="vendor1@example.com", subject="hello world")
    assert agent._pass_filter(msg) is False

async def test_filter_pass():
    """满足全部条件 → 通过"""
    agent = MailGatewayAgent()
    msg = _make_mock_email(from_="vendor1@example.com", subject="OTS认可 测试报告")
    assert agent._pass_filter(msg) is True

def test_extract_part_no_found():
    """主题包含已知 part_no → 提取成功"""
    agent = MailGatewayAgent()
    known_parts = {"TEST-001", "ABC-123"}
    result = agent._match_part_no("RE: TEST-001 OTS测试报告 V2", known_parts)
    assert result == "TEST-001"

def test_extract_part_no_not_found():
    """主题不含任何已知 part_no → 返回 None"""
    agent = MailGatewayAgent()
    result = agent._match_part_no("hello world", {"TEST-001"})
    assert result is None

def test_is_allowed_attachment():
    agent = MailGatewayAgent()
    assert agent._is_allowed_attachment("report.pdf") is True
    assert agent._is_allowed_attachment("report.exe") is False
    assert agent._is_allowed_attachment("data.xlsx") is True

def _make_mock_email(from_, subject):
    """构造 mock email.message 对象"""
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"] = from_
    msg["Subject"] = subject
    return msg
```

#### `tests/test_parser.py`

```python
async def test_parse_valid_json():
    """LLM 返回合法 JSON → 成功解析"""
    ...

async def test_parse_invalid_json_retry():
    """LLM 返回非法 JSON → L1 重试 → 成功"""
    ...

async def test_parse_retry_exhausted():
    """3 次重试全部失败 → 降级"""
    ...

async def test_confidence_below_threshold():
    """字段置信度 <0.85 → 标记 HUMAN_PENDING"""
    ...

async def test_parse_pdf_text_extraction():
    """PDF 文本提取 → 构造正确的 user message"""
    ...

async def test_parse_xlsx_to_markdown():
    """Excel 转 markdown 表格"""
    ...
```

#### `tests/test_data_checker.py`

```python
def test_check_all_fields_present():
    """所有字段齐全 → pass"""
    ...

def test_check_missing_fields():
    """有字段缺失 → fail, 返回 missing_items"""
    ...

def test_check_empty_fields():
    """字段值为 None 或空字符串 → 视为缺失"""
    ...

def test_check_unknown_part_type():
    """未知零件类型 → 返回空清单，不崩溃"""
    ...
```

### 7.3 集成测试 — 事件驱动链路（真实 DeepSeek V4）

```python
# tests/test_integration.py

@pytest.mark.asyncio
async def test_report_received_triggers_parsing(db_session, minio_client):
    """
    端到端集成测试（真实 DeepSeek V4 API）：
    1. 创建 Part + ApprovalTask
    2. 上传测试文件到 MinIO
    3. 发布 report.received 事件
    4. 等待解析 Agent 调用 DeepSeek V4 处理
    5. 验证 ParsedReport 已写入数据库
    """
    parser = ParserAgent()
    checker = DataCheckerAgent()
    await event_bus.start()
    await parser.start()
    await checker.start()
    
    # ... 创建测试数据 + 发布事件 ...
    
    # 等待异步处理（最多 60 秒，含 DeepSeek API 调用）
    for _ in range(60):
        await asyncio.sleep(1)
        reports = await db_session.execute(
            select(ParsedReport).where(ParsedReport.task_id == task.id)
        )
        if reports.scalar_one_or_none():
            break
    
    # 验证
    report = (await db_session.execute(...)).scalar_one()
    assert report.overall_confidence > 0
    assert report.test_type != ""
    
    # 清理
    await checker.stop(); await parser.stop(); await event_bus.stop()
```

### 7.4 端到端 — curl 手动全链路

```bash
# ═══════════════════════════════════════
# 测试方案 A：Webhook 方式（无需真实邮箱）
# ═══════════════════════════════════════

# Step 0: 启动环境
docker compose up -d
docker exec ots-minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker exec ots-minio mc mb local/ots-reports --ignore-existing
uvicorn app.main:app --reload --port 8000

# Step 1: 创建零件 + 任务
TASK_ID=$(curl -s -X POST http://localhost:8000/api/parts \
  -H "Content-Type: application/json" \
  -d '{
    "part_no": "OTS-2026-001",
    "part_name": "前副车架焊接总成",
    "part_type": "金属支架",
    "supplier": "XX精工制造有限公司",
    "project_code": "P2026-SUV"
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['task']['id'])")

echo "Task created: $TASK_ID"

# Step 2: 上传测试报告到 MinIO
# 方案 2a: 先通过 /api/tasks/{id}/reports 上传
STORAGE_PATH=$(curl -s -X POST "http://localhost:8000/api/tasks/$TASK_ID/reports" \
  -F "file=@test_report.pdf" \
  -F "task_id=$TASK_ID" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['storage_path'])")

echo "File uploaded: $STORAGE_PATH"

# Step 3: 通过 Webhook 触发解析管线（模拟邮件到达）
curl -X POST http://localhost:8000/api/webhooks/mail \
  -H "Content-Type: application/json" \
  -d "{
    \"mail_from\": \"vendor1@example.com\",
    \"mail_subject\": \"RE: OTS-2026-001 前副车架OTS认可测试报告\",
    \"part_no\": \"OTS-2026-001\",
    \"attachments\": [\"$STORAGE_PATH\"]
  }"

# Step 4: 等待 5-30 秒后查看结果
sleep 10
curl -s http://localhost:8000/api/tasks/$TASK_ID | python3 -m json.tool
```

### 7.5 真实 LLM 调用注意事项

- `.env` 中已配置 `DEEPSEEK_API_KEY=sk-07d4de5c6d654394b920c3f635170a3d`
- 默认模型 `deepseek-reasoner`（DeepSeek V4），可在 `.env` 中调整
- 单元测试中的 parser/data_checker 测试不调用 LLM（直接测试私有方法）
- 集成测试和端到端测试走真实 API 调用
- 建议测试时使用小文件（< 1MB）降低 API 延迟

### 7.6 测试 IMAP 监听（需要真实邮箱）

```bash
# 配置 .env 中的邮件参数
# MAIL_IMAP_HOST=imap.gmail.com  (或 imap.qq.com / imap.feishu.cn)
# MAIL_IMAP_USER=your-test@example.com
# MAIL_IMAP_PASSWORD=your-app-password

# 启动后查看日志确认 IDLE 已连接
uvicorn app.main:app --reload --port 8000 2>&1 | grep "IMAP"

# 用另一个邮箱发一封测试邮件（主题包含 "OTS" + 已创建的 part_no）
# 观察日志是否有 "report.received" 事件发布
```

### 7.7 测试检查清单

- [ ] `pytest tests/test_mail_gateway.py` — 7 个过滤/提取函数测试全部通过
- [ ] `pytest tests/test_parser.py` — L1/L2 纠错逻辑覆盖
- [ ] `pytest tests/test_data_checker.py` — 3 种零件类型清单核对
- [ ] `pytest tests/test_integration.py` — 真实 DeepSeek V4 下全链路走通
- [ ] curl Webhook 方式全链路（真实 DeepSeek V4）
- [ ] `GET /api/tasks/{id}` 返回完整的解析结果 + missing_items
- [ ] （可选）真实 IMAP 监听测试

---

## 八、文件依赖图（编码顺序）

```
              config.py  db/models.py  db/session.py
                   │           │            │
              ┌────┴───────────┴────────────┴────┐
              │         schemas/tasks.py          │
              └───────────────┬───────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
         api/parts.py   api/tasks.py    events/bus.py
              │               │               │
              └───────┬───────┘               │
                      │                       │
              ┌───────┴───────────────┐       │
              │     main.py           │       │
              └───────┬───────────────┘       │
                      │                       │
          ┌───────────┼───────────┬───────────┘
          │           │           │
  mail_gateway.py  parser.py  data_checker.py
```

---

## 九、启动命令（完整版）

```bash
# 1. 基础设施
docker compose up -d
docker exec ots-minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker exec ots-minio mc mb local/ots-reports --ignore-existing

# 2. 依赖
pip install python-multipart openpyxl pypdf pdfplumber pytest pytest-asyncio --break-system-packages

# 3. 跑测试
pytest tests/ -v

# 4. 启动（DeepSeek V4 API 已配置在 .env，开箱即用）
uvicorn app.main:app --reload --port 8000
```

---

*本文档覆盖：邮件网关 + 报告解析 + 资料检查，含单元/集成/端到端三层测试方案。LLM 统一使用 DeepSeek V4 API（`deepseek-reasoner`），API Key 已配置。*
