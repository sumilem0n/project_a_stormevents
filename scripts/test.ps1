Param()
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
  python -m venv .venv
}
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt -r requirements-dev.txt
pytest -q --cov=api --cov-report=term-missing --cov-report=xml --cov-fail-under=50