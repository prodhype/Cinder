#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$ROOT/../.." && pwd)"
cd "$ROOT"

if ! command -v cinder >/dev/null 2>&1; then
  if PYTHONPATH="$REPO_ROOT" python3 -c "import cinder.cli" >/dev/null 2>&1; then
    cinder() {
      PYTHONPATH="$REPO_ROOT" python3 -m cinder "$@"
    }
  else
    echo "error: cinder not found on PATH (and PYTHONPATH=$REPO_ROOT cannot import cinder)" >&2
    exit 1
  fi
fi

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
cinder emit-project lib.ci -o generated
cc -std=c11 -O2 -Wall -Wextra -Wpedantic \
  -I"$REPO_ROOT/cinder/runtime" \
  -I"$ROOT/generated" \
  -c "$ROOT/generated/cinder_gen/lib.c" \
  -o "$ROOT/build/lib.o"
cc -std=c11 -O2 -Wall -Wextra -Wpedantic \
  -I"$REPO_ROOT/cinder/runtime" \
  -c "$REPO_ROOT/cinder/runtime/cinder_runtime.c" \
  -o "$ROOT/build/cinder_runtime.o"

case "$(uname -s)" in
  Darwin) LIB_EXT=dylib ;;
  *) LIB_EXT=so ;;
esac
LIB="$ROOT/build/libcinder_python_host.$LIB_EXT"
cc -shared -O2 -o "$LIB" "$ROOT/build/lib.o" "$ROOT/build/cinder_runtime.o"

echo "built $LIB"
python3 "$ROOT/host/main.py"
