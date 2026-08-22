#!/usr/bin/env bash
# Build the Linux x64 glibc Lite archive. Lite provisions its runtime on first run.
# Usage: bash scripts/make-portable-linux.sh [--no-build]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/linux/package-common.sh"

no_build=0
case "${1:-}" in
  "") ;;
  --no-build) no_build=1 ;;
  *) die "Usage: $0 [--no-build]" ;;
esac
require_linux_x64_glibc
if (( ! no_build )); then (cd "$ROOT/app" && npm run tauri build -- --no-bundle); fi
read_release_inputs "$ROOT"
stage="$(prepare_stage "$ROOT/dist" "_mdflux_linux_lite_stage")"
archive="$ROOT/dist/MDFlux_${APP_VERSION}_linux_x64_glibc_lite.tar.gz"
cleanup() { cleanup_stage "$ROOT/dist" "$stage"; }
trap cleanup EXIT
copy_portable_payload "$RELEASE_BINARY" "$RELEASE_RESOURCES" "$stage"
write_edition_manifest "$stage/resources/edition.json" "lite" "$APP_VERSION" "$GIT_COMMIT" "linux-x64-glibc" "null" "core" "$LOCK_SHA256"
create_archive "$stage" "$archive"
verify_extracted_archive "$ROOT" "$archive" "linux-x64-glibc" "lite"
echo "Linux Lite archive: $archive"
