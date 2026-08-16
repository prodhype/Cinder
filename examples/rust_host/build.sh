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

# rustup installs cargo under ~/.cargo/bin; many shells never add that to PATH.
if ! command -v cargo >/dev/null 2>&1; then
  if [[ -x "${CARGO_HOME:-$HOME/.cargo}/bin/cargo" ]]; then
    export PATH="${CARGO_HOME:-$HOME/.cargo}/bin:$PATH"
  fi
fi
command -v cargo >/dev/null 2>&1 || {
  echo "error: cargo (Rust toolchain) is required" >&2
  echo "  install: https://rustup.rs  (then open a new shell, or: source \"\$HOME/.cargo/env\")" >&2
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

# Force cargo to relink when the prebuilt Cinder objects change.
# build.rs links them via rustc-link-arg and declares rerun-if-changed on them.
# --release so the host Leibniz loop is a fair comparison against Cinder -O2.
export CARGO_TARGET_DIR="$ROOT/build/cargo"
cargo build --release --manifest-path "$ROOT/host/Cargo.toml" --quiet
BIN="$CARGO_TARGET_DIR/release/rust_host"
echo "built $BIN"
"$BIN"
