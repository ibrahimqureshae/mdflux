#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <published-file-or-directory> [...]" >&2
  exit 64
fi

for target in "$@"; do
  if [ ! -e "$target" ]; then
    echo "release output does not exist: $target" >&2
    exit 66
  fi

  if grep -R -a -n -F "/nix/store/" -- "$target"; then
    echo "refusing release output with Nix Store references: $target" >&2
    exit 1
  fi
done
