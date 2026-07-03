@echo off
chcp 65001 >nul
echo ========================================
echo    关闭 Edge 并以调试模式启动
echo ========================================
echo.

REM 查找并关闭所有 Edge 进程
echo [1/2] 关闭现有 Edge...
tasklist /fi "imagename eq msedge.exe" 2>nul | find /i "msedge.exe" >nul
if %errorlevel%==0 (
    taskkill /f /im msedge.exe >nul 2>&1
    echo       已关闭 Edge
    timeout /t 2 /nobreak >nul
) else (
    echo       未检测到运行中的 Edge
)

REM 以调试模式启动 Edge
echo [2/2] 以 --remote-debugging-port=9222 启动 Edge...
start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --user-data-dir="C:\Users\Ark\AppData\Local\Microsoft\Edge\User Data"

echo.
echo Edge 调试模式已启动，端口：9222
echo 可以用 playwright / CDP 工具连接
pause
