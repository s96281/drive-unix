@echo off
chcp 65001 >nul
echo ========================================================
echo   啟動 drive-unix 開發模式 (前後端分離 + 熱重載)
echo ========================================================
echo.
echo 1. 正在於獨立視窗啟動後端 API (http://127.0.0.1:8000)...
start "drive-unix Backend API" cmd /k ".\.venv\Scripts\python.exe -m web --reload"

echo 2. 正在啟動前端 Vite Dev 伺服器 (http://localhost:5173)...
cd frontend
npm run dev
pause
