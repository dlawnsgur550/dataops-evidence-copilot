#!/bin/zsh
set -eu
cd "$(dirname "$0")"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python scripts/run_ui.py
elif [[ -x ../dataops-copilot/.venv/bin/python ]]; then
  exec ../dataops-copilot/.venv/bin/python scripts/run_ui.py
elif command -v uv >/dev/null 2>&1; then
  exec uv run --locked python scripts/run_ui.py
else
  print 'Python 3.11~3.12와 uv가 필요합니다. README의 실행 절차를 확인하세요.'
  read '?Enter를 누르면 닫힙니다. '
fi
