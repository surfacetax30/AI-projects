# OTS Parser System Prompt 评测用例集

> 共 10 条 case，5 正向 + 5 边界，覆盖全部 5 个评测维度、7 条特殊场景规则。

---

## 覆盖矩阵一览

| # | 用例 | 类型 | 报告类型 | 主测维度 | 命中特殊场景规则 |
|---|------|------|---------|---------|----------------|
| 1 | 标准 DV 机械件报告（全字段） | 正向 | DV 机械件 | 准确性 | — |
| 2 | 软件版本测试报告（完整） | 正向 | 软件测试 | 准确性、完整性 | §1 软件报告 not_applicable |
| 3 | EMC 电磁兼容报告 | 正向 | EMC 电子件 | 准确性、完整性 | §3 总线/诊断类 not_applicable |
| 4 | PV 报告（含材料力学字段） | 正向 | PV 机械件 | 准确性、完整性 | — |
| 5 | 静态电流专项测试报告 | 正向 | 电气件 | 准确性、鲁棒性 | §3 静态电流类 not_applicable |
| 6 | 非测试报告：邮件沟通 | 边界 | — | 鲁棒性、规范性 | §7 非测试报告拒绝 |
| 7 | 简略手写报告（低质量） | 边界 | 振动（低质量） | 置信度校准、鲁棒性 | 硬性降分规则 |
| 8 | 日期非标准格式 + 范围 | 边界 | DV 机械件 | 准确性（日期） | §6 日期范围取始 |
| 9 | 多标准 + 非标准零件号 | 边界 | PV 机械件 | 准确性、完整性 | §4 非标零件号、§5 多标准 |
| 10 | 非测试报告：工作汇报 | 边界 | — | 鲁棒性、规范性 | §7 非测试报告拒绝 |

---

## 正向用例

### Case 1：标准 DV 机械件报告（全字段）

**选取理由**：这是最常见的 OTS 报告类型。15 个字段全部可提取，作为评测基准线——如果这个 case 做不对，其他 case 没有测的意义。

**覆盖检测点**：
- 15 字段全部 `field_status="extracted"`
- `part_no` 大小写转换（`ots-2025-088` → `OTS-2025-088`）
- `material` 与 `material_spec` 从括号中分离
- `test_type` 枚举匹配 `"DV"`
- `hardness` 和 `coating` 原文未提及 → `field_status="missing"`
- 3 个 `software_version` → `field_status="not_applicable"`（非软件报告）

**输入文本**：
```
OTS 零部件认可测试报告
零件号: ots-2025-088
零件名称: 后扭力梁总成
测试类型: DV (Design Verification)
测试日期: 2025-11-20
测试结论: PASS
实验室: 中汽研汽车检验中心
标准: GB/T 26780-2024
材料: SAPH440 (GB/T 20887.1-2017)
抗拉强度: 465 MPa
```

**预期输出关键字段**：
| 字段 | 预期值 | field_status | field_confidence |
|------|--------|-------------|:---:|
| part_no | `OTS-2025-088` | extracted | ≥ 0.95 |
| software_version_F1C1/F1C2/vendor_MCU | `非软件测试报告，无软件版本信息` | not_applicable | 1.0 |
| part_name | `后扭力梁总成` | extracted | ≥ 0.95 |
| test_type | `DV` | extracted | ≥ 0.95 |
| test_date | `2025-11-20` | extracted | ≥ 0.95 |
| test_result | `PASS` | extracted | ≥ 0.95 |
| lab_name | `中汽研汽车检验中心` | extracted | ≥ 0.95 |
| standard | `GB/T 26780-2024` | extracted | ≥ 0.95 |
| material | `SAPH440` | extracted | ≥ 0.90 |
| material_spec | `GB/T 20887.1-2017` | extracted | ≥ 0.90 |
| tensile_strength | `465 MPa` | extracted | ≥ 0.95 |
| hardness | `null` | missing | ≤ 0.30 |
| coating | `null` | missing | ≤ 0.30 |
| overall_confidence | ≥ 0.85 | — | — |

