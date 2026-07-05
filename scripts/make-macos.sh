#!/usr/bin/env bash
# Build MDFlux and package it as an unsigned .app bundle + .dmg for macOS arm64.
# Produces MDFlux.app, MDFlux.dmg, and a SHA512SUMS file under dist/.
#
# Usage:  bash scripts/make-macos.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RELEASE_DIR="$ROOT/app/src-tauri/target/release/bundle"
DIST_DIR="$ROOT/dist"

# Build the Tauri app (macOS bundle + dmg).
echo "==> Building MDFlux for macOS (arm64)..."
pushd "$ROOT/app" >/dev/null
npm run tauri build
popd >/dev/null

# Locate the built artifacts.
APP="$(find "$RELEASE_DIR/macos" -maxdepth 1 -name '*.app' -print -quit)"
DMG="$(find "$RELEASE_DIR/dmg" -maxdepth 1 -name '*.dmg' -print -quit)"

if [ -z "$APP" ] || [ ! -d "$APP" ]; then
  echo "ERROR: .app bundle not found under $RELEASE_DIR/macos" >&2
  exit 1
fi

if [ -z "$DMG" ] || [ ! -f "$DMG" ]; then
  echo "ERROR: .dmg not found under $RELEASE_DIR/dmg" >&2
  exit 1
fi

# Read version from tauri.conf.json for artifact naming.
VERSION="$(node -p "require('$ROOT/app/src-tauri/tauri.conf.json').version")"
APP_NAME="MDFlux_${VERSION}_arm64.app"
DMG_NAME="MDFlux_${VERSION}_arm64.dmg"

mkdir -p "$DIST_DIR"

# Copy and rename artifacts.
cp -R "$APP" "$DIST_DIR/$APP_NAME"
cp "$DMG" "$DIST_DIR/$DMG_NAME"

# Generate SHA-512 checksums.
pushd "$DIST_DIR" >/dev/null
shasum -a 512 "$APP_NAME" "$DMG_NAME" > SHA512SUMS
echo "==> Verifying SHA-512 checksums..."
shasum -a 512 -c SHA512SUMS
popd >/dev/null

echo ""
echo "==> macOS build complete. Artifacts:"
echo "    App:  $DIST_DIR/$APP_NAME"
echo "    DMG:  $DIST_DIR/$DMG_NAME"
echo "    Sums: $DIST_DIR/SHA512SUMS"
echo ""
echo "    To unblock Gatekeeper after copying to /Applications:"
echo "      xattr -dr com.apple.quarantine /Applications/MDFlux.app"
