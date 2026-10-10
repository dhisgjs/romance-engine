@echo off
rem ============================================
rem  wx-chat-export 一键启动
rem  双击运行，浏览器会自动打开 http://127.0.0.1:8542
rem  所有缓存/临时文件均在项目目录内，不写系统盘
rem ============================================
setlocal
set "ROOT=%~dp0"
set "PIP_CACHE_DIR=%ROOT%.pipcache"
set "TMP=%ROOT%data\tmp"
set "TEMP=%ROOT%data\tmp"
if not exist "%TMP%" mkdir "%TMP%" >nul 2>&1
set "PY=%ROOT%.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [初始化] 首次运行：创建虚拟环境并安装依赖（需要已安装 Python 3.10+，仅写本项目目录）...
    where python >nul 2>nul || (echo [错误] 未找到 python，请先安装 Python 3.10+ 并加入 PATH & pause & exit /b 1)
    python -m venv "%ROOT%.venv"
    "%PY%" -m pip install -q -r "%ROOT%requirements.txt" || (echo [错误] 依赖安装失败，请检查网络 & pause & exit /b 1)
)

cd /d "%ROOT%"
echo [启动] wx-chat-export  http://127.0.0.1:8542/
"%PY%" backend\main.py %*
pause
