# Script khởi chạy Tunnel (Ngrok Static Domain hoặc Cloudflare)
# Trỏ thẳng vào FastAPI Server tại http://127.0.0.1:8000
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ngrokPath = Join-Path $scriptDir "ngrok.exe"
$cloudflaredPath = Join-Path $scriptDir "cloudflared.exe"

$domain = "glorious-apple-unissued.ngrok-free.dev"

if (Test-Path $ngrokPath) {
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host " [NGROK] ĐANG MỞ TUNNEL CỐ ĐỊNH CHO SERVER (PORT 8000)" -ForegroundColor Green
    Write-Host " Domain vĩnh viễn: https://$domain" -ForegroundColor Cyan
    Write-Host " (Đã thêm vào Firebase Console -> Authorized domains)" -ForegroundColor Yellow
    Write-Host "================================================================" -ForegroundColor Green
    & $ngrokPath http 8000 --url "https://$domain"
    exit
}

if (-not (Test-Path $cloudflaredPath)) {
    Write-Host "[*] Đang tải cloudflared.exe chính thức từ Cloudflare..." -ForegroundColor Cyan
    curl.exe -L -o $cloudflaredPath "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
}

Write-Host "================================================================" -ForegroundColor Green
Write-Host " [CLOUDFLARE] ĐANG MỞ HTTPS TUNNEL CHO SERVER (PORT 8000)" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
& $cloudflaredPath tunnel --url http://127.0.0.1:8000

