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
command -v go >/dev/null 2>&1 || {
  echo "error: go is required" >&2
  exit 1
}

mkdir -p build generated

# -O2 so the Leibniz timing demo reflects optimized native code, not -O0.
"$CINDER" emit-project lib.ci -o generated
cc -std=c11 -O2 -Wall -Wextra -Wpedantic \
  -I"$REPO_ROOT/runtime" \
  -I"$ROOT/generated" \
  -c "$ROOT/generated/cinder_gen/lib.c" \
  -o "$ROOT/build/lib.o"
cc -std=c11 -O2 -Wall -Wextra -Wpedantic \
  -I"$REPO_ROOT/runtime" \
  -c "$REPO_ROOT/runtime/cinder_runtime.c" \
  -o "$ROOT/build/cinder_runtime.o"

(
  # Force cgo to relink the rebuilt Cinder objects.
  # When lib.ci or the runtime changes after an initial build, this command can
  # reuse the cached cgo package because the objects referenced only through
  # #cgo LDFLAGS are not included in its cache invalidation; rerunning the
  # script then executes the old Cinder implementation even though both .o
  # files were rebuilt. go help cache explicitly states that the build cache
  # does not detect changes to C libraries imported with cgo and recommends
  # cleaning the cache or using go build -a, so force a rebuild here.
  cd host
  go build -a -o "$ROOT/build/go_host" .
)

echo "built $ROOT/build/go_host"
"$ROOT/build/go_host"
