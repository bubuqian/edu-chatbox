"""课程管理服务"""
import os
import json
import copy
import shutil
import uuid
import logging
from datetime import datetime
from config import COURSES_DIR
from .memory_service import memory_service, DEFAULT_MEMORY

logger = logging.getLogger(__name__)


class CourseService:
    def _courses_meta_path(self) -> str:
        return os.path.join(COURSES_DIR, "courses.json")

    def _load_courses_meta(self) -> list:
        path = self._courses_meta_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save_courses_meta(self, courses: list):
        path = self._courses_meta_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(courses, f, indent=2, ensure_ascii=False)

    def get_courses(self) -> list:
        return self._load_courses_meta()

    def get_course(self, course_id: str) -> dict | None:
        for c in self._load_courses_meta():
            if c["id"] == course_id:
                return c
        return None

    def create_course(self, name: str, element: str = "pyro", description: str = "") -> dict:
        course_id = str(uuid.uuid4())[:8]
        course_dir = os.path.join(COURSES_DIR, course_id)
        os.makedirs(course_dir, exist_ok=True)
        os.makedirs(os.path.join(course_dir, "uploads"), exist_ok=True)
        os.makedirs(os.path.join(course_dir, "references"), exist_ok=True)

        memory = json.loads(json.dumps(DEFAULT_MEMORY))
        memory["course_info"]["name"] = name
        memory["course_info"]["element"] = element
        memory["course_info"]["description"] = description
        memory_service.save_memory(course_id, memory)

        course_meta = {
            "id": course_id,
            "name": name,
            "element": element,
            "description": description,
        }
        courses = self._load_courses_meta()
        courses.append(course_meta)
        self._save_courses_meta(courses)
        return course_meta

    def update_course(self, course_id: str, updates: dict) -> dict | None:
        courses = self._load_courses_meta()
        for c in courses:
            if c["id"] == course_id:
                c.update(updates)
                self._save_courses_meta(courses)
                memory = memory_service.load_memory(course_id)
                if "name" in updates:
                    memory["course_info"]["name"] = updates["name"]
                if "element" in updates:
                    memory["course_info"]["element"] = updates["element"]
                if "description" in updates:
                    memory["course_info"]["description"] = updates["description"]
                memory_service.save_memory(course_id, memory)
                return c
        return None

    def remove_course(self, course_id: str) -> bool:
        """软删除：仅从 courses.json 移除（界面上不再显示），保留所有文件和数据库数据"""
        courses = self._load_courses_meta()
        new_courses = [c for c in courses if c["id"] != course_id]
        if len(new_courses) == len(courses):
            return False
        self._save_courses_meta(new_courses)
        return True

    def delete_course(self, course_id: str) -> bool:
        """永久删除：从 courses.json 移除 + 删除课程目录"""
        courses = self._load_courses_meta()
        new_courses = [c for c in courses if c["id"] != course_id]
        if len(new_courses) < len(courses):
            self._save_courses_meta(new_courses)
        course_dir = os.path.join(COURSES_DIR, course_id)
        if os.path.exists(course_dir):
            shutil.rmtree(course_dir)
            return True
        return len(new_courses) < len(courses)

    def get_all_course_dirs(self) -> list:
        """获取所有存在目录的课程（含已从界面移除的），用于继承和管理"""
        active_courses = {c["id"]: c for c in self._load_courses_meta()}
        all_courses = []
        if not os.path.isdir(COURSES_DIR):
            return all_courses
        for entry in os.listdir(COURSES_DIR):
            course_dir = os.path.join(COURSES_DIR, entry)
            if not os.path.isdir(course_dir) or entry == "__pycache__":
                continue
            mem_path = os.path.join(course_dir, "memory.json")
            if not os.path.exists(mem_path):
                continue
            if entry in active_courses:
                info = active_courses[entry].copy()
                info["archived"] = False
            else:
                # Try to read course info from memory.json
                try:
                    with open(mem_path, "r", encoding="utf-8") as f:
                        mem = json.load(f)
                    ci = mem.get("course_info", {})
                    info = {
                        "id": entry,
                        "name": ci.get("name", "未命名课程"),
                        "element": ci.get("element", "geo"),
                        "description": ci.get("description", ""),
                        "archived": True,
                    }
                except Exception:
                    info = {"id": entry, "name": "未命名课程", "element": "geo", "description": "", "archived": True}
            all_courses.append(info)
        return all_courses

    def create_course_from_archive(
        self,
        name: str,
        element: str = "pyro",
        description: str = "",
        inherit_from: list[str] = None,
        source_memories: dict[str, dict] = None,
        archive_data: dict[str, dict] = None,
    ) -> dict:
        """从旧课程档案继承创建新课程

        创建一个全新的课程（新 ID），知识点和题库从空白开始，
        但将来源课程的学习积累浓缩为"学生能力档案摘要"，
        注入 AI context 让新课程的 AI 了解学生的底子。

        继承的内容（作为能力画像，不搬运数据）：
        1. 学生画像（学习风格、难度偏好）
        2. 先修知识能力摘要（哪些学过/掌握了/薄弱的）
        3. 常见错误模式
        """
        # 1. 创建全新课程（新 ID，独立目录）
        course_id = str(uuid.uuid4())[:8]
        course_dir = os.path.join(COURSES_DIR, course_id)
        os.makedirs(course_dir, exist_ok=True)
        os.makedirs(os.path.join(course_dir, "uploads"), exist_ok=True)
        os.makedirs(os.path.join(course_dir, "references"), exist_ok=True)

        memory = json.loads(json.dumps(DEFAULT_MEMORY))
        memory["course_info"]["name"] = name
        memory["course_info"]["element"] = element
        memory["course_info"]["description"] = description

        if not inherit_from or not source_memories:
            memory_service.save_memory(course_id, memory)
            course_meta = {"id": course_id, "name": name, "element": element, "description": description}
            courses = self._load_courses_meta()
            courses.append(course_meta)
            self._save_courses_meta(courses)
            return course_meta

        now = datetime.now()
        source_names = []
        all_kp_entries = []  # [(kp_name, mastery, course_name)]
        strengths = []
        weaknesses = []
        error_summaries = []

        # 2. 从来源课程提取知识点能力数据（只读取，不复制到新课程）
        for src_id in inherit_from:
            src_mem = source_memories.get(src_id, {})
            src_name = src_mem.get("course_info", {}).get("name", src_id)
            source_names.append(src_name)

            # 从活跃 memory 中读取知识点
            seen_kps = set()
            for kp in src_mem.get("knowledge_points", []):
                kp_name = kp.get("name", "")
                if not kp_name:
                    continue
                mastery = kp.get("mastery", 0)
                all_kp_entries.append((kp_name, mastery, src_name))
                seen_kps.add(kp_name)

                if mastery >= 80:
                    strengths.append(f"{kp_name}({mastery}%)")
                elif mastery < 50 and kp.get("interaction_depth", 0) >= 1:
                    weaknesses.append(f"{kp_name}({mastery}%)")

            # 从归档快照补充已不在活跃 memory 中的知识点
            if archive_data and src_id in archive_data:
                arch = archive_data[src_id]
                for kp_name, snap in arch.get("kp_latest", {}).items():
                    if kp_name in seen_kps:
                        continue
                    mastery = snap.get("mastery", 0)
                    all_kp_entries.append((kp_name, mastery, src_name))

                # 提取错误模式
                for kp_name, errors in arch.get("error_patterns", {}).items():
                    for err in errors[:2]:
                        analysis = err.get("error_analysis", "")
                        if analysis:
                            error_summaries.append(f"{kp_name}: {analysis}")

        # 3. 继承学生画像（合并多来源）
        merged_profile = {}
        for src_id in inherit_from:
            src_mem = source_memories.get(src_id, {})
            src_profile = src_mem.get("student_profile", {})
            if not merged_profile:
                merged_profile = copy.deepcopy(src_profile)
            else:
                # 合并 notes
                existing_notes = merged_profile.get("notes", "")
                new_notes = src_profile.get("notes", "")
                if new_notes and new_notes not in existing_notes:
                    merged_profile["notes"] = f"{existing_notes}; {new_notes}" if existing_notes else new_notes
        if merged_profile:
            memory["student_profile"] = merged_profile

        # 4. 生成结构化的先修知识能力摘要
        summary_parts = []
        summary_parts.append(f"来源课程: {', '.join(source_names)}")
        summary_parts.append(f"继承时间: {now.strftime('%Y-%m-%d')}")
        summary_parts.append(f"先修知识点总数: {len(all_kp_entries)}")

        if all_kp_entries:
            avg_mastery = round(sum(m for _, m, _ in all_kp_entries) / len(all_kp_entries))
            summary_parts.append(f"整体平均掌握度: {avg_mastery}%")

        if strengths:
            summary_parts.append(f"已掌握的知识: {', '.join(strengths[:15])}")
        if weaknesses:
            summary_parts.append(f"薄弱环节: {', '.join(weaknesses[:15])}")
        if error_summaries:
            summary_parts.append(f"常见错误模式: {'; '.join(error_summaries[:8])}")

        # 学习风格描述
        if merged_profile.get("learning_style"):
            summary_parts.append(f"学习风格: {merged_profile['learning_style']}")
        if merged_profile.get("difficulty_preference"):
            summary_parts.append(f"难度偏好: {merged_profile['difficulty_preference']}")
        if merged_profile.get("notes"):
            summary_parts.append(f"学生特点: {merged_profile['notes']}")

        # 5. 存储到 memory（不是知识点列表，而是文本摘要）
        memory["prior_knowledge"] = {
            "source_courses": [
                {"id": src_id, "name": source_memories.get(src_id, {}).get("course_info", {}).get("name", src_id)}
                for src_id in inherit_from
            ],
            "inherited_at": now.isoformat(),
            "summary": "\n".join(summary_parts),
            "kp_overview": [
                {"name": kp_name, "mastery": mastery, "from_course": course_name}
                for kp_name, mastery, course_name in sorted(all_kp_entries, key=lambda x: -x[1])
            ],
            "strengths": strengths[:15],
            "weaknesses": weaknesses[:15],
            "error_patterns": error_summaries[:8],
        }

        # knowledge_points 保持空白 — 新课程自己积累
        memory["knowledge_points"] = []

        # 6. 保存新课程 memory（题库不复制，从空白开始）
        memory_service.save_memory(course_id, memory)

        # 7. 注册课程元数据
        course_meta = {
            "id": course_id,
            "name": name,
            "element": element,
            "description": description,
        }
        courses = self._load_courses_meta()
        courses.append(course_meta)
        self._save_courses_meta(courses)

        logger.info(f"Created course '{name}' ({course_id}) with prior knowledge from {source_names}, "
                    f"{len(all_kp_entries)} prior KPs summarized")

        return {
            **course_meta,
            "inherited": True,
            "prior_kp_count": len(all_kp_entries),
            "source_courses": source_names,
        }


course_service = CourseService()
