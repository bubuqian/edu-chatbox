"""EduChat - 教学专用 ChatBox 应用入口"""
import os
import sys
import logging
import threading
import time
import socket
import traceback
from contextlib import asynccontextmanager

# Ensure working directory is app root (exe dir when frozen, source dir when dev)
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    # console=False 时 sys.stdout/stderr 为 None，需要修复以防第三方库崩溃
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from config import APP_NAME, HOST, PORT, STATIC_DIR, TEMPLATES_DIR
from api import router
from services.db_service import db_service
from services.review_service import review_service
from services.reminder_service import reminder_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {APP_NAME}...")
    await db_service.init_db()
    await review_service.start()
    await reminder_service.start()
    logger.info(f"{APP_NAME} is ready at http://{HOST}:{PORT}")
    yield
    logger.info(f"Shutting down {APP_NAME}...")
    await reminder_service.stop()
    await review_service.stop()
    await db_service.close()
    logger.info(f"{APP_NAME} stopped.")


app = FastAPI(title=APP_NAME, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.include_router(router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/schedule", response_class=HTMLResponse)
async def schedule_page(request: Request):
    return templates.TemplateResponse("schedule.html", {"request": request})


if __name__ == "__main__":
    if getattr(sys, 'frozen', False):
        # ── 打包环境：GUI 桌面窗口模式 ──
        # 错误日志写入文件（无控制台）
        err_log = os.path.join(BASE_DIR, "educhat_error.log")
        file_handler = logging.FileHandler(err_log, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.getLogger().addHandler(file_handler)

        def _run_server():
            try:
                uvicorn.run(app, host=HOST, port=PORT, log_level="info")
            except Exception:
                logger.error(f"Server crashed:\n{traceback.format_exc()}")

        def _wait_for_server(timeout=30.0):
            start = time.time()
            while time.time() - start < timeout:
                try:
                    with socket.create_connection((HOST, PORT), timeout=1):
                        return True
                except OSError:
                    time.sleep(0.3)
            return False

        try:
            # 后台线程启动服务
            server_thread = threading.Thread(target=_run_server, daemon=True)
            server_thread.start()
            logger.info("Server thread started...")

            if not _wait_for_server():
                logger.error("Server failed to start within 30s")
                sys.exit(1)
            logger.info(f"Server ready at http://{HOST}:{PORT}")

            # 创建 pywebview 原生窗口
            import webview
            window = webview.create_window(
                title=APP_NAME,
                url=f"http://{HOST}:{PORT}",
                width=1280,
                height=860,
                min_size=(900, 600),
                text_select=True,
                confirm_close=False,
            )
            webview.start(debug=False)
            logger.info("Window closed, exiting.")
        except Exception:
            logger.error(f"GUI launch failed:\n{traceback.format_exc()}")
        finally:
            os._exit(0)
    else:
        # ── 开发环境：传统浏览器模式 ──
        uvicorn.run(app, host=HOST, port=PORT)
