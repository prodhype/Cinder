#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$ROOT/../.." && pwd)"
cd "$ROOT"

CINDER="${CINDER:-cinder}"
command -v "$CINDER" >/dev/null 2>&1 || {
  echo "error: Cinder compiler not found: $CINDER" >&2
  exit 1
}

command -v cc >/dev/null 2>&1 || {
  echo "error: cc (C toolchain) is required" >&2
  exit 1
}
command -v python3 >/dev/null 2>&1 || {
  echo "error: python3 is required" >&2
  exit 1
}

mkdir -p build generated

# -O2 so the Leibniz timing demo reflects optimized native code, not -O0.
# -fPIC is required on x86_64 Linux when linking these objects into a .so.
"$CINDER" emit-project lib.ci -o generated
cc -std=c11 -O2 -fPIC -Wall -Wextra -Wpedantic \
  -I"$REPO_ROOT/runtime" \
  -I"$ROOT/generated" \
  -c "$ROOT/generated/cinder_gen/lib.c" \
  -o "$ROOT/build/lib.o"
cc -std=c11 -O2 -fPIC -Wall -Wextra -Wpedantic \
  -I"$REPO_ROOT/runtime" \
  -c "$REPO_ROOT/runtime/cinder_runtime.c" \
  -o "$ROOT/build/cinder_runtime.o"

case "$(uname -s)" in
  Darwin) LIB_EXT=dylib ;;
  *) LIB_EXT=so ;;
esac
LIB="$ROOT/build/libcinder_python_host.$LIB_EXT"
cc -shared -O2 -o "$LIB" "$ROOT/build/lib.o" "$ROOT/build/cinder_runtime.o"

echo "built $LIB"
python3 "$ROOT/host/main.py"
