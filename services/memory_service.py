"""记忆文件服务 - 每课程独立 memory.json + question_bank.json
四维度 mastery 计算（基础层+验证层）:
  基础层: comprehension×0.15 + practice×0.40（上限55）
  验证层: test×0.30 + review×0.15（叠加贡献）
practice = AI生成的练习正确率 | test = 学生上传的作业/考试逐题正确率（含订正折扣）
"""
import json
import os
import asyncio
import logging
from datetime import datetime, timedelta
from config import COURSES_DIR

logger = logging.getLogger(__name__)


def _fire_archive(coro):
    """从同步代码中安全触发异步归档操作（不阻塞当前线程）"""
    def _on_done(t):
        if t.exception():
            logger.error(f"Archive task failed: {t.exception()}")
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        task.add_done_callback(_on_done)
    except RuntimeError:
        logger.warning("No running event loop for archive task")


# 纠错做对折扣系数
CORRECTION_DISCOUNT = 0.5
# test_score_history 保留最近 N 次
TEST_SCORE_HISTORY_LIMIT = 5
# review_quality_history 保留最近 N 次
REVIEW_QUALITY_HISTORY_LIMIT = 10

# ===================== 题库容量控制 =====================
# 每个知识点最多保留的题目数（错题 + 正确题总和）
MAX_QUESTIONS_PER_KP = 20
# 每个知识点最多保留的错题数（错题优先保留）
MAX_WRONG_PER_KP = 15
# 复习时注入的最大错题数
REVIEW_QUESTION_LIMIT = 5
# 单道题的题面+解析最大字符数（超长截断，防止上下文爆炸）
QUESTION_MAX_CHARS = 500

DEFAULT_MEMORY = {
    "course_info": {
        "name": "",
        "element": "pyro",
        "description": "",
        "teacher": "",
        "textbook": "",
    },
    "learning_progress": {
        "current_topic": "",
        "completed_topics": [],
        "mastery_level": 0,
        "total_sessions": 0,
    },
    "teaching_plan": {
        "goals": [],
        "steps": [],
        "current_step": 0,
        "direction": "",
    },
    "knowledge_points": [],
    "homework_history": [],
    "exam_history": [],
    "review_schedule": [],
    "review_history": [],
    "schedule": [],
    "quiz_analysis": {
        "strengths": [],
        "weaknesses": [],
        "recent_scores": [],
    },
    "student_profile": {
        "learning_style": "",
        "difficulty_preference": "medium",
        "notes": "",
    },
}


# ===================== Mastery 计算核心函数 =====================

def calculate_mastery(kp: dict) -> int:
    """两层结构计算知识点掌握度：基础层（绝对权重）+ 验证层（叠加贡献）

    ── 设计理念 ──
    教学(comprehension)和练习(practice)由 AI 主动驱动，几乎必然产生数据；
    测验(test)和复习(review)需要学生自主发起，很可能长期缺失。

    因此采用"基础层 + 验证层"两层结构：
    - 基础层（comp + practice）使用绝对权重，上限封顶 55 分
    - 验证层（test + review）作为叠加贡献，有数据时在基础分之上增加
    - 四维度齐全时满分 = 15 + 40 + 30 + 15 = 100
    - 保证单调性：加入验证层数据后掌握度 ≥ 纯基础层分数

    ── 数据来源区分 ──
    - practice（AI练习）: practice_total / practice_correct — AI 生成的练习题
    - test（作业/考试）: test_total / test_correct — 学生上传的作业/考试逐题数据
      * 订正做对的题目按 CORRECTION_DISCOUNT 折扣计入 test_correct
      * test_correct 可能包含小数（因为订正折扣），这是正常的

    ── comprehension 分级衰减（基于 interaction_depth）──
    - depth=0 (taught)   : × 0（纯讲解不计入）
    - depth=1 (assessed) : × 0.5（问答确认打五折）
    - depth≥2 (practiced/tested/corrected/reviewed) : × 1.0（全额）

    ── 各维度最大贡献 ──
    | 维度        | 最大贡献 | 层级   | 数据来源         |
    |------------|---------|--------|-----------------|
    | comp       | 15 分   | 基础层 | AI 评估理解度    |
    | practice   | 40 分   | 基础层 | AI 生成的练习题  |
    | test       | 30 分   | 验证层 | 学生上传作业/考试 |
    | review     | 15 分   | 验证层 | 学生复习表现     |
    """
    comp = kp.get("comprehension", 0)
    # practice: AI 生成的练习
    prac_total = kp.get("practice_total", 0)
    prac_correct = kp.get("practice_correct", 0)
    # test: 学生上传的作业/考试（含订正折扣）
    test_total = kp.get("test_total", 0)
    test_correct = kp.get("test_correct", 0)
    # 兼容旧数据：如果有旧的 test_score_history 但没有 test_total，回退到旧逻辑
    tsh = kp.get("test_score_history", [])
    rqh = kp.get("review_quality_history", [])
    depth = kp.get("interaction_depth", 0)

    has_practice = prac_total > 0
    has_test = test_total > 0 or len(tsh) > 0  # 兼容旧数据
    has_review = len(rqh) > 0

    # ── comprehension 根据 interaction_depth 衰减 ──
    if depth <= 0:
        effective_comp = 0           # taught: 不计入
    elif depth == 1:
        effective_comp = comp * 0.5  # assessed: 打五折
    else:
        effective_comp = comp        # practiced/tested 及以上: 全额

    # ── 各维度标准化到 0-100 ──
    practice_acc = (prac_correct / prac_total * 100) if has_practice else 0
    # test: 优先用新的逐题数据，回退到旧 test_score_history
    if test_total > 0:
        test_acc = (test_correct / test_total * 100)
    elif len(tsh) > 0:
        test_acc = sum(tsh) / len(tsh)  # 旧数据兼容
    else:
        test_acc = 0
    review_perf = (sum(rqh) / len(rqh) / 5 * 100) if has_review else 0

    # ── 基础层：绝对权重，不归一化 ──
    # comp 最高贡献 15 分，practice 最高贡献 40 分，基础层上限 55 分
    base_score = effective_comp * 0.15 + practice_acc * 0.40

    if base_score <= 0 and not has_test and not has_review:
        return 0

    # ── 验证层：test 和 review 使用绝对权重叠加 ──
    # test 最高贡献 30 分，review 最高贡献 15 分，各自独立不归一化
    verify_score = 0
    if has_test:
        verify_score += test_acc * 0.30
    if has_review:
        verify_score += review_perf * 0.15

    result = base_score + verify_score
    return max(0, min(100, round(result)))


