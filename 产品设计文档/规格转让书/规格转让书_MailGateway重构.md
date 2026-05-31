# 规格转让书 — MailGateway 重构：每日全量过滤（规则引擎 + LLM 分类）

> **交付对象**：Code（Trae Solo Code）
> **设计者**：Solo（Trae Solo）
> **日期**：2026-05-28
> **优先级**：P1（MVP 阶段核心 Agent 重设计）

---

## 一、为什么需要重构

### 1.1 当前 MailGateway 的三个致命短板

| 短板 | 具体表现 | 业务后果 |
|------|---------|---------|
| **白名单硬编码** | 3 个示例邮箱，新增供应商需改代码 | 新供应商的第一封报告被误拦，PE 根本不知道 |
| **黑白判定** | 返回 accepted/rejected，没有中间态 | 发件人不在白名单但主题像报告 → 直接丢弃，不可恢复 |
| **静默丢弃** | reject 后只在日志里打一行 `INFO` | PE 不知道丢了什么，供应商不知道被拒了 |

### 1.2 为什么选择"每日全量"而非"实时逐封"

| 对比维度 | 实时逐封（当前） | 每日全量（目标） |
|---------|:---:|:---:|
| PE 工作流匹配度 | 低 — PE 不会实时盯着邮箱 | **高** — PE 通常每天上午处理昨日积压 |
| LLM 调用成本 | N 封邮件 = N 次 API 调用 | N 封邮件 = 1 次 API 调用（批量分类） |
| 白名单更新响应 | 需重启服务 | 改配置文件即可 |
| 误拦恢复 | 不可恢复（已丢弃） | 全部保留在队列中，人工可复核 |
| 产品形态 | API 触发，无独立界面 | 生成《每日邮件过滤报告》，有独立查看入口 |

> 结论：**每日全量**更符合 PE 的日常节奏，且能从根本上解决静默丢弃问题。

---

## 二、目标架构：两层过滤

```
┌─────────────────────────────────────────────────────────────┐
│                      每日 9:00 触发                           │
│                   (cron / 手动 / webhook)                      │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: 规则引擎（确定性、零成本、秒级）                      │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ 白名单匹配 → 主题含 OTS/测试报告 → 附件格式正确       │ │
│  │   → status = "auto_accepted"                         │ │
│  ├───────────────────────────────────────────────────────┤ │
│  │ 黑名单发件人 → 明显非业务主题（"团建通知"、"工资条"） │ │
│  │   → status = "auto_rejected"                         │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  约 60-70% 邮件在此层判完                                     │
└─────────────────────┬───────────────────────────────────────┘
                      │ 规则引擎无法判定的（约 30-40%）
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: LLM 语义分类（模糊边界、语义理解）                    │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ 输入：发件人 + 主题 + 正文前 300 字 + 附件列表         │ │
│  │ 输出：classification + part_no + confidence            │ │
│  │                                                       │ │
│  │ 分类结果：                                             │ │
│  │   "OTS报告提交" → auto_accepted (confidence ≥ 0.8)    │ │
│  │   "进度沟通"   → auto_rejected                        │ │
│  │   "问题反馈"   → auto_rejected (抄送 PE 摘要)         │ │
│  │   "非业务邮件" → auto_rejected                        │ │
│  │   "不确定"     → pending_human (confidence < 0.8)      │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  批量调用：N 封邮件 → 1 次 LLM 请求（Few-Shot 中给 4 例）     │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                      分类后的动作                             │
│                                                             │
│  auto_accepted   → 发布 REPORT_RECEIVED 事件 → 进入 Pipeline │
│  auto_rejected   → 记录到 EventLog（type=MAIL_REJECTED）     │
│  pending_human   → 记录到 DB，等待 PE 在前端确认             │
│                                                             │
│  生成《每日邮件过滤报告》                                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、MailGateway System Prompt 设计

### 3.1 角色与指令

与 Parser 的 SP 不同，MailGateway 的 SP 是**分类器而非提取器**——它不输出 15 个字段，而是判定"这封邮件该不该进管线"。

```
# 角色
你是汽车行业 PE（产品工程师）部门的邮件分类助手。
你负责在每天早上审核收件箱中的邮件，
判断每封邮件是否属于 OTS 零部件测试报告的正式提交。

