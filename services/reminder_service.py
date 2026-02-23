"""提醒调度服务 - 三路通知（持久化去重 + 过期日程处理 + 邮件节流）"""
import asyncio
import json
import logging
import os
from datetime import datetime, date, timedelta
from config import REMINDER_CHECK_INTERVAL, EMAIL_DIGEST_INTERVAL, EMAIL_DAILY_LIMIT, DATA_DIR
from .memory_service import memory_service
from .course_service import course_service
from .settings_service import settings_service
from .review_service import review_service
from .imessage_service import imessage_service

logger = logging.getLogger(__name__)

_NOTIFIED_KEYS_PATH = os.path.join(DATA_DIR, ".notified_keys.json")


class ReminderService:
    def __init__(self):
        self._task = None
        self._running = False
        self._sse_queues: list[asyncio.Queue] = []
        self._pending_notifications = []

        # --- 去重（持久化到文件，重启不丢失） ---
        self._notified_keys: set[str] = set()
        self._notified_date: str = ""
        self._load_notified_keys()

        # --- 邮件节流 ---
        self._last_email_time: float = 0
        self._email_count_today: int = 0
        self._email_count_date: str = ""
        self._email_buffer: list[dict] = []

    def _load_notified_keys(self):
        """从文件恢复已通知记录，避免重启后重复通知"""
        try:
            if os.path.exists(_NOTIFIED_KEYS_PATH):
                with open(_NOTIFIED_KEYS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                saved_date = data.get("date", "")
                if saved_date == date.today().isoformat():
                    self._notified_keys = set(data.get("keys", []))
                    self._notified_date = saved_date
                    self._last_email_time = data.get("last_email_time", 0)
                    self._email_count_today = data.get("email_count_today", 0)
                    self._email_count_date = saved_date
                    logger.info(f"Restored {len(self._notified_keys)} notified keys from disk")
                else:
                    logger.info("Notified keys file is from a different day, starting fresh")
        except Exception as e:
            logger.warning(f"Failed to load notified keys: {e}")

    def _save_notified_keys(self):
        """持久化已通知记录到文件"""
        try:
            data = {
                "date": self._notified_date or date.today().isoformat(),
                "keys": list(self._notified_keys),
                "last_email_time": self._last_email_time,
                "email_count_today": self._email_count_today,
            }
            with open(_NOTIFIED_KEYS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to save notified keys: {e}")

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("ReminderService started")

    async def stop(self):
        self._running = False
        if self._email_buffer:
            await self._flush_email_buffer()
        self._save_notified_keys()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ReminderService stopped")

    def subscribe_sse(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self._sse_queues.append(q)
        return q

    def unsubscribe_sse(self, q: asyncio.Queue):
        if q in self._sse_queues:
            self._sse_queues.remove(q)

    async def _broadcast_sse(self, data: dict):
        msg = json.dumps(data, ensure_ascii=False)
        dead = []
        for q in self._sse_queues:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._sse_queues.remove(q)

    async def _check_loop(self):
        try:
            while self._running:
                await self._check_all()
                await asyncio.sleep(REMINDER_CHECK_INTERVAL)
        except asyncio.CancelledError:
            pass

    def _make_key(self, notification: dict) -> str:
        """为每条通知生成唯一 key，同一 key 当天只通知一次"""
        today = date.today().isoformat()
        if notification["type"] == "schedule":
            event = notification["event"]
            eid = event.get("id") or event.get("title", "unknown")
            return f"schedule:{notification['course_id']}:{eid}:{today}"
        else:
            # review 类型：按课程+知识点数量+日期去重
            # 这样即使 pending 被保留，同样的 review 提醒不会重复
            return f"review:{notification['course_id']}:{notification.get('count', 0)}:{today}"

    # ---- 过期日程处理 ----
    def _handle_expired_schedule(self, course_id: str, memory: dict, now: datetime) -> bool:
        schedule = memory.get("schedule", [])
        dirty = False

        for event in schedule:
            event_time_str = event.get("datetime") or event.get("date")
            if not event_time_str:
                continue
            try:
                event_time = datetime.fromisoformat(event_time_str)
            except (ValueError, TypeError):
                continue

            if event_time < now and event.get("status") != "expired":
                event["status"] = "expired"
                event["expired_at"] = now.isoformat()
                dirty = True

                repeat = event.get("repeat")
                if repeat:
                    new_event = self._create_next_occurrence(event, event_time, now)
                    if new_event:
                        schedule.append(new_event)
                        logger.info(f"Auto-created next occurrence for '{event.get('title')}' "
                                    f"-> {new_event.get('datetime') or new_event.get('date')}")

        if dirty:
            memory["schedule"] = schedule
        return dirty

    def _create_next_occurrence(self, event: dict, old_time: datetime, now: datetime) -> dict | None:
        repeat = event.get("repeat", "")
        delta_map = {
            "daily": timedelta(days=1),
            "weekdays": timedelta(days=1),
            "weekly": timedelta(weeks=1),
            "biweekly": timedelta(weeks=2),
            "monthly": None,
        }

        if repeat not in delta_map:
            return None

        # Check repeat_count limit (repeat_count = total occurrences including the original)
        repeat_count = event.get("repeat_count")
        occurrence_num = event.get("_occurrence_num", 0) + 1
        if repeat_count and occurrence_num >= repeat_count:
            return None

        new_event = {
            k: v for k, v in event.items()
            if k not in ("id", "status", "expired_at", "created_at", "rescheduled_at")
        }
        new_event["id"] = now.strftime("%Y%m%d%H%M%S%f")
        new_event["created_at"] = now.isoformat()
        new_event["auto_generated"] = True
        new_event["_occurrence_num"] = occurrence_num

        if repeat == "monthly":
            year = old_time.year + (old_time.month // 12)
            month = (old_time.month % 12) + 1
            day = min(old_time.day, 28)
            new_time = old_time.replace(year=year, month=month, day=day)
        elif repeat == "weekdays":
            new_time = old_time + timedelta(days=1)
            while new_time.weekday() >= 5:  # 5=Sat, 6=Sun
                new_time += timedelta(days=1)
            while new_time < now:
                new_time += timedelta(days=1)
                while new_time.weekday() >= 5:
                    new_time += timedelta(days=1)
        else:
            delta = delta_map[repeat]
            new_time = old_time + delta
            while new_time < now:
                new_time += delta

        time_field = "datetime" if event.get("datetime") else "date"
        new_event[time_field] = new_time.isoformat()
        return new_event

    # ---- 邮件节流 ----
    def _can_send_email(self) -> bool:
        now = datetime.now()
        today_str = date.today().isoformat()

        if self._email_count_date != today_str:
            self._email_count_today = 0
            self._email_count_date = today_str

        if self._email_count_today >= EMAIL_DAILY_LIMIT:
            return False

        if (now.timestamp() - self._last_email_time) < EMAIL_DIGEST_INTERVAL:
            return False

        return True

    async def _flush_email_buffer(self):
        if not self._email_buffer:
            return

        imsg_config = settings_service.get_imessage_config()
        if not imsg_config.get("enabled"):
            self._email_buffer.clear()
            return

        body = self._format_email_body(self._email_buffer)
        count = len(self._email_buffer)
        self._email_buffer.clear()

        try:
            await imessage_service.send_reminder(
                imsg_config,
                f"EduChat 学习提醒（{count} 条）",
                body,
            )
            self._last_email_time = datetime.now().timestamp()
            self._email_count_today += 1
            self._save_notified_keys()
            logger.info(f"Sent digest email with {count} notifications "
                        f"(today: {self._email_count_today}/{EMAIL_DAILY_LIMIT})")
        except Exception as e:
            logger.error(f"Failed to send digest email: {e}")

    async def _check_all(self):
        try:
            now = datetime.now()
            today_str = date.today().isoformat()

            # 跨天清空已通知记录
            if self._notified_date != today_str:
                self._notified_keys.clear()
                self._notified_date = today_str

            courses = course_service.get_courses()
            notifications = []

            for course in courses:
                cid = course["id"]
                memory = memory_service.load_memory(cid)

                if self._handle_expired_schedule(cid, memory, now):
                    memory_service.save_memory(cid, memory)

                for event in memory.get("schedule", []):
                    if event.get("status") == "expired":
                        continue
                    event_time_str = event.get("datetime") or event.get("date")
                    if not event_time_str:
                        continue
                    try:
                        event_time = datetime.fromisoformat(event_time_str)
                    except (ValueError, TypeError):
                        continue

                    diff = (event_time - now).total_seconds()
                    if 0 < diff <= 900:
                        notifications.append({
                            "type": "schedule",
                            "course_id": cid,
                            "course_name": course["name"],
                            "event": event,
                            "minutes_until": round(diff / 60),
                        })

            # 从 review_service 获取待复习知识点（携带详细信息用于邮件）
            pending = review_service.get_pending_reviews()
            for cid, info in pending.items():
                if info["points"]:
                    point_details = []
                    for p in info["points"][:5]:
                        point_details.append({
                            "name": p["name"],
                            "mastery": p.get("mastery", 0),
                            "next_review": p.get("next_review", ""),
                        })
                    notifications.append({
                        "type": "review",
                        "course_id": cid,
                        "course_name": info["course_name"],
                        "points": [p["name"] for p in info["points"][:5]],
                        "point_details": point_details,
                        "count": len(info["points"]),
                    })

            # 过滤掉已通知过的
            new_notifications = []
            for n in notifications:
                key = self._make_key(n)
                if key not in self._notified_keys:
                    new_notifications.append(n)
                    self._notified_keys.add(key)

            # SSE + Toast：立即发送
            for n in new_notifications:
                await self._broadcast_sse(n)
                await self._send_win_toast(n)

            # 邮件：累积到缓冲区，达到间隔才汇总发送
            if new_notifications:
                self._email_buffer.extend(new_notifications)
                self._save_notified_keys()

            if self._email_buffer and self._can_send_email():
                await self._flush_email_buffer()

            self._pending_notifications = notifications

        except Exception as e:
            logger.error(f"Reminder check error: {e}")

    async def _send_win_toast(self, notification: dict):
        try:
            from winotify import Notification
            if notification["type"] == "schedule":
                event = notification["event"]
                toast = Notification(
                    app_id="EduChat",
                    title=f"📅 {notification['course_name']} - 日程提醒",
                    msg=f"{event.get('title', '学习任务')} 将在 {notification['minutes_until']} 分钟后开始",
                )
            else:
                toast = Notification(
                    app_id="EduChat",
                    title=f"📚 {notification['course_name']} - 复习提醒",
                    msg=f"有 {notification['count']} 个知识点需要复习",
                )
            toast.show()
        except Exception as e:
            logger.debug(f"Win toast error: {e}")

    def _format_email_body(self, notifications: list) -> str:
        now = datetime.now()
        time_str = now.strftime("%Y年%m月%d日 %H:%M")
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday = weekdays[now.weekday()]

        parts = []

        # 问候语
        hour = now.hour
        if hour < 12:
            greeting = "早上好，冒险者！新的一天充满可能"
        elif hour < 18:
            greeting = "下午好，冒险者！冒险正当时"
        else:
            greeting = "晚上好，冒险者！夜晚也能积累经验值"

        parts.append(f"""
        <p style="font-size:15px;color:#3C3224;font-weight:600;margin:0 0 4px;">🌟 {greeting}！</p>
        <p style="font-size:12px;color:#A69B88;margin:0 0 16px;">{time_str} {weekday}</p>
        """)

        # 日程提醒
        schedule_items = [n for n in notifications if n["type"] == "schedule"]
        if schedule_items:
            parts.append("""
            <div style="margin-bottom:16px;">
              <p style="font-size:13px;color:#9A7A2E;font-weight:600;margin:0 0 8px;letter-spacing:1px;">
                ◆ 冒险纪行 · 日程提醒
              </p>
            """)
            for n in schedule_items:
                event = n["event"]
                title = event.get("title", "学习任务")
                event_time_str = event.get("datetime") or event.get("date", "")
                try:
                    et = datetime.fromisoformat(event_time_str)
                    display_time = et.strftime("%m月%d日 %H:%M")
                except (ValueError, TypeError):
                    display_time = event_time_str

                minutes = n.get("minutes_until", 0)
                if minutes <= 5:
                    urgency = "⚡ 即将开始"
                    urgency_color = "#D45A4A"
                elif minutes <= 30:
                    urgency = f"⏰ {minutes} 分钟后"
                    urgency_color = "#C49934"
                else:
                    urgency = f"📅 {minutes} 分钟后"
                    urgency_color = "#3A9FD4"

                parts.append(f"""
                <div style="background:rgba(255,253,245,0.9);border:1px solid rgba(180,146,58,0.18);border-left:3px solid #D4A853;border-radius:8px;padding:12px 14px;margin-bottom:8px;">
                  <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:14px;color:#3C3224;font-weight:600;">{title}</span>
                    <span style="font-size:11px;color:{urgency_color};font-weight:600;">{urgency}</span>
                  </div>
                  <p style="margin:4px 0 0;font-size:12px;color:#7A6E5D;">
                    📚 {n['course_name']}　·　🕐 {display_time}
                  </p>
                </div>
                """)
            parts.append("</div>")

        # 复习提醒
        review_items = [n for n in notifications if n["type"] == "review"]
        if review_items:
            parts.append("""
            <div style="margin-bottom:16px;">
              <p style="font-size:13px;color:#9A7A2E;font-weight:600;margin:0 0 8px;letter-spacing:1px;">
                ◆ 每日委托 · 知识点复习
              </p>
            """)
            for n in review_items:
                course = n["course_name"]
                count = n.get("count", 0)
                details = n.get("point_details", [])
                if not details:
                    details = [{"name": name, "mastery": 0, "next_review": ""} for name in n.get("points", [])]

                parts.append(f"""
                <div style="background:rgba(255,253,245,0.9);border:1px solid rgba(180,146,58,0.18);border-left:3px solid #9B5FD4;border-radius:8px;padding:12px 14px;margin-bottom:8px;">
                  <p style="margin:0 0 8px;font-size:14px;color:#3C3224;font-weight:600;">
                    📖 {course} <span style="font-size:12px;color:#7A6E5D;font-weight:normal;">· {count} 个知识点待复习</span>
                  </p>
                """)

                for d in details:
                    mastery = d.get("mastery", 0)
                    if mastery >= 80:
                        bar_color = "linear-gradient(90deg,#B8923A,#D4A853)"
                        level = "精通"
                        level_color = "#9A7A2E"
                    elif mastery >= 50:
                        bar_color = "linear-gradient(90deg,#3A9FD4,#52B5C4)"
                        level = "熟练"
                        level_color = "#3A9FD4"
                    elif mastery >= 30:
                        bar_color = "linear-gradient(90deg,#C49934,#D4A853)"
                        level = "一般"
                        level_color = "#C49934"
                    else:
                        bar_color = "linear-gradient(90deg,#D45A4A,#E2604A)"
                        level = "薄弱"
                        level_color = "#D45A4A"

                    nr = d.get("next_review", "")
                    try:
                        rt = datetime.fromisoformat(nr)
                        review_display = rt.strftime("%m月%d日 %H:%M")
                    except (ValueError, TypeError):
                        review_display = "待定"

                    parts.append(f"""
                    <div style="margin-bottom:6px;">
                      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;">
                        <span style="font-size:12px;color:#3C3224;">{d['name']}</span>
                        <span style="font-size:10px;color:{level_color};font-weight:600;">{level} {mastery}%</span>
                      </div>
                      <div style="height:4px;background:#EDE3CC;border-radius:2px;overflow:hidden;">
                        <div style="width:{mastery}%;height:100%;background:{bar_color};border-radius:2px;"></div>
                      </div>
                      <p style="margin:2px 0 0;font-size:10px;color:#A69B88;">复习时间：{review_display}</p>
                    </div>
                    """)

                parts.append("</div>")
            parts.append("</div>")

        return "\n".join(parts)

    async def send_test_email(self) -> dict:
        """发送一封测试样例邮件，用当前课程数据模拟通知内容"""
        imsg_config = settings_service.get_imessage_config()
        if not imsg_config.get("enabled"):
            return {"success": False, "message": "邮件通知未启用，请先在设置中开启"}

        now = datetime.now()
        test_notifications = []

        # 收集所有课程的知识点作为模拟复习通知
        courses = course_service.get_courses()
        for course in courses:
            cid = course["id"]
            memory = memory_service.load_memory(cid)
            kps = memory.get("knowledge_points", [])
            if kps:
                point_details = []
                for kp in kps[:5]:
                    point_details.append({
                        "name": kp["name"],
                        "mastery": kp.get("mastery", 0),
                        "next_review": kp.get("next_review", ""),
                    })
                test_notifications.append({
                    "type": "review",
                    "course_id": cid,
                    "course_name": course["name"],
                    "points": [kp["name"] for kp in kps[:5]],
                    "point_details": point_details,
                    "count": len(kps),
                })

            # 模拟一个日程事件
            schedule = memory.get("schedule", [])
            upcoming = [e for e in schedule if e.get("status") != "expired"]
            if upcoming:
                event = upcoming[0]
                test_notifications.append({
                    "type": "schedule",
                    "course_id": cid,
                    "course_name": course["name"],
                    "event": event,
                    "minutes_until": 15,
                })

        if not test_notifications:
            # 没有真实数据，创建样例
            test_notifications = [{
                "type": "review",
                "course_id": "test",
                "course_name": "样例课程",
                "points": ["知识点A", "知识点B", "知识点C"],
                "point_details": [
                    {"name": "知识点A", "mastery": 85, "next_review": now.isoformat()},
                    {"name": "知识点B", "mastery": 45, "next_review": now.isoformat()},
                    {"name": "知识点C", "mastery": 15, "next_review": now.isoformat()},
                ],
                "count": 3,
            }]

        body = self._format_email_body(test_notifications)
        count = len(test_notifications)

        try:
            await imessage_service.send_reminder(
                imsg_config,
                f"EduChat 学习提醒（{count} 条）",
                body,
            )
            return {"success": True, "message": f"测试邮件已发送至 {imsg_config['to_email']}"}
        except Exception as e:
            return {"success": False, "message": f"发送失败: {str(e)}"}

    def get_pending(self) -> list:
        return self._pending_notifications


reminder_service = ReminderService()
