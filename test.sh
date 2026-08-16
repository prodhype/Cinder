#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_ROOT="${CINDER_BOOTSTRAP_DIR:-$ROOT/.cinder/bootstrap}"
COMPILER="$BOOTSTRAP_ROOT/cinder-gen2"
RUNNER="$ROOT/.cinder/cinder-native-tests"
RUNNER_BUILD="$ROOT/.cinder/native-test-runner-build"

verify_direct_build() {
  local sources=()
  while IFS= read -r source; do
    sources+=("$source")
  done < <(
    find "$BOOTSTRAP_ROOT/gen2-build/cinder_gen" \
      -type f \
      -name '*.c' \
      -print |
    LC_ALL=C sort
  )

  "${CC:-cc}" \
    -std=c11 \
    -w \
    -O2 \
    -I "$ROOT/runtime" \
    -I "$BOOTSTRAP_ROOT/gen2-build" \
    -I "$ROOT/compiler_selfhost/src" \
    "${sources[@]}" \
    "$ROOT/runtime/cinder_runtime.c" \
    -o "$BOOTSTRAP_ROOT/cinder-direct-gen2"

  test -x "$BOOTSTRAP_ROOT/cinder-direct-gen2"
  test ! -e "$BOOTSTRAP_ROOT/gen2-build/cinder_selfhost_replay.c"
  test ! -e "$BOOTSTRAP_ROOT/gen2-build/cinder_selfhost_gen2.c"
  printf '%s\n' "direct generated C build: PASS"
}

verify_path_isolation() {
  local empty_path="$BOOTSTRAP_ROOT/empty-path"
  mkdir -p "$empty_path"

  PATH="$empty_path" \
    "$BOOTSTRAP_ROOT/cinder-gen1" \
    check "$ROOT/examples/hello.ci"
  PATH="$empty_path" \
    "$BOOTSTRAP_ROOT/cinder-gen2" \
    check "$ROOT/examples/hello.ci"
  PATH="$empty_path" \
    "$BOOTSTRAP_ROOT/cinder-direct-gen2" \
    check "$ROOT/examples/hello.ci"

  printf '%s\n' "native execution with an isolated PATH: PASS"
}

cd "$ROOT"

bash "$ROOT/bootstrap.sh"
verify_direct_build
verify_path_isolation

"$COMPILER" build "$ROOT/tests/native" \
  -o "$RUNNER" \
  --build-dir "$RUNNER_BUILD"
"$RUNNER" "$COMPILER" "$ROOT"

bash "$ROOT/scripts/run-smoke.sh" "$COMPILER"

printf '%s\n' "all native tests: PASS"
