#!/bin/sh
# Run ui3 tests in the bioqueue-ui3 conda env (SQLite, no Postgres required).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${CONDA_PREFIX:-$HOME/miniconda3/envs/bioqueue-ui3}/bin/python"
if [ ! -x "$PY" ]; then
  PY="$HOME/miniconda3/envs/bioqueue-ui3/bin/python"
fi
cd "$ROOT"
exec "$PY" manage.py test ui --settings=ui.test_settings "$@"
