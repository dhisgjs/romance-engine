@echo off
rem ============================================
rem  romance-engine 一键推送脚本
rem  用法：双击运行或 push.bat
rem  网络恢复后执行：git 代理会自动绕开（直连）
rem ============================================
setlocal
cd /d "%~dp0"

echo [1/3] 检查网络...
git -c http.proxy= -c https.proxy= ls-remote https://github.com/dhisgjs/romance-engine.git >nul 2>&1
if errorlevel 1 (
    echo [失败] GitHub 仍然不可达，请开启代理(127.0.0.1:7897)或稍后重试
    pause
    exit /b 1
)

echo [2/3] 关联远端...
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    git remote add origin https://github.com/dhisgjs/romance-engine.git
) else (
    git remote set-url origin https://github.com/dhisgjs/romance-engine.git
)

echo [3/3] 推送（先 rebase 远端 main，再推）...
git -c http.proxy= -c https.proxy= fetch origin main
if errorlevel 1 (
    echo [失败] fetch 失败，请稍后重试
    pause
    exit /b 1
)
git rebase origin/main
if errorlevel 1 (
    echo [注意] rebase 有冲突，请手动解决后再 git push
    pause
    exit /b 1
)
git -c http.proxy= -c https.proxy= push -u origin main
if errorlevel 1 (
    echo [失败] push 失败，可能需要先在浏览器登录一次 GitHub
    echo 备选：git push 时按提示输入用户名 dhisgjs 和密码
    pause
    exit /b 1
)
echo [完成] 已推送到 https://github.com/dhisgjs/romance-engine
pause