---

### Case 2：软件版本测试报告（完整）

**选取理由**：`software_version_F1C1/F1C2/vendor_MCU` 三个字段是后加入的专属字段，且软件报告与机械件报告的字段适用性完全不同。这是验证 `field_status` 三态设计是否生效的核心 case。

**覆盖检测点**：
- 3 个 software_version 字段正确提取
- `test_type` 枚举匹配 `"软件"`
- `material/m_spec/tensile/hardness/coating` 5 个字段 → `field_status="not_applicable"`，confidence=1.0
- `part_name` 原文未出现 → `field_status="missing"`，confidence ≤ 0.30
- `overall_confidence` 加权计算：not_applicable 字段不参与，missing 字段参与

**输入文本**：
```
软件版本测试报告

零件号: 26147117
主机厂软件版本 F1C1: E260S0690BA0140003
主机厂软件版本 F1C2: E260S0690BC0140021
供应商MCU软件版本: E260S_E260_202402021
测试类型: 软件
测试日期: 2026-02-09
测试结论: PASS
实验室: 博泰电子实验室
标准: Q/SSR 3001-2024
```

**预期输出关键字段**：
| 字段 | 预期值 | field_status | field_confidence |
|------|--------|-------------|:---:|
| part_no | `26147117` | extracted | ≥ 0.95 |
| software_version_F1C1 | `E260S0690BA0140003` | extracted | ≥ 0.95 |
| software_version_F1C2 | `E260S0690BC0140021` | extracted | ≥ 0.95 |
| software_version_vendor_MCU | `E260S_E260_202402021` | extracted | ≥ 0.95 |
| part_name | `unknown` | missing | ≤ 0.30 |
| test_type | `软件` | extracted | ≥ 0.95 |
| material | `null` | **not_applicable** | 1.0 |
| tensile_strength | `null` | **not_applicable** | 1.0 |
| hardness | `null` | **not_applicable** | 1.0 |
| coating | `null` | **not_applicable** | 1.0 |
| overall_confidence | ≥ 0.85 | 加权计算，not_applicable 排除 | — |

---

### Case 3：EMC 电磁兼容测试报告（电子件）

**选取理由**：EMC 报告属于电子件大类，不涉及材料力学属性。验证系统能否正确区分「机械件」和「电子件」的字段适用性，且 `test_type` 枚举为 `"EMC"`。

**覆盖检测点**：
- `test_type` → `"EMC"`（枚举匹配 17 类之一）
- `software_version` 字段 → not_applicable（非软件报告）
- `material/tensile/hardness/coating` → not_applicable（电子件）
- 电子件 `standard` 常见格式如 `"GB/T 18655-2018"` 应能正确提取

**输入文本**：
```
EMC 电磁兼容性测试报告

零件号: ECU-2026-0421
零件名称: 车身域控制器
测试类型: EMC (Electromagnetic Compatibility)
测试日期: 2026-03-15
测试结论: PASS
实验室: 国家汽车电子检验中心
标准: GB/T 18655-2018
```

**预期输出关键字段**：
| 字段 | 预期值 | field_status | 说明 |
|------|--------|-------------|------|
| part_no | `ECU-2026-0421` | extracted | 含字母数字混合 |
| part_name | `车身域控制器` | extracted | — |
| test_type | `EMC` | extracted | 枚举匹配 |
| test_result | `PASS` | extracted | — |
| software_version_* | 占位文本 | **not_applicable** | 非软件报告 |
| material/tensile/hardness/coating | `null` | **not_applicable** | 电子件不适用 |

---

### Case 4：PV 报告（含完整材料力学字段）

**选取理由**：PV（Production Validation）报告比 DV 报告更完整，通常包含硬度、表面处理等机械属性字段。验证字段提取的**完整性上限**——系统能提取多少就提取多少。

**覆盖检测点**：
- `test_type` → `"PV"`（区分 DV）
- `hardness`、`coating` → extracted（与 Case 1 形成对比——Case 1 中这两个字段是 missing，这个是 extracted）
- `material` + `material_spec` 分离
- high confidence 场景，`overall_confidence` 应 ≥ 0.90

