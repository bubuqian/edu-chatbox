"""EduChat 集中配置"""
import os
import sys

# 应用信息
APP_NAME = "EduChat"
APP_VERSION = "1.0.0"
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "9090"))

# 目录 — 区分 PyInstaller 打包环境和开发环境
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后：exe 所在目录存放可写数据，_MEIPASS 存放只读资源
    APP_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = sys._MEIPASS
else:
    # 开发环境：源码目录
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR

BASE_DIR = APP_DIR
TEMPLATES_DIR = os.path.join(BUNDLE_DIR, "templates")
STATIC_DIR = os.path.join(BUNDLE_DIR, "static")
DATA_DIR = os.path.join(APP_DIR, "data")
COURSES_DIR = os.path.join(DATA_DIR, "courses")
DB_PATH = os.path.join(DATA_DIR, "edu_chatbox.db")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

# Gemini 默认设置
DEFAULT_MODEL = "gemini-2.5-flash"  # 默认使用稳定版；可在前端切换到 3.1
DEFAULT_CONNECTION_MODE = "ai_studio"

# 可选模型列表（AI Studio / Vertex AI 通用）
GEMINI_MODELS = [
    {
        "group": "Gemini 3.1",
        "models": [
            {"id": "gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro", "desc": "最新旗舰，高级推理与代理编码", "tags": ["thinking", "code", "agent", "preview"]},
        ],
    },
    {
        "group": "Gemini 3.0",
        "models": [
            {"id": "gemini-3-pro-preview",   "name": "Gemini 3 Pro",   "desc": "先进推理模型，多模态理解",   "tags": ["thinking", "code", "multimodal", "preview"]},
            {"id": "gemini-3-flash-preview",  "name": "Gemini 3 Flash", "desc": "低成本 Frontier 级性能",     "tags": ["fast", "multimodal", "preview"]},
        ],
    },
    {
        "group": "Gemini 2.5",
        "models": [
            {"id": "gemini-2.5-pro",          "name": "Gemini 2.5 Pro",        "desc": "深度推理与编码，复杂任务",    "tags": ["thinking", "code", "multimodal"]},
            {"id": "gemini-2.5-flash",         "name": "Gemini 2.5 Flash",      "desc": "平衡速度与质量，支持思考",    "tags": ["thinking", "fast", "multimodal"]},
            {"id": "gemini-2.5-flash-lite",    "name": "Gemini 2.5 Flash Lite", "desc": "最快速度，低延迟轻量任务",    "tags": ["fast", "lite"]},
        ],
    },
    {
        "group": "Gemini 2.0 (旧版)",
        "models": [
            {"id": "gemini-2.0-flash",        "name": "Gemini 2.0 Flash",      "desc": "上代旗舰 Flash，已弃用",     "tags": ["fast", "deprecated"]},
            {"id": "gemini-2.0-flash-lite",    "name": "Gemini 2.0 Flash Lite", "desc": "上代轻量版，已弃用",          "tags": ["fast", "lite", "deprecated"]},
        ],
    },
    {
        "group": "Gemini 1.5 (旧版)",
        "models": [
            {"id": "gemini-1.5-pro",   "name": "Gemini 1.5 Pro",   "desc": "超长上下文 200万 tokens", "tags": ["long-context", "multimodal"]},
            {"id": "gemini-1.5-flash",  "name": "Gemini 1.5 Flash", "desc": "经典 Flash，兼容性好",    "tags": ["fast", "multimodal"]},
        ],
    },
]

# 可用工具列表
GEMINI_TOOLS = [
    {"id": "google_search",    "name": "Google 搜索",  "desc": "联网搜索实时信息",   "icon": "search"},
    {"id": "code_execution",   "name": "代码执行",      "desc": "在沙盒中运行代码",   "icon": "code"},
    {"id": "url_context",      "name": "URL 上下文",    "desc": "读取和引用网页内容", "icon": "link"},
]

# 定时任务
REMINDER_CHECK_INTERVAL = int(os.getenv("REMINDER_CHECK_INTERVAL", "60"))
REVIEW_SCAN_INTERVAL = int(os.getenv("REVIEW_SCAN_INTERVAL", "3600"))

# 邮件提醒节流
EMAIL_DIGEST_INTERVAL = int(os.getenv("EMAIL_DIGEST_INTERVAL", "3600"))  # 汇总邮件最小间隔（秒）
EMAIL_DAILY_LIMIT = int(os.getenv("EMAIL_DAILY_LIMIT", "5"))  # 每日邮件上限

# 文件上传
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
MAX_FILES = 5
MAX_REFERENCES = 20
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp3", ".wav", ".ogg", ".txt", ".md"}

# 元素色系
ELEMENT_COLORS = {
    "pyro": "#EF7A5A",
    "hydro": "#4FC1E9",
    "electro": "#B47AEC",
    "dendro": "#7BC862",
    "cryo": "#72D6E3",
    "anemo": "#74D4B0",
    "geo": "#D4A853",
}

# 默认 app_state
DEFAULT_APP_STATE = {
    "current_course_id": None,
    "current_session_id": None,
    "sidebar_collapsed": False,
    "sidebar_active_panel": "sessions",
    "chat_mode": "normal",
    "schedule_view": "week",
    "schedule_date": None,
}

# 默认 gemini_config
DEFAULT_GEMINI_CONFIG = {
    "connection_mode": DEFAULT_CONNECTION_MODE,
    "model": DEFAULT_MODEL,
    "tools": ["google_search", "code_execution", "url_context"],
    "api_key": "",
    "vertex_project": "",
    "vertex_location": "us-central1",
    "openai_api_key": "",
    "openai_base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "custom_api_key": "",
    "custom_base_url": "",
    "custom_backend": "openai",
}

# 默认邮件提醒配置
DEFAULT_IMESSAGE_CONFIG = {
    "enabled": False,
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_pass": "",
    "to_email": "",
}

# 确保数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(COURSES_DIR, exist_ok=True)
