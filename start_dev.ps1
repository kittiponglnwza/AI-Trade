$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Starting MT5 Real-Time Trading Desk (Dev Mode)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Backend API : http://localhost:8000 (Docs: /docs)" -ForegroundColor Green
Write-Host " Frontend UI : http://localhost:5173" -ForegroundColor Green
Write-Host " WebSocket   : ws://localhost:8000/ws/live" -ForegroundColor Green
Write-Host "----------------------------------------------------------" -ForegroundColor DarkGray
Write-Host " Tip for Vercel HTTPS bridge:" -ForegroundColor Yellow
Write-Host "   cloudflared tunnel --url http://localhost:8000" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan

$BackendCmd = "Set-Location '$BackendDir'; python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
$FrontendCmd = "Set-Location '$FrontendDir'; npm run dev"

Start-Process powershell -ArgumentList "-NoExit", "-Command", $BackendCmd
Start-Process powershell -ArgumentList "-NoExit", "-Command", $FrontendCmd
