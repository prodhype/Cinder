#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_ROOT="${CINDER_BOOTSTRAP_DIR:-$ROOT/.cinder/bootstrap}"
PROJECT="$ROOT/compiler_selfhost"
SUMS="$ROOT/bootstrap/SHA256SUMS"

case "$(uname -s):$(uname -m)" in
  Darwin:arm64)
    PLATFORM="darwin-arm64"
    ;;
  Linux:x86_64 | Linux:amd64)
    PLATFORM="linux-x86_64"
    ;;
  *)
    printf 'error: no Cinder bootstrap seed for %s/%s\n' \
      "$(uname -s)" "$(uname -m)" >&2
    exit 1
    ;;
esac

SEED="$ROOT/bootstrap/$PLATFORM/cinder"
RELATIVE_SEED="$PLATFORM/cinder"

if [[ ! -x "$SEED" ]]; then
  printf 'error: bootstrap seed is missing or not executable: %s\n' "$SEED" >&2
  exit 1
fi

EXPECTED="$(
  awk -v path="$RELATIVE_SEED" '$2 == path { print $1 }' "$SUMS"
)"
if [[ -z "$EXPECTED" ]]; then
  printf 'error: bootstrap seed has no checksum: %s\n' "$RELATIVE_SEED" >&2
  exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL="$(sha256sum "$SEED" | awk '{ print $1 }')"
elif command -v shasum >/dev/null 2>&1; then
  ACTUAL="$(shasum -a 256 "$SEED" | awk '{ print $1 }')"
else
  printf 'error: sha256sum or shasum is required to verify the seed\n' >&2
  exit 1
fi

if [[ "$ACTUAL" != "$EXPECTED" ]]; then
  printf 'error: bootstrap seed checksum mismatch for %s\n' "$RELATIVE_SEED" >&2
  printf 'expected: %s\nactual:   %s\n' "$EXPECTED" "$ACTUAL" >&2
  exit 1
fi

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT"
cd "$ROOT"

"$SEED" build "$PROJECT" \
  -o "$BUILD_ROOT/cinder-gen1" \
  --build-dir "$BUILD_ROOT/gen1-build"

"$BUILD_ROOT/cinder-gen1" build "$PROJECT" \
  -o "$BUILD_ROOT/cinder-gen2" \
  --build-dir "$BUILD_ROOT/gen2-build"

diff -ru \
  "$BUILD_ROOT/gen1-build/cinder_gen" \
  "$BUILD_ROOT/gen2-build/cinder_gen"

printf '%s\n' "bootstrap seed checksum: PASS ($PLATFORM)"
printf '%s\n' "gen1/gen2 generated-C fixed point: PASS"
printf '%s\n' "$BUILD_ROOT/cinder-gen2"
