$ErrorActionPreference = "Stop"
$python = ${env:PYTHON_BIN}
if (-not $python) { $python = "py -3.13" }

# venv test
& $python -m venv .venv
& .\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -e ".[all]" pre-commit commitizen ruff mypy

pre-commit install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg

if (-not (Test-Path ".secrets.baseline")) {
  pip install detect-secrets
  detect-secrets scan | Out-File -Encoding utf8 ".secrets.baseline"
  git add .secrets.baseline
}

pre-commit run --all-files
Write-Host "✅ Bootstrap complete. Use '.\.venv\Scripts\Activate.ps1' to activate."
