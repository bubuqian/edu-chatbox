"""API 路由"""
import os
import uuid
import json
import asyncio
import mimetypes
from fastapi import APIRouter, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from typing import Optional
from config import GEMINI_MODELS, GEMINI_TOOLS, COURSES_DIR
from services.settings_service import settings_service
from services.course_service import course_service
from services.memory_service import memory_service
from services.db_service import db_service
from services.chat_service import chat_service, _build_wrong_questions_context
from services.reference_service import reference_service
from services.review_service import review_service
from services.reminder_service import reminder_service
from services.imessage_service import imessage_service

import logging

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

# 互动深度降级阈值
_MIN_MSGS_FOR_ASSESSED = 2   # 至少 2 轮学生消息才算有互动确认
_MIN_MSGS_FOR_PRACTICED = 3  # 至少 3 轮学生消息才算做了练习


def _validate_interaction_types(knowledge_updates: list, user_msg_count: int) -> list:
    """根据会话中学生消息轮次校验 AI 标记的 interaction_type

    防止 AI 在互动不充分时过度标记。规则：
    - user_msg_count < 2 → 所有 assessed/practiced 降级为 taught
    - user_msg_count < 3 → practiced 降级为 assessed
    """
    validated = []
    for update in knowledge_updates:
        u = dict(update)
        itype = u.get("interaction_type", "taught")

        if itype in ("assessed", "practiced") and user_msg_count < _MIN_MSGS_FOR_ASSESSED:
            logger.info(f"Downgrade '{u.get('name')}' from '{itype}' to 'taught' "
                        f"(user_msg_count={user_msg_count} < {_MIN_MSGS_FOR_ASSESSED})")
            u["interaction_type"] = "taught"
        elif itype == "practiced" and user_msg_count < _MIN_MSGS_FOR_PRACTICED:
            logger.info(f"Downgrade '{u.get('name')}' from 'practiced' to 'assessed' "
                        f"(user_msg_count={user_msg_count} < {_MIN_MSGS_FOR_PRACTICED})")
            u["interaction_type"] = "assessed"

        validated.append(u)
    return validated


# ============ App State ============
@router.get("/state")
async def get_state():
    return {"success": True, "data": settings_service.get_app_state()}


@router.post("/state")
async def save_state(request: Request):
    data = await request.json()
    settings_service.save_app_state(data)
    return {"success": True}


# ============ Settings ============
@router.get("/models")
async def get_models():
    return {"success": True, "data": {"models": GEMINI_MODELS, "tools": GEMINI_TOOLS}}


@router.get("/settings")
async def get_settings():
    return {"success": True, "data": settings_service.get_all()}


@router.post("/settings/gemini")
async def save_gemini_config(request: Request):
    data = await request.json()
    settings_service.save_gemini_config(data)
    return {"success": True}


@router.post("/settings/imessage")
async def save_imessage_config(request: Request):
    data = await request.json()
    settings_service.save_imessage_config(data)
    return {"success": True}


@router.post("/settings/test-gemini")
async def test_gemini(request: Request):
    data = await request.json()
    result = await chat_service.test_connection(data)
    return result


@router.post("/settings/test-imessage")
async def test_imessage(request: Request):
    data = await request.json()
    result = await imessage_service.test_connection(data)
    return result


# ============ Courses ============
@router.get("/courses")
async def get_courses():
    return {"success": True, "data": course_service.get_courses()}


@router.get("/courses/all-history")
async def get_all_history_courses():
    """获取所有历史课程（含已从界面移除的），用于继承管理"""
    courses = course_service.get_all_course_dirs()
    for c in courses:
        stats = await db_service.get_archive_stats(c["id"])
        c["archive_stats"] = stats
    return {"success": True, "data": courses}


