# -*- mode: python ; coding: utf-8 -*-
"""EduChat PyInstaller 打包配置"""

import os
from PyInstaller.utils.hooks import collect_data_files, collect_all

block_cipher = None

# 收集第三方包的数据文件和二进制
winotify_datas = collect_data_files('winotify')
fitz_datas, fitz_binaries, fitz_hiddenimports = collect_all('fitz')
pymupdf_datas, pymupdf_binaries, pymupdf_hiddenimports = collect_all('pymupdf')
webview_datas, webview_binaries, webview_hiddenimports = collect_all('webview')
clr_datas, clr_binaries, clr_hiddenimports = collect_all('clr_loader')
pythonnet_datas, pythonnet_binaries, pythonnet_hiddenimports = collect_all('pythonnet')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=fitz_binaries + pymupdf_binaries + webview_binaries + clr_binaries + pythonnet_binaries,
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
    ] + winotify_datas + fitz_datas + pymupdf_datas + webview_datas + clr_datas + pythonnet_datas,
    hiddenimports=[
        # GUI 桌面窗口
        'webview',
        'webview.platforms',
        'webview.platforms.winforms',
        'clr_loader',
        'pythonnet',
        'clr',
        'System',
        'System.Windows.Forms',
        'System.Drawing',
        'bottle',
        'proxy_tools',
        # FastAPI / Uvicorn 完整链
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'fastapi',
        'starlette',
        'starlette.responses',
        'starlette.routing',
        'starlette.middleware',
        'starlette.staticfiles',
        'starlette.templating',
        'anyio',
        'anyio._backends',
        'anyio._backends._asyncio',
        # Jinja2
        'jinja2',
        'markupsafe',
        # AI SDK
        'google.genai',
        'google.genai.types',
        'openai',
        # 数据库
        'aiosqlite',
        'sqlite3',
        # 邮件
        'aiosmtplib',
        # Windows 通知
        'winotify',
        # PDF
        'fitz',
        'pymupdf',
        # 文件上传
        'multipart',
        'python_multipart',
        # 其他
        'email.mime.text',
        'email.mime.multipart',
    ] + fitz_hiddenimports + pymupdf_hiddenimports + webview_hiddenimports + clr_hiddenimports + pythonnet_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy',
        'PIL', 'cv2', 'torch', 'tensorflow',
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EduChat',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI 模式，隐藏控制台窗口
    icon=None,      # 如需图标，改为 icon='path/to/icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EduChat',
)
