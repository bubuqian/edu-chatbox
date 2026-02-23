"""遗忘曲线复习服务 - SM-2 算法 + 分层复习（含过期自动顺延）"""
import asyncio
import logging
from datetime import datetime, timedelta, time as dtime
from config import REVIEW_SCAN_INTERVAL, COURSES_DIR
from .memory_service import memory_service, calculate_mastery, determine_review_tier, _ensure_kp_fields
from .db_service import db_service
from .course_service import course_service

logger = logging.getLogger(__name__)

# 知识点到期后，在此时间窗口内会被标记为"待复习"推送给 reminder_service
_DUE_WINDOW_SECONDS = 600  # 10 分钟窗口

# KP 快照去重：记录每课程上次快照时间，每天最多拍一次
_last_kp_snapshot_date = {}


def _safe_archive(coro):
    """统一的异步归档触发（带错误日志）"""
    def _on_done(t):
        if t.exception():
            logger.error(f"Archive task failed: {t.exception()}")
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        task.add_done_callback(_on_done)
    except RuntimeError:
        logger.warning("No running event loop for archive task")


def sm2_update(point: dict, quality: int) -> dict:
    """简化 SM-2 算法更新知识点复习参数
    quality: 0-5 评估质量（0=完全忘记, 5=完美记忆）
    """
    ef = point.get("easiness_factor", 2.5)
    interval = point.get("interval_days", 1)
    review_count = point.get("review_count", 0)

    ef = max(1.3, ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))

    if quality < 3:
        interval = 1
    else:
        if review_count == 0:
            interval = 1
        elif review_count == 1:
            interval = 6
        else:
            interval = round(interval * ef)

    review_count += 1
    next_review = (datetime.now() + timedelta(days=interval)).isoformat()

    point["easiness_factor"] = round(ef, 2)
    point["interval_days"] = interval
    point["review_count"] = review_count
    point["next_review"] = next_review
    return point


def _next_morning(now: datetime) -> datetime:
    """返回明天上午 9:00"""
    tomorrow = now.date() + timedelta(days=1)
    return datetime.combine(tomorrow, dtime(9, 0))


def _reschedule_overdue(point: dict, now: datetime) -> bool:
    """检查知识点是否过期，若超过到期窗口则顺延到明天上午。

    策略（分层）：
    - mastery < 40 → 不需要复习，跳过
    - 到期 ≤ _DUE_WINDOW_SECONDS → 不处理（属于正常触发窗口，由 reminder 推送）
    - 过期 ≤ 30 天               → 顺延到明天 9:00
    - 过期 > 30 天               → 顺延到明天 9:00 + 降低 comprehension + 重置 interval
    """
    _ensure_kp_fields(point)
    mastery = point.get("mastery", 0)

    # mastery < 40 表示尚未达到复习阈值
    if mastery < 40:
        point["next_review"] = None
        point["review_tier"] = None
        return False

    nr = point.get("next_review")
    if not nr:
        return False
    try:
        review_dt = datetime.fromisoformat(nr)
    except (ValueError, TypeError):
        return False

    if review_dt >= now:
        return False  # 未过期

    overdue_seconds = (now - review_dt).total_seconds()

    if overdue_seconds <= _DUE_WINDOW_SECONDS:
        return False  # 在到期窗口内，让 reminder 正常推送

    overdue_days = overdue_seconds / 86400
    new_time = _next_morning(now)

    if overdue_days > 30:
        # 严重过期：降低 comprehension（而非直接改 mastery），然后重算
        old_comp = point.get("comprehension", 0)
        point["comprehension"] = max(0, old_comp - 15)
        point["interval_days"] = 1
        point["mastery"] = calculate_mastery(point)
        # 重新判定复习层级
        tier, fixed_interval = determine_review_tier(point["mastery"])
        point["review_tier"] = tier
        if tier is None:
            point["next_review"] = None
            logger.info(f"Overdue point '{point.get('name')}' dropped below review threshold after decay")
            return True

    point["next_review"] = new_time.isoformat()
    point["rescheduled_at"] = now.isoformat()
    logger.info(f"Rescheduled overdue point '{point.get('name')}' "
                f"(overdue {overdue_days:.1f}d) -> {point['next_review']}")
    return True


