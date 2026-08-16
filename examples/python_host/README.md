# python_host — Cinder as a Python ctypes library

Python is the host. Cinder supplies `@export` functions with a C ABI. The host
loads a small shared library built from the generated C and calls it with
ctypes — the same flat-ABI pattern as calling Cinder from Go (cgo) or Rust.

Inside those exports, Cinder owns a **Session** (with a nested audit `List`),
dispatches an exhaustive **`variant Request`**, and returns via **`Result`/`?`**.
When the export returns — including on error paths — the session drops
deterministically. That ownership and exhaustiveness story is what Python does
not check.

A separate export runs the same **Leibniz π** loop as `examples/leibniz_pi.ci`.
The host times that native `-O2` loop against an equivalent pure-Python
implementation — CPython interprets the series; Cinder runs the same algorithm
as compiled C.

This example is manual; it is not part of the native smoke suite.

## Layout

```text
lib.ci           # @export C-ABI surface (no main)
host/main.py     # ctypes caller + timing (stdlib only)
build.sh         # emit → compile -O2 → shared lib → run
```

## Prerequisites

- `cinder` on `PATH`, or set `CINDER` to a native compiler path
- A C toolchain (`cc`)
- Python 3 with the standard library (`ctypes`)

## Build and run

```sh
./build.sh
```

Expected output (each request export drops its `Session` before returning, then
the host times Leibniz π). Milliseconds and speedup vary by machine; the shape
should match:

```text
built .../examples/python_host/build/libcinder_python_host.dylib
cinder drop Session(1)
42
cinder drop Session(2)
-1
cinder drop Session(3)
10
Leibniz π with 30000000 iterations
python: π ≈ 3.141592686923  (1552.6 ms)
cinder: π ≈ 3.141592686923  (16.1 ms)
speedup: 96.2x (python / cinder)
```

On Linux the shared library ends in `.so` instead of `.dylib`.

What the script does:

1. `cinder emit-project lib.ci -o generated`
2. Compile `generated/cinder_gen/lib.c` and `runtime/cinder_runtime.c` to objects under `build/` with `-O2`
3. Link `build/libcinder_python_host.{dylib,so}` from those objects
4. Run `python3 host/main.py`

## Why not in Python?

- **Runtime speed** — the same Leibniz series in Cinder (readable C11, `-O2`)
  finishes roughly two orders of magnitude sooner than the pure-Python loop in
  this example. Keep orchestration in Python; move hot loops behind `@export`.
- **Deterministic drop** — Cinder runs `Session.__del__` when the local leaves
  scope, including after `Err` paths. Python `__del__` is tied to the GC and is
  not prompt or reliable; you reach for `try`/`finally` or a context manager and
  must remember to use them.
- **Exhaustiveness** — Cinder `match` on `variant Request` must cover every
  case. A Python `match` on a `Union` of dataclasses will not fail the build
  when a new request kind is added.
- **Typed `Result`** — Errors are `Err` codes with `?` propagation, not
  exceptions that can escape an unchecked call site.
- **GIL** — ctypes releases the GIL for the duration of the C call, so the
  native Leibniz body does not hold the interpreter lock.

## FFI notes

- Export only C primitives (`i32`, `f64`, `const char*`, opaque pointers, …).
  Do not put `String`, `List`, `Map`, or other Cinder runtime layouts on the
  public C API unless the host understands those layouts.
- Link `cinder_runtime.c` with the host. Lists, `print`, and range checks need
  runtime symbols.
- Cinder does not yet ship a shared-library build mode; this script builds one
  locally after `emit-project` so ctypes can load it.
- No third-party packages: the host uses stdlib `ctypes` only.
- `build.sh` passes `-O2` so the timing demo measures optimized native code.
