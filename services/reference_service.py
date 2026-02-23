"""参考资料管理服务

上传时自动触发内容提取和摘要生成（PDF/图片/音频 → 文本 → AI 摘要）
对话时使用摘要缓存构建上下文，支持所有文件格式
"""
import os
import uuid
import logging
from datetime import datetime
from config import COURSES_DIR, MAX_REFERENCES, MAX_FILE_SIZE, ALLOWED_EXTENSIONS
from services.content_extractor import (
    extract_and_summarize, get_cached_summary, delete_summary,
    SUMMARY_DIR_NAME,
)

logger = logging.getLogger(__name__)


class ReferenceService:
    def _ref_dir(self, course_id: str) -> str:
        return os.path.join(COURSES_DIR, course_id, "references")

    def _upload_dir(self, course_id: str) -> str:
        return os.path.join(COURSES_DIR, course_id, "uploads")

    def list_references(self, course_id: str) -> list:
        ref_dir = self._ref_dir(course_id)
        if not os.path.exists(ref_dir):
            return []
        files = []
        for fname in os.listdir(ref_dir):
            if fname == SUMMARY_DIR_NAME:
                continue
            fpath = os.path.join(ref_dir, fname)
            if os.path.isfile(fpath):
                # 检查是否有摘要缓存
                cached = get_cached_summary(ref_dir, fname)
                files.append({
                    "name": fname,
                    "size": os.path.getsize(fpath),
                    "created_at": datetime.fromtimestamp(os.path.getctime(fpath)).isoformat(),
                    "has_summary": cached is not None,
                    "summary_length": cached["summary_length"] if cached else 0,
                })
        return sorted(files, key=lambda x: x["created_at"], reverse=True)

    async def upload_reference(self, course_id: str, filename: str, content: bytes) -> dict:
        ref_dir = self._ref_dir(course_id)
        os.makedirs(ref_dir, exist_ok=True)

        existing = self.list_references(course_id)
        if len(existing) >= MAX_REFERENCES:
            raise ValueError(f"参考资料数量已达上限 ({MAX_REFERENCES})")

        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型: {ext}")

        if len(content) > MAX_FILE_SIZE:
            raise ValueError(f"文件大小超过限制 ({MAX_FILE_SIZE // 1024 // 1024}MB)")

        safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        fpath = os.path.join(ref_dir, safe_name)
        with open(fpath, "wb") as f:
            f.write(content)

        return {
            "name": safe_name,
            "original_name": filename,
            "size": len(content),
            "has_summary": False,  # 上传后还没有摘要
        }

    async def process_reference(self, course_id: str, filename: str, gemini_config: dict) -> dict:
        """对单个参考资料执行内容提取和摘要生成

        应在上传后异步调用，不阻塞上传响应。
        返回: {"status": "ok"|"cached"|"error"|..., "summary": str, "raw_length": int}
        """
        ref_dir = self._ref_dir(course_id)
        fpath = os.path.join(ref_dir, filename)
        if not os.path.isfile(fpath):
            return {"status": "not_found", "summary": "", "raw_length": 0}
        return await extract_and_summarize(fpath, filename, ref_dir, gemini_config)

    def delete_reference(self, course_id: str, filename: str) -> bool:
        ref_dir = self._ref_dir(course_id)
        fpath = os.path.join(ref_dir, filename)
        if os.path.exists(fpath):
            os.remove(fpath)
            # 同时删除摘要缓存
            delete_summary(ref_dir, filename)
            return True
        return False

    async def save_upload(self, course_id: str, filename: str, content: bytes) -> str:
        upload_dir = self._upload_dir(course_id)
        os.makedirs(upload_dir, exist_ok=True)
        safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        fpath = os.path.join(upload_dir, safe_name)
        with open(fpath, "wb") as f:
            f.write(content)
        return fpath

    def get_reference_context(self, course_id: str) -> str:
        """构建参考资料上下文，优先使用摘要缓存

        优先级：摘要缓存 > 原文读取（txt/md）> 文件名占位
        """
        refs = self.list_references(course_id)
        if not refs:
            return ""
        ref_dir = self._ref_dir(course_id)
        parts = []

        for r in refs:
            fname = r["name"]
            fpath = os.path.join(ref_dir, fname)
            ext = os.path.splitext(fname)[1].lower()

            # 优先使用摘要缓存
            cached = get_cached_summary(ref_dir, fname)
            if cached and cached.get("summary"):
                summary = cached["summary"]
                raw_len = cached.get("raw_text_length", 0)
                parts.append(
                    f"[参考资料: {fname}] (原文 {raw_len} 字，已生成摘要)\n{summary}"
                )
                continue

            # 回退：txt/md 直接读取
            if ext in {".txt", ".md"}:
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()[:8000]  # 提高到 8000 字
                    parts.append(f"[参考资料: {fname}]\n{content}")
                except Exception:
                    parts.append(f"[参考资料: {fname}] (无法读取)")
            else:
                # 二进制文件没有摘要缓存 → 提示未解析
                parts.append(
                    f"[参考资料: {fname}] (大小: {r['size']} bytes，尚未解析内容，"
                    f"请在参考资料管理中点击\"解析\"生成摘要)"
                )

        return "\n\n".join(parts)

    def get_summary_status(self, course_id: str) -> list:
        """获取所有参考资料的摘要状态"""
        refs = self.list_references(course_id)
        statuses = []
        for r in refs:
            statuses.append({
                "name": r["name"],
                "size": r["size"],
                "has_summary": r.get("has_summary", False),
                "summary_length": r.get("summary_length", 0),
            })
        return statuses

    def get_file_summary(self, course_id: str, filename: str) -> dict | None:
        """获取单个参考资料的摘要内容"""
        ref_dir = self._ref_dir(course_id)
        cached = get_cached_summary(ref_dir, filename)
        if cached:
            return {
                "filename": filename,
                "summary": cached.get("summary", ""),
                "raw_text_length": cached.get("raw_text_length", 0),
                "summary_length": cached.get("summary_length", 0),
                "created_at": cached.get("created_at", ""),
            }
        # txt/md 无摘要缓存时直接读取
        ext = os.path.splitext(filename)[1].lower()
        if ext in {".txt", ".md"}:
            fpath = os.path.join(ref_dir, filename)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                    return {
                        "filename": filename,
                        "summary": content[:8000],
                        "raw_text_length": len(content),
                        "summary_length": min(len(content), 8000),
                        "created_at": "",
                        "is_raw_text": True,
                    }
                except Exception:
                    pass
        return None


reference_service = ReferenceService()
