# test-restart.ps1
# One-click clean Tauri data, set ceshi as watch dir, then start dev

$dataDir = "$env:LOCALAPPDATA\app.zhixia.ai\data"
$chromaDir = "$dataDir\db\chroma"
$wikiDir = "$dataDir\wiki"
$watchDirsFile = "$dataDir\watch_dirs.json"
$projectRoot = "e:\Users\bob\Documents\BobBase\aizsk\zhixia"
$batPath = "$projectRoot\start-dev.bat"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " 知匣 Test Restart Script" -ForegroundColor Cyan
Write-Host "========================================"

# 1. Kill existing processes on dev ports
Write-Host "`n[1/4] Killing existing processes on ports 1420 / 8765..." -ForegroundColor Yellow
Get-NetTCPConnection -LocalPort 1420 -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    Write-Host "  Killed port 1420 process"
}
Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    Write-Host "  Killed port 8765 process"
}
Start-Sleep -Seconds 1

# 2. Remove old vector DB and wiki
Write-Host "`n[2/4] Cleaning old data..." -ForegroundColor Yellow
if (Test-Path $chromaDir) {
    Remove-Item -Recurse -Force $chromaDir
    Write-Host "  Removed ChromaDB"
} else {
    Write-Host "  ChromaDB not found, skipped"
}
if (Test-Path $wikiDir) {
    Remove-Item -Recurse -Force $wikiDir
    Write-Host "  Removed wiki"
} else {
    Write-Host "  Wiki not found, skipped"
}

# 3. Set watch dir to ceshi
Write-Host "`n[3/4] Setting watch dir to C:\Users\bob\Downloads\ceshi ..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
@('C:\Users\bob\Downloads\ceshi') | ConvertTo-Json | Set-Content -Path $watchDirsFile -Encoding UTF8
Write-Host "  watch_dirs.json updated"

# 4. Launch dev environment
Write-Host "`n[4/4] Starting dev environment..." -ForegroundColor Yellow
Write-Host "  Please wait for the Tauri window and Python backend to start.`n"
Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$batPath`"" -WorkingDirectory $projectRoot

Write-Host "Done. New window launched. Wait for indexing to complete before testing." -ForegroundColor Green