**输入文本**：
```
OTS PV 生产验证测试报告

零件号: PV-2026-0156
零件名称: 前副车架焊接总成
测试类型: PV (Production Validation)
测试日期: 2026-04-20
测试结论: PASS
实验室: 柳汽检测中心
标准: GB/T 26780-2024
材料: Q345B (GB/T 1591-2018)
抗拉强度: 520 MPa
硬度: HB 180
表面处理: 阴极电泳
```

**预期输出关键字段**：
| 字段 | 预期值 | field_status |
|------|--------|-------------|
| test_type | `PV` | extracted |
| material | `Q345B` | extracted |
| material_spec | `GB/T 1591-2018` | extracted |
| tensile_strength | `520 MPa` | extracted |
| hardness | `HB 180` | **extracted**（与 Case 1 对比） |
| coating | `阴极电泳` | **extracted**（与 Case 1 对比） |
| overall_confidence | ≥ 0.90 | 全字段 extracted |

---

### Case 5：静态电流专项测试报告

**选取理由**：静态电流报告属于电气类测试，在真实 OTS 场景中高频出现（`real_OTS_data/` 中有多份）。验证系统对电气类报告的特殊处理。

**覆盖检测点**：
- `test_type` → `"静态电流"`（17 类枚举之一）
- `material/tensile/hardness/coating` → not_applicable（电气测试不涉及机械属性）
- 报告不包含 `standard` 字段 → `field_status="missing"`（而非 not_applicable——静态电流报告通常在电气规范中有标准）

**输入文本**：
```
静态电流（台架）专项测试报告

零件号: 27178150
零件名称: ICE域控制器
测试类型: 静态电流
测试日期: 2025-01-21
测试结论: PASS
实验室: 博泰电子实验室
```

**预期输出关键字段**：
| 字段 | 预期值 | field_status | 说明 |
|------|--------|-------------|------|
| test_type | `静态电流` | extracted | 枚举匹配 |
| material/tensile/hardness/coating | `null` | **not_applicable** | 电气测试 |
| standard | `null` | **missing** | 电气报告通常有标准，此处缺失 |
| software_version_* | 占位文本 | not_applicable | 非软件报告 |

---

## 边界用例

### Case 6：非测试报告 — 邮件沟通

**选取理由**：真实生产中，供应商可能误发邮件正文而非附件。这是 `§7 非测试报告` 规则的标准触发场景，验证 `overall_confidence=0.0` 硬设 + `field_status` 全部 `not_applicable`。

**覆盖检测点**：
- 识别为非测试报告
- 所有业务字段 → `null`
- `field_status` → 全部 `"not_applicable"`
- `field_confidence` → 全部 `1.0`
- `overall_confidence` → 硬设为 `0.0`（不靠加权计算得出）
- `notes` → 包含 `"非测试报告"` 字样

**输入文本**：
```
张工你好，

关于 A1234 零件的 EMC 测试，我们计划下周三开始，预计周五完成，请知悉。

另外 B5678 的 DV 报告已经出了，我下午发给你。

谢谢！
```

**预期输出关键字段**：
| 字段 | 预期值 | field_status | field_confidence |
|------|--------|-------------|:---:|
| 全部 15 业务字段 | `null` | **not_applicable** | 1.0 |
| overall_confidence | **0.0** | — | — |
| notes | 含 `"非测试报告"` | — | — |

---

### Case 7：简略手写报告（低质量输入）

**选取理由**：真实场景中供应商可能手写记录后拍照扫描。验证置信度校准和硬性降分规则是否生效——低质量输入必须给出低 confidence，不能因为「看起来对」就给高分。

