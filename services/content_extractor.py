"""参考资料内容提取与摘要服务

支持格式：
- PDF → PyMuPDF 文本提取
- 图片 (png/jpg/jpeg/gif/webp) → Gemini 多模态 OCR/描述
- 音频 (mp3/wav/ogg) → Gemini 多模态转写
- 文本 (txt/md) → 直接读取

提取后调用 Gemini 生成教学导向的结构化摘要，缓存为 .summary.json
"""
import os
import json
import logging
import hashlib
from datetime import datetime

logger = logging.getLogger(__name__)

# 摘要缓存目录名
SUMMARY_DIR_NAME = "_summaries"

# 文本提取上限（字符），超过后截断再摘要
MAX_EXTRACT_CHARS = 200_000

# 摘要的 token 目标（指导 AI 的输出长度）
SUMMARY_TARGET_CHARS = 8000

# 文件类型分组
TEXT_EXTS = {".txt", ".md"}
PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg"}

SUMMARIZE_PROMPT = """你是一个教学资料分析专家。请对以下教学参考资料的内容进行结构化摘要，用于辅助 AI 教师在日常教学对话中参考。

要求：
1. **保留核心知识结构**：章节标题、知识点列表、关键定义、定理、公式（用 LaTeX 格式）
2. **保留典型例题**：摘录有代表性的例题及其解法要点（每个知识点 1-2 道）
3. **标注重难点**：标记教材中强调的重点、易错点、考试高频内容
4. **忽略无关内容**：跳过出版信息、版权页、装饰性文字、重复的练习题（保留典型即可）
5. **保持简洁**：总字数控制在 3000-6000 字，信息密度要高
6. **使用 Markdown 格式**：层次清晰，方便阅读

输出格式示例：
```
# [资料标题]

## 第一章 xxx
### 知识点1：xxx
- 定义：...
- 公式：$...$
- 重点/易错点：...
- 典型例题：...

### 知识点2：xxx
...
```

以下是待摘要的资料内容：
---
{content}
---

请生成结构化摘要："""

IMAGE_EXTRACT_PROMPT = """这是一份教学参考资料的图片（可能是教材页面、习题、笔记等）。请：
1. 完整识别并提取图片中的所有文字内容（OCR）
2. 如果包含数学公式，用 LaTeX 格式转写
3. 如果包含图表/插图，用文字描述其内容
4. 保持原文结构和排版逻辑

请直接输出提取的内容，不要添加额外解释。"""

AUDIO_EXTRACT_PROMPT = """这是一份教学相关的音频（可能是课堂录音、讲解视频的音频等）。请：
1. 完整转写音频中的所有语音内容
2. 如果提到数学公式，用 LaTeX 格式表示
3. 标注不同说话者（如果可以区分）
4. 保持时间顺序

请直接输出转写内容，不要添加额外解释。"""