@router.post("/courses")
async def create_course(request: Request):
    data = await request.json()
    inherit_from = data.get("inherit_from", [])

    if inherit_from:
        # 从档案继承创建新课程（支持已从界面移除但目录仍存在的课程）
        source_memories = {}
        archive_data = {}
        for src_id in inherit_from:
            mem = memory_service.load_memory(src_id)
            if not mem or not mem.get("course_info", {}).get("name"):
                return JSONResponse(status_code=400, content={
                    "success": False, "error": f"来源课程 {src_id} 数据不存在"
                })
            source_memories[src_id] = mem
            archive_data[src_id] = await db_service.get_inherited_archive_data(src_id)

        course = course_service.create_course_from_archive(
            name=data["name"],
            element=data.get("element", "pyro"),
            description=data.get("description", ""),
            inherit_from=inherit_from,
            source_memories=source_memories,
            archive_data=archive_data,
        )
    else:
        course = course_service.create_course(
            name=data["name"],
            element=data.get("element", "pyro"),
            description=data.get("description", ""),
        )
    return {"success": True, "data": course}


@router.put("/courses/{course_id}")
async def update_course(course_id: str, request: Request):
    data = await request.json()
    result = course_service.update_course(course_id, data)
    if result:
        return {"success": True, "data": result}
    return JSONResponse(status_code=404, content={"success": False, "error": "课程不存在"})


@router.delete("/courses/{course_id}")
async def remove_course(course_id: str):
    """软删除：仅从界面移除，保留数据用于继承"""
    if course_service.remove_course(course_id):
        return {"success": True}
    return JSONResponse(status_code=404, content={"success": False, "error": "课程不存在"})


