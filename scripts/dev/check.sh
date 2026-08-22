#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"

(
  cd "$repo_root/app"
  npm run check
)
(
  cd "$repo_root/app/src-tauri"
  cargo check --locked
  cargo test --locked
)
"$repo_root/scripts/dev/test-sidecar.sh"
