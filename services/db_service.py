"""数据库服务 - SQLite 对话历史持久化 + 学习档案归档"""
import aiosqlite
import json
import uuid
from datetime import datetime
from config import DB_PATH


class DatabaseService:
    def __init__(self):
        self._db = None

    async def init_db(self):
        self._db = await aiosqlite.connect(DB_PATH)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '新对话',
                mode TEXT NOT NULL DEFAULT 'normal',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_course ON sessions(course_id);

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                attachments TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

            /* ===== 学习档案归档表 ===== */

            /* 考试/作业得分归档：test_score_history 截断时写入 */
            CREATE TABLE IF NOT EXISTS archive_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id TEXT NOT NULL,
                knowledge_point TEXT NOT NULL,
                score_rate REAL NOT NULL,
                source TEXT DEFAULT 'test',
                archived_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_archive_scores_course ON archive_scores(course_id);
            CREATE INDEX IF NOT EXISTS idx_archive_scores_kp ON archive_scores(course_id, knowledge_point);

            /* 复习记录归档：review_history / review_quality_history 截断时写入 */
            CREATE TABLE IF NOT EXISTS archive_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id TEXT NOT NULL,
                knowledge_point TEXT NOT NULL,
                quality INTEGER,
                mastery_after INTEGER,
                scheduled_date TEXT,
                completed_at TEXT,
                source TEXT DEFAULT 'review',
                archived_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_archive_reviews_course ON archive_reviews(course_id);
            CREATE INDEX IF NOT EXISTS idx_archive_reviews_kp ON archive_reviews(course_id, knowledge_point);

            /* 被淘汰题目归档：question_bank 容量淘汰时写入 */
            CREATE TABLE IF NOT EXISTS archive_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id TEXT NOT NULL,
                question_id TEXT,
                knowledge_point TEXT NOT NULL,
                question TEXT NOT NULL,
                student_answer TEXT,
                correct_answer TEXT,
                is_correct INTEGER DEFAULT 1,
                difficulty TEXT DEFAULT 'medium',
                error_analysis TEXT,
                source TEXT,
                review_count INTEGER DEFAULT 0,
                mastered INTEGER DEFAULT 0,
                original_created_at TEXT,
                archived_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_archive_questions_course ON archive_questions(course_id);
            CREATE INDEX IF NOT EXISTS idx_archive_questions_kp ON archive_questions(course_id, knowledge_point);

            /* 知识点快照归档：定期或截断时对知识点状态拍快照 */
            CREATE TABLE IF NOT EXISTS archive_kp_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id TEXT NOT NULL,
                knowledge_point TEXT NOT NULL,
                mastery INTEGER DEFAULT 0,
                comprehension INTEGER DEFAULT 0,
                practice_total INTEGER DEFAULT 0,
                practice_correct INTEGER DEFAULT 0,
                review_count INTEGER DEFAULT 0,
                easiness_factor REAL DEFAULT 2.5,
                interval_days INTEGER DEFAULT 1,
                interaction_depth INTEGER DEFAULT 0,
                snapshot_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_archive_kp_snap_course ON archive_kp_snapshots(course_id);
            CREATE INDEX IF NOT EXISTS idx_archive_kp_snap_kp ON archive_kp_snapshots(course_id, knowledge_point);

            /* memory.json 完整快照归档 */
            CREATE TABLE IF NOT EXISTS archive_memory_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id TEXT NOT NULL,
                memory_json TEXT NOT NULL,
                reason TEXT DEFAULT 'periodic',
                snapshot_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_archive_mem_snap_course ON archive_memory_snapshots(course_id);
        """)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    # --- Sessions ---
    async def create_session(self, session_id: str, course_id: str, title: str = "新对话", mode: str = "normal"):
        now = datetime.now().isoformat()
        await self._db.execute(
            "INSERT INTO sessions (id, course_id, title, mode, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, course_id, title, mode, now, now)
        )
        await self._db.commit()
        return {"id": session_id, "course_id": course_id, "title": title, "mode": mode, "created_at": now, "updated_at": now}

    async def get_sessions(self, course_id: str):
        cursor = await self._db.execute(
            "SELECT * FROM sessions WHERE course_id = ? ORDER BY updated_at DESC", (course_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_session(self, session_id: str, title: str = None):
        if title:
            await self._db.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title, datetime.now().isoformat(), session_id)
            )
            await self._db.commit()

    async def delete_session(self, session_id: str):
        await self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await self._db.commit()

    async def get_session(self, session_id: str):
        cursor = await self._db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    # --- Messages ---
    async def add_message(self, session_id: str, role: str, content: str, attachments: list = None):
        now = datetime.now().isoformat()
        await self._db.execute(
            "INSERT INTO messages (session_id, role, content, attachments, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, json.dumps(attachments or []), now)
        )
        await self._db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id)
        )
        await self._db.commit()

    async def get_messages(self, session_id: str, limit: int = 100):
        cursor = await self._db.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
            (session_id, limit)
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["attachments"] = json.loads(d["attachments"]) if d["attachments"] else []
            result.append(d)
        return result

    async def get_recent_messages(self, session_id: str, limit: int = 20):
        cursor = await self._db.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit)
        )
        rows = await cursor.fetchall()
        result = []
        for r in reversed(list(rows)):
            d = dict(r)
            d["attachments"] = json.loads(d["attachments"]) if d["attachments"] else []
            result.append(d)
        return result

    async def delete_messages_by_session(self, session_id: str):
        await self._db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await self._db.commit()

    # ===== Archive: 写入方法 =====

    async def archive_scores(self, course_id: str, kp_name: str, scores: list, source: str = "test"):
        """归档被截断的 test_score_history 条目"""
        if not scores:
            return
        now = datetime.now().isoformat()
        await self._db.executemany(
            "INSERT INTO archive_scores (course_id, knowledge_point, score_rate, source, archived_at) VALUES (?, ?, ?, ?, ?)",
            [(course_id, kp_name, s, source, now) for s in scores]
        )
        await self._db.commit()

    async def archive_reviews(self, course_id: str, records: list):
        """归档被截断的 review_history 条目"""
        if not records:
            return
        now = datetime.now().isoformat()
        rows = []
        for r in records:
            rows.append((
                course_id,
                r.get("knowledge_point", ""),
                r.get("quality"),
                r.get("mastery_after"),
                r.get("scheduled_date"),
                r.get("completed_at"),
                "review",
                now,
            ))
        await self._db.executemany(
            "INSERT INTO archive_reviews (course_id, knowledge_point, quality, mastery_after, scheduled_date, completed_at, source, archived_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows
        )
        await self._db.commit()

    async def archive_review_qualities(self, course_id: str, kp_name: str, qualities: list):
        """归档被截断的 review_quality_history 条目（存为简化 review 记录）"""
        if not qualities:
            return
        now = datetime.now().isoformat()
        rows = [(course_id, kp_name, q, None, None, None, "quality_history", now) for q in qualities]
        await self._db.executemany(
            "INSERT INTO archive_reviews (course_id, knowledge_point, quality, mastery_after, scheduled_date, completed_at, source, archived_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows
        )
        await self._db.commit()

    async def archive_questions(self, course_id: str, questions: list):
        """归档被淘汰的题目"""
        if not questions:
            return
        now = datetime.now().isoformat()
        rows = []
        for q in questions:
            rows.append((
                course_id,
                q.get("id", ""),
                q.get("knowledge_point", ""),
                q.get("question", ""),
                q.get("student_answer", ""),
                q.get("correct_answer", ""),
                1 if q.get("is_correct", True) else 0,
                q.get("difficulty", "medium"),
                q.get("error_analysis", ""),
                q.get("source", ""),
                q.get("review_count", 0),
                1 if q.get("mastered", False) else 0,
                q.get("created_at", ""),
                now,
            ))
        await self._db.executemany(
            """INSERT INTO archive_questions
               (course_id, question_id, knowledge_point, question, student_answer, correct_answer,
                is_correct, difficulty, error_analysis, source, review_count, mastered,
                original_created_at, archived_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows
        )
        await self._db.commit()

    async def archive_kp_snapshot(self, course_id: str, kps: list):
        """对当前所有知识点拍快照"""
        if not kps:
            return
        now = datetime.now().isoformat()
        rows = []
        for kp in kps:
            rows.append((
                course_id,
                kp.get("name", ""),
                kp.get("mastery", 0),
                kp.get("comprehension", 0),
                kp.get("practice_total", 0),
                kp.get("practice_correct", 0),
                kp.get("review_count", 0),
                kp.get("easiness_factor", 2.5),
                kp.get("interval_days", 1),
                kp.get("interaction_depth", 0),
                now,
            ))
        await self._db.executemany(
            """INSERT INTO archive_kp_snapshots
               (course_id, knowledge_point, mastery, comprehension, practice_total, practice_correct,
                review_count, easiness_factor, interval_days, interaction_depth, snapshot_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows
        )
        await self._db.commit()

    async def archive_memory_snapshot(self, course_id: str, memory: dict, reason: str = "periodic"):
        """归档 memory.json 完整快照"""
        now = datetime.now().isoformat()
        await self._db.execute(
            "INSERT INTO archive_memory_snapshots (course_id, memory_json, reason, snapshot_at) VALUES (?, ?, ?, ?)",
            (course_id, json.dumps(memory, ensure_ascii=False), reason, now)
        )
        await self._db.commit()

    # ===== Archive: 查询方法 =====

    async def get_archive_scores(self, course_id: str, kp_name: str = None, limit: int = 500):
        """查询归档的成绩记录"""
        base = "SELECT id, course_id, knowledge_point AS kp_name, score_rate AS score, source, archived_at FROM archive_scores"
        if kp_name:
            cursor = await self._db.execute(
                f"{base} WHERE course_id = ? AND knowledge_point = ? ORDER BY archived_at DESC LIMIT ?",
                (course_id, kp_name, limit)
            )
        else:
            cursor = await self._db.execute(
                f"{base} WHERE course_id = ? ORDER BY archived_at DESC LIMIT ?",
                (course_id, limit)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_archive_reviews(self, course_id: str, kp_name: str = None, limit: int = 500):
        """查询归档的复习记录"""
        base = ("SELECT id, course_id, knowledge_point AS kp_name, quality, mastery_after AS mastery, "
                "scheduled_date AS next_review, completed_at, source, archived_at FROM archive_reviews")
        if kp_name:
            cursor = await self._db.execute(
                f"{base} WHERE course_id = ? AND knowledge_point = ? ORDER BY archived_at DESC LIMIT ?",
                (course_id, kp_name, limit)
            )
        else:
            cursor = await self._db.execute(
                f"{base} WHERE course_id = ? ORDER BY archived_at DESC LIMIT ?",
                (course_id, limit)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_archive_questions(self, course_id: str, kp_name: str = None, limit: int = 500):
        """查询归档的题目"""
        base = ("SELECT id, course_id, question_id, knowledge_point AS kp_name, question, student_answer, "
                "correct_answer, is_correct, difficulty, error_analysis, source, review_count, mastered, "
                "original_created_at, archived_at FROM archive_questions")
        if kp_name:
            cursor = await self._db.execute(
                f"{base} WHERE course_id = ? AND knowledge_point = ? ORDER BY archived_at DESC LIMIT ?",
                (course_id, kp_name, limit)
            )
        else:
            cursor = await self._db.execute(
                f"{base} WHERE course_id = ? ORDER BY archived_at DESC LIMIT ?",
                (course_id, limit)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_archive_kp_snapshots(self, course_id: str, kp_name: str = None, limit: int = 200):
        """查询知识点快照"""
        base = ("SELECT id, course_id, knowledge_point AS kp_name, mastery, comprehension, "
                "practice_total, practice_correct, review_count, easiness_factor, interval_days, "
                "interaction_depth, snapshot_at FROM archive_kp_snapshots")
        if kp_name:
            cursor = await self._db.execute(
                f"{base} WHERE course_id = ? AND knowledge_point = ? ORDER BY snapshot_at DESC LIMIT ?",
                (course_id, kp_name, limit)
            )
        else:
            cursor = await self._db.execute(
                f"{base} WHERE course_id = ? ORDER BY snapshot_at DESC LIMIT ?",
                (course_id, limit)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_archive_memory_snapshots(self, course_id: str, limit: int = 50):
        """查询 memory 快照列表（不含完整 JSON，减少传输量）"""
        cursor = await self._db.execute(
            "SELECT id, course_id, reason, snapshot_at AS created_at FROM archive_memory_snapshots WHERE course_id = ? ORDER BY snapshot_at DESC LIMIT ?",
            (course_id, limit)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_archive_memory_snapshot_detail(self, snapshot_id: int):
        """获取某个 memory 快照的完整 JSON"""
        cursor = await self._db.execute(
            "SELECT id, course_id, memory_json, reason, snapshot_at AS created_at FROM archive_memory_snapshots WHERE id = ?",
            (snapshot_id,)
        )
        row = await cursor.fetchone()
        if row:
            d = dict(row)
            d["snapshot_data"] = json.loads(d["memory_json"]) if d["memory_json"] else {}
            del d["memory_json"]
            return d
        return None

    async def get_archive_stats(self, course_id: str):
        """获取归档数据统计概览"""
        key_map = {
            "archive_scores": "scores_count",
            "archive_reviews": "reviews_count",
            "archive_questions": "questions_count",
            "archive_kp_snapshots": "kp_snapshots_count",
            "archive_memory_snapshots": "memory_snapshots_count",
        }
        stats = {}
        for table, key in key_map.items():
            cursor = await self._db.execute(
                f"SELECT COUNT(*) as cnt FROM {table} WHERE course_id = ?", (course_id,)
            )
            row = await cursor.fetchone()
            stats[key] = row["cnt"] if row else 0

        # earliest / latest date
        for col, alias in [("MIN", "earliest_date"), ("MAX", "latest_date")]:
            dates = []
            for tbl, date_col in [("archive_scores", "archived_at"), ("archive_reviews", "archived_at"),
                                   ("archive_questions", "archived_at"), ("archive_kp_snapshots", "snapshot_at"),
                                   ("archive_memory_snapshots", "snapshot_at")]:
                cursor = await self._db.execute(
                    f"SELECT {col}({date_col}) as d FROM {tbl} WHERE course_id = ?", (course_id,)
                )
                row = await cursor.fetchone()
                if row and row["d"]:
                    dates.append(row["d"])
            if dates:
                stats[alias] = min(dates) if col == "MIN" else max(dates)
            else:
                stats[alias] = None
        return stats

    async def get_inherited_archive_data(self, course_id: str) -> dict:
        """提取用于继承到新课程的归档数据摘要

        返回:
        - kp_latest: 每个知识点最新快照状态
        - weak_kps: 薄弱知识点列表（mastery < 60）
        - strong_kps: 掌握良好的知识点列表（mastery >= 60）
        - error_patterns: 高频错误模式（从归档错题中提取）
        - score_summary: 按知识点的平均得分
        - total_reviews: 总复习记录数
        - total_scores: 总成绩记录数
        - total_questions: 总题目记录数
        """
        # 1. 每个知识点的最新快照
        cursor = await self._db.execute(
            """SELECT knowledge_point, mastery, comprehension, practice_total, practice_correct,
                      review_count, easiness_factor, interval_days, interaction_depth, snapshot_at
               FROM archive_kp_snapshots
               WHERE course_id = ?
               ORDER BY snapshot_at DESC""",
            (course_id,)
        )
        rows = await cursor.fetchall()
        kp_latest = {}
        for r in rows:
            kp_name = r["knowledge_point"]
            if kp_name not in kp_latest:
                kp_latest[kp_name] = dict(r)

        # 2. 按知识点的平均得分
        cursor = await self._db.execute(
            """SELECT knowledge_point, AVG(score_rate) as avg_score, COUNT(*) as count
               FROM archive_scores WHERE course_id = ?
               GROUP BY knowledge_point""",
            (course_id,)
        )
        rows = await cursor.fetchall()
        score_summary = {r["knowledge_point"]: {"avg_score": round(r["avg_score"], 1), "count": r["count"]} for r in rows}

        # 3. 高频错题的错误模式（只取错题，按知识点分组）
        cursor = await self._db.execute(
            """SELECT knowledge_point, question, error_analysis, difficulty
               FROM archive_questions
               WHERE course_id = ? AND is_correct = 0
               ORDER BY archived_at DESC LIMIT 50""",
            (course_id,)
        )
        rows = await cursor.fetchall()
        error_patterns = {}
        for r in rows:
            kp = r["knowledge_point"]
            error_patterns.setdefault(kp, []).append({
                "question": r["question"][:100] if r["question"] else "",
                "error_analysis": r["error_analysis"] or "",
                "difficulty": r["difficulty"],
            })

        # 4. 统计概要
        stats = await self.get_archive_stats(course_id)

        return {
            "kp_latest": kp_latest,
            "score_summary": score_summary,
            "error_patterns": error_patterns,
            "stats": stats,
        }

    async def import_all_archives(self, course_id: str, data: dict) -> dict:
        """导入完整归档数据到指定课程（追加模式，不删除已有数据）

        data 格式与 export_all_archives 输出一致。
        返回各类数据的导入计数。
        """
        counts = {"scores": 0, "reviews": 0, "questions": 0, "kp_snapshots": 0, "memory_snapshots": 0, "sessions": 0, "messages": 0}

        # 1. 导入成绩记录
        for s in data.get("scores", []):
            await self._db.execute(
                "INSERT INTO archive_scores (course_id, knowledge_point, score_rate, source, archived_at) VALUES (?, ?, ?, ?, ?)",
                (course_id, s.get("kp_name", ""), s.get("score", 0), s.get("source", "test"), s.get("archived_at", datetime.now().isoformat()))
            )
            counts["scores"] += 1

        # 2. 导入复习记录
        for r in data.get("reviews", []):
            await self._db.execute(
                "INSERT INTO archive_reviews (course_id, knowledge_point, quality, mastery_after, scheduled_date, completed_at, source, archived_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (course_id, r.get("kp_name", ""), r.get("quality"), r.get("mastery"), r.get("next_review"), r.get("completed_at"), r.get("source", "review"), r.get("archived_at", datetime.now().isoformat()))
            )
            counts["reviews"] += 1

        # 3. 导入错题归档
        for q in data.get("questions", []):
            await self._db.execute(
                """INSERT INTO archive_questions
                   (course_id, question_id, knowledge_point, question, student_answer, correct_answer,
                    is_correct, difficulty, error_analysis, source, review_count, mastered,
                    original_created_at, archived_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (course_id, q.get("question_id", ""), q.get("kp_name", ""), q.get("question", ""),
                 q.get("student_answer", ""), q.get("correct_answer", ""),
                 q.get("is_correct", 1), q.get("difficulty", "medium"),
                 q.get("error_analysis", ""), q.get("source", ""),
                 q.get("review_count", 0), q.get("mastered", 0),
                 q.get("original_created_at", ""), q.get("archived_at", datetime.now().isoformat()))
            )
            counts["questions"] += 1

        # 4. 导入知识点快照
        for kp in data.get("kp_snapshots", []):
            await self._db.execute(
                """INSERT INTO archive_kp_snapshots
                   (course_id, knowledge_point, mastery, comprehension, practice_total, practice_correct,
                    review_count, easiness_factor, interval_days, interaction_depth, snapshot_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (course_id, kp.get("kp_name", ""), kp.get("mastery", 0), kp.get("comprehension", 0),
                 kp.get("practice_total", 0), kp.get("practice_correct", 0),
                 kp.get("review_count", 0), kp.get("easiness_factor", 2.5),
                 kp.get("interval_days", 1), kp.get("interaction_depth", 0),
                 kp.get("snapshot_at", datetime.now().isoformat()))
            )
            counts["kp_snapshots"] += 1

        # 5. 导入 memory 快照
        for ms in data.get("memory_snapshots", []):
            mem_json = ms.get("memory_json", {})
            if isinstance(mem_json, dict):
                mem_json = json.dumps(mem_json, ensure_ascii=False)
            await self._db.execute(
                "INSERT INTO archive_memory_snapshots (course_id, memory_json, reason, snapshot_at) VALUES (?, ?, ?, ?)",
                (course_id, mem_json, ms.get("reason", "imported"), ms.get("snapshot_at", datetime.now().isoformat()))
            )
            counts["memory_snapshots"] += 1

        # 6. 导入会话和消息（可选）
        if data.get("messages"):
            # 按 session_id 分组
            sessions_map = {}
            for msg in data["messages"]:
                sid = msg.get("session_id", "")
                if sid not in sessions_map:
                    sessions_map[sid] = {
                        "title": msg.get("title", "导入的对话"),
                        "mode": msg.get("mode", "normal"),
                        "created_at": msg.get("session_created", datetime.now().isoformat()),
                        "messages": []
                    }
                sessions_map[sid]["messages"].append(msg)

            for old_sid, sdata in sessions_map.items():
                new_sid = f"imp_{uuid.uuid4().hex[:8]}"
                now = datetime.now().isoformat()
                await self._db.execute(
                    "INSERT INTO sessions (id, course_id, title, mode, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (new_sid, course_id, sdata["title"], sdata["mode"], sdata["created_at"], now)
                )
                counts["sessions"] += 1
                for msg in sdata["messages"]:
                    await self._db.execute(
                        "INSERT INTO messages (session_id, role, content, attachments, created_at) VALUES (?, ?, ?, ?, ?)",
                        (new_sid, msg.get("role", "user"), msg.get("content", ""), "[]", msg.get("msg_created", now))
                    )
                    counts["messages"] += 1

        await self._db.commit()
        return counts

    async def export_all_archives(self, course_id: str):
        """导出课程的全部归档数据（用于完整恢复）"""
        result = {
            "course_id": course_id,
            "exported_at": datetime.now().isoformat(),
            "scores": await self.get_archive_scores(course_id, limit=99999),
            "reviews": await self.get_archive_reviews(course_id, limit=99999),
            "questions": await self.get_archive_questions(course_id, limit=99999),
            "kp_snapshots": await self.get_archive_kp_snapshots(course_id, limit=99999),
        }
        # Memory snapshots: include full JSON
        cursor = await self._db.execute(
            "SELECT * FROM archive_memory_snapshots WHERE course_id = ? ORDER BY snapshot_at ASC",
            (course_id,)
        )
        rows = await cursor.fetchall()
        snapshots = []
        for r in rows:
            d = dict(r)
            d["memory_json"] = json.loads(d["memory_json"]) if d["memory_json"] else {}
            snapshots.append(d)
        result["memory_snapshots"] = snapshots

        # Also include current messages from all sessions
        cursor = await self._db.execute(
            "SELECT s.id as session_id, s.title, s.mode, s.created_at as session_created, m.role, m.content, m.created_at as msg_created "
            "FROM sessions s JOIN messages m ON s.id = m.session_id "
            "WHERE s.course_id = ? ORDER BY m.created_at ASC",
            (course_id,)
        )
        rows = await cursor.fetchall()
        result["messages"] = [dict(r) for r in rows]

        return result

    async def purge_course_data(self, course_id: str):
        """永久删除某课程在数据库中的所有数据"""
        # Delete messages for all sessions of this course
        await self._db.execute(
            "DELETE FROM messages WHERE session_id IN (SELECT id FROM sessions WHERE course_id = ?)",
            (course_id,)
        )
        await self._db.execute("DELETE FROM sessions WHERE course_id = ?", (course_id,))
        await self._db.execute("DELETE FROM archive_scores WHERE course_id = ?", (course_id,))
        await self._db.execute("DELETE FROM archive_reviews WHERE course_id = ?", (course_id,))
        await self._db.execute("DELETE FROM archive_questions WHERE course_id = ?", (course_id,))
        await self._db.execute("DELETE FROM archive_kp_snapshots WHERE course_id = ?", (course_id,))
        await self._db.execute("DELETE FROM archive_memory_snapshots WHERE course_id = ?", (course_id,))
        await self._db.commit()


db_service = DatabaseService()