# 任务
阅读每封邮件的基本信息（发件人、主题、正文摘要、附件），
将其分入以下 5 类之一。

# 分类定义

| 分类 | 定义 | 后续动作 |
|------|------|---------|
| OTS报告提交 | 供应商/实验室正式提交 OTS 测试报告。邮件包含附件（PDF/DOCX/XLSX），主题或正文中提及测试报告、认可、交样 | 进入自动解析管线 |
| 进度沟通 | 询问测试进度、预计完成时间、催促进度。不含测试报告附件 | 归档，不进入管线 |
| "问题反馈" | 供应商报告测试异常、尺寸超差、需整改。可能含问题清单或 8D 报告 | 抄送 PE 关注 |
| 非业务邮件 | 群发通知、营销邮件、工资条、与 OTS 认可无关的内容 | 归档，不通知 |
| 不确定 | 邮件信息不足以做出明确判断（正文过短、附件无法识别、发件人不明） | 转人工审核 |

# 输入变量
你将在一次请求中收到多封邮件（以 JSON 数组提供），每封邮件包含：
- mail_from: 发件人邮箱地址
- mail_subject: 邮件主题
- mail_body_preview: 正文前 300 字符
- attachments: 附件文件名列表（如 ["DV测试报告.pdf", "材料证明.docx"]）

# 输出 Schema
返回一个 JSON 数组，每封邮件对应一个对象：

```json
[
  {
    "mail_index": 0,
    "classification": "OTS报告提交",
    "part_no": "OTS-2026-0099 或 null",
    "has_report_attachment": true,
    "confidence": 0.90,
    "reason": "主题含'OTS测试报告'，附件为PDF/DOCX格式，发件人可信"
  }
]
```

# 置信度指南

| 场景 | confidence 范围 |
|------|:---:|
| 发件人已知 + 主题明确 + 附件格式标准 | 0.90–1.00 |
| 发件人已知但主题模糊，正文可推断 | 0.70–0.85 |
| 发件人不明，主题含测试关键词但无明确报告附件 | 0.50–0.65 |
| 信息不足以分类 | 0.00–0.45，classification="不确定" |
```

### 3.2 为什么 SP 比 Parser 短很多

| 对比 | Parser SP | MailGateway SP |
|------|-----------|---------------|
| 任务 | 从正文中提取 15 个字段 | 从 4 个维度判断邮件类型 |
| 复杂度 | 字段提取 + 枚举匹配 + 日期规范 + 置信度校准 | 5 选 1 分类 |
| 特殊场景 | 8 条（软件/非软件/日期范围/多标准…） | 几乎没有边界规则，LLM 的语义理解已够 |
| 预估长度 | 447 行 | **约 80–120 行** |
| 需要 Few-Shot 吗 | 需要（4 例） | 需要（3 例：明确报告 / 进度沟通 / 不确定） |

---

## 四、每日批处理的触发机制

### 4.1 MVP 阶段：手动触发（最简方案）

```
方式 1: API 触发
POST /api/mail/batch-process
  → MailGateway 执行全量过滤
  → 返回《每日邮件过滤报告》

方式 2: CLI 触发
python3 scripts/process_daily_mail.py
```

MVP 不做 cron 定时任务（避免引入 celery/apscheduler 依赖），PE 每天早上打开前端点击"处理今日邮件"按钮即可。

### 4.2 V1.0：定时任务

```
cron: 0 9 * * 1-5  (工作日每天 9:00)
  → 调用 POST /api/mail/batch-process
```

### 4.3 邮件数据从哪来

| 来源 | MVP | V1.0 |
|------|:---:|:---:|
| Webhook 模拟 | ✅ 当前方式，POST `/api/webhooks/mail`，写入 `pending_mails` 表 | 保留作为测试入口 |
| IMAP 拉取 | ❌ 不做 | ✅ 连接真实邮件服务器（.env 中 IMAP 配置已有占位），每天 9:00 拉取新邮件写入 `pending_mails` |

**MVP 的邮件数据表**（替代当前的 asyncio.Queue）：

```python
# 新建表: pending_mails
class PendingMail(Base):
    __tablename__ = "pending_mails"

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    mail_from: Mapped[str] = mapped_column(String(256))
    mail_subject: Mapped[str] = mapped_column(String(512))
    mail_body_preview: Mapped[str] = mapped_column(Text)
    attachments: Mapped[list] = mapped_column(JSON)
    received_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(32), default="pending")
    classification: Mapped[Optional[str]]
    classified_at: Mapped[Optional[datetime]]
    classified_by: Mapped[Optional[str]]  # "rule_engine" | "llm" | "human"
    task_id: Mapped[Optional[str]]       # 如果进入管线，关联的 task_id
    batch_id: Mapped[Optional[str]]      # 批处理批次号
