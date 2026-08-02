set -euo pipefail

ROOT="$(pwd)"
PROOF="$ROOT/.cinder/selfhost-proof"
EMPTY_PATH="$PROOF/empty-path"

mkdir -p "$EMPTY_PATH"

PATH="$EMPTY_PATH" \
  "$PROOF/cinder-gen2" \
  check "$ROOT/examples/hello.ci"

PATH="$EMPTY_PATH" \
  "$PROOF/cinder-gen3" \
  check "$ROOT/examples/hello.ci"

PATH="$EMPTY_PATH" \
  "$PROOF/cinder-direct-gen2" \
  check "$ROOT/examples/hello.ci"

printf '%s\n' "native execution without Python: PASS"