@router.delete("/courses/{course_id}/purge")
async def purge_course(course_id: str):
    """永久删除：清理文件目录 + 数据库所有归档数据"""
    try:
        await db_service.purge_course_data(course_id)
        course_service.delete_course(course_id)
        return {"success": True}
    except Exception as e:
        logger.error(f"Purge course {course_id} failed: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


# ============ Sessions ============
@router.get("/sessions/{course_id}")
async def get_sessions(course_id: str):
    sessions = await db_service.get_sessions(course_id)
    return {"success": True, "data": sessions}


@router.get("/sessions/{course_id}/current")
async def get_or_create_current_session(course_id: str):
    """获取课程的唯一会话，不存在则自动创建"""
    sessions = await db_service.get_sessions(course_id)
    if sessions:
        return {"success": True, "data": sessions[0]}
    # 自动创建
    session_id = str(uuid.uuid4())[:8]
    session = await db_service.create_session(
        session_id=session_id,
        course_id=course_id,
        title="对话",
        mode="normal",
    )
    return {"success": True, "data": session}


@router.post("/sessions")
async def create_session(request: Request):
    data = await request.json()
    session_id = str(uuid.uuid4())[:8]
    session = await db_service.create_session(
        session_id=session_id,
        course_id=data["course_id"],
        title=data.get("title", "新对话"),
        mode=data.get("mode", "normal"),
    )
    return {"success": True, "data": session}


@router.put("/sessions/{session_id}")
async def update_session(session_id: str, request: Request):
    data = await request.json()
    await db_service.update_session(session_id, title=data.get("title"))
    return {"success": True}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    await db_service.delete_session(session_id)
    return {"success": True}


# ============ Messages ============
@router.get("/messages/{session_id}")
async def get_messages(session_id: str):
    messages = await db_service.get_messages(session_id)
    return {"success": True, "data": messages}


# ============ Chat (SSE) ============
@router.post("/chat")
async def chat(
    course_id: str = Form(...),
    session_id: str = Form(...),
    message: str = Form(""),
    mode: str = Form("normal"),
    tools: str = Form(""),
    review_point: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    gemini_config = settings_service.get_gemini_config()
    # Override tools from the request if provided
    if tools:
        try:
            gemini_config["tools"] = json.loads(tools)
        except (json.JSONDecodeError, TypeError):
            gemini_config["tools"] = [t.strip() for t in tools.split(",") if t.strip()]
    memory = memory_service.load_memory(course_id)
    ref_context = reference_service.get_reference_context(course_id)

    # Save uploaded files & build Gemini file_parts
    attachment_names = []
    file_parts = []
    for f in files:
        if f.filename:
            content = await f.read()
            path = await reference_service.save_upload(course_id, f.filename, content)
            attachment_names.append(f.filename)
            # Build Gemini Part for multimodal input
            try:
                from google.genai import types as genai_types
                mime = f.content_type or mimetypes.guess_type(f.filename)[0] or "application/octet-stream"
                file_parts.append(genai_types.Part.from_bytes(data=content, mime_type=mime))
            except Exception as e:
                logger.warning(f"Failed to build Gemini file part for {f.filename}: {e}")

    # Save user message
    await db_service.add_message(session_id, "user", message, attachment_names)

    # Get conversation history
    history = await db_service.get_recent_messages(session_id, limit=20)
    chat_messages = [{"role": m["role"], "content": m["content"]} for m in history]

    # Build wrong questions context for review mode
    wrong_questions_ctx = ""
    if mode == "review" and review_point:
        wrong_qs = memory_service.get_questions_for_review(course_id, review_point)
        wrong_questions_ctx = _build_wrong_questions_context(wrong_qs)

    async def event_stream():
        full_response = ""
        stream_error = None
        try:
            async for chunk in chat_service.stream_chat(
                gemini_config=gemini_config,
                memory=memory,
                messages=chat_messages,
                mode=mode,
                reference_context=ref_context,
                file_parts=file_parts or None,
                review_point=review_point,
                wrong_questions_context=wrong_questions_ctx,
            ):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
        except Exception as e:
            stream_error = str(e)
            yield f"data: {json.dumps({'type': 'error', 'content': stream_error}, ensure_ascii=False)}\n\n"

        # If stream errored and no content was received, don't save or parse
        if stream_error and not full_response.strip():
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            return

        # If stream errored but partial content was received, save partial content
        # (don't include error text in saved message)

        # Parse and process AI response
        parsed = chat_service.parse_ai_response(full_response)

        # Save AI message (clean text only)
        await db_service.add_message(session_id, "assistant", parsed["clean_text"])

        # Process knowledge updates — with interaction depth validation
        if parsed["knowledge_updates"]:
            # 代码侧兜底：根据会话中学生消息轮次校验 interaction_type
            # 防止 AI 在互动不充分时过度标记
            user_msg_count = sum(1 for m in chat_messages if m.get("role") == "user")
            validated_updates = _validate_interaction_types(parsed["knowledge_updates"], user_msg_count)
            memory_service.update_knowledge_points(course_id, validated_updates)

        # Process memory updates
        for mu in parsed["memory_updates"]:
            memory_service.update_memory_field(course_id, mu["field_path"], mu["value"])

        # Process homework result
        if parsed["homework_result"]:
            memory_service.add_homework_record(course_id, parsed["homework_result"])
            yield f"data: {json.dumps({'type': 'homework_result', 'data': parsed['homework_result']}, ensure_ascii=False)}\n\n"

        # Process exam result
        if parsed["exam_result"]:
            memory_service.add_exam_record(course_id, parsed["exam_result"])
            yield f"data: {json.dumps({'type': 'exam_result', 'data': parsed['exam_result']}, ensure_ascii=False)}\n\n"

        # Process question records — save to question bank
        if parsed.get("question_records"):
            source = "homework" if mode == "homework_check" else "exam" if mode == "exam_analysis" else "review" if mode == "review" else "practice"
            memory_service.add_questions(course_id, parsed["question_records"], source=source)

        # Process review completion
        if parsed.get("review_complete") and review_point:
            quality = parsed["review_complete"].get("quality", 3)
            review_service.complete_review(course_id, review_point, quality)
            # Mark reviewed questions as reviewed
            memory_service.mark_questions_reviewed(course_id, review_point)
            # Notify frontend that review is completed
            yield f"data: {json.dumps({'type': 'review_completed', 'point_name': review_point, 'quality': quality}, ensure_ascii=False)}\n\n"

        # Process step completions (AI 标记教学步骤内容已完成)
        for sc in parsed.get("step_completes", []):
            step_title = sc.get("step_title", "")
            if step_title:
                memory_service.mark_step_completed(course_id, step_title)
                logger.info(f"Step teaching completed: '{step_title}'")
                yield f"data: {json.dumps({'type': 'step_complete', 'step_title': step_title}, ensure_ascii=False)}\n\n"

        # Update learning progress
        updated_memory = memory_service.load_memory(course_id)
        lp = updated_memory.get("learning_progress", {})
        lp["total_sessions"] = lp.get("total_sessions", 0) + 1
        memory_service.update_memory_field(course_id, "learning_progress.total_sessions", lp["total_sessions"])

        # Auto-title session if first message
        if len(history) <= 2 and message:
            title = message[:30] + ("..." if len(message) > 30 else "")
            await db_service.update_session(session_id, title=title)
            yield f"data: {json.dumps({'type': 'session_title', 'title': title}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ============ Memory ============
@router.get("/memory/{course_id}")
async def get_memory(course_id: str):
    memory = memory_service.load_memory(course_id)
    # 每次读取时同步教学计划状态（根据知识点 mastery 自动推进）
    memory_service._sync_teaching_plan(memory)
    return {"success": True, "data": memory}


@router.post("/memory/{course_id}")
async def save_memory(course_id: str, request: Request):
    data = await request.json()
    memory_service.save_memory(course_id, data)
    return {"success": True}


@router.put("/memory/{course_id}/field")
async def update_memory_field(course_id: str, request: Request):
    data = await request.json()
    result = memory_service.update_memory_field(course_id, data["field_path"], data["value"])
    return {"success": True, "data": result}


# ============ References ============
@router.get("/references/{course_id}")
async def get_references(course_id: str):
    refs = reference_service.list_references(course_id)
    return {"success": True, "data": refs}


@router.post("/references/{course_id}")
async def upload_reference(course_id: str, file: UploadFile = File(...)):
    try:
        content = await file.read()
        result = await reference_service.upload_reference(course_id, file.filename, content)
        # 上传后自动触发后台解析（不阻塞上传响应）
        gemini_config = settings_service.get_gemini_config()
        if gemini_config.get("api_key") or gemini_config.get("connection_mode") == "vertex_ai":
            asyncio.create_task(_process_reference_bg(course_id, result["name"], gemini_config))
        return {"success": True, "data": result}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})


