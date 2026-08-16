#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPILER="${1:-$ROOT/.cinder/bootstrap/cinder-gen2}"
WORK="$ROOT/.cinder/native-smoke"

if [[ ! -x "$COMPILER" ]]; then
  printf 'error: compiler is missing or not executable: %s\n' "$COMPILER" >&2
  exit 2
fi

rm -rf "$WORK" "$ROOT/.cinder/example-output"
mkdir -p "$WORK"

cleanup_example_outputs() {
  rm -f \
    "$ROOT/aggregate_ownership.log" \
    "$ROOT/aggregate_ownership_a.txt" \
    "$ROOT/aggregate_ownership_b.txt"
  rm -rf "$ROOT/.cinder/example-output"
}
trap cleanup_example_outputs EXIT

targets=("$ROOT"/examples/*.ci)
targets+=(
  "$ROOT/examples/class_project"
  "$ROOT/examples/module_project"
)

if [[ "${#targets[@]}" -ne 41 ]]; then
  printf 'error: expected 41 smoke targets, found %d\n' "${#targets[@]}" >&2
  exit 2
fi

failures=0
index=0
for target in "${targets[@]}"; do
  index=$((index + 1))
  name="$(basename "$target")"
  output="$WORK/$name.bin"
  build_dir="$WORK/$name-build"
  stdout="$WORK/$name.stdout"
  stderr="$WORK/$name.stderr"
  expected=0
  input=""

  case "$name" in
    generics.ci | owned.ci)
      expected=42
      ;;
  esac
  case "$name" in
    input.ci)
      input=$'World\n'
      ;;
    fizzbuzz.ci)
      input=$'15\n'
      ;;
    towers_of_hanoi.ci)
      input=$'3\n'
      ;;
  esac

  if [[ -n "$input" ]]; then
    printf '%s' "$input" |
      "$COMPILER" run "$target" \
        -o "$output" \
        --build-dir "$build_dir" \
        >"$stdout" 2>"$stderr"
    status="${PIPESTATUS[1]}"
  else
    "$COMPILER" run "$target" \
      -o "$output" \
      --build-dir "$build_dir" \
      >"$stdout" 2>"$stderr"
    status=$?
  fi

  if [[ "$status" -eq "$expected" ]]; then
    printf 'PASS [%d/41] %s\n' "$index" "${target#"$ROOT/"}"
  else
    failures=$((failures + 1))
    printf 'FAIL [%d/41] %s (expected %d, got %d)\n' \
      "$index" "${target#"$ROOT/"}" "$expected" "$status" >&2
    if [[ -s "$stderr" ]]; then
      while IFS= read -r line; do
        printf '  %s\n' "$line" >&2
      done <"$stderr"
    fi
  fi
done

printf 'smoke tests: %d passed, %d failed\n' "$((41 - failures))" "$failures"
if [[ "$failures" -ne 0 ]]; then
  exit 1
fi
