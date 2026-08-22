#!/usr/bin/env bash
set -euo pipefail

edition="${1:?usage: build-linux.sh <lite|full>}"
repo_root="$(git rev-parse --show-toplevel)"

if [ "$(uname -s)" != "Linux" ]; then
  echo "build-linux-${edition} must run in Linux or WSL." >&2
  exit 1
fi

case "$edition" in
  lite) builder="$repo_root/scripts/make-portable-linux.sh" ;;
  full) builder="$repo_root/scripts/make-portable-linux-full.sh" ;;
  *) echo "unknown Linux edition: $edition" >&2; exit 64 ;;
esac

if [ ! -f "$builder" ]; then
  echo "missing ${builder##*/}; the Linux packaging script is unavailable." >&2
  exit 69
fi

bash "$builder"

# Check the normal release binary if it exists; the package script performs
# archive-specific checks itself.
binary="$repo_root/app/src-tauri/target/release/MDFlux"
if [ -f "$binary" ]; then
  "$repo_root/scripts/dev/check-no-nix-store.sh" "$binary"
fi
