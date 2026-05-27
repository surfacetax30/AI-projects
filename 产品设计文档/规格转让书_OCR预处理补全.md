# 规格转让书 — OCR 预处理补全

> 交付对象：Trae Solo Code  
> 问题发现：Trae Solo（产品设计）  
> 日期：2026-05-27  

---

## 〇、问题描述

### 当前能力

```
文件 → extractor.py → 纯文本 → DeepSeek V4 → 结构化字段
```

| 文件类型 | 当前状态 | 原理 |
|---------|:--:|------|
| 文本型 PDF | ✅ 能提取 | `pypdf` 直接读文字层 |
| DOCX / XLSX / CSV / TXT | ✅ 能提取 | 各自解析库 |
| **扫描件 PDF**（图片转的PDF） | ❌ 空文本 | `pypdf` 提取不到文字 |
| **照片/截图**（jpg/png） | ❌ 返回占位符 | 无处理逻辑 |

### 根因

`_extract_pdf()` 只调了 `pypdf` 的 `extract_text()`，对扫描件返回空。  
`_extract_image()` 直接返回占位符。  
图片和扫描件没有任何 OCR 处理。

---

## 一、实现目标

**在 extractor 内部加 OCR 降级逻辑：优先文字提取 → 文字为空时走 OCR。**

### 完整能力矩阵（补全后）

| 文件类型 | 提取路径 | 状态 |
|---------|---------|:--:|
| 文本型 PDF | `pypdf` 文字层 | ✅ 不变 |
| 扫描件 PDF | `pdf2image` → `paddleocr` 逐页识别 | 🆕 |
| DOCX / XLSX / CSV / TXT | 各自解析库 | ✅ 不变 |
| 图片 (png/jpg/jpeg) | `paddleocr` 直接识别 | 🆕 |
| 混合 PDF（部分页有文字、部分扫描） | 优先文字，空页走 OCR | 🆕 |

---

## 二、代码产物

### 2.1 修改文件：`app/services/extractor.py`

**只改 3 处，不动其他函数。**

#### 改动 1：新增 OCR 模块（文件末尾追加，~50 行）

```python
# ═══════════════════════════════════════════════════════════
# OCR 降级处理（扫描件 / 图片）
# ═══════════════════════════════════════════════════════════

def _ocr_image(img_bytes: bytes) -> str:
    """对单张图片执行 PaddleOCR 中文识别，返回文字。"""
    from paddleocr import PaddleOCR
    import numpy as np
    from PIL import Image

    # 懒加载单例，避免每次调用都初始化模型
    global _ocr_instance
    if "_ocr_instance" not in globals():
        _ocr_instance = PaddleOCR(lang="ch", show_log=False)

    image = Image.open(io.BytesIO(img_bytes))
    img_array = np.array(image)
    result = _ocr_instance.ocr(img_array)

    if not result or not result[0]:
        return ""

    lines = []
    for line_info in result[0]:
        text = line_info[1][0]  # (bbox, (text, confidence))
        if text and text.strip():
            lines.append(text.strip())
    return "\n".join(lines)


def _ocr_pdf_pages(data: bytes) -> str:
    """将 PDF 逐页转图片 → OCR 识别 → 拼接文本。"""
    from pdf2image import convert_from_bytes

    try:
        images = convert_from_bytes(data, dpi=200)
    except Exception:
        return ""

    all_text = []
    for i, img in enumerate(images):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page_text = _ocr_image(buf.getvalue())
        if page_text:
            all_text.append(f"[Page {i+1}]\n{page_text}")

    return "\n\n".join(all_text) if all_text else ""
```

#### 改动 2：修改 `_extract_pdf()` — 加降级逻辑

**在原有函数末尾 `return` 之前，插入降级判断：**

```python
def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    empty_pages = 0
    for page in reader.pages:
        t = page.extract_text()
        if t and t.strip():
            pages.append(t.strip())
        else:
            empty_pages += 1

    text_result = "\n\n".join(pages) if pages else ""

    # ── OCR 降级：超过一半页面为空 → 启动 OCR ──
    total = len(reader.pages)
    if total > 0 and empty_pages / total > 0.5:
        logger.info(f"PDF 扫描件检测: {empty_pages}/{total} 页无文字层，启动 OCR")
        ocr_text = _ocr_pdf_pages(data)
        if ocr_text:
            return ocr_text

    return text_result if text_result else "[PDF 无可提取文本]"
```