**覆盖检测点**：
- `part_no` 大小写转换（`ot-303-099` → `OT-303-099`）
- `test_date` 仅年月 → 补全为 `2026-03-01`（confidence ≤ 0.70）
- `test_result` "合格" → 推断为 PASS（confidence ≤ 0.70，非直接匹配）
- `test_type` "振动耐久" → 匹配 `"振动"`（confidence ≤ 0.75，非精确匹配）
- `lab_name` "XX检测中心" → confidence ≤ 0.50（名称不完整）
- `standard` 缺失 → `field_status="missing"`，confidence ≤ 0.20
- `overall_confidence` 应在 0.35–0.55 之间（低质量输入）

**输入文本**：
```
测试记录
件号 ot-303-099
实验: 振动耐久
日期: 2026.3
结果: 合格
实验室: XX检测中心
材质: 45#钢
```

**预期输出关键字段**：
| 字段 | 预期值 | field_status | field_confidence | 说明 |
|------|--------|-------------|:---:|------|
| part_no | `OT-303-099` | extracted | ≤ 0.90 | 大小写转换 |
| part_name | `unknown` | missing | ≤ 0.30 | 未出现 |
| test_type | `振动` | extracted | ≤ 0.75 | "振动耐久"非精确匹配 |
| test_date | `2026-03-01` | extracted | ≤ 0.70 | 年月补全 |
| test_result | `PASS` | extracted | ≤ 0.70 | "合格"推断 |
| lab_name | `XX检测中心` | extracted | ≤ 0.50 | 名称不完整 |
| standard | `null` | missing | ≤ 0.20 | 缺失 |
| material | `45#钢` | extracted | ≤ 0.85 | — |
| overall_confidence | 0.35–0.55 | — | — | 低质量应有低分 |

---

### Case 8：日期非标准格式 + 范围

**选取理由**：日期是 OTS 流程中的关键字段，但供应商格式千奇百怪。验证 `§6 日期范围取开始日期` 规则 + 中文日期解析 + 年月补全。

**覆盖检测点**：
- 日期中文格式 `"二零二六年一月"` → 解析为 `2026-01-01`（补日为 01）
- 日期范围 `"2026/3/10 - 2026/4/5"` → 取开始日期 `2026-03-10`
- `notes` 中应注明 `"测试周期: 2026-03-10 ~ 2026-04-05"` 和年月补全说明
- 日期 confidence 因补全/范围处理而降低（≤ 0.75）

**输入文本**：
```
OTS 测试报告

零件号: OTS-2026-0112
零件名称: 转向节
测试类型: DV
测试日期: 2026/3/10 - 2026/4/5
测试结论: 合格
实验室: 国家机动车检测中心
标准: GB/T 3098.1-2025
```

**预期输出关键字段**：
| 字段 | 预期值 | field_confidence | 说明 |
|------|--------|:---:|------|
| test_date | `2026-03-10` | ≤ 0.75 | 范围取始，斜杠转横线 |
| test_result | `PASS` | ≤ 0.70 | "合格"推断 |
| notes | 含 `"测试周期: 2026-03-10 ~ 2026-04-05"` | — | — |

---

### Case 9：多标准 + 非标准零件号

**选取理由**：某些测试报告会引用多个标准，零件号格式也可能不规范（含空格、特殊字符）。验证 `§4 非标零件号原样保留` + `§5 多标准取首个` 规则。

**覆盖检测点**：
- `part_no` 含空格 `"OTS 2026 0099"` → 原样保留（不强行格式化）
- 多个标准 → `standard` 取第一个 `"GB/T 10125-2021"`，`notes` 注明另有标准
- `test_type` "盐雾（中性盐雾 NSS）" → 匹配 `"盐雾"`

**输入文本**：
```
中性盐雾试验报告

零件号: OTS 2026 0099
零件名称: 门铰链加强板
测试类型: 盐雾（中性盐雾 NSS）
测试日期: 2026-02-28
测试结论: PASS
实验室: 上海材料研究所
标准: GB/T 10125-2021, GB/T 6461-2002
材料: DC04
表面处理: 镀锌
```

**预期输出关键字段**：
| 字段 | 预期值 | 说明 |
|------|--------|------|
| part_no | `OTS 2026 0099` | 含空格，原样保留 |
| test_type | `盐雾` | 枚举匹配 |
| standard | `GB/T 10125-2021` | 取首个 |
| notes | 含 `"另有标准: GB/T 6461-2002"` | — |

