#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
uv sync --frozen --no-dev
pushd frontend >/dev/null
npm ci
npm run build
popd >/dev/null
printf '%s\n' 'Open http://127.0.0.1:8000 ; Ctrl+C to stop.'
exec uv run --no-sync uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
