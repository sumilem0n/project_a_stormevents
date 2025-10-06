param(
  [int]$Port = 8000,
  [string]$BindHost = "127.0.0.1"
)

$env:OFFLINE_MODE = "1"
Write-Host "Starting FastAPI in OFFLINE_MODE (Host=$BindHost Port=$Port)..." -ForegroundColor Cyan
python -m uvicorn api.app:app --reload --host $BindHost --port $Port
