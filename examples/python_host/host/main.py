#!/usr/bin/env python3
"""Load the Cinder shared library and call the flat @export surface."""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
ITERATIONS = 30_000_000

if sys.platform == "darwin":
    LIB_PATH = BUILD / "libcinder_python_host.dylib"
else:
    LIB_PATH = BUILD / "libcinder_python_host.so"

if not LIB_PATH.is_file():
    raise SystemExit(
        f"error: missing {LIB_PATH}\n"
        "  run ./build.sh from examples/python_host first"
    )

lib = ctypes.CDLL(str(LIB_PATH))

lib.cinder_sum.argtypes = [ctypes.c_int32, ctypes.c_int32]
lib.cinder_sum.restype = ctypes.c_int32

lib.cinder_div.argtypes = [ctypes.c_int32, ctypes.c_int32]
lib.cinder_div.restype = ctypes.c_int32

lib.cinder_clamp.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
lib.cinder_clamp.restype = ctypes.c_int32

lib.cinder_leibniz.argtypes = [ctypes.c_int32]
lib.cinder_leibniz.restype = ctypes.c_double

libc = ctypes.CDLL(None)
libc.fflush.argtypes = [ctypes.c_void_p]
libc.fflush.restype = ctypes.c_int


def call(fn, *args: int) -> None:
    # Cinder's destructor / print lines write to libc stdout. Flush so they
    # interleave with Python's print when stdout is redirected or fully buffered.
    value = int(fn(*args))
    libc.fflush(None)
    print(value, flush=True)


def python_leibniz(iterations: int) -> float:
    # Same series as cinder_leibniz / examples/leibniz_pi.ci.
    # CPython will not auto-vectorize this; the Cinder export can.
    pi = 1.0
    for i in range(2, iterations + 2):
        x = -1.0 + 2.0 * (i & 1)
        pi += x / (2 * i - 1)
    return pi * 4.0


def time_call(label: str, fn) -> tuple[float, float]:
    started = time.perf_counter()
    value = float(fn())
    elapsed = time.perf_counter() - started
    print(f"{label}: π ≈ {value:.12f}  ({elapsed * 1000.0:.1f} ms)", flush=True)
    return value, elapsed


def main() -> None:
    call(lib.cinder_sum, 20, 22)
    call(lib.cinder_div, 10, 0)
    call(lib.cinder_clamp, 10, 0, 100)

    print(f"Leibniz π with {ITERATIONS} iterations", flush=True)
    py_value, py_elapsed = time_call("python", lambda: python_leibniz(ITERATIONS))
    ci_value, ci_elapsed = time_call(
        "cinder", lambda: lib.cinder_leibniz(ITERATIONS)
    )
    if abs(py_value - ci_value) > 1e-9:
        raise SystemExit(
            f"error: results diverged: python={py_value!r} cinder={ci_value!r}"
        )
    if ci_elapsed <= 0.0:
        raise SystemExit("error: cinder timing was non-positive")
    speedup = py_elapsed / ci_elapsed
    print(f"speedup: {speedup:.1f}x (python / cinder)", flush=True)


if __name__ == "__main__":
    main()