async def _process_reference_bg(course_id: str, filename: str, gemini_config: dict):
    """后台任务：解析参考资料并生成摘要"""
    try:
        result = await reference_service.process_reference(course_id, filename, gemini_config)
        logger.info(f"参考资料解析完成: {filename} -> {result['status']} (原文{result.get('raw_length', 0)}字)")
    except Exception as e:
        logger.error(f"参考资料后台解析失败: {filename} -> {e}")


@router.post("/references/{course_id}/process/{filename}")
async def process_reference(course_id: str, filename: str):
    """手动触发单个参考资料的内容解析和摘要生成"""
    gemini_config = settings_service.get_gemini_config()
    if not (gemini_config.get("api_key") or gemini_config.get("connection_mode") == "vertex_ai"):
        return JSONResponse(status_code=400, content={
            "success": False, "error": "未配置 API Key，无法解析参考资料"
        })
    try:
        result = await reference_service.process_reference(course_id, filename, gemini_config)
        return {"success": True, "data": result}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/references/{course_id}/process-all")
async def process_all_references(course_id: str):
    """批量解析所有尚未解析的参考资料"""
    gemini_config = settings_service.get_gemini_config()
    if not (gemini_config.get("api_key") or gemini_config.get("connection_mode") == "vertex_ai"):
        return JSONResponse(status_code=400, content={
            "success": False, "error": "未配置 API Key，无法解析参考资料"
        })
    refs = reference_service.list_references(course_id)
    results = []
    for r in refs:
        if not r.get("has_summary"):
            try:
                result = await reference_service.process_reference(course_id, r["name"], gemini_config)
                result["filename"] = r["name"]
                results.append(result)
            except Exception as e:
                results.append({"filename": r["name"], "status": "error", "error": str(e)})
    return {"success": True, "data": {"processed": len(results), "results": results}}


