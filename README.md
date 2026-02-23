# EduChat — AI 智能教学助手

基于 AI 的智能教学辅助聊天应用，采用原神（Genshin Impact）浅色羊皮纸视觉风格。将教学场景游戏化——冒险手册代替学习档案、命之座代替知识点掌握度、派遣探索代替作业批改、深境螺旋代替考试分析。

## 核心功能

- **多课程 AI 教学对话** — 3 种对话模式（普通教学/作业批改/考试分析），SSE 流式输出
- **智能记忆系统（冒险手册）** — AI 自动提取知识点、学习进度、教学计划，每课程独立档案
- **四维度知识点掌握度** — 理解度 15% + 练习正确率 40% + 考核表现 30% + 复习表现 15% 加权计算
- **分层遗忘曲线复习** — SM-2 间隔递增防遗忘 + 低频巩固 + 自动过期衰减
- **题库系统** — 自动从对话提取练习题，按知识点分组，溢出归档
- **三路通知** — 浏览器 SSE + Windows 桌面 Toast + SMTP 邮件（原神风格 HTML 模板）
- **日程管理（冒险纪行）** — 周/月视图日历，支持重复事件
- **参考资料管理（圣遗物）** — PDF/图片/音频内容提取 + AI 结构化摘要
- **作业批改（派遣探索）** — 逐题批改 + 按知识点拆分得分率
- **考试分析（深境螺旋）** — 强弱项识别 + 自动生成练习题
- **学习档案归档** — 双层存储（JSON 热层 + SQLite 冷层），支持导出/导入
- **教学计划自动推进** — 双条件推进（AI 标记 + mastery 达标）

## 技术栈

| 层级 | 选型 |
|------|------|
| 后端 | Python + FastAPI + Uvicorn |
| AI 引擎 | Google Gemini / OpenAI 兼容接口 |
| 数据库 | SQLite (aiosqlite) + JSON |
| 前端 | 原生 HTML/CSS/JS（Markdown + KaTeX + 代码高亮） |
| 内容提取 | PyMuPDF + Gemini 多模态 |
| 桌面通知 | winotify (Windows) |
| 邮件 | aiosmtplib |
| UI 主题 | 原神浅色羊皮纸 · 金色暖色调 · 7 元素色课程体系 |

## 安装与运行

### 环境要求

- Python 3.12（推荐）
- Git

### 安装步骤

```bash
# 克隆仓库
git clone https://github.com/bubuqian/edu-chatbox.git
cd edu-chatbox

# 创建虚拟环境
python -m venv .venv312
# Windows
.venv312\Scripts\activate
# macOS/Linux
source .venv312/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 启动

```bash
python main.py
```

启动后访问 `http://localhost:9090`，首次使用需在设置中配置 API Key。

## 项目结构

```
edu-chatbox/
├── main.py                 # 应用入口
├── config.py               # 集中配置
├── requirements.txt        # Python 依赖
├── api/
│   └── routes.py           # 56 个 API 端点
├── services/
│   ├── chat_service.py     # AI 对话引擎
│   ├── memory_service.py   # 记忆档案管理
│   ├── review_service.py   # 遗忘曲线复习
│   ├── reminder_service.py # 三路提醒调度
│   ├── course_service.py   # 课程 CRUD
│   ├── db_service.py       # SQLite 操作
│   ├── reference_service.py    # 参考资料管理
│   ├── content_extractor.py    # 内容提取与摘要
│   ├── imessage_service.py     # SMTP 邮件
│   └── settings_service.py     # 设置管理
├── static/
│   ├── css/style.css       # 原神羊皮纸主题样式
│   └── js/
│       ├── app.js          # 主页交互逻辑
│       └── schedule.js     # 日程页逻辑
├── templates/
│   ├── index.html          # 主聊天页
│   └── schedule.html       # 日程页
└── data/                   # 运行时数据（不纳入版本控制）
    ├── settings.json       # 配置（含 API Key）
    ├── edu_chatbox.db      # SQLite 数据库
    └── courses/            # 课程数据
```

## 游戏化概念映射

| 原神概念 | 教学功能 |
|---------|---------|
| 冒险手册 | 学习记忆面板 |
| 冒险等阶 | 学习进度 |
| 命之座 | 知识点掌握度 |
| 冒险之证 | 教学计划 |
| 深境螺旋 | 考试/测验 |
| 每日委托 | 复习日程 |
| 派遣探索 | 作业批改 |
| 圣遗物 | 参考资料 |
| 元素属性 | 课程分类（火水雷草冰风岩） |
| 冒险纪行 | 日程表 |