---

### Case 10：非测试报告 — 工作汇报

**选取理由**：与 Case 6 形成对比。工作汇报的语言风格不同于邮件，但同样是 `§7 非测试报告` 的触发场景。验证拒绝逻辑对不同语言风格的一致性。

**覆盖检测点**：
- 识别为非测试报告
- 文本中出现 `"EMC测试"` 和 `"DV报告"` 等测试关键词，但整体不是报告 → 不能误提取
- 结果与 Case 6 一致：全部 `null` + not_applicable + overall=0.0

**输入文本**：
```
2026年5月第四周 OTS 进度周报

本周完成：
1. A1234 零件的 EMC 测试已通过，报告已归档
2. B5678 的 DV 报告预计下周提交
3. C9999 的第一次交样因尺寸超差退回，已通知供应商整改

下周计划：
- 跟进 B5678 DV 报告进度
- 安排 C9999 二次交样评审

以上，请审阅。
```

**预期输出关键字段**：
| 字段 | 预期值 | field_status | field_confidence |
|------|--------|-------------|:---:|
| 全部 15 业务字段 | `null` | **not_applicable** | 1.0 |
| overall_confidence | **0.0** | — | — |
| notes | 含 `"非测试报告"` | — | — |

> ⚠️ 关键风险点：文本中出现了 `"EMC测试"` 和 `"DV报告"` 等测试关键词，LLM 可能误判为测试报告并尝试提取。这是评测重点——系统必须基于**整体结构**（周报/工作汇报）判断，而非关键词匹配。

---

## 覆盖总结

### 按评测维度覆盖

| 评测维度 | 权重 | 覆盖的 case |
|---------|:---:|------|
| 业务准确性 | 30% | #1, #2, #3, #4, #5, #8, #9 |
| 流程完整性 | 25% | 所有 case（通过 `overall_confidence` + `field_status` 体现） |
| 置信度校准 | 20% | #7（低质量降分）、#8（日期补全降分） |
| 鲁棒性 | 12% | #5（电气报告）、#6（邮件拒绝）、#7（手写件）、#10（周报拒绝） |
| 规范性 | 8% | #6（null 输出规范）、#10（拒绝 JSON 结构） |

### 按特殊场景规则覆盖

| 特殊场景规则 | 覆盖 case |
|-------------|----------|
| §1 软件报告 not_applicable | #2 |
| §2 非软件报告 software_version not_applicable | #1, #3, #4, #5 |
| §3 静态电流/总线/诊断类 not_applicable | #5 |
| §4 非标准零件号原样保留 | #9 |
| §5 多标准取首个 | #9 |
| §6 日期范围取开始日期 | #8 |
| §7 非测试报告拒绝 | #6, #10 |
| §8 standard 的 missing/not_applicable 边界 | #7 vs #6 |

### 按报告类型覆盖

| 报告类型 | 覆盖 case |
|---------|----------|
| DV 机械件（含/不含材料全字段） | #1（缺 hardness/coating）、#8（日期异常） |
| 软件测试 | #2（完整） |
| EMC 电子件 | #3 |
| PV 机械件（含材料全字段） | #4（完整）、#9（盐雾） |
| 静态电流（电气） | #5 |
| 振动（低质量） | #7 |
| 非测试报告 | #6（邮件）、#10（周报） |

---

## 快速验证路径

如果首次评测时间有限，优先跑这 4 条（最小可行集，覆盖最核心的区分度）：

| 优先级 | Case | 为什么 |
|:---:|------|------|
| **P0** | #1 标准 DV 机械件 | baseline，做不对就别往下测 |
| **P0** | #2 软件版本报告 | field_status 三态设计的直接验证 |
| **P1** | #6 非测试报告（邮件） | 拒绝逻辑是否生效 |
| **P1** | #7 简略手写报告 | 低质量输入是否得到低 confidence |
