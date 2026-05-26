你是 Trae Solo Code，负责工程实现。先完整理解项目，再开始编码。

---

## 第一步：读取项目（按顺序，不要跳）

1. 先读 `对话记忆_20260526.md`
2. 再读 `规格转让书.md`
3. 然后读 `docs/PRD_零件OTS认可AI_Agent.docx`
4. 最后打开 `diagrams/` 下的三张 .drawio 图
5. 读完向我确认你的理解，我确认后再开始写代码

---

## 第二步：确认基础设施

检查以下文件是否存在且可直接使用：

| 文件 | 说明 |
|------|------|
| `docker-compose.yml` | PostgreSQL + MinIO，运行 `docker compose up -d` 启动 |
| `requirements.txt` | pip install -r requirements.txt |
| `.env` | DeepSeek API Key 已配置 |
| `app/config.py` | 配置加载器 |
| `app/db/session.py` | 异步 SQLAlchemy 引擎 |
| `app/db/models.py` | 4 张表：Part / ApprovalTask / ParsedReport / EventLog |
| `app/events/types.py` | 13 种事件类型 |
| `app/events/bus.py` | asyncio.Queue 事件总线（单例 event_bus） |
| `app/agents/base.py` | Agent 基类 |
| `app/services/llm.py` | DeepSeek API 客户端（单例 llm） |
| `app/main.py` | FastAPI 入口，已含 auto-create tables |

---

## 第三步：开始 Sprint 1 实现

按以下顺序实现，每完成一个 module 后通知我验证。

### 1. 模拟数据生成 `scripts/generate_mock_data.py`
- 生成 10 封邮件 JSON、5 份测试报告文本（含 1 份 FAIL 案例）
- 存到 tests/fixtures/

### 2. 邮件网关 Agent `app/agents/mail_gateway.py`
- 继承 BaseAgent，name="mail_gateway"
- MVP 阶段不用真实 IMAP，从 fixtures 读文件模拟
- 实现规则过滤（主题/发件人/附件名白名单）
- 通过后 publish Event(type=REPORT_RECEIVED)

### 3. 解析 Agent `app/agents/parser.py`
- 继承 BaseAgent，name="parser"
- 订阅 REPORT_RECEIVED 事件
- 调用 llm.chat() 提取字段：零件号、测试类型、测试日期、测试结果、实验室
- 逐字段置信度评分（MVP 用 LLM 自评，不做加权）
- publish REPORT_PARSED 或 REPORT_PARSE_FAILED

### 4. 编排 Agent `app/agents/orchestrator.py`
- name="orchestrator"
- 订阅所有功能 Agent 事件
- 状态机：CREATED → TEST_APPLYING → TESTING → REPORT_COLLECTING → DATA_ORGANIZING → SIGNING → CLOSED
- 只有编排 Agent 有权改 ApprovalTask.state
- HUMAN_PENDING 是 flag 不是状态
- publish TASK_STATE_CHANGED → 通知协程消费

---

## 关键约束（必须遵守）

1. **单进程**：所有 Agent 在同一 FastAPI 进程中
2. **事件驱动**：Agent 间通过 event_bus 通信，不要直接 import 调用
3. **编排独权**：只有 orchestrator 改状态
4. **置信度 MVP**：固定阈值 ≥0.90 自动 / 0.75-0.89 标记 / <0.75 复核
5. **LLM 用 DeepSeek**：client 已在 app/services/llm.py
6. **假阴性优先**：异常识别宁可误报不可漏报
7. **Mock 先行**：MVP 阶段不接真实邮箱，用 fixtures 模拟

---

先读文件，向我确认理解，然后开始写代码。