@router.get("/references/{course_id}/summary-status")
async def get_summary_status(course_id: str):
    """获取所有参考资料的摘要状态"""
    statuses = reference_service.get_summary_status(course_id)
    return {"success": True, "data": statuses}


@router.get("/references/{course_id}/summary/{filename}")
async def get_file_summary(course_id: str, filename: str):
    """获取单个参考资料的摘要内容"""
    result = reference_service.get_file_summary(course_id, filename)
    if result:
        return {"success": True, "data": result}
    return JSONResponse(status_code=404, content={
        "success": False, "error": "该文件尚未解析，请先点击解析按钮"
    })


@router.delete("/references/{course_id}/{filename}")
async def delete_reference(course_id: str, filename: str):
    if reference_service.delete_reference(course_id, filename):
        return {"success": True}
    return JSONResponse(status_code=404, content={"success": False, "error": "文件不存在"})


@router.get("/references/{course_id}/file/{filename}")
async def get_reference_file(course_id: str, filename: str):
    """预览/下载参考资料文件"""
    fpath = os.path.join(COURSES_DIR, course_id, "references", filename)
    if not os.path.isfile(fpath):
        return JSONResponse(status_code=404, content={"success": False, "error": "文件不存在"})

    ext = os.path.splitext(filename)[1].lower()
    media_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".txt": "text/plain; charset=utf-8",
        ".md": "text/plain; charset=utf-8",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
    }
    media_type = media_map.get(ext, "application/octet-stream")
    # 可在浏览器内预览的类型使用 inline，其余走下载
    inline_types = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt", ".md", ".mp3", ".wav", ".ogg"}
    if ext in inline_types:
        from urllib.parse import quote
        encoded_name = quote(filename)
        def file_iterator():
            with open(fpath, "rb") as f:
                while chunk := f.read(1024 * 256):
                    yield chunk
        return StreamingResponse(
            file_iterator(),
            media_type=media_type,
            headers={
                "Content-Disposition": f"inline; filename*=UTF-8''{encoded_name}",
            },
        )
    return FileResponse(fpath, media_type=media_type, filename=filename)


# ============ Schedule (aggregated) ============
@router.get("/schedule")
async def get_all_schedules(start: str = "", end: str = ""):
    courses = course_service.get_courses()
    all_events = []
    for course in courses:
        cid = course["id"]
        memory = memory_service.load_memory(cid)

        dirty = False
        for idx, event in enumerate(memory.get("schedule", [])):
            if not event.get("id"):
                event["id"] = f"sched_{uuid.uuid4().hex[:12]}"
                dirty = True
            event["course_id"] = cid
            event["course_name"] = course["name"]
            event["course_element"] = course.get("element", "pyro")
            all_events.append(event)
        if dirty:
            memory_service.save_memory(cid, memory)

        for review in memory.get("review_schedule", []):
            # review_schedule 只包含未来待复习事件
            next_review_dt = review.get("next_review", "")
            all_events.append({
                "id": f"review_{cid}_{review['knowledge_point']}",
                "title": f"复习: {review['knowledge_point']}",
                "type": "review",
                "date": next_review_dt[:10],
                "datetime": next_review_dt,
                "course_id": cid,
                "course_name": course["name"],
                "course_element": course.get("element", "pyro"),
                "mastery": review.get("mastery", 0),
                "review_tier": review.get("review_tier"),
                "completed": False,
            })

        # review_history：已完成的复习记录（独立事件）
        for idx, record in enumerate(memory.get("review_history", [])):
            scheduled_dt = record.get("scheduled_date", "")
            completed_at = record.get("completed_at", "")
            # 使用原始预定日期作为日程日期
            event_dt = scheduled_dt or completed_at
            if not event_dt:
                continue
            all_events.append({
                "id": f"review_done_{cid}_{record['knowledge_point']}_{idx}",
                "title": f"复习: {record['knowledge_point']}",
                "type": "review",
                "date": event_dt[:10],
                "datetime": event_dt,
                "course_id": cid,
                "course_name": course["name"],
                "course_element": course.get("element", "pyro"),
                "mastery": record.get("mastery_after", 0),
                "completed": True,
                "completed_at": completed_at,
                "quality": record.get("quality", 0),
            })

    return {"success": True, "data": all_events}


