#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPILER="${1:-$ROOT/.cinder/bootstrap/cinder-gen2}"
WORK="$ROOT/.cinder/native-smoke"
TIMEOUT_SECONDS="${CINDER_SMOKE_TIMEOUT_SECONDS:-60}"

if [[ ! -x "$COMPILER" ]]; then
  printf 'error: compiler is missing or not executable: %s\n' "$COMPILER" >&2
  exit 2
fi
if [[ ! "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  printf 'error: CINDER_SMOKE_TIMEOUT_SECONDS must be a positive integer\n' >&2
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

run_with_timeout() {
  local timeout_seconds="$1"
  local marker="$2"
  local stdin_file="$3"
  shift 3

  rm -f "$marker"
  "$@" <"$stdin_file" &
  local command_pid=$!

  (
    sleep "$timeout_seconds"
    if kill -0 "$command_pid" 2>/dev/null; then
      : >"$marker"
      printf 'smoke target timed out after %s seconds\n' "$timeout_seconds" >&2
      if command -v pkill >/dev/null 2>&1; then
        pkill -TERM -P "$command_pid" 2>/dev/null || true
      fi
      kill -TERM "$command_pid" 2>/dev/null || true
      sleep 2
      if command -v pkill >/dev/null 2>&1; then
        pkill -KILL -P "$command_pid" 2>/dev/null || true
      fi
      kill -KILL "$command_pid" 2>/dev/null || true
    fi
  ) &
  local timer_pid=$!

  wait "$command_pid"
  local status=$?
  kill "$timer_pid" 2>/dev/null || true
  wait "$timer_pid" 2>/dev/null || true

  if [[ -e "$marker" ]]; then
    return 124
  fi
  return "$status"
}

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
  stdin_file="$WORK/$name.stdin"
  timeout_marker="$WORK/$name.timeout"
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

  printf '%s' "$input" >"$stdin_file"
  run_with_timeout "$TIMEOUT_SECONDS" "$timeout_marker" "$stdin_file" \
    "$COMPILER" run "$target" \
    -o "$output" \
    --build-dir "$build_dir" \
    >"$stdout" 2>"$stderr"
  status=$?

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
