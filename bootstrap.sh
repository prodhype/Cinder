#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_ROOT="${CINDER_BOOTSTRAP_DIR:-$ROOT/.cinder/bootstrap}"
if [[ "$BUILD_ROOT" != /* ]]; then
  BUILD_ROOT="$(pwd)/$BUILD_ROOT"
fi
PROJECT="$ROOT/compiler_selfhost"
SUMS="$ROOT/bootstrap/SHA256SUMS"

require_macos_version() {
  local minimum="15.4"
  local reported
  local major
  local minor

  if ! command -v sw_vers >/dev/null 2>&1; then
    printf 'error: the macOS ARM64 seed requires macOS %s or newer\n' \
      "$minimum" >&2
    printf 'error: cannot detect macOS because sw_vers is unavailable\n' >&2
    exit 1
  fi

  reported="$(sw_vers -productVersion 2>/dev/null || true)"
  if [[ ! "$reported" =~ ^([0-9]+)\.([0-9]+) ]]; then
    printf 'error: the macOS ARM64 seed requires macOS %s or newer\n' \
      "$minimum" >&2
    printf 'error: detected an unrecognized macOS version: %s\n' \
      "${reported:-unknown}" >&2
    exit 1
  fi

  major="${BASH_REMATCH[1]}"
  minor="${BASH_REMATCH[2]}"
  if ((major < 15 || (major == 15 && minor < 4))); then
    printf 'error: the macOS ARM64 seed requires macOS %s or newer' \
      "$minimum" >&2
    printf ' (detected macOS %s)\n' "$reported" >&2
    printf '%s\n' \
      'error: use a newer host or rebuild the seed with an older deployment target' >&2
    exit 1
  fi
}

require_linux_glibc() {
  local minimum="2.34"
  local reported
  local major
  local minor

  if ! command -v getconf >/dev/null 2>&1; then
    printf 'error: the Linux x86_64 seed requires glibc %s or newer\n' \
      "$minimum" >&2
    printf 'error: cannot detect glibc because getconf is unavailable\n' >&2
    exit 1
  fi

  reported="$(getconf GNU_LIBC_VERSION 2>/dev/null || true)"
  if [[ ! "$reported" =~ ^glibc[[:space:]]+([0-9]+)\.([0-9]+) ]]; then
    printf 'error: the Linux x86_64 seed requires glibc %s or newer\n' \
      "$minimum" >&2
    printf 'error: detected an unsupported or unrecognized C library: %s\n' \
      "${reported:-unknown}" >&2
    exit 1
  fi

  major="${BASH_REMATCH[1]}"
  minor="${BASH_REMATCH[2]}"
  if ((major < 2 || (major == 2 && minor < 34))); then
    printf 'error: the Linux x86_64 seed requires glibc %s or newer' \
      "$minimum" >&2
    printf ' (detected glibc %s.%s)\n' "$major" "$minor" >&2
    printf '%s\n' \
      'error: use a newer host/container or rebuild the seed for an older baseline' >&2
    exit 1
  fi
}

case "$(uname -s):$(uname -m)" in
  Darwin:arm64)
    require_macos_version
    PLATFORM="darwin-arm64"
    ;;
  Linux:x86_64 | Linux:amd64)
    require_linux_glibc
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

SEED_CC="${CC:-cc}"
if [[ -n "${CC:-}" ]]; then
  SEED_CC="$BUILD_ROOT/cc-wrapper"
  printf '#!/bin/sh\nexec %s "$@"\n' "$CC" > "$SEED_CC"
  chmod +x "$SEED_CC"
fi

"$SEED" build --cc "$SEED_CC" "$PROJECT" \
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