**关键逻辑：**
- 统计 `pypdf` 提取为空的页数
- 超过一半是空页 → 判定为扫描件 → 启动 OCR
- OCR 成功 → 返回 OCR 结果
- OCR 失败 → 返回原有的 "[PDF 无可提取文本]"

#### 改动 3：修改 `_extract_image()` — 替换占位符

```python
def _extract_image(data: bytes) -> str:
    """图片 → PaddleOCR 识别。"""
    result = _ocr_image(data)
    return result if result else "[图片无可识别文字]"
```

### 2.2 新增依赖

```bash
pip install paddleocr paddlepaddle pdf2image --break-system-packages
```

**完整依赖变化：**

| 依赖 | 用途 | 大小 |
|------|------|------|
| `paddleocr` | 中文 OCR 引擎 | ~50MB |
| `paddlepaddle` | PaddleOCR 的深度学习框架 | ~300MB |
| `pdf2image` | PDF 页面 → PNG 图片 | ~2MB |

> PaddleOCR 首次运行时会自动下载 `ch_PP-OCRv4_det` 和 `ch_PP-OCRv4_rec` 模型文件（~15MB），缓存在 `~/.paddleocr/`。

---

## 三、改动影响范围

| 文件 | 操作 | 行数 |
|------|------|:--:|
| `app/services/extractor.py` | ✏️ 追加 OCR 模块 + 改 `_extract_pdf` + 改 `_extract_image` | +60 / -5 |
| `requirements.txt` | ✏️ 追加 paddleocr, paddlepaddle, pdf2image | +3 |

**不动其他文件。** API、Parser、EventBus 全部无需修改。`extract_text()` 的主入口签名不变。

---

## 四、补全后的判断流程

```
extract_text(filename, bytes)
    │
    ├─ .pdf ──→ pypdf 提取文字
    │              │
    │              ├─ 文字充足 (>50% 页有内容) → 返回文本 ✅
    │              │
    │              └─ 多数页为空 → 扫描件判定
    │                              │
    │                              └─ pdf2image 逐页转 PNG
    │                                   │
    │                                   └─ PaddleOCR 逐页识别
    │                                        │
    │                                        ├─ 有文字 → 返回 OCR 文本 ✅
    │                                        └─ 无文字 → "[PDF 无可提取文本]"
    │
    ├─ .png/.jpg/.jpeg ──→ PaddleOCR 直接识别
    │                         │
    │                         ├─ 有文字 → 返回 OCR 文本 ✅
    │                         └─ 无文字 → "[图片无可识别文字]"
    │
    └─ .docx/.xlsx/.csv/.txt ──→ 原有提取逻辑（不变） ✅
```

---

## 五、验收标准

| # | 测试 | 预期 |
|---|------|------|
| 1 | 上传**文本型 PDF**（Word 导出的） | 走 `pypdf` 路径，不触发 OCR，行为和现在一致 |
| 2 | 上传**扫描件 PDF**（图片转的，无文字层） | `pypdf` 返回空 → 自动降级 OCR → 提取出文字 |
| 3 | 上传**混合 PDF**（第1页文字、第2页扫描） | 超过 50% 空页 → 启动 OCR，覆盖全部页面 |
| 4 | 上传**照片**（手机拍的纸质报告 `.jpg`） | PaddleOCR 识别 → 提取出文字 |
| 5 | 上传**纯图片**（无文字的 logo） | 返回 `[图片无可识别文字]`，不报错 |
| 6 | 上传**多页扫描 PDF**（10页） | 逐页识别，`[Page 1]`/`[Page 2]` 标记 |
| 7 | OCR 结果超过 4000 字符 | `extract_text()` 截断到 4000，和现有行为一致 |
| 8 | PaddleOCR 未安装 / 初始化失败 | 降级为原有错误信息，不 crash |

---

## 六、性能与约束

1. **首次加载**：PaddleOCR 首次初始化约 3-5 秒（加载模型），之后复用单例
2. **单页识别**：200 DPI 下约 2-5 秒/页（取决于文字密度）
3. **内存**：`pdf2image` 需要 `poppler-utils` 系统包（`apt install poppler-utils`）
4. **CPU 密集**：OCR 在 CPU 上运行，不依赖 GPU
5. **文本拼接**：多页 OCR 结果用 `[Page N]` 分隔，帮助后续 LLM 理解结构
6. **不改变主接口**：`extract_text()` 签名和返回值格式不变
