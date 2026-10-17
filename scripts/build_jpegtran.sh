#!/usr/bin/env bash
# Build a self-contained jpegtran (libjpeg-turbo, statically linked) for the app bundle.
# Homebrew's binary needs Homebrew's dylibs and the build machine's macOS version, so the
# app ships its own. Output is cached: build/jpegtran/jpegtran
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="3.1.2"
WORK="$ROOT/build/jpegtran"
OUT="$WORK/jpegtran"
export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-12.0}"

if [ -x "$OUT" ] && "$OUT" -version 2>&1 | grep -q "$VERSION"; then
  echo "jpegtran $VERSION already built"
  exit 0
fi

mkdir -p "$WORK"
cd "$WORK"
TARBALL="libjpeg-turbo-$VERSION.tar.gz"
if [ ! -f "$TARBALL" ]; then
  curl -fsSL -o "$TARBALL" "https://github.com/libjpeg-turbo/libjpeg-turbo/releases/download/$VERSION/$TARBALL"
fi
rm -rf "src" "cmake-build"
mkdir src
tar -xzf "$TARBALL" -C src --strip-components 1

uvx --from cmake cmake -S src -B cmake-build \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DCMAKE_OSX_DEPLOYMENT_TARGET="$MACOSX_DEPLOYMENT_TARGET" \
  -DENABLE_SHARED=OFF \
  -DENABLE_STATIC=ON \
  -DWITH_TURBOJPEG=OFF \
  -DWITH_SIMD=ON >/dev/null
uvx --from cmake cmake --build cmake-build --target jpegtran-static --parallel >/dev/null

cp cmake-build/jpegtran-static "$OUT"
strip -x "$OUT"
"$OUT" -version 2>&1 | head -1
otool -L "$OUT" | tail -n +2
