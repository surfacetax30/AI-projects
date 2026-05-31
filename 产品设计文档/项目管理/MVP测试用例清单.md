# MVP 测试用例清单 — 零件 OTS 认可 AI Agent

> 分析时间：2026-05-27
> 代码基准：MVP V0.1（3节点：邮件网关 + 解析 + 资料检查）
> 现有测试：60 个（全部通过 ✅）

---

## 一、现有测试覆盖扫描

| 模块 | 测试文件 | 已覆盖 | 状态 |
|------|---------|:------:|:--:|
| Parser Agent | `test_parser.py` | JSON解析、置信度、阈值边界、纠正、高/低/无效置信度处理 | ✅ 12 |
| Data Checker | `test_data_checker.py` | 必选项过滤、完整/缺失核对、空核对、模板加载、兜底、pass/fail/error | ✅ 12 |
| Mail Gateway | `test_mail_gateway.py` | 发件人过滤、主题匹配、附件校验、全规则组合、零件号提取 | ✅ 12 |
| Parts API | `test_api_parts.py` | CRUD、去空格、列表、详情、404 | ✅ 6 |
| Tasks API | `test_api_tasks.py` | 任务详情、404、Webhook、报告上传、事件触发 | ✅ 7 |
| Models | `test_models.py` | ChecklistTemplate 创建、默认值 | ✅ 2 |
| Schemas | `test_schemas.py` | PartCreate/TaskResponse/Webhook/Upload 序列化 | ✅ 7 |

**已覆盖但存在盲区的模块：** Parser（未测空 LLM 响应/无 field_confidence 降级）、Data Checker（未测 build_result 边界）、Mail Gateway（未测 process() 方法）、Tasks API（未测重复 part_no、无文件上传）

---

## 二、需新增的测试用例（按优先级排序）

### 🔴 P0 — 阻塞性错误路径（必须补）

| # | 模块 | 用例名称 | 测试目标 | 输入 | 预期结果 |
|---|------|---------|---------|------|---------|
| TC01 | API Parts | `test_create_duplicate_part_no_returns_error` | 重复零件号不应静默创建 | 两次 POST `/api/parts` 相同 part_no | 第二次返回 4xx 或数据库 IntegrityError |
| TC02 | API Tasks | `test_upload_without_file_returns_error` | 不上传文件应拒绝 | POST `/api/tasks/{id}/reports` 不带 file | 422 Unprocessable Entity |
| TC03 | API Tasks | `test_upload_task_id_overflow` | 超短/超长 task_id | POST 带 task_id=`""` 或 256 字符 | 404 或 422 |
| TC04 | Parser | `test_process_with_empty_llm_response` | LLM 返回空字符串 | `_call_llm` 返回 `""` | `status=="error"` 且不 crash |
| TC05 | Parser | `test_process_missing_field_confidence` | LLM 返回的 JSON 不含 `field_confidence` 键 | `{"part_no":"X","test_type":"DV"}` | `overall_confidence==0.0`, `status=="pending_human"` |
| TC06 | Data Checker | `test_process_with_none_part_type` | part_type 为 None | `{"task_id":"t","part_type":null}` | `status=="error"` |
| TC07 | MailGateway | `test_subject_matches_with_none` | 主题为 None | `_subject_matches(None)` | 返回 False，不 crash |

### 🟡 P1 — 业务逻辑补全

| # | 模块 | 用例名称 | 测试目标 | 输入 | 预期结果 |
|---|------|---------|---------|------|---------|
| TC08 | Parser | `test_overall_confidence_with_empty_dict` | 空 confidences 的计算 | `_compute_overall_confidence({})` | `0.0` |
| TC09 | Parser | `test_find_low_confidence_at_threshold` | 置信度恰好 0.75 | `{"a":0.75, "b":0.76}` | `"a"` 在 low_fields 中, `"b"` 不在 |
| TC10 | Parser | `test_apply_corrections_preserves_unknown_keys` | 未知字段不被丢弃 | `{"unknown_field":"val"}` | `unknown_field` 保留 |
| TC11 | Parser | `test_apply_corrections_skips_field_confidence` | `field_confidence` 被过滤 | `{"part_no":"x", "field_confidence":{}}` | 结果不含 `field_confidence` |
| TC12 | Data Checker | `test_build_result_with_empty_checklist` | 空清单 | `_build_result("x", [], [])` | `overall_result=="pass"`, `total_required==0` |
| TC13 | Data Checker | `test_build_result_all_items_have_status` | 每项都标记 present/missing | 3 项清单，1 缺失 | `all_items` 含 3 个元素，status 正确 |
| TC14 | Data Checker | `test_process_default_template_for_unknown_type` | 未知类型走 default | `process({"part_type":"xxx"})` | 返回 DEFAULT_TEMPLATE 的核对结果 |
| TC15 | MailGateway | `test_process_accepts_valid_payload` | `process()` 方法接收正确 payload | `{"mail_from":"vendor1@...", "mail_subject":"OTS测试"}` | `accepted==True` |
| TC16 | MailGateway | `test_process_rejects_invalid_sender` | `process()` 拒绝并发件人 | `{"mail_from":"bad@..."}` | `accepted==False, reason=="filter_rejected"` |
| TC17 | MailGateway | `test_extract_part_no_case_insensitive` | 大小写不敏感 | `"ots-2026-001 测试"` | `"OTS-2026-001"` |
| TC18 | MailGateway | `test_extract_part_no_multiple_matches_first_wins` | 多个匹配取第一个 | `"OTS-2026-001 OTS-2026-002"` | `"OTS-2026-001"` |
| TC19 | MailGateway | `test_attachment_valid_uppercase_extension` | 大写扩展名也通过 | `_attachment_valid("REPORT.PDF")` | True |

