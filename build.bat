@echo off
chcp 65001 >nul
echo ========================================
echo   EduChat 打包工具 (Python 3.12 venv)
echo ========================================
echo.

REM 激活虚拟环境
if exist ".venv312\Scripts\activate.bat" (
    call .venv312\Scripts\activate.bat
    echo [INFO] 已激活 .venv312 虚拟环境
) else (
    echo [ERROR] 找不到 .venv312 虚拟环境！
    echo         请先运行: C:\Python312\python.exe -m venv .venv312
    pause
    exit /b 1
)

echo [INFO] Python 版本:
python --version
echo.

REM 检查 PyInstaller
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [INFO] 正在安装 PyInstaller...
    pip install pyinstaller
    echo.
)

echo [INFO] 开始打包 EduChat...
echo.
pyinstaller --clean --noconfirm EduChat.spec

if errorlevel 1 (
    echo.
    echo [ERROR] 打包失败！请检查上方错误信息。
    pause
    exit /b 1
)

echo.
echo ========================================
echo   打包完成！
echo ========================================
echo.
echo 输出目录: dist\EduChat\
echo 运行方式: 双击 dist\EduChat\EduChat.exe
echo.
echo 分发时请将整个 dist\EduChat\ 文件夹复制给对方。
echo 首次运行会自动在 EduChat.exe 旁创建 data\ 目录。
echo.
pause