@router.post("/schedule/{course_id}")
async def add_schedule_event(course_id: str, request: Request):
    data = await request.json()
    event = memory_service.add_schedule_event(course_id, data)
    return {"success": True, "data": event}


@router.put("/schedule/{course_id}/{event_id}")
async def update_schedule_event(course_id: str, event_id: str, request: Request):
    data = await request.json()
    memory_service.update_schedule_event(course_id, event_id, data)
    return {"success": True}


@router.delete("/schedule/{course_id}/{event_id}")
async def delete_schedule_event(course_id: str, event_id: str):
    # 复习事件不可真正删除，走顺延逻辑
    if event_id.startswith("review_"):
        prefix = f"review_{course_id}_"
        if event_id.startswith(prefix):
            kp_name = event_id[len(prefix):]
            result = memory_service.postpone_review_event(course_id, kp_name)
            return {"success": True, "postponed": True, "data": result}
        else:
            memory_service.delete_schedule_event(course_id, event_id)
    else:
        memory_service.delete_schedule_event(course_id, event_id)
    return {"success": True}


# ============ Review ============
@router.get("/review/pending")
async def get_pending_reviews():
    return {"success": True, "data": review_service.get_pending_reviews()}


@router.get("/review/{course_id}")
async def get_review_status(course_id: str):
    status = review_service.get_course_review_status(course_id)
    return {"success": True, "data": status}


@router.post("/review/{course_id}/complete")
async def complete_review(course_id: str, request: Request):
    data = await request.json()
    result = review_service.complete_review(course_id, data["point_name"], data.get("quality", 3))
    return result


# ============ Reminders (SSE) ============
@router.get("/reminders/stream")
async def reminder_stream():
    queue = reminder_service.subscribe_sse()

    async def event_gen():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            reminder_service.unsubscribe_sse(queue)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/reminders/pending")
async def get_pending_reminders():
    return {"success": True, "data": reminder_service.get_pending()}


@router.post("/reminders/check")
async def trigger_reminder_check():
    """手动触发一次提醒检查（测试用）"""
    await reminder_service._check_all()
    return {"success": True, "data": reminder_service.get_pending()}


@router.post("/reminders/test-email")
async def send_test_email():
    """发送一封测试样例邮件"""
    result = await reminder_service.send_test_email()
    return result


# ============ Knowledge Points ============
@router.get("/knowledge/{course_id}")
async def get_knowledge_points(course_id: str):
    points = memory_service.get_knowledge_points(course_id)
    return {"success": True, "data": points}


# ============ Question Bank ============
@router.get("/question-bank/{course_id}")
async def get_question_bank_stats(course_id: str):
    stats = memory_service.get_question_bank_stats(course_id)
    return {"success": True, "data": stats}


