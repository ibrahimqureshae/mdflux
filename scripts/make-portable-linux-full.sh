#!/usr/bin/env bash
# Build the Linux x64 glibc Full archive with an immutable bundled Python 3.12.
# Usage: bash scripts/make-portable-linux-full.sh [--no-build] [--uv /path/to/uv]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/linux/package-common.sh"

no_build=0
uv_path="${UV_PATH:-}"
while (( "$#" )); do
  case "$1" in
    --no-build) no_build=1 ;;
    --uv) shift; (( "$#" )) || die "--uv requires a path"; uv_path="$1" ;;
    *) die "Usage: $0 [--no-build] [--uv /path/to/uv]" ;;
  esac
  shift
done

require_linux_x64_glibc
if (( ! no_build )); then (cd "$ROOT/app" && npm run tauri build -- --no-bundle); fi
read_release_inputs "$ROOT"
uv_path="${uv_path:-$(command -v uv || true)}"
[[ -n "$uv_path" && -x "$uv_path" ]] || die "uv was not found; install uv or pass --uv /path/to/uv"
managed_python="$($uv_path python find --managed-python 3.12 2>/dev/null || true)"
if [[ -z "$managed_python" || ! -x "$managed_python" ]]; then
  "$uv_path" python install 3.12
  managed_python="$($uv_path python find --managed-python 3.12)"
fi
[[ -x "$managed_python" ]] || die "uv did not return an executable managed Python 3.12"
python_root="$(cd "$(dirname "$managed_python")/.." && pwd -P)"
stage="$(prepare_stage "$ROOT/dist" "_mdflux_linux_full_stage")"
archive="$ROOT/dist/MDFlux_${APP_VERSION}_linux_x64_glibc_full.tar.gz"
cleanup() { cleanup_stage "$ROOT/dist" "$stage"; }
trap cleanup EXIT

copy_portable_payload "$RELEASE_BINARY" "$RELEASE_RESOURCES" "$stage"
runtime="$stage/resources/runtime"
mkdir -p "$runtime"
cp -a "$python_root/." "$runtime/"
runtime_python="$runtime/bin/python3"
[[ -x "$runtime_python" ]] || die "Bundled runtime is missing bin/python3"
"$runtime_python" -I -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version; print(sys.version)'
full_lock="$stage/resources/sidecar/requirements-full.lock"
[[ -f "$full_lock" ]] || die "Packaged requirements-full.lock is missing"
[[ "$(sha256_file "$full_lock")" == "$LOCK_SHA256" ]] || die "Packaged requirements-full.lock checksum differs from the canonical lock"
UV_LINK_MODE=copy "$uv_path" pip install --python "$runtime_python" --system --break-system-packages --require-hashes -r "$full_lock"
# Console entry points created by pip contain an absolute shebang to the
# temporary staging directory. The desktop sidecar imports these packages and
# does not use their CLI wrappers, so retain only the relocatable interpreters.
find "$runtime/bin" -mindepth 1 -maxdepth 1 \
  ! -name 'python' ! -name 'python3' ! -name 'python3.*' -delete
# The uv standalone distribution includes the optional Tk extension, but not
# its Tcl/Tk shared libraries. MDFlux has no Tk UI, so omit that unusable module
# instead of creating a host dependency in the portable archive.
find "$runtime/lib" -type f -name '_tkinter*.so' -delete
"$runtime_python" -I -c 'import markitdown, openai, httpx, rapidocr, onnxruntime, pypdfium2, faster_whisper, ctranslate2; print("bundled runtime imports: OK")'
python_version="$($runtime_python -I -c 'import platform; print(platform.python_version())')"
write_edition_manifest "$stage/resources/edition.json" "full" "$APP_VERSION" "$GIT_COMMIT" "linux-x64-glibc" "\"$python_version\"" "core,ocr,audio-runtime" "$LOCK_SHA256"
create_archive "$stage" "$archive"
verify_extracted_archive "$ROOT" "$archive" "linux-x64-glibc" "full"
echo "Linux Full archive: $archive"
