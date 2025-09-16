#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3.13}"

# 1) Check Python
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "❌ Need Python 3.13 installed (tried '$PYTHON_BIN')."
  exit 1
fi

# 2) Create venv
$PYTHON_BIN -m venv .venv
source .venv/bin/activate

# 3) Upgrade pip & install project (dev extras)
python -m pip install --upgrade pip
pip install -e ".[all]" pre-commit commitizen ruff mypy

# 4) Install git hooks
pre-commit install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg

# 5) (Optional) initialize detect-secrets baseline one time
if ! test -f .secrets.baseline; then
  pip install detect-secrets
  detect-secrets scan > .secrets.baseline || true
  git add .secrets.baseline || true
fi

# 6) Run hooks across repo once
pre-commit run --all-files || true

echo "✅ Bootstrap complete. Activate with: 'source .venv/bin/activate'"
echo "   Try: 'just test'  or  'pytest -q -m \"not slow\"'"