```

**状态机**：
```
pending → (规则引擎判定) → auto_accepted / auto_rejected / to_llm
to_llm  → (LLM 分类)     → auto_accepted / auto_rejected / pending_human
pending_human → (PE 审核) → auto_accepted / auto_rejected
```

---

## 五、事件流变更

### 5.1 新增事件类型

```python
# app/events/types.py 新增
class EventType:
    # ... 原有 13 种事件不变 ...

    MAIL_BATCH_STARTED    = "mail.batch_started"    # 批处理开始
    MAIL_CLASSIFIED       = "mail.classified"       # 单封邮件分类完成
    MAIL_BATCH_COMPLETED  = "mail.batch_completed"  # 批处理完成，报告生成
    MAIL_HUMAN_NEEDED     = "mail.human_needed"     # 有邮件需要人工审核
```

### 5.2 Pipeline 流程变更

```
旧流程：
  webhook → REPORT_RECEIVED → MailGateway.process() → accept? → Parser → DataChecker

新流程：
  webhook → 写入 pending_mails（status=pending）
  ── 每日触发 ──→ MailGateway.batch_process()
    → Layer 1 规则引擎（批量判定）
    → Layer 2 LLM 分类（仅 to_llm 的邮件，一次 API 调用）
    → auto_accepted:
      → 发布 MailGateway.REPORT_RECEIVED → Parser → DataChecker
    → auto_rejected:
      → 记录 MAIL_REJECTED 事件
    → pending_human:
      → 记录 MAIL_HUMAN_NEEDED 事件
      → PE 在前端审核
```

### 5.3 MailGateway 的接口变化

```python
class MailGateway(BaseAgent):
    name = "mail_gateway"

    def __init__(self):
        self._system_prompt = load_sp("mail_gateway")  # 统一走 sp_loader

    # 原 process() 方法 → 废弃，与主流不兼容
    # async def process(self, payload: dict) -> dict:  # 废弃

    async def batch_process(self, mails: list[dict]) -> dict:
        """每日全量过滤主入口"""
        # Step 1: 规则引擎
        rule_results = self._rule_engine_classify(mails)
        # Step 2: LLM 分类（仅对 to_llm 的邮件）
        to_llm = [m for m in rule_results if m["status"] == "to_llm"]
        if to_llm:
            llm_results = await self._llm_classify(to_llm)
        # Step 3: 合并结果
        # Step 4: 发布事件 + 更新 DB
        # Step 5: 生成报告
```

---

## 六、规则引擎的规则定义

规则引擎逻辑简单，但需要**可配置**而非**硬编码**。

### 6.1 规则配置文件 `config/mail_rules.yaml`

```yaml
# 规则引擎配置 — Solo 可直接编辑，无需改代码
# Code 在 MailGateway.__init__ 时加载此文件

# --- 白名单规则 ---
whitelist:
  senders:
    - "vendor1@example.com"
    - "vendor2@supplier.cn"
    - "lab@testing.org"
    - "pateo@partner.com"        # Solo 新增供应商时在此添加
  subject_keywords:
    - "OTS"
    - "认可"
    - "测试报告"
    - "PPAP"
    - "交样"
  attachment_exts:
    - ".pdf"
    - ".docx"
    - ".xlsx"
    - ".csv"
    - ".zip"

# --- 黑名单规则 ---
blacklist:
  subject_exclude_keywords:      # 包含任一关键词 → 直接 auto_rejected
    - "团建"
    - "工资条"
    - "会议邀请"
    - "Newsletter"
  sender_patterns:                # 发件人匹配任一模式 → 直接 auto_rejected
    - "noreply@*"
    - "marketing@*"