class ReviewService:
    def __init__(self):
        self._task = None
        self._running = False
        self._pending_reviews = {}

    async def start(self):
        self._running = True
        await self._scan_all_courses()
        self._task = asyncio.create_task(self._scan_loop())
        logger.info("ReviewService started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ReviewService stopped")

    async def _scan_loop(self):
        try:
            while self._running:
                await asyncio.sleep(REVIEW_SCAN_INTERVAL)
                await self._scan_all_courses()
        except asyncio.CancelledError:
            pass

    async def _scan_all_courses(self):
        try:
            courses = course_service.get_courses()
            now = datetime.now()
            new_pending = {}

            for course in courses:
                cid = course["id"]
                memory = memory_service.load_memory(cid)
                kps = memory.get("knowledge_points", [])
                dirty = False

                # 确保所有知识点有新字段
                for kp in kps:
                    _ensure_kp_fields(kp)

                # 第一遍：处理所有过期顺延
                for kp in kps:
                    if _reschedule_overdue(kp, now):
                        dirty = True

                if dirty:
                    memory["knowledge_points"] = kps
                    memory_service.save_memory(cid, memory)

                # 第二遍：收集在到期窗口内的知识点（刚到期还没被顺延的）
                # 跳过 mastery < 40（未达到复习阈值）的知识点
                due_points = []
                for kp in kps:
                    if kp.get("mastery", 0) < 40:
                        continue
                    nr = kp.get("next_review")
                    if nr:
                        try:
                            review_dt = datetime.fromisoformat(nr)
                            overdue = (now - review_dt).total_seconds()
                            if 0 < overdue <= _DUE_WINDOW_SECONDS:
                                due_points.append(kp)
                        except (ValueError, TypeError):
                            pass

                if due_points:
                    new_pending[cid] = {
                        "course_name": course["name"],
                        "points": due_points,
                    }

                # 更新 review_schedule 用于前端日程表展示
                # 展示 mastery >= 40 的知识点（所有进入复习队列的）
                review_schedule = []
                for kp in kps:
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
                memory_service.update_review_schedule(cid, review_schedule)

                # 定期知识点快照归档（每课程每天最多拍一次快照）
                if kps:
                    today = datetime.now().date().isoformat()
                    if _last_kp_snapshot_date.get(cid) != today:
                        await db_service.archive_kp_snapshot(cid, kps)
                        _last_kp_snapshot_date[cid] = today

            # 原子替换 pending，确保顺延后的知识点不会残留
            self._pending_reviews = new_pending

        except Exception as e:
            logger.error(f"Review scan error: {e}")

    def get_pending_reviews(self) -> dict:
        return self._pending_reviews

    def get_course_review_status(self, course_id: str) -> list:
        memory = memory_service.load_memory(course_id)
        return memory.get("review_schedule", [])


    def complete_review(self, course_id: str, point_name: str, quality: int) -> dict:
        """完成一次复习，更新 SM-2 参数、重算 mastery，写入 review_history"""
        memory = memory_service.load_memory(course_id)
        kps = memory.get("knowledge_points", [])
        now = datetime.now()

        for kp in kps:
            if kp["name"] == point_name:
                _ensure_kp_fields(kp)

                # 保存本轮复习的原始预定日期（完成记录需要）
                scheduled_date = kp.get("next_review")

                # 追加 quality 到 review_quality_history
                rqh = kp["review_quality_history"]
                rqh.append(quality)
                if len(rqh) > 10:
                    # 归档被截断的 quality 记录
                    evicted_q = rqh[:-10]
                    _safe_archive(db_service.archive_review_qualities(course_id, point_name, evicted_q))
                    kp["review_quality_history"] = rqh[-10:]

                # 重算 mastery
                kp["mastery"] = calculate_mastery(kp)

                # 分层复习判定 → 计算下一次复习时间
                tier, fixed_interval = determine_review_tier(kp["mastery"])
                kp["review_tier"] = tier

                if tier is None:
                    kp["next_review"] = None
                elif tier == "consolidation":
                    kp["review_count"] = kp.get("review_count", 0) + 1
                    kp["next_review"] = (now + timedelta(days=fixed_interval)).isoformat()
                elif tier == "sm2":
                    sm2_update(kp, quality)

                kp["last_reviewed_at"] = now.isoformat()
                kp["updated_at"] = now.isoformat()

                # 直接在当前 memory 对象上追加 review_history
                history = memory.setdefault("review_history", [])
                history.append({
                    "knowledge_point": point_name,
                    "scheduled_date": scheduled_date,
                    "completed_at": now.isoformat(),
                    "quality": quality,
                    "mastery_after": kp["mastery"],
                })
                if len(history) > 200:
                    # 归档被截断的复习记录
                    evicted_h = history[:-200]
                    _safe_archive(db_service.archive_reviews(course_id, evicted_h))
                    memory["review_history"] = history[-200:]

                break

        # 同步更新 review_schedule（只包含未来待复习事件）
        review_schedule = []
        for kp in kps:
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

        memory["knowledge_points"] = kps
        memory_service.save_memory(course_id, memory)
        return {"success": True, "points": kps}


review_service = ReviewService()