def determine_review_tier(mastery: int) -> tuple:
    """根据 mastery 值决定复习层级
    Returns: (tier, fixed_interval_days)
        - (None, None)           : mastery < 40, 不复习
        - ("consolidation", 5)   : 40 <= mastery < 70, 低频巩固
        - ("sm2", None)          : mastery >= 70, SM-2 间隔递增
    """
    if mastery < 40:
        return (None, None)
    elif mastery < 70:
        return ("consolidation", 5)
    else:
        return ("sm2", None)


def _ensure_kp_fields(kp: dict):
    """确保知识点包含所有新增字段（兼容旧数据）"""
    kp.setdefault("comprehension", 0)
    kp.setdefault("interaction_depth", 0)
    kp.setdefault("practice_total", 0)
    kp.setdefault("practice_correct", 0)
    kp.setdefault("test_total", 0)        # 作业/考试总题数
    kp.setdefault("test_correct", 0)      # 作业/考试正确数（含订正折扣）
    kp.setdefault("test_score_history", [])  # 旧字段保留兼容
    kp.setdefault("review_quality_history", [])
    kp.setdefault("review_tier", None)
    kp.setdefault("chapter", "")

    # 兼容旧数据：如果有旧的 test_score_history 但没有 test_total，迁移数据
    # 把旧的 score_rate 均值转换为等效的 test_total/test_correct
    if len(kp.get("test_score_history", [])) > 0 and kp.get("test_total", 0) == 0:
        tsh = kp["test_score_history"]
        avg_rate = sum(tsh) / len(tsh)
        # 用虚拟 10 题来等效旧数据
        kp["test_total"] = 10
        kp["test_correct"] = round(avg_rate / 100 * 10, 1)

    # 兼容旧数据：如果已有 practice_total > 0 但没有 interaction_depth，自动修正为 2
    if kp.get("practice_total", 0) > 0 and kp["interaction_depth"] == 0:
        kp["interaction_depth"] = 2
    elif kp.get("test_total", 0) > 0 and kp["interaction_depth"] < 2:
        kp["interaction_depth"] = 2
    elif len(kp.get("test_score_history", [])) > 0 and kp["interaction_depth"] < 2:
        kp["interaction_depth"] = 2
    elif len(kp.get("review_quality_history", [])) > 0 and kp["interaction_depth"] < 2:
        kp["interaction_depth"] = 2


