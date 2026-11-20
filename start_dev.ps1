$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$CfDir = Join-Path $env:LOCALAPPDATA "cloudflared"
$CfExe = Join-Path $CfDir "cloudflared.exe"
$CfLog = Join-Path $CfDir "tunnel.log"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Starting AI Multi-Market Trading Desk (MT5 + Supabase)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Backend API : http://localhost:8000" -ForegroundColor Green
Write-Host " Frontend UI : http://localhost:5173" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan

$BackendCmd = "Set-Location '$BackendDir'; python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
$FrontendCmd = "Set-Location '$FrontendDir'; npm run dev"

Start-Process powershell -ArgumentList "-NoExit", "-Command", $BackendCmd
Start-Process powershell -ArgumentList "-NoExit", "-Command", $FrontendCmd

if (Test-Path $CfExe) {
    if (Test-Path $CfLog) { Remove-Item $CfLog -Force -ErrorAction SilentlyContinue }
    Write-Host "Starting Cloudflare HTTPS Tunnel..." -ForegroundColor Yellow
    Start-Process -FilePath $CfExe -ArgumentList "tunnel", "--url", "http://127.0.0.1:8000", "--no-autoupdate", "--logfile", $CfLog -WindowStyle Minimized

    $TunnelUrl = $null
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Path $CfLog) {
            $Match = Select-String -Path $CfLog -Pattern "https://[a-zA-Z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
            if ($Match) {
                $TunnelUrl = $Match.Matches[0].Value
                break
            }
        }
    }

    if ($TunnelUrl) {
        Write-Host "----------------------------------------------------------" -ForegroundColor DarkGray
        Write-Host " Cloudflare Tunnel Live : $TunnelUrl" -ForegroundColor Green
        for ($j = 0; $j -lt 10; $j++) {
            try {
                $Headers = @{ "X-API-Key" = "mt5-local-dev-key"; "Content-Type" = "application/json" }
                $Body = @{ public_base_url = $TunnelUrl } | ConvertTo-Json
                Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/discord/config" -Method Put -Headers $Headers -Body $Body | Out-Null
                Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/supabase/sync-all" -Method Post -Headers $Headers | Out-Null
                Write-Host " Auto-Synced Tunnel URL to Supabase & Discord!" -ForegroundColor Cyan
                break
            } catch {
                Start-Sleep -Seconds 1
            }
        }
        Write-Host "==========================================================" -ForegroundColor Cyan
    }
}
