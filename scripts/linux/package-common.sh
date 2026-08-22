#!/usr/bin/env bash
# Shared, Linux-only packaging helpers. Called by the two portable builders.
set -euo pipefail
die() { echo "error: $*" >&2; exit 1; }
sha256_file() { sha256sum "$1" | awk '{print $1}'; }
require_linux_x64_glibc() { [[ "$(uname -s)" == Linux ]] || die "Linux packaging must run on Linux"; [[ "$(uname -m)" == x86_64 ]] || die "Only Linux x86_64 is supported"; getconf GNU_LIBC_VERSION >/dev/null 2>&1 || die "A glibc host is required"; }
read_release_inputs() { local root="$1"; RELEASE_BINARY="$root/app/src-tauri/target/release/app"; RELEASE_RESOURCES="$root/app/src-tauri/target/release/resources"; [[ -f "$RELEASE_BINARY" ]] || die "Release binary not found at $RELEASE_BINARY"; [[ -d "$RELEASE_RESOURCES" ]] || die "Release resources not found at $RELEASE_RESOURCES"; APP_VERSION="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$root/app/src-tauri/tauri.conf.json" | head -n 1)"; [[ -n "$APP_VERSION" ]] || die "Could not read the application version"; GIT_COMMIT="$(git -C "$root" rev-parse HEAD)"; FULL_LOCK="$root/app/src-tauri/resources/sidecar/requirements-full.lock"; [[ -f "$FULL_LOCK" ]] || die "Canonical requirements-full.lock is missing"; LOCK_SHA256="$(sha256_file "$FULL_LOCK")"; }
prepare_stage() { local dist="$1" name="$2" stage dist_real; mkdir -p "$dist"; dist_real="$(cd "$dist" && pwd -P)"; stage="$dist_real/$name"; [[ "$stage" == "$dist_real/"* && "$stage" != "$dist_real" ]] || die "Unsafe staging path: $stage"; rm -rf -- "$stage"; mkdir -p "$stage"; printf '%s\n' "$stage"; }
cleanup_stage() { local dist="$1" stage="$2" dist_real stage_real; [[ -n "$stage" && -d "$stage" ]] || return 0; dist_real="$(cd "$dist" && pwd -P)"; stage_real="$(cd "$stage" && pwd -P)"; [[ "$stage_real" == "$dist_real/"* && "$stage_real" != "$dist_real" ]] || die "Refusing unsafe cleanup path: $stage_real"; rm -rf -- "$stage_real"; }
copy_portable_payload() { local binary="$1" resources="$2" stage="$3"; cp "$binary" "$stage/MDFlux"; chmod 0755 "$stage/MDFlux"; cp -a "$resources" "$stage/resources"; [[ -d "$stage/resources/sidecar" ]] || die "Packaged sidecar resources are missing"; }
write_edition_manifest() { local output="$1" edition="$2" version="$3" commit="$4" platform="$5" python_version="$6" components="$7" lock_sha="$8" built_at component_json="" component; local -a component_array; built_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; IFS=',' read -r -a component_array <<< "$components"; for component in "${component_array[@]}"; do component_json+="${component_json:+,}\"$component\""; done; cat > "$output" <<EOF
{
  "schema": 1,
  "edition": "$edition",
  "app_version": "$version",
  "commit": "$commit",
  "platform": "$platform",
  "python_version": $python_version,
  "components": [$component_json],
  "dependency_lock_sha256": "$lock_sha",
  "built_at_utc": "$built_at"
}
EOF
}
create_archive() { local stage="$1" archive="$2"; rm -f -- "$archive"; tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner -C "$stage" -czf "$archive" MDFlux resources; }
verify_extracted_archive() { local root="$1" archive="$2" platform="$3" edition="$4"; "$root/scripts/linux/verify-portable-archive.sh" "$archive" "$platform" "$edition"; }
