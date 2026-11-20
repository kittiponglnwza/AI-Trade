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

# 1. Clean up stale/duplicate processes so ports & tunnel.log never conflict
Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
foreach ($port in @(8000, 5173, 5174)) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        if ($c.OwningProcess -gt 0) {
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
}
Start-Sleep -Seconds 1

Write-Host " Backend API : http://localhost:8000" -ForegroundColor Green
Write-Host " Frontend UI : http://localhost:5173" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan

$BackendCmd = "Set-Location '$BackendDir'; python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
$FrontendCmd = "Set-Location '$FrontendDir'; npm run dev -- --host --port 5173"

Start-Process powershell -ArgumentList "-NoExit", "-Command", $BackendCmd
Start-Process powershell -ArgumentList "-NoExit", "-Command", $FrontendCmd

function Start-And-Sync-Tunnel {
    Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 700
    if (Test-Path $CfLog) { Remove-Item $CfLog -Force -ErrorAction SilentlyContinue }

    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Starting fresh Cloudflare HTTPS Tunnel..." -ForegroundColor Yellow
    Start-Process -FilePath $CfExe -ArgumentList "tunnel", "--url", "http://127.0.0.1:8000", "--no-autoupdate", "--logfile", $CfLog -WindowStyle Minimized

    $TunnelUrl = $null
    for ($i = 0; $i -lt 25; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Path $CfLog) {
            $Match = Select-String -Path $CfLog -Pattern "https://[a-zA-Z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -Last 1
            if ($Match) {
                $TunnelUrl = $Match.Matches[0].Value
                break
            }
        }
    }

    if (-not $TunnelUrl) {
        Write-Host "[WARN] Could not obtain Cloudflare Tunnel URL yet." -ForegroundColor Red
        return $null
    }

    Write-Host "----------------------------------------------------------" -ForegroundColor DarkGray
    Write-Host " Cloudflare Tunnel Live : $TunnelUrl" -ForegroundColor Green

    $Headers = @{ "X-API-Key" = "mt5-local-dev-key"; "Content-Type" = "application/json" }
    $Body = @{ public_base_url = $TunnelUrl } | ConvertTo-Json
    for ($j = 0; $j -lt 30; $j++) {
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/discord/config" -Method Put -Headers $Headers -Body $Body -TimeoutSec 5 | Out-Null
            Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/supabase/sync-all" -Method Post -Headers $Headers -TimeoutSec 10 | Out-Null
            Write-Host " Auto-Synced Tunnel URL to Supabase & Discord!" -ForegroundColor Cyan
            break
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    Write-Host "==========================================================" -ForegroundColor Cyan
    return $TunnelUrl
}

if (Test-Path $CfExe) {
    $ActiveUrl = Start-And-Sync-Tunnel
    Write-Host " Tunnel Self-Heal Watchdog ACTIVE (keep this window open / minimized)." -ForegroundColor DarkCyan
    while ($true) {
        Start-Sleep -Seconds 30
        $cfRunning = Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue
        $deadTunnel = $false
        if (-not $cfRunning) {
            $deadTunnel = $true
        } elseif (Test-Path $CfLog) {
            $tail = Get-Content $CfLog -Tail 8 -ErrorAction SilentlyContinue | Out-String
            if ($tail -match "Unauthorized: Tunnel not found") {
                $deadTunnel = $true
            }
        }
        if ($deadTunnel) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Tunnel dropped/expired — auto-healing..." -ForegroundColor Yellow
            $ActiveUrl = Start-And-Sync-Tunnel
        }
    }
}
