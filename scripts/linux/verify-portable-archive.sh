#!/usr/bin/env bash
# Validate a Linux MDFlux archive after extraction. Run this on the supported Linux host.
set -euo pipefail
die() { echo "error: $*" >&2; exit 1; }
[[ "$#" == 3 ]] || die "Usage: $0 ARCHIVE linux-x64-glibc lite|full"
archive="$1"; expected_platform="$2"; expected_edition="$3"
[[ -f "$archive" ]] || die "Archive not found: $archive"
[[ "$(uname -s)" == Linux ]] || die "Archive verification must run on Linux"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/mdflux-verify.XXXXXX")"
cleanup() { [[ "$tmp" == "${TMPDIR:-/tmp}"/mdflux-verify.* ]] && rm -rf -- "$tmp"; }
trap cleanup EXIT
tar -xzf "$archive" -C "$tmp"
[[ -x "$tmp/MDFlux" ]] || die "MDFlux is missing or not executable"; [[ -d "$tmp/resources/sidecar" ]] || die "Sidecar directory is missing"; manifest="$tmp/resources/edition.json"; [[ -f "$manifest" ]] || die "edition.json is missing"
python3 - "$manifest" "$expected_platform" "$expected_edition" <<'PY'
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8")); required = {"schema", "edition", "app_version", "commit", "platform", "python_version", "components", "dependency_lock_sha256", "built_at_utc"}
assert not required - m.keys(), f"manifest fields missing: {sorted(required - m.keys())}"
assert m["schema"] == 1 and m["platform"] == sys.argv[2] and m["edition"] == sys.argv[3]
assert m["components"] == (["core"] if sys.argv[3] == "lite" else ["core", "ocr", "audio-runtime"])
assert (m["python_version"] is None) if sys.argv[3] == "lite" else isinstance(m["python_version"], str)
PY
lock="$tmp/resources/sidecar/requirements-full.lock"; [[ -f "$lock" ]] || die "Packaged requirements-full.lock is missing"
expected_hash="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["dependency_lock_sha256"])' "$manifest")"; actual_hash="$(sha256sum "$lock" | awk '{print $1}')"; [[ "$actual_hash" == "$expected_hash" ]] || die "Dependency lock checksum mismatch"
runtime_library_path=""
if [[ "$expected_edition" == lite ]]; then [[ ! -e "$tmp/resources/runtime" ]] || die "Lite archive unexpectedly bundles a runtime"; else runtime_root="$tmp/resources/runtime"; runtime="$runtime_root/bin/python3"; [[ -x "$runtime" ]] || die "Full archive is missing executable resources/runtime/bin/python3"; "$runtime" -I -c 'import markitdown, openai, httpx, rapidocr, onnxruntime, pypdfium2, faster_whisper, ctranslate2'; printf '%s\n' '{"v":1,"id":"packaging-health","method":"health","params":{}}' | (cd "$tmp/resources/sidecar" && "$runtime" main.py) | grep -q '"ok": true' || die "Packaged sidecar health request failed"; runtime_library_path="$runtime_root/lib"; while IFS= read -r -d '' wheel_libs; do runtime_library_path+=":$wheel_libs"; done < <(find "$runtime_root" -type d -name '*.libs' -print0); fi
if grep -RIl --exclude='*.pyc' --exclude='*.so' -E '/nix/store|_mdflux_linux_(lite|full)_stage' "$tmp" >/dev/null; then grep -RIl --exclude='*.pyc' --exclude='*.so' -E '/nix/store|_mdflux_linux_(lite|full)_stage' "$tmp" >&2; die "Archive contains a Nix Store or staging path"; fi
while IFS= read -r -d '' executable; do if [[ -n "$runtime_library_path" ]]; then ldd_output="$(LD_LIBRARY_PATH="$runtime_library_path${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ldd "$executable" 2>&1 || true)"; else ldd_output="$(ldd "$executable" 2>&1 || true)"; fi; if grep -Eq 'not found|/nix/store|_mdflux_linux_(lite|full)_stage' <<< "$ldd_output" || strings "$executable" | grep -Eq '/nix/store|_mdflux_linux_(lite|full)_stage'; then printf '%s\n%s\n' "$executable" "$ldd_output" >&2; die "Native dependency inspection failed"; fi; done < <(find "$tmp" -type f \( -name MDFlux -o -name python3 -o -name '*.so' -o -name '*.so.*' \) -print0)
echo "Verified $archive ($expected_platform, $expected_edition)"