@router.get("/archive/{course_id}/inherit-preview")
async def get_inherit_preview(course_id: str):
    """获取课程的可继承数据预览（用于继承创建时的信息展示）"""
    memory = memory_service.load_memory(course_id)
    if not memory or not memory.get("course_info", {}).get("name"):
        # Fallback: try get_course for active courses
        course = course_service.get_course(course_id)
        if not course:
            return JSONResponse(status_code=404, content={"success": False, "error": "课程不存在"})
        memory = memory_service.load_memory(course_id)

    course_name = memory.get("course_info", {}).get("name", "未命名")
    course_element = memory.get("course_info", {}).get("element", "geo")
    kps = memory.get("knowledge_points", [])

    # 统计知识点掌握情况
    kp_summary = []
    for kp in kps:
        kp_summary.append({
            "name": kp.get("name", ""),
            "mastery": kp.get("mastery", 0),
            "interaction_depth": kp.get("interaction_depth", 0),
        })
    kp_summary.sort(key=lambda x: x["mastery"], reverse=True)

    # 统计题库错题数
    qbank_stats = memory_service.get_question_bank_stats(course_id)
    wrong_active = qbank_stats.get("wrong", 0) - qbank_stats.get("mastered", 0)

    # 归档统计
    archive_stats = await db_service.get_archive_stats(course_id)

    avg_mastery = round(sum(kp.get("mastery", 0) for kp in kps) / len(kps)) if kps else 0

    return {"success": True, "data": {
        "course_id": course_id,
        "course_name": course_name,
        "element": course_element,
        "kp_count": len(kps),
        "avg_mastery": avg_mastery,
        "kp_summary": kp_summary[:15],
        "wrong_questions_active": wrong_active,
        "student_profile": memory.get("student_profile", {}),
        "archive_stats": archive_stats,
    }}


# ============ Archive (学习档案) ============
@router.get("/archive/{course_id}/stats")
async def get_archive_stats(course_id: str):
    """获取归档数据统计概览"""
    stats = await db_service.get_archive_stats(course_id)
    return {"success": True, "data": stats}


@router.get("/archive/{course_id}/scores")
async def get_archive_scores(course_id: str, kp: str = "", limit: int = 500):
    data = await db_service.get_archive_scores(course_id, kp_name=kp or None, limit=limit)
    return {"success": True, "data": data}


@router.get("/archive/{course_id}/reviews")
async def get_archive_reviews(course_id: str, kp: str = "", limit: int = 500):
    data = await db_service.get_archive_reviews(course_id, kp_name=kp or None, limit=limit)
    return {"success": True, "data": data}


@router.get("/archive/{course_id}/questions")
async def get_archive_questions(course_id: str, kp: str = "", limit: int = 500):
    data = await db_service.get_archive_questions(course_id, kp_name=kp or None, limit=limit)
    return {"success": True, "data": data}


@router.get("/archive/{course_id}/kp-snapshots")
async def get_archive_kp_snapshots(course_id: str, kp: str = "", limit: int = 200):
    data = await db_service.get_archive_kp_snapshots(course_id, kp_name=kp or None, limit=limit)
    return {"success": True, "data": data}


@router.get("/archive/{course_id}/memory-snapshots")
async def get_archive_memory_snapshots(course_id: str, limit: int = 50):
    data = await db_service.get_archive_memory_snapshots(course_id, limit=limit)
    return {"success": True, "data": data}


@router.get("/archive/memory-snapshot/{snapshot_id}")
async def get_archive_memory_snapshot_detail(snapshot_id: int):
    data = await db_service.get_archive_memory_snapshot_detail(snapshot_id)
    if data:
        return {"success": True, "data": data}
    return JSONResponse(status_code=404, content={"success": False, "error": "快照不存在"})


@router.get("/archive/{course_id}/export")
async def export_archives(course_id: str):
    """导出课程完整学习档案（JSON）"""
    data = await db_service.export_all_archives(course_id)
    # 附带当前 memory.json（不只依赖归档快照）
    current_memory = memory_service.load_memory(course_id)
    data["current_memory"] = current_memory
    # 附带课程元信息
    courses = course_service.get_courses()
    course_meta = next((c for c in courses if c["id"] == course_id), None)
    if course_meta:
        data["course_meta"] = course_meta
    return JSONResponse(content={"success": True, "data": data})


