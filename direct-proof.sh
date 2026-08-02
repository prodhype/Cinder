set -euo pipefail

ROOT="$(pwd)"
PROOF="$ROOT/.cinder/selfhost-proof"

SOURCES=()
while IFS= read -r source; do
  SOURCES+=("$source")
done < <(
  find "$PROOF/gen2-build/cinder_gen" \
    -type f \
    -name '*.c' \
    -print |
  LC_ALL=C sort
)

cc \
  -std=c11 \
  -Wall \
  -Wextra \
  -Wpedantic \
  -O2 \
  -I "$ROOT/cinder/runtime" \
  -I "$PROOF/gen2-build" \
  -I "$ROOT/compiler_selfhost/src" \
  "${SOURCES[@]}" \
  "$ROOT/cinder/runtime/cinder_runtime.c" \
  -o "$PROOF/cinder-direct-gen2"

test -x "$PROOF/cinder-direct-gen2"
test ! -e "$PROOF/gen2-build/cinder_selfhost_replay.c"
test ! -e "$PROOF/gen2-build/cinder_selfhost_gen2.c"

printf '%s\n' "direct generated C build: PASS"