class MemoryService:
    def _memory_path(self, course_id: str) -> str:
        return os.path.join(COURSES_DIR, course_id, "memory.json")

    def load_memory(self, course_id: str) -> dict:
        path = self._memory_path(course_id)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = json.loads(json.dumps(DEFAULT_MEMORY))
            self._deep_merge(merged, data)
            return merged
        return json.loads(json.dumps(DEFAULT_MEMORY))

    def save_memory(self, course_id: str, memory: dict):
        path = self._memory_path(course_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=2, ensure_ascii=False)

    def _deep_merge(self, base: dict, override: dict):
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                self._deep_merge(base[k], v)
            else:
                base[k] = v

    def update_memory_field(self, course_id: str, field_path: str, value):
        memory = self.load_memory(course_id)
        keys = field_path.split(".")
        obj = memory
        for k in keys[:-1]:
            obj = obj.setdefault(k, {})
        obj[keys[-1]] = value
        # 如果更新了 teaching_plan 相关字段
        if keys[0] == "teaching_plan":
            # 写入 steps 时，自动创建步骤中关联但尚不存在的知识点
            if field_path == "teaching_plan.steps" and isinstance(value, list):
                self._auto_create_linked_kps(memory)
            self._sync_teaching_plan(memory)
            # 同步更新 learning_progress 和 schedule
            self._sync_learning_progress(memory)
            self._auto_generate_schedule(memory)
            self._auto_update_quiz_analysis(memory)
        self.save_memory(course_id, memory)
        return memory

    def _auto_create_linked_kps(self, memory: dict):
        """教学计划驱动知识点创建：自动为步骤中关联但尚不存在的知识点创建初始记录

        这确保了"先有计划，再有知识点"的正确流程，
        AI 可以自由制定细粒度的教学计划，系统自动补全知识点。
        """
        steps = memory.get("teaching_plan", {}).get("steps", [])
        existing_kps = {kp["name"] for kp in memory.get("knowledge_points", [])}
        now = datetime.now()

        for step in steps:
            if not isinstance(step, dict):
                continue
            for kp_name in step.get("linked_kps", []):
                if kp_name and kp_name not in existing_kps:
                    # 创建初始知识点
                    new_kp = {
                        "name": kp_name,
                        "chapter": step.get("chapter", ""),
                        "difficulty": "medium",
                        "comprehension": 0,
                        "interaction_depth": 0,
                        "practice_total": 0,
                        "practice_correct": 0,
                        "test_total": 0,
                        "test_correct": 0,
                        "test_score_history": [],
                        "review_quality_history": [],
                        "mastery": 0,
                        "review_count": 0,
                        "easiness_factor": 2.5,
                        "interval_days": 1,
                        "next_review": None,
                        "review_tier": None,
                        "created_at": now.isoformat(),
                        "updated_at": now.isoformat(),
                    }
                    memory.setdefault("knowledge_points", []).append(new_kp)
                    existing_kps.add(kp_name)
                    logger.info(f"Auto-created knowledge point '{kp_name}' from teaching plan step '{step.get('title', '?')}'")

    def _sync_learning_progress(self, memory: dict):
        """教学计划更新时自动同步 learning_progress 字段

        - mastery_level: 所有知识点的平均 mastery
        - current_topic: 当前步骤（in_progress 或第一个 not_started）的标题
        - current_phase: 当前步骤所在的教学阶段描述
        - completed_topics: 所有 mastered 步骤的标题列表
        """
        tp = memory.get("teaching_plan", {})
        steps = tp.get("steps", [])
        kps = memory.get("knowledge_points", [])
        lp = memory.setdefault("learning_progress", {})

        # 计算整体 mastery_level（所有关联知识点的平均值）
        plan_kp_names = set()
        for step in steps:
            if isinstance(step, dict):
                for kn in step.get("linked_kps", []):
                    plan_kp_names.add(kn)

        if plan_kp_names:
            kp_map = {kp["name"]: kp for kp in kps}
            masteries = [kp_map[n].get("mastery", 0) for n in plan_kp_names if n in kp_map]
            lp["mastery_level"] = round(sum(masteries) / len(masteries)) if masteries else 0
        else:
            lp["mastery_level"] = 0

        # current_topic: 当前正在学习的步骤
        current_step_idx = tp.get("current_step", 0)
        if steps and 0 <= current_step_idx < len(steps):
            step = steps[current_step_idx]
            if isinstance(step, dict):
                lp["current_topic"] = step.get("title", "")
            elif isinstance(step, str):
                lp["current_topic"] = step
        else:
            lp["current_topic"] = ""

        # current_phase: 根据步骤进度自动生成简短描述
        if steps:
            mastered_count = sum(1 for s in steps if isinstance(s, dict) and s.get("status") == "mastered")
            total = len(steps)
            if mastered_count == 0:
                lp["current_phase"] = "准备开始学习"
            elif mastered_count < total * 0.3:
                lp["current_phase"] = "基础学习阶段"
            elif mastered_count < total * 0.7:
                lp["current_phase"] = "核心知识强化"
            elif mastered_count < total:
                lp["current_phase"] = "综合提升阶段"
            else:
                lp["current_phase"] = "全部完成"
        else:
            lp["current_phase"] = "尚无教学计划"

        # completed_topics: mastered 步骤标题列表
        lp["completed_topics"] = [
            s.get("title", "") for s in steps
            if isinstance(s, dict) and s.get("status") == "mastered"
        ]

        memory["learning_progress"] = lp

    def _auto_update_quiz_analysis(self, memory: dict):
        """根据知识点数据自动计算 quiz_analysis（strengths/weaknesses/recent_scores）

        不再依赖 AI 通过 MEMORY_UPDATE 更新，从知识点数据中程序化提取：
        - strengths: mastery >= 60 且有做题记录的知识点
        - weaknesses: mastery < 40 且有互动记录（interaction_depth > 0），或做题正确率 < 50%
        - recent_scores: 从有做题记录的知识点中计算最近的正确率
        """
        kps = memory.get("knowledge_points", [])
        if not kps:
            return

        strengths = []
        weaknesses = []
        score_data = []  # (updated_at, accuracy)

        for kp in kps:
            name = kp.get("name", "")
            mastery = kp.get("mastery", 0)
            depth = kp.get("interaction_depth", 0)
            practice_total = kp.get("practice_total", 0)
            practice_correct = kp.get("practice_correct", 0)
            test_total = kp.get("test_total", 0)
            test_correct = kp.get("test_correct", 0)
            total_questions = practice_total + test_total
            total_correct = practice_correct + test_correct

            # 只分析有过互动的知识点（depth > 0）
            if depth == 0:
                continue

            # strengths: mastery >= 60
            if mastery >= 60:
                strengths.append((mastery, name))

            # weaknesses: mastery < 40，或做题正确率 < 50%（至少做了2题）
            if mastery < 40:
                weaknesses.append((mastery, name))
            elif total_questions >= 2 and total_correct / total_questions < 0.5:
                weaknesses.append((mastery, name))

            # 收集做题数据用于 recent_scores
            if total_questions > 0:
                accuracy = round(total_correct / total_questions * 100)
                score_data.append((kp.get("updated_at", ""), accuracy))

        # 排序：strengths 按 mastery 降序，weaknesses 按 mastery 升序
        strengths.sort(reverse=True)
        weaknesses.sort()

        qa = memory.setdefault("quiz_analysis", {})
        qa["strengths"] = [name for _, name in strengths[:8]]
        qa["weaknesses"] = [name for _, name in weaknesses[:8]]

        # recent_scores: 按时间排序取最近的分数
        if score_data:
            score_data.sort(key=lambda x: x[0], reverse=True)
            qa["recent_scores"] = [score for _, score in score_data[:10]]

    def _auto_generate_schedule(self, memory: dict):
        """教学计划更新时，根据步骤自动生成复习日程

        规则：
        - 清除旧的自动生成日程（保留手动添加的）
        - 只为 needs_review 步骤安排复习日程
        - not_started 和 in_progress 不生成日程（学习时间由用户自行安排）
        - 每天最多安排 2 个复习事件，按日期递增排列
        """
        tp = memory.get("teaching_plan", {})
        steps = tp.get("steps", [])
        if not steps:
            return

        old_schedule = memory.get("schedule", [])
        manual_events = [e for e in old_schedule if not e.get("auto_generated")]

        # 只收集 needs_review 步骤
        pending_steps = [s for s in steps if isinstance(s, dict) and s.get("status") == "needs_review"]

        if not pending_steps:
            memory["schedule"] = manual_events
            return

        now = datetime.now()
        new_events = []
        day_offset = 1
        daily_count = 0
        MAX_SCHEDULE_EVENTS = 14

        for step in pending_steps:
            if len(new_events) >= MAX_SCHEDULE_EVENTS:
                break

            title = step.get("title", "学习")
            event_title = f"{title} · 巩固复习"
            desc = f"巩固复习「{title}」"

            hour = 15 if daily_count % 2 == 0 else 19
            event_date = now + timedelta(days=day_offset)
            event_datetime = event_date.replace(hour=hour, minute=0, second=0, microsecond=0)

            new_events.append({
                "id": f"auto_{event_datetime.strftime('%Y%m%d%H%M')}_{len(new_events)}",
                "title": event_title,
                "type": "review",
                "datetime": event_datetime.isoformat(),
                "description": desc,
                "auto_generated": True,
                "created_at": now.isoformat(),
            })

            daily_count += 1
            if daily_count % 2 == 0:
                day_offset += 1

        memory["schedule"] = manual_events + new_events
        logger.info(f"Auto-generated {len(new_events)} review schedule events")


    # --- Knowledge Points ---
    def get_knowledge_points(self, course_id: str) -> list:
        return self.load_memory(course_id).get("knowledge_points", [])

    def update_knowledge_points(self, course_id: str, points: list):
        """处理 KNOWLEDGE_UPDATE 数据，更新知识点的各维度并重算 mastery

        每条 point 包含: name, chapter?, difficulty?, interaction_type, comprehension, questions_total?, questions_correct?

        interaction_type → interaction_depth 映射：
        - "taught"    → 0 (纯讲解，不增加 mastery)
        - "assessed"  → 1 (互动问答确认了理解)
        - "practiced" → 2 (做了练习题)
        - "tested"    → 2 (作业/考试)
        - "corrected" → 2 (纠错订正)
        depth 只升不降（取 max），确保一旦有过更高级别互动就保持
        """
        DEPTH_MAP = {
            "taught": 0,
            "assessed": 1,
            "practiced": 2,
            "tested": 2,
            "corrected": 2,
        }

        memory = self.load_memory(course_id)
        existing = {p["name"]: p for p in memory.get("knowledge_points", [])}
        now = datetime.now()

        for p in points:
            name = p.get("name", "")
            if not name:
                continue
            interaction_type = p.get("interaction_type", "taught")
            comprehension = p.get("comprehension", 0)
            q_total = p.get("questions_total", 0)
            q_correct = p.get("questions_correct", 0)

            new_depth = DEPTH_MAP.get(interaction_type, 0)

            if name in existing:
                kp = existing[name]
                _ensure_kp_fields(kp)

                # 更新 chapter / difficulty（如有新值）
                if p.get("chapter"):
                    kp["chapter"] = p["chapter"]
                if p.get("difficulty"):
                    kp["difficulty"] = p["difficulty"]

                # interaction_depth 只升不降
                old_depth = kp.get("interaction_depth", 0)
                kp["interaction_depth"] = max(old_depth, new_depth)

                # 加权平均更新 comprehension，防止 AI 评估波动过大
                old_comp = kp.get("comprehension", 0)
                if old_comp > 0:
                    kp["comprehension"] = round(old_comp * 0.4 + comprehension * 0.6)
                else:
                    kp["comprehension"] = comprehension

                # 根据 interaction_type 更新做题统计
                # practiced = AI 生成的练习 → 写入 practice_total/correct
                # tested = 学生上传的作业/考试 → 不在此处写入 test 数据
                #          （由 HOMEWORK/EXAM_RESULT → update_test_scores 专门处理，避免双写）
                # corrected = 订正 → 写入 test_correct（折扣），不增加 test_total
                if interaction_type == "practiced":
                    kp["practice_total"] += q_total
                    kp["practice_correct"] += q_correct
                elif interaction_type == "corrected":
                    # 订正：不增加 total，correct 按折扣累加到 test
                    kp["test_correct"] += q_correct * CORRECTION_DISCOUNT

                kp["updated_at"] = now.isoformat()

            else:
                # 新知识点
                kp = {
                    "name": name,
                    "chapter": p.get("chapter", ""),
                    "difficulty": p.get("difficulty", "medium"),
                    "comprehension": comprehension,
                    "interaction_depth": new_depth,
                    "practice_total": 0,
                    "practice_correct": 0,
                    "test_total": 0,
                    "test_correct": 0,
                    "test_score_history": [],
                    "review_quality_history": [],
                    "mastery": 0,
                    "review_count": 0,
                    "easiness_factor": 2.5,
                    "interval_days": 1,
                    "next_review": None,
                    "review_tier": None,
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
                if interaction_type == "practiced":
                    kp["practice_total"] += q_total
                    kp["practice_correct"] += q_correct
                elif interaction_type == "corrected":
                    kp["test_correct"] += q_correct * CORRECTION_DISCOUNT
                # tested 不在此处写入 test 数据（由 update_test_scores 处理）
                existing[name] = kp

            # 重算 mastery
            kp["mastery"] = calculate_mastery(kp)

            # 分层复习判定
            tier, fixed_interval = determine_review_tier(kp["mastery"])
            old_tier = kp.get("review_tier")
            kp["review_tier"] = tier

            if tier is None:
                # mastery < 40，不复习
                kp["next_review"] = None
            elif tier == "consolidation":
                # 40-70: 固定 5 天间隔。仅在首次进入或从 null 升级时设置
                if old_tier != "consolidation" or not kp.get("next_review"):
                    kp["next_review"] = (now + timedelta(days=fixed_interval)).isoformat()
            elif tier == "sm2":
                # >= 70: SM-2。仅在首次进入时设置初始复习时间
                if old_tier != "sm2" or not kp.get("next_review"):
                    kp["next_review"] = (now + timedelta(days=kp.get("interval_days", 1))).isoformat()

        memory["knowledge_points"] = list(existing.values())
        # 自动同步教学计划步骤状态
        self._sync_teaching_plan(memory)
        self._sync_learning_progress(memory)
        # 自动从知识点数据计算 quiz_analysis
        self._auto_update_quiz_analysis(memory)
        self.save_memory(course_id, memory)
        return memory["knowledge_points"]

    def _sync_teaching_plan(self, memory: dict):
        """根据知识点 mastery + 教学完成标记 自动推进教学计划步骤状态

        步骤完成判定（双条件）：
        - teaching_completed == True：AI 确认该步骤的教学内容已全部完成（讲解+出题+批改闭环）
        - 所有关联知识点 mastery >= threshold：学生真正掌握了这些知识点

        步骤状态流转：
        - not_started: 尚未开始学习
        - in_progress: 已开始学习（知识点 mastery > 0 或 teaching_completed 部分完成）
        - mastered: teaching_completed=True 且 所有关联知识点 mastery >= threshold
        - needs_review: 曾经 mastered 但某个知识点 mastery 跌回阈值以下

        current_step 自动计算为第一个非 mastered 的步骤索引
        """
        tp = memory.get("teaching_plan", {})
        steps = tp.get("steps", [])
        if not steps:
            return

        kp_map = {kp["name"]: kp for kp in memory.get("knowledge_points", [])}

        first_non_mastered = len(steps)  # 默认全部完成

        for i, step in enumerate(steps):
            # 兼容旧格式：字符串步骤自动转为对象
            if isinstance(step, str):
                step = {"title": step, "linked_kps": [], "mastery_threshold": 60, "status": "not_started", "teaching_completed": False}
                steps[i] = step

            # 确保新字段存在
            step.setdefault("teaching_completed", False)

            linked_kps = step.get("linked_kps", [])
            threshold = step.get("mastery_threshold", 60)
            old_status = step.get("status", "not_started")
            teaching_done = step.get("teaching_completed", False)

            if not linked_kps:
                # 没有关联知识点：仅看 teaching_completed
                if teaching_done:
                    step["status"] = "mastered"
                elif old_status not in ("mastered",):
                    if first_non_mastered > i:
                        first_non_mastered = i
                continue

            # 收集关联知识点的 mastery
            kp_masteries = []
            for kp_name in linked_kps:
                kp = kp_map.get(kp_name)
                if kp:
                    kp_masteries.append(kp.get("mastery", 0))
                else:
                    kp_masteries.append(0)

            all_above_threshold = all(m >= threshold for m in kp_masteries)
            any_started = any(m > 0 for m in kp_masteries)

            # 双条件判定：教学完成 + 知识点达标
            if teaching_done and all_above_threshold:
                step["status"] = "mastered"
            elif old_status == "mastered" and not all_above_threshold:
                # 曾达标但知识点跌回
                step["status"] = "needs_review"
            elif any_started or teaching_done:
                step["status"] = "in_progress"
            else:
                step["status"] = "not_started"

            if step["status"] != "mastered" and first_non_mastered > i:
                first_non_mastered = i

        tp["steps"] = steps
        tp["current_step"] = first_non_mastered
        memory["teaching_plan"] = tp

    def mark_step_completed(self, course_id: str, step_title: str):
        """AI 标记某个教学步骤的教学内容已全部完成（讲解+出题+批改闭环）

        这是步骤达标的必要条件之一，另一个条件是关联知识点 mastery 达标。
        两个条件都满足后，_sync_teaching_plan 会自动将步骤标记为 mastered。
        """
        memory = self.load_memory(course_id)
        tp = memory.get("teaching_plan", {})
        steps = tp.get("steps", [])
        changed = False

        for step in steps:
            if isinstance(step, dict) and step.get("title") == step_title:
                step["teaching_completed"] = True
                changed = True
                logger.info(f"Step '{step_title}' marked as teaching_completed")
                break

        if changed:
            self._sync_teaching_plan(memory)
            self._sync_learning_progress(memory)
            self._auto_update_quiz_analysis(memory)
            self.save_memory(course_id, memory)
        return memory

    def update_test_scores(self, course_id: str, knowledge_scores: list):
        """将作业/考试的按知识点逐题数据写入 test_total/test_correct 并重算 mastery

        knowledge_scores 格式:
        [{"name": "知识点名", "questions_total": 3, "questions_correct": 2}]

        注意：此函数不再使用旧的 score_rate 字段。如果 AI 仍输出 score_rate，
        会尝试用 score_rate 反推等效的 total/correct（假设 10 题基数）。
        """
        if not knowledge_scores:
            return
        memory = self.load_memory(course_id)
        kp_map = {kp["name"]: kp for kp in memory.get("knowledge_points", [])}
        changed = False

        for ks in knowledge_scores:
            name = ks.get("name", "")
            if name not in kp_map:
                continue
            kp = kp_map[name]
            _ensure_kp_fields(kp)

            # 优先使用逐题数据
            q_total = ks.get("questions_total", 0)
            q_correct = ks.get("questions_correct", 0)

            if q_total <= 0:
                # 兼容旧格式：如果只有 score_rate，用虚拟题数反推
                score_rate = ks.get("score_rate", 0)
                if score_rate > 0:
                    q_total = 10
                    q_correct = round(score_rate / 100 * 10)
                else:
                    continue

            kp["test_total"] += q_total
            kp["test_correct"] += q_correct

            # 有测试成绩 → interaction_depth 至少为 2
            if kp.get("interaction_depth", 0) < 2:
                kp["interaction_depth"] = 2
            kp["mastery"] = calculate_mastery(kp)

            # 分层复习更新
            tier, fixed_interval = determine_review_tier(kp["mastery"])
            old_tier = kp.get("review_tier")
            kp["review_tier"] = tier
            now = datetime.now()
            if tier is None:
                kp["next_review"] = None
            elif tier == "consolidation" and (old_tier != "consolidation" or not kp.get("next_review")):
                kp["next_review"] = (now + timedelta(days=fixed_interval)).isoformat()
            elif tier == "sm2" and (old_tier != "sm2" or not kp.get("next_review")):
                kp["next_review"] = (now + timedelta(days=kp.get("interval_days", 1))).isoformat()

            changed = True

        if changed:
            memory["knowledge_points"] = list(kp_map.values())
            self._sync_teaching_plan(memory)
            self._sync_learning_progress(memory)
            self._auto_update_quiz_analysis(memory)
            self.save_memory(course_id, memory)

    # --- Homework ---
    def add_homework_record(self, course_id: str, record: dict):
        memory = self.load_memory(course_id)
        record.setdefault("id", datetime.now().strftime("%Y%m%d%H%M%S"))
        record.setdefault("created_at", datetime.now().isoformat())
        memory["homework_history"].append(record)
        self.save_memory(course_id, memory)
        # 提取 knowledge_scores 更新 test_total/test_correct
        knowledge_scores = record.get("knowledge_scores", [])
        if knowledge_scores:
            self.update_test_scores(course_id, knowledge_scores)
        return record

    # --- Exam ---
    def add_exam_record(self, course_id: str, record: dict):
        memory = self.load_memory(course_id)
        record.setdefault("id", datetime.now().strftime("%Y%m%d%H%M%S"))
        record.setdefault("created_at", datetime.now().isoformat())
        memory["exam_history"].append(record)
        self.save_memory(course_id, memory)
        # 提取 knowledge_scores 更新 test_total/test_correct
        knowledge_scores = record.get("knowledge_scores", [])
        if knowledge_scores:
            self.update_test_scores(course_id, knowledge_scores)
        return record

    # --- Review Schedule ---
    def update_review_schedule(self, course_id: str, schedule: list):
        memory = self.load_memory(course_id)
        memory["review_schedule"] = schedule
        self.save_memory(course_id, memory)

    def postpone_review_event(self, course_id: str, knowledge_point: str) -> dict | None:
        """顺延复习事件到下一个记忆点（基于原定时间往后推一个间隔）"""
        memory = self.load_memory(course_id)
        now = datetime.now()
        result = None

        for kp in memory.get("knowledge_points", []):
            if kp.get("name") != knowledge_point:
                continue

            # 以原定复习时间为基准往后推，而非当前时间
            old_review = kp.get("next_review")
            try:
                base_dt = datetime.fromisoformat(old_review) if old_review else now
            except (ValueError, TypeError):
                base_dt = now

            tier = kp.get("review_tier")
            if tier == "consolidation":
                # 巩固层：固定 5 天后
                delta = timedelta(days=5)
            elif tier == "sm2":
                # SM-2 层：当前 interval × EF，至少 1 天
                interval = max(kp.get("interval_days", 1), 1)
                ef = kp.get("easiness_factor", 2.5)
                new_interval = max(1, round(interval * ef))
                delta = timedelta(days=new_interval)
            else:
                # 兜底 +1 天
                delta = timedelta(days=1)

            new_dt = base_dt + delta
            # 确保新时间严格在当前时间之后（至少明天）
            tomorrow_9am = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            if new_dt < tomorrow_9am:
                new_dt = tomorrow_9am
            else:
                new_dt = new_dt.replace(hour=9, minute=0, second=0, microsecond=0)

            kp["next_review"] = new_dt.isoformat()
            kp["rescheduled_at"] = now.isoformat()
            result = {"next_review": new_dt.isoformat(), "knowledge_point": knowledge_point}
            break

        if result:
            # 同步更新 review_schedule
            review_schedule = []
            for kp in memory.get("knowledge_points", []):
                if kp.get("mastery", 0) < 40:
                    continue
                nr = kp.get("next_review")
                if nr:
                    review_schedule.append({
                        "knowledge_point": kp["name"],
                        "next_review": nr,
                        "mastery": kp.get("mastery", 0),
                        "review_tier": kp.get("review_tier"),
                    })
            memory["review_schedule"] = review_schedule
            self.save_memory(course_id, memory)

        return result

    # --- Review History (completed reviews) ---
    def add_review_history(self, course_id: str, record: dict):
        """追加一条已完成的复习记录"""
        memory = self.load_memory(course_id)
        history = memory.setdefault("review_history", [])
        history.append(record)
        # 只保留最近 200 条，防止无限增长
        if len(history) > 200:
            # 归档被截断的复习记录
            evicted = history[:-200]
            from .db_service import db_service
            _fire_archive(db_service.archive_reviews(course_id, evicted))
            memory["review_history"] = history[-200:]
        self.save_memory(course_id, memory)

    # --- Schedule ---
    def get_schedule(self, course_id: str) -> list:
        return self.load_memory(course_id).get("schedule", [])

    def add_schedule_event(self, course_id: str, event: dict):
        memory = self.load_memory(course_id)
        event.setdefault("id", datetime.now().strftime("%Y%m%d%H%M%S%f"))
        event.setdefault("created_at", datetime.now().isoformat())
        memory["schedule"].append(event)
        self.save_memory(course_id, memory)
        return event

    def update_schedule_event(self, course_id: str, event_id: str, updates: dict):
        memory = self.load_memory(course_id)
        for e in memory["schedule"]:
            if e.get("id") == event_id:
                e.update(updates)
                break
        self.save_memory(course_id, memory)

    def delete_schedule_event(self, course_id: str, event_id: str):
        memory = self.load_memory(course_id)
        memory["schedule"] = [e for e in memory["schedule"] if e.get("id") != event_id]
        self.save_memory(course_id, memory)

    # ===================== Question Bank (独立文件) =====================

    def _qbank_path(self, course_id: str) -> str:
        return os.path.join(COURSES_DIR, course_id, "question_bank.json")

    def _load_qbank(self, course_id: str) -> dict:
        """加载题库，结构: {"questions": [...], "stats": {"total": N, "wrong": N}}"""
        path = self._qbank_path(course_id)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"questions": [], "stats": {"total": 0, "wrong": 0}}

    def _save_qbank(self, course_id: str, qbank: dict):
        path = self._qbank_path(course_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(qbank, f, indent=2, ensure_ascii=False)

    def _truncate_text(self, text: str, max_chars: int = QUESTION_MAX_CHARS) -> str:
        """截断过长文本，防止单道题占用过多上下文"""
        if len(text) <= max_chars:
            return text
        return text[:max_chars - 3] + "..."

    def add_questions(self, course_id: str, questions: list, source: str = "chat"):
        """添加题目到题库

        每条 question 结构:
        {
            "question": "题面",
            "student_answer": "学生答案",
            "correct_answer": "正确答案",
            "is_correct": true/false,
            "knowledge_point": "关联知识点",
            "difficulty": "easy/medium/hard",
            "error_analysis": "错因分析（仅错题）",
            "source": "homework/exam/practice/review"
        }
        """
        if not questions:
            return

        qbank = self._load_qbank(course_id)
        now = datetime.now().isoformat()

        for q in questions:
            if not q.get("question") or not q.get("knowledge_point"):
                continue

            entry = {
                "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
                "question": self._truncate_text(q.get("question", "")),
                "student_answer": self._truncate_text(q.get("student_answer", ""), 200),
                "correct_answer": self._truncate_text(q.get("correct_answer", ""), 300),
                "is_correct": q.get("is_correct", True),
                "knowledge_point": q.get("knowledge_point", ""),
                "difficulty": q.get("difficulty", "medium"),
                "error_analysis": self._truncate_text(q.get("error_analysis", ""), 200),
                "source": source,
                "created_at": now,
                "review_count": 0,
                "last_reviewed": None,
                "mastered": False,
            }
            qbank["questions"].append(entry)

        # 执行容量淘汰（返回被淘汰的题目用于归档）
        evicted = self._evict_questions(qbank)

        # 归档被淘汰的题目
        if evicted:
            from .db_service import db_service
            _fire_archive(db_service.archive_questions(course_id, evicted))

        # 更新统计
        qbank["stats"]["total"] = len(qbank["questions"])
        qbank["stats"]["wrong"] = sum(1 for q in qbank["questions"] if not q["is_correct"])

        self._save_qbank(course_id, qbank)
        logger.info(f"Added {len(questions)} questions for course {course_id}, "
                    f"bank size: {qbank['stats']['total']}")

    def _evict_questions(self, qbank: dict) -> list:
        """容量淘汰策略：按知识点分组，每个知识点保留上限内的题目

        淘汰优先级（从先淘汰到最后淘汰）：
        1. 已标记 mastered=True 的正确题（最先淘汰）
        2. 较老的正确题
        3. review_count >= 3 且标记 mastered 的错题
        4. 较老的错题（最后才淘汰）

        Returns: 被淘汰的题目列表（用于归档）
        """
        by_kp = {}
        for q in qbank["questions"]:
            kp = q.get("knowledge_point", "未分类")
            by_kp.setdefault(kp, []).append(q)

        kept = []
        evicted = []
        for kp, qs in by_kp.items():
            if len(qs) <= MAX_QUESTIONS_PER_KP:
                kept.extend(qs)
                continue

            # 分成错题和正确题
            wrong = [q for q in qs if not q["is_correct"]]
            correct = [q for q in qs if q["is_correct"]]

            # 错题排序：mastered + review_count 高的排前面（先淘汰）
            wrong.sort(key=lambda q: (
                q.get("mastered", False),
                q.get("review_count", 0),
                q.get("created_at", ""),
            ))
            # 正确题排序：mastered 的排前面（先淘汰），然后按时间
            correct.sort(key=lambda q: (
                not q.get("mastered", False),  # mastered=True 排前面
                q.get("created_at", ""),
            ))

            # 先保留错题（上限 MAX_WRONG_PER_KP），再用剩余空间保留正确题
            kept_wrong = wrong[-MAX_WRONG_PER_KP:] if len(wrong) > MAX_WRONG_PER_KP else wrong
            remaining_slots = MAX_QUESTIONS_PER_KP - len(kept_wrong)
            kept_correct = correct[-remaining_slots:] if remaining_slots > 0 else []

            # 计算被淘汰的题目
            kept_set = set(id(q) for q in kept_wrong) | set(id(q) for q in kept_correct)
            for q in qs:
                if id(q) not in kept_set:
                    evicted.append(q)

            kept.extend(kept_wrong)
            kept.extend(kept_correct)

        qbank["questions"] = kept
        return evicted

    def get_questions_for_review(self, course_id: str, point_name: str) -> list:
        """获取某知识点的精选错题用于复习上下文注入

        选取策略：
        1. 只选该知识点的**错题**（is_correct=False 且 mastered=False）
        2. 按 review_count 升序（复习次数少的优先）
        3. 最多返回 REVIEW_QUESTION_LIMIT 条
        4. 返回精简格式（不含 id 等元数据），控制 token 消耗
        """
        qbank = self._load_qbank(course_id)
        candidates = [
            q for q in qbank["questions"]
            if q.get("knowledge_point") == point_name
            and not q.get("is_correct", True)
            and not q.get("mastered", False)
        ]

        # review_count 低的优先，同 count 则老题优先
        candidates.sort(key=lambda q: (q.get("review_count", 0), q.get("created_at", "")))

        selected = candidates[:REVIEW_QUESTION_LIMIT]

        # 返回精简格式
        result = []
        for q in selected:
            entry = {
                "question": q["question"],
                "student_answer": q.get("student_answer", ""),
                "correct_answer": q.get("correct_answer", ""),
                "error_analysis": q.get("error_analysis", ""),
                "difficulty": q.get("difficulty", "medium"),
                "source": q.get("source", ""),
            }
            result.append(entry)

        return result

    def mark_questions_reviewed(self, course_id: str, point_name: str):
        """复习后标记该知识点的错题 review_count +1"""
        qbank = self._load_qbank(course_id)
        now = datetime.now().isoformat()
        changed = False

        for q in qbank["questions"]:
            if (q.get("knowledge_point") == point_name
                    and not q.get("is_correct", True)
                    and not q.get("mastered", False)):
                q["review_count"] = q.get("review_count", 0) + 1
                q["last_reviewed"] = now
                # 复习 3 次以上自动标记为已掌握
                if q["review_count"] >= 3:
                    q["mastered"] = True
                changed = True

        if changed:
            self._save_qbank(course_id, qbank)

    def get_question_bank_stats(self, course_id: str) -> dict:
        """获取题库统计信息"""
        qbank = self._load_qbank(course_id)
        questions = qbank["questions"]

        by_kp = {}
        for q in questions:
            kp = q.get("knowledge_point", "未分类")
            by_kp.setdefault(kp, {"total": 0, "wrong": 0, "mastered": 0})
            by_kp[kp]["total"] += 1
            if not q.get("is_correct", True):
                by_kp[kp]["wrong"] += 1
            if q.get("mastered", False):
                by_kp[kp]["mastered"] += 1

        return {
            "total": len(questions),
            "wrong": sum(1 for q in questions if not q.get("is_correct", True)),
            "mastered": sum(1 for q in questions if q.get("mastered", False)),
            "by_knowledge_point": by_kp,
        }


memory_service = MemoryService()