# --- 触发 LLM 的条件 ---
llm_fallback:
  # 满足以下任一条件 → 送入 LLM
  - rule_result == "to_llm"     # 规则引擎无法判定
  - subject_has_keyword_but_no_attachment  # 主题像但没附件（可能漏发）
  - sender_not_in_whitelist_but_subject_looks_like_report

# --- 批处理参数 ---
batch:
  max_mails_per_batch: 50       # 单次批处理最多处理 50 封邮件
  llm_timeout_seconds: 60       # LLM 分类超时
```

**核心设计原则**：Solo 在白名单里加一个供应商，只需改 YAML 的一行，不需要走规格转让书 → Code 改代码的链路。

---

## 七、前端交互设计

### 7.1 每日邮件过滤报告页面（新 Tab）

```
┌─────────────────────────────────────────────────────┐
│  📬 每日邮件过滤报告 — 2026-05-28                      │
│                                                       │
│  共收到 12 封邮件                                     │
│  ✅ 自动放行 7 封    ❌ 自动拒绝 3 封    ⚠️ 待审核 2 封 │
│                                                       │
│  ┌─────────────────────────────────────────────┐     │
│  │ [待审核]                                     │     │
│  │ ┌──────────────────────────────────────────┐│     │
│  │ │ ⚠️ 发件人: new_vendor@xyz.cn              ││     │
│  │ │ 主题: E260S 项目 OTS 测试报告提交          ││     │
│  │ │ 附件: 测试报告.docx                       ││     │
│  │ │ 分类: OTS报告提交 (LLM, 置信度 0.72)       ││     │
│  │ │ 原因: 发件人不在白名单，但主题和附件符合    ││     │
│  │ │ [放行进管线] [拒绝] [添加到白名单]          ││     │
│  │ └──────────────────────────────────────────┘│     │
│  │ ┌──────────────────────────────────────────┐│     │
│  │ │ ⚠️ 发件人: vendor1@example.com            ││     │
│  │ │ 主题: 关于上次测试结果的讨论                ││     │
│  │ │ 附件: 无                                  ││     │
│  │ │ 分类: 不确定 (LLM, 置信度 0.48)            ││     │
│  │ │ [放行进管线] [拒绝（进度沟通）]             ││     │
│  │ └──────────────────────────────────────────┘│     │
│  └─────────────────────────────────────────────┘     │
│                                                       │
│  ┌─────────────────────────────────────────────┐     │
│  │ [已处理] — 点击展开                            │     │
│  │ 7 封自动放行（白名单）                         │     │
│  │ 3 封自动拒绝（非业务）                         │     │
│  └─────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────┘
```

---

## 八、与 Parser 管线的衔接

### 8.1 什么时候 Parser 介入

```
MailGateway 判定 auto_accepted
  → 写 parsed_report（status="pending_parse"）
  → 发布 REPORT_RECEIVED 事件
  → _handle_report_received 被触发
  → MailGateway.process() 跳过（不再做二次过滤）
  → 直接进入 Parser → DataChecker
```

**关键变更**：`_handle_report_received` 中的 `mail_gateway.process()` 调用需要移除，改为在 MailGateway 批处理后直接发布结果。

### 8.2 `_handle_report_received` 的简化

```python
async def _handle_report_received(event: Event):
    """当前版本: 跳过 MailGateway 过滤（已在批处理中完成）"""
    payload = event.payload
    task_id = payload.get("task_id", "")

    # 直接进入 Parser
    parse_result = await parser.process({...})
    # 然后进入 DataChecker
    check_result = await data_checker.process({...})
```

MailGateway 不再作为 Pipeline 中的一个串行节点，而是**作为 Pipeline 的前置闸门**，在 Pipeline 启动之前完成过滤。

---

## 九、LLM 调用策略

### 9.1 批量调用 vs 逐封调用

```
逐封调用：12 封邮件 × 1 次 API 调用 = 12 次请求
批量调用：12 封邮件 → 1 次 API 请求 = 1 次请求

