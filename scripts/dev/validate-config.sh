#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"

python3 - "$repo_root/devenv.lock" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    lock = json.load(source)

node = lock["nodes"]["nixpkgs"]["locked"]
assert lock["version"] == 7
assert node["type"] == "github"
assert len(node["rev"]) == 40
assert node["narHash"].startswith("sha256-")
PY

for command in dev check test-sidecar build-linux-lite build-linux-full; do
  grep -Fq "$command.exec" "$repo_root/devenv.nix"
done