### 🟢 P2 — 集成测试

| # | 模块 | 用例名称 | 测试目标 | 输入 | 预期结果 |
|---|------|---------|---------|------|---------|
| TC20 | Integration | `test_create_part_upload_webhook_full_chain` | 端到端全链路（创零件→上传→webhook） | POST parts → POST report → POST webhook → GET task | 任务时间线含 ≥2 个事件 |
| TC21 | Integration | `test_webhook_with_unknown_part_no` | 不存在的零件号 | POST webhook `part_no="NONEXIST"` | 404 |
| TC22 | Integration | `test_task_detail_with_multiple_reports` | 一个任务多次上传 | 同一 task 上传 3 次 | GET 返回 3 个 reports |
| TC23 | Integration | `test_mail_gateway_filter_in_webhook_flow` | Webhook 经过网关过滤 | POST webhook `mail_from="spam@evil.com"` | 过滤器拒绝（但 API 端不会校验 sender，这个测试验证 MailGateway 独立过滤） |
| TC24 | EventBus | `test_event_bus_publish_and_consume` | 事件正确发布和消费 | publish Event → 注册 handler → 等待 | handler 被调用 |
| TC25 | EventBus | `test_event_bus_handler_exception_does_not_crash` | handler 抛异常不拖垮总线 | publish → handler raise → publish again | 第二个事件正常消费 |
| TC26 | Integration | `test_concurrent_report_uploads` | 并发上传不冲突 | 同时 POST 5 个 upload | 全部返回 200，时间线有 5 个事件 |

### 🔵 P3 — 边界值 & 数据完整性

| # | 模块 | 用例名称 | 测试目标 | 输入 | 预期结果 |
|---|------|---------|---------|------|---------|
| TC27 | API Parts | `test_create_part_empty_required_fields` | 必填字段为空 | `{"part_no":""}` | 422 |
| TC28 | API Parts | `test_create_part_extra_long_fields` | 超长字段 | `part_no` 超过 64 字符 | 422 或截断 |
| TC29 | API Tasks | `test_task_detail_task_id_injection` | SQL 注入尝试 | `task_id="1'; DROP TABLE--"` | 404，不执行恶意 SQL |
| TC30 | Schemas | `test_webhook_payload_missing_part_no` | 缺少必填字段 | `{"mail_from":"x","mail_subject":"y"}` | 422 |

---

## 三、未覆盖的代码路径速查

以下代码路径在现有 60 个测试中**未被触发**，建议优先补充：

### `app/agents/parser.py`

```python
# Line 44: _compute_overall_confidence({})  → 0.0 （未测空 dict）
# Line 48: _is_auto_approve(0.85) vs _is_auto_approve(0.849) 边界 ✅ （已测）
# Line 52: _find_low_confidence_fields 恰好 0.75 的字段 （未测）
# Line 54-67: _apply_corrections 含 field_confidence 键的过滤 （未测）
# Line 56: "if key == 'field_confidence': continue" （未测）
# Line 87-88: LLM 调用失败抛异常 → status=="error" （未测）
# Line 94: parsed.pop("field_confidence", {}) — 当 JSON 不含此键 （未测）
```

### `app/agents/data_checker.py`

```python
# Line 106: "if not part_type:" — part_type 为 None 或空字符串 （未测）
# Line 109: checklist + parsed_fields 的 code/key 匹配逻辑何时匹配何时不匹配 （未测整个匹配机理）
# Line 74: "all_items" 输出包含所有项且 status 正确 （未直接测）
```

### `app/agents/mail_gateway.py`

```python
# Line 32-34: _subject_matches(None) （未测）
# Line 37-38: _attachment_valid("REPORT.PDF") 大写 （未测）
# Line 46: "if sender not in self.VALID_SENDERS" — 边界大小写 （未测）
# Line 54-56: _extract_part_no — 正则 PART_NO_PATTERN 边界 （未测非匹配场景）
# Line 58-74: process() 方法本身 （未测 — 所有现有测试只测私有方法）
```

### `app/api/tasks.py`

```python
# Line 89: file_content 过大 → 内存风险 （未测）
# Line 102: event_bus.publish() 异常会不会导致 500 （未测）
```

### `app/api/parts.py`

```python
# Line 21-29: 重复 part_no 创建会触发 IntegrityError （未测）
```

---

## 四、运行命令

```bash
# 跑全部现有测试
pytest tests/ -v

# 只跑新增的高优先级
pytest tests/ -v -k "duplicate or empty_fields or none or threshold or process_accepts or full_chain"

# 带覆盖率
pytest tests/ --cov=app --cov-report=term-missing

# 已通过: 60 passed ✅
```

---

## 五、建议补充顺序

```
第一轮 (30 分钟): TC01 - TC07 (P0 阻塞路径)
第二轮 (30 分钟): TC08 - TC19 (P1 业务逻辑)
第三轮 (45 分钟): TC20 - TC26 (P2 集成测试)
第四轮 (15 分钟): TC27 - TC30 (P3 边界值)
```

---

*分析基于对 12 个源文件 + 8 个测试文件的逐行比对。现有 60 个测试覆盖良好，重点补 P0 的 7 个盲区即可达到生产级覆盖。*
