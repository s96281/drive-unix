# 啟動 drive-unix 前後端整合服務
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  啟動 drive-unix 前後端整合服務 (FastAPI + React SPA)  " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "Web 介面位址: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "API 文件位址: http://127.0.0.1:8000/docs" -ForegroundColor Green
Write-Host ""

Start-Process "http://127.0.0.1:8000"
& .\.venv\Scripts\python.exe -m web