def _summary_dir(ref_dir: str) -> str:
    """摘要缓存目录：references/_summaries/"""
    d = os.path.join(ref_dir, SUMMARY_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def _summary_path(ref_dir: str, filename: str) -> str:
    """给定参考资料文件名，返回对应的摘要缓存路径"""
    return os.path.join(_summary_dir(ref_dir), f"{filename}.summary.json")


def _file_hash(fpath: str) -> str:
    """计算文件的 MD5 哈希，用于判断是否需要重新解析"""
    h = hashlib.md5()
    with open(fpath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def get_cached_summary(ref_dir: str, filename: str) -> dict | None:
    """读取已缓存的摘要，如果文件哈希不匹配（文件被替换）则返回 None"""
    sp = _summary_path(ref_dir, filename)
    if not os.path.exists(sp):
        return None
    try:
        with open(sp, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 验证文件哈希是否匹配
        fpath = os.path.join(ref_dir, filename)
        if os.path.exists(fpath) and data.get("file_hash") == _file_hash(fpath):
            return data
        return None  # 文件已变更，需要重新解析
    except Exception:
        return None


def save_summary(ref_dir: str, filename: str, summary: str, raw_text_len: int, file_hash: str):
    """保存摘要缓存"""
    sp = _summary_path(ref_dir, filename)
    data = {
        "filename": filename,
        "file_hash": file_hash,
        "summary": summary,
        "raw_text_length": raw_text_len,
        "summary_length": len(summary),
        "created_at": datetime.now().isoformat(),
    }
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def delete_summary(ref_dir: str, filename: str):
    """删除摘要缓存"""
    sp = _summary_path(ref_dir, filename)
    if os.path.exists(sp):
        os.remove(sp)


# ============ 文本提取 ============

# 图片型 PDF OCR 时的分批策略
PDF_OCR_MAX_PAGES = 40          # 最多 OCR 多少页（控制 API 费用）
PDF_OCR_BATCH_SIZE = 5          # 每次 API 调用发送几页图片
PDF_OCR_DPI = 150               # 渲染 DPI（越高越清晰但越慢）

PDF_PAGE_OCR_PROMPT = """这些是一本教材的连续页面图片。请：
1. 完整识别并提取每页中的所有文字内容（OCR）
2. 数学公式用 LaTeX 格式（$...$）表示
3. 如果包含图表/插图，用文字简要描述
4. 在每页内容前标注页码（如 "--- 第X页 ---"）
5. 保持原文结构和排版逻辑

请直接输出提取的内容，不要添加额外解释。"""


def extract_text_from_pdf(fpath: str) -> str:
    """使用 PyMuPDF 提取 PDF 全文（纯文字层）"""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(fpath)
        texts = []
        for page_num, page in enumerate(doc):
            text = page.get_text("text")
            if text.strip():
                texts.append(f"--- 第{page_num + 1}页 ---\n{text.strip()}")
        doc.close()
        full_text = "\n\n".join(texts)
        if len(full_text) > MAX_EXTRACT_CHARS:
            full_text = full_text[:MAX_EXTRACT_CHARS] + "\n\n[...内容过长已截断...]"
        return full_text
    except ImportError:
        logger.error("PyMuPDF 未安装，无法解析 PDF。请运行: pip install PyMuPDF")
        return ""
    except Exception as e:
        logger.error(f"PDF 解析失败: {e}")
        return ""


def _select_pages_for_ocr(total_pages: int) -> list[int]:
    """智能选择要 OCR 的页面索引（均匀抽样覆盖全书）
    
    策略：
    - 总页数 <= PDF_OCR_MAX_PAGES：全部 OCR
    - 总页数 > PDF_OCR_MAX_PAGES：均匀抽样，确保首尾和目录页被包含
    """
    if total_pages <= PDF_OCR_MAX_PAGES:
        return list(range(total_pages))
    
    # 必须包含的页面：前3页（封面+目录）、最后1页
    must_include = {0, 1, 2, min(total_pages - 1, 3)}
    remaining_slots = PDF_OCR_MAX_PAGES - len(must_include)
    
    # 均匀分布剩余名额
    step = total_pages / remaining_slots
    sampled = set()
    for i in range(remaining_slots):
        idx = int(i * step)
        if idx not in must_include:
            sampled.add(idx)
    
    all_pages = sorted(must_include | sampled)
    return all_pages[:PDF_OCR_MAX_PAGES]


async def extract_text_from_pdf_via_ocr(fpath: str, gemini_config: dict) -> str:
    """对图片型/扫描版 PDF：渲染页面为图片 → Gemini 多模态 OCR
    
    分批发送页面图片给 Gemini，避免单次请求过大。
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF 未安装")
        return ""
    
    client, model = await _get_genai_client(gemini_config)
    if not client:
        logger.error("无法获取 Gemini 客户端，图片型 PDF 需要 Gemini API 进行 OCR")
        return ""
    
    try:
        doc = fitz.open(fpath)
        total_pages = len(doc)
        pages_to_ocr = _select_pages_for_ocr(total_pages)
        logger.info(f"图片型 PDF: {total_pages}页, 选择{len(pages_to_ocr)}页进行 OCR")
        
        from google.genai import types
        all_texts = []
        
        # 分批处理
        for batch_start in range(0, len(pages_to_ocr), PDF_OCR_BATCH_SIZE):
            batch_indices = pages_to_ocr[batch_start:batch_start + PDF_OCR_BATCH_SIZE]
            parts = []
            page_info = []
            
            for page_idx in batch_indices:
                page = doc[page_idx]
                # 渲染为 PNG 图片
                mat = fitz.Matrix(PDF_OCR_DPI / 72, PDF_OCR_DPI / 72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                
                parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/png"))
                page_info.append(str(page_idx + 1))
            
            # 添加 prompt
            batch_prompt = f"以下是教材第 {', '.join(page_info)} 页的图片。\n\n{PDF_PAGE_OCR_PROMPT}"
            parts.append(types.Part.from_text(text=batch_prompt))
            
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=[types.Content(role="user", parts=parts)],
                    config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=8192),
                )
                batch_text = response.text or ""
                if batch_text.strip():
                    all_texts.append(batch_text.strip())
                logger.info(f"PDF OCR 批次 {batch_start // PDF_OCR_BATCH_SIZE + 1}: "
                           f"第{page_info[0]}-{page_info[-1]}页, 提取{len(batch_text)}字")
            except Exception as e:
                logger.error(f"PDF OCR 批次失败 (第{page_info[0]}-{page_info[-1]}页): {e}")
                continue
        
        doc.close()
        
        full_text = "\n\n".join(all_texts)
        if total_pages > PDF_OCR_MAX_PAGES:
            full_text = f"[注：本PDF共{total_pages}页，已均匀抽取{len(pages_to_ocr)}页进行OCR识别]\n\n" + full_text
        
        if len(full_text) > MAX_EXTRACT_CHARS:
            full_text = full_text[:MAX_EXTRACT_CHARS] + "\n\n[...内容过长已截断...]"
        
        return full_text
    except Exception as e:
        logger.error(f"PDF OCR 解析失败: {e}")
        return ""


def extract_text_from_file(fpath: str) -> str:
    """读取文本文件全文"""
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            text = f.read()
        if len(text) > MAX_EXTRACT_CHARS:
            text = text[:MAX_EXTRACT_CHARS] + "\n\n[...内容过长已截断...]"
        return text
    except Exception as e:
        logger.error(f"文本文件读取失败: {e}")
        return ""


async def extract_from_image_via_gemini(fpath: str, gemini_config: dict) -> str:
    """使用 Gemini 多模态 API 提取图片中的文字内容"""
    try:
        client, model = await _get_genai_client(gemini_config)
        if not client:
            return ""

        from google.genai import types
        with open(fpath, "rb") as f:
            image_bytes = f.read()

        ext = os.path.splitext(fpath)[1].lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".gif": "image/gif", ".webp": "image/webp"}
        mime = mime_map.get(ext, "image/png")

        response = client.models.generate_content(
            model=model,
            contents=[
                types.Content(role="user", parts=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime),
                    types.Part.from_text(text=IMAGE_EXTRACT_PROMPT),
                ])
            ],
            config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=4096),
        )
        return response.text or ""
    except Exception as e:
        logger.error(f"Gemini 图片解析失败: {e}")
        return ""


async def extract_from_audio_via_gemini(fpath: str, gemini_config: dict) -> str:
    """使用 Gemini 多模态 API 转写音频内容"""
    try:
        client, model = await _get_genai_client(gemini_config)
        if not client:
            return ""

        from google.genai import types
        with open(fpath, "rb") as f:
            audio_bytes = f.read()

        ext = os.path.splitext(fpath)[1].lower()
        mime_map = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg"}
        mime = mime_map.get(ext, "audio/mpeg")

        response = client.models.generate_content(
            model=model,
            contents=[
                types.Content(role="user", parts=[
                    types.Part.from_bytes(data=audio_bytes, mime_type=mime),
                    types.Part.from_text(text=AUDIO_EXTRACT_PROMPT),
                ])
            ],
            config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=8192),
        )
        return response.text or ""
    except Exception as e:
        logger.error(f"Gemini 音频解析失败: {e}")
        return ""


async def _get_genai_client(gemini_config: dict):
    """获取 google-genai 客户端（复用 chat_service 的连接逻辑）"""
    from google import genai
    mode = gemini_config.get("connection_mode", "ai_studio")
    model = gemini_config.get("model", "gemini-2.5-flash")

    try:
        if mode == "ai_studio":
            api_key = gemini_config.get("api_key", "")
            if not api_key:
                logger.error("未配置 AI Studio API Key，无法解析多媒体参考资料")
                return None, None
            client = genai.Client(api_key=api_key)
        elif mode == "vertex_ai":
            project = gemini_config.get("vertex_project", "")
            location = gemini_config.get("vertex_location", "us-central1")
            client = genai.Client(vertexai=True, project=project, location=location)
        else:
            logger.warning(f"多媒体解析暂不支持 {mode} 模式，仅支持 ai_studio 和 vertex_ai")
            return None, None
        return client, model
    except Exception as e:
        logger.error(f"获取 Gemini 客户端失败: {e}")
        return None, None


async def generate_summary_via_gemini(raw_text: str, filename: str, gemini_config: dict) -> str:
    """调用 Gemini 对提取的原始文本生成教学导向的结构化摘要"""
    if not raw_text.strip():
        return ""

    # 短文本不需要摘要，直接使用原文
    if len(raw_text) <= SUMMARY_TARGET_CHARS:
        return raw_text

    try:
        client, model = await _get_genai_client(gemini_config)
        if not client:
            # 无法连接 Gemini，退回到截断原文
            return raw_text[:SUMMARY_TARGET_CHARS] + "\n\n[...未能生成摘要，仅截断原文...]"

        from google.genai import types
        prompt = SUMMARIZE_PROMPT.format(content=raw_text[:MAX_EXTRACT_CHARS])

        response = client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
            config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=8192),
        )
        summary = response.text or ""
        if not summary.strip():
            return raw_text[:SUMMARY_TARGET_CHARS]
        return summary
    except Exception as e:
        logger.error(f"Gemini 摘要生成失败: {e}")
        return raw_text[:SUMMARY_TARGET_CHARS] + "\n\n[...摘要生成失败，仅截断原文...]"


# ============ 主流程 ============

async def extract_and_summarize(fpath: str, filename: str, ref_dir: str, gemini_config: dict) -> dict:
    """完整流程：提取内容 → 生成摘要 → 缓存

    返回: {"status": "ok"|"error"|"skipped", "summary": str, "raw_length": int}
    """
    # 检查缓存
    cached = get_cached_summary(ref_dir, filename)
    if cached:
        return {"status": "cached", "summary": cached["summary"], "raw_length": cached["raw_text_length"]}

    ext = os.path.splitext(filename)[1].lower()
    fhash = _file_hash(fpath)
    raw_text = ""

    # 第一步：提取原始文本
    if ext in TEXT_EXTS:
        raw_text = extract_text_from_file(fpath)
    elif ext in PDF_EXTS:
        # 先尝试文字层提取，失败则走 OCR
        raw_text = extract_text_from_pdf(fpath)
        if not raw_text.strip():
            logger.info(f"PDF 无文字层（扫描版），启动 Gemini OCR: {filename}")
            raw_text = await extract_text_from_pdf_via_ocr(fpath, gemini_config)
    elif ext in IMAGE_EXTS:
        raw_text = await extract_from_image_via_gemini(fpath, gemini_config)
    elif ext in AUDIO_EXTS:
        raw_text = await extract_from_audio_via_gemini(fpath, gemini_config)
    else:
        return {"status": "unsupported", "summary": "", "raw_length": 0}

    if not raw_text.strip():
        return {"status": "empty", "summary": "", "raw_length": 0}

    # 第二步：生成摘要（长文本才需要）
    summary = await generate_summary_via_gemini(raw_text, filename, gemini_config)

    # 第三步：缓存
    save_summary(ref_dir, filename, summary, len(raw_text), fhash)

    return {"status": "ok", "summary": summary, "raw_length": len(raw_text)}


async def process_all_references(ref_dir: str, gemini_config: dict) -> dict:
    """处理目录下所有参考资料，返回处理结果汇总"""
    if not os.path.exists(ref_dir):
        return {"processed": 0, "results": []}

    results = []
    for fname in os.listdir(ref_dir):
        if fname == SUMMARY_DIR_NAME:
            continue
        fpath = os.path.join(ref_dir, fname)
        if not os.path.isfile(fpath):
            continue
        result = await extract_and_summarize(fpath, fname, ref_dir, gemini_config)
        result["filename"] = fname
        results.append(result)

    return {"processed": len(results), "results": results}
