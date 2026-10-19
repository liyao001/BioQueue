#!/bin/sh
# Run worker unit tests. Prefers the pixi env when available.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if command -v pixi >/dev/null 2>&1 && [ -f "$ROOT/worker/pixi.toml" ]; then
  exec pixi run --manifest-path "$ROOT/worker/pixi.toml" test "$@"
fi
if [ -n "${BIOQUEUE_PYTHON:-}" ] && [ -x "${BIOQUEUE_PYTHON}" ]; then
  PY="${BIOQUEUE_PYTHON}"
elif [ -n "${CONDA_PREFIX:-}" ] && [ -x "${CONDA_PREFIX}/bin/python" ]; then
  PY="${CONDA_PREFIX}/bin/python"
else
  PY="python3"
fi
exec "$PY" manage.py test worker.tests --settings=worker.test_settings "$@"