@router.post("/archive/import")
async def import_archives(request: Request):
    """导入完整学习档案 JSON

    body: {
        "data": {...导出的JSON对象},
        "target_course_id": "可选，指定导入到哪个课程",
        "create_new": true/false,
        "course_name": "可选，创建新课程时的自定义名称",
        "course_element": "可选，创建新课程时的元素色"
    }
    """
    body = await request.json()
    archive_data = body.get("data")
    if not archive_data or not isinstance(archive_data, dict):
        return JSONResponse(status_code=400, content={"success": False, "error": "无效的档案数据"})

    create_new = body.get("create_new", False)
    target_course_id = body.get("target_course_id")

    if create_new:
        # 提取课程信息的优先级: 前端传入 > course_meta > current_memory > memory_snapshots > 默认值
        course_name = body.get("course_name", "").strip()
        course_element = body.get("course_element", "").strip()
        course_desc = ""

        # 从 course_meta 提取（导出时附带的课程元信息）
        meta = archive_data.get("course_meta", {})
        if not course_name and meta.get("name"):
            course_name = meta["name"] + " (导入)"
        if not course_element and meta.get("element"):
            course_element = meta["element"]
        if meta.get("description"):
            course_desc = meta["description"]

        # 从 current_memory 提取（导出时附带的当前 memory）
        cur_mem = archive_data.get("current_memory", {})
        ci = cur_mem.get("course_info", {})
        if not course_name and ci.get("name"):
            course_name = ci["name"] + " (导入)"
        if not course_element and ci.get("element"):
            course_element = ci["element"]
        if not course_desc and ci.get("description"):
            course_desc = ci["description"]

        # 从 memory_snapshots 提取（兜底）
        snapshots = archive_data.get("memory_snapshots", [])
        if snapshots and (not course_name or not course_element):
            latest_mem = snapshots[-1].get("memory_json", {})
            if isinstance(latest_mem, str):
                try:
                    latest_mem = json.loads(latest_mem)
                except Exception:
                    latest_mem = {}
            sci = latest_mem.get("course_info", {})
            if not course_name and sci.get("name"):
                course_name = sci["name"] + " (导入)"
            if not course_element and sci.get("element"):
                course_element = sci["element"]

        # 最终默认值
        if not course_name:
            course_name = "导入的课程"
        if not course_element:
            course_element = "geo"

        new_course = course_service.create_course(course_name, course_element, course_desc)
        target_course_id = new_course["id"]

        # 用 current_memory 恢复 memory.json（优先），否则用最新 memory_snapshot
        restore_mem = None
        if cur_mem and cur_mem.get("course_info"):
            restore_mem = cur_mem
        elif snapshots:
            restore_mem = snapshots[-1].get("memory_json", {})
            if isinstance(restore_mem, str):
                try:
                    restore_mem = json.loads(restore_mem)
                except Exception:
                    restore_mem = None

        if restore_mem and isinstance(restore_mem, dict):
            restore_mem.setdefault("course_info", {})["name"] = course_name
            restore_mem["course_info"]["element"] = course_element
            memory_service.save_memory(target_course_id, restore_mem)
    else:
        if not target_course_id:
            return JSONResponse(status_code=400, content={"success": False, "error": "未指定目标课程"})
        courses = course_service.get_courses()
        if not any(c["id"] == target_course_id for c in courses):
            return JSONResponse(status_code=404, content={"success": False, "error": "目标课程不存在"})

    # 执行导入
    counts = await db_service.import_all_archives(target_course_id, archive_data)

    return {
        "success": True,
        "course_id": target_course_id,
        "create_new": create_new,
        "counts": counts,
        "message": f"导入完成: {counts['scores']}条成绩, {counts['reviews']}条复习, {counts['questions']}条错题, {counts['kp_snapshots']}条快照, {counts['sessions']}个会话"
    }


@router.post("/archive/{course_id}/snapshot")
async def create_manual_snapshot(course_id: str):
    """手动触发一次完整 memory 快照"""
    # 校验课程存在
    courses = course_service.get_courses()
    if not any(c["id"] == course_id for c in courses):
        return JSONResponse(status_code=404, content={"success": False, "error": "课程不存在"})
    memory = memory_service.load_memory(course_id)
    await db_service.archive_memory_snapshot(course_id, memory, reason="manual")
    kps = memory.get("knowledge_points", [])
    if kps:
        await db_service.archive_kp_snapshot(course_id, kps)
    return {"success": True, "message": "快照已创建"}
