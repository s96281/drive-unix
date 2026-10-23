@echo off
chcp 65001 >nul
echo ========================================================
echo   啟動 drive-unix 前後端整合服務 (FastAPI + React SPA)
echo ========================================================
echo.
echo 前後端整合介面: http://127.0.0.1:8000
echo API 文件位址:   http://127.0.0.1:8000/docs
echo.
echo 正在開啟瀏覽器...
start http://127.0.0.1:8000
echo.
echo 正在啟動伺服器 (按 Ctrl+C 可停止)...
.\.venv\Scripts\python.exe -m web
pause