批量调用节省：token 开销（共享 system prompt）、网络延迟、API rate limit 消耗
```

### 9.2 为什么批量调用不影响分类质量

邮件分类是**独立推理**——邮件 A 是什么类别，与邮件 B 无关。LLM 不会因为"上一封是测试报告"就把下一封也判定为测试报告。Few-Shot 示例已经固化了分类标准。

### 9.3 LLM 调用失败时的降级

```
LLM API 超时 / 限流 / 返回非 JSON
  → 该批次所有 to_llm 邮件 → status = "pending_human"
  → 批处理报告注明 "LLM 分类不可用，X 封邮件需人工审核"
  → 不阻塞 auto_accepted / auto_rejected 的后续 Pipeline
```

---

## 十、改动清单

| # | 改动 | 涉及文件 | 类型 |
|---|------|---------|------|
| 1 | 新建 `config/mail_rules.yaml` | 新文件 | 配置文件 |
| 2 | 新建 `sp/mail_gateway.txt` | 新文件 | SP 文件（80–120 行） |
| 3 | 新建 `app/agents/mail_gateway.py` | 重写 | Agent 逻辑 |
| 4 | 新建 `app/db/models.py` | 新增 `PendingMail` 表 | DB |
| 5 | 修改 `app/events/types.py` | 新增 4 个事件类型 | 事件 |
| 6 | 修改 `app/main.py` | `_handle_report_received` 移除 MailGateway 调用 | Pipeline |
| 7 | 修改 `app/api/tasks.py` | webhook 写入 `pending_mails` 而非发事件 | API |
| 8 | 新建 API `POST /api/mail/batch-process` | 新端点 | API |
| 9 | 新建前端「每日邮件报告」Tab | `index.html` | 前端 |

### 改动的兼容性说明

| 旧接口/行为 | 新接口/行为 | 兼容策略 |
|-----------|-----------|---------|
| `POST /api/webhooks/mail` → 直接发 REPORT_RECEIVED | → 写入 `pending_mails`，等批处理 | webhook 返回 `{"status": "queued"}` |
| `MailGateway.process(payload)` | → `MailGateway.batch_process(mails)` | 删除旧方法，添加新方法 |
| `_handle_report_received` 第一步调 MailGateway | → 不再调 MailGateway | 移除此行 |
| `mail_gateway.inbound_queue` | → 废弃 | 删除 asyncio.Queue |

---

## 十一、校验清单（Code 完成开发后自检）

| # | 检查项 | 验证方式 |
|---|--------|---------|
| 1 | `sp/mail_gateway.txt` 存在且可加载 | `load_sp("mail_gateway")` 无异常 |
| 2 | `config/mail_rules.yaml` 被正确解析 | 在 YAML 中加一个测试邮箱，规则引擎应匹配 |
| 3 | webhook 写入 `pending_mails` 而非发事件 | POST webhook → 查 DB `pending_mails` 有记录 |
| 4 | 批处理 API 正常返回 | POST `/api/mail/batch-process` → 返回报告 JSON |
| 5 | 规则引擎正确判定白名单邮件 | 白名单发件人 + OTS 主题 → `auto_accepted` |
| 6 | 规则引擎正确判定黑名单邮件 | "团建通知" 主题 → `auto_rejected` |
| 7 | LLM 分类正确判定中间态 | 发件人不明但主题像报告 → 返回 classification + confidence |
| 8 | `auto_accepted` → 进入 Parser 管线 | 查 `ParsedReport` 有对应记录 |
| 9 | `pending_human` → 前端待审核列表可见 | 打开前端「每日邮件报告」Tab |
| 10 | LLM 超时 → 该批次邮件降级为 `pending_human` | 模拟 API 超时 |

---

## 十二、实施步骤总结

```
Step 1:  新建 config/mail_rules.yaml
Step 2:  新建 sp/mail_gateway.txt (参考第三章 SP 设计)
Step 3:  新建 PendingMail 数据库模型 + migration
Step 4:  重写 MailGateway agent (batch_process + 两层过滤)
Step 5:  新增 4 个事件类型
Step 6:  修改 main.py（移除 _handle_report_received 中的 mail_gateway.process）
Step 7:  修改 webhook API（写入 pending_mails 而非发事件）
Step 8:  新建 POST /api/mail/batch-process 端点
Step 9:  新增前端「每日邮件报告」Tab
Step 10: 改脚本 parse_file.py 等方式中 mail_gateway 引用
Step 11: 按照校验清单自检
```
