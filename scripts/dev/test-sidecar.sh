#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
sidecar_dir="$repo_root/app/src-tauri/resources/sidecar"

if [[ -n "${SIDECAR_TEST_PYTHON:-}" ]]; then
  test_python="$SIDECAR_TEST_PYTHON"
elif command -v uv >/dev/null 2>&1; then
  test_venv="$repo_root/.venv-sidecar-tests"
  test_python="$test_venv/bin/python"
  if [[ ! -x "$test_python" ]]; then
    uv venv --python 3.12 "$test_venv"
  fi
  UV_LINK_MODE=copy uv pip install --python "$test_python" --require-hashes \
    -r "$sidecar_dir/requirements.lock"
else
  test_python="$(command -v python3 || true)"
  [[ -n "$test_python" ]] || {
    echo "error: install uv or set SIDECAR_TEST_PYTHON to a prepared interpreter" >&2
    exit 1
  }
  "$test_python" -c 'import httpx' 2>/dev/null || {
    echo "error: sidecar test dependencies are missing; install uv or set SIDECAR_TEST_PYTHON" >&2
    exit 1
  }
fi

cd "$sidecar_dir"
exec "$test_python" -m unittest discover -s tests -p "test_*.py"
