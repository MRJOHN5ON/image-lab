#!/usr/bin/env bash
# Build a self-contained Image Lab.app (bundled Python) and a DMG for GitHub Releases.
#
#   scripts/build_release.sh 2.0.0             build dist/release/Image-Lab-2.0.0-arm64.dmg
#   scripts/build_release.sh 2.0.0 --publish   ...and upload it as GitHub release v2.0.0 (draft)
#   scripts/build_release.sh --relock          refresh packaging/requirements-build.lock
#
# Needs: uv, Node.js 18+, Xcode Command Line Tools. Users of the DMG need nothing.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Oldest macOS we support. Every compiled wheel must have a build for this version.
export MACOSX_DEPLOYMENT_TARGET=12.0
PY_VERSION=3.12
VENV="$ROOT/.venv-build"
LOCK="packaging/requirements-build.lock"
OUT="$ROOT/dist/release"
UV_PLATFORM=(--python-platform aarch64-apple-darwin)
BINARY_ONLY=()
for pkg in pillow pillow-heif pyobjc-core pydantic-core; do
  BINARY_ONLY+=(--only-binary "$pkg")
done

if [ "${1:-}" = "--relock" ]; then
  uv pip compile -q --python-version "$PY_VERSION" "${UV_PLATFORM[@]}" "${BINARY_ONLY[@]}" \
    --custom-compile-command "scripts/build_release.sh --relock" \
    packaging/requirements-build.txt -o "$LOCK"
  echo "Updated $LOCK"
  exit 0
fi

VERSION="${1:-}"
PUBLISH="${2:-}"
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Usage: scripts/build_release.sh <version, e.g. 2.0.0> [--publish]" >&2
  exit 1
fi
if [ "$(uname -m)" != "arm64" ]; then
  echo "Release builds must run on Apple Silicon (arm64)." >&2
  exit 1
fi
DMG="$OUT/Image-Lab-${VERSION}-arm64.dmg"
APP="$ROOT/build/pyinstaller/dist/Image Lab.app"

step() { printf '\n→ %s\n' "$1"; }

step "Python build environment (Python $PY_VERSION, macOS $MACOSX_DEPLOYMENT_TARGET wheels)"
if [ ! -x "$VENV/bin/python" ]; then
  uv venv -q --managed-python --python "$PY_VERSION" "$VENV"
fi
uv pip sync -q --python "$VENV/bin/python" "${UV_PLATFORM[@]}" "${BINARY_ONLY[@]}" "$LOCK"

step "Tests"
uv pip install -q --python "$VENV/bin/python" pytest httpx
(cd backend && "$VENV/bin/python" -m pytest -q -p no:cacheprovider)

step "Frontend"
(cd frontend && { [ -d node_modules ] || npm ci --no-fund --no-audit; } && npm run build --silent)

step "jpegtran (static libjpeg-turbo)"
scripts/build_jpegtran.sh

step "Icon and version"
[ -f packaging/ImageLab.icns ] || "$VENV/bin/python" scripts/make_icon.py
mkdir -p build
printf '%s\n' "$VERSION" > build/VERSION

step "PyInstaller"
IMAGE_LAB_VERSION="$VERSION" "$VENV/bin/pyinstaller" --noconfirm --clean --log-level WARN \
  --distpath build/pyinstaller/dist --workpath build/pyinstaller/work \
  packaging/ImageLab.spec

step "Verifying the bundle is self-contained"
"$VENV/bin/python" scripts/verify_bundle.py "$APP"
codesign --verify --deep --strict "$APP"

step "Smoke test (engine, worker processes, jpegtran inside the bundle)"
IMAGE_LAB_SMOKE_TEST=1 IMAGE_LAB_DATA_DIR="$(mktemp -d)" IMAGE_LAB_PORT=0 \
  "$APP/Contents/MacOS/ImageLab"

step "DMG"
mkdir -p "$OUT"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -quiet -volname "Image Lab" -srcfolder "$STAGE" -fs HFS+ -format ULMO "$DMG"
(cd "$OUT" && shasum -a 256 "$(basename "$DMG")" > "$(basename "$DMG").sha256")

echo ""
echo "✓ $DMG ($(du -h "$DMG" | cut -f1))"

if [ "$PUBLISH" = "--publish" ]; then
  step "Publishing draft GitHub release v$VERSION"
  gh release create "v$VERSION" "$DMG" "$DMG.sha256" \
    --draft --title "Image Lab $VERSION" --notes-file packaging/release-notes.md
  echo "Draft created. Review and publish it on GitHub."
fi
