# go_host — Cinder as a Go cgo library

Go is the host. Cinder supplies `@export` functions with a C ABI. The host
includes the generated header and links the compiled C object — the same pattern
as calling Cinder from C++.

Inside those exports, Cinder builds an **arena-owned expression AST**, evaluates
it with **exhaustive variant matching** and `Result`/`?`, then **drops** the
arena (including a destructor-bearing `Trace`) when the call returns. That
ownership and exhaustiveness story is what Go does not check.

A separate export runs the same **Leibniz π** loop as `examples/leibniz_pi.ci`.
The host times that native `-O2` loop against an equivalent optimized Go
implementation — a fair native-vs-native check (often near parity), not a
CPython-style win.

This example is manual; it is not part of the gen3 smoke suite.

## Layout

```text
lib.ci           # @export C-ABI surface (no main)
host/main.go     # cgo caller + timing
host/go.mod
build.sh         # emit → compile -O2 → go build → run
```

## Prerequisites

- `cinder` on `PATH`, or this repo importable via `PYTHONPATH` (the script falls back to `python3 -m cinder`)
- A C toolchain (`cc`)
- Go 1.22+ with cgo enabled

## Build and run

```sh
./build.sh
```

Expected output (each export drops its arena before returning; destructor lines
and Go’s `Println` results share stdout, then the host times Leibniz π).
Milliseconds and speedup vary by machine; the shape should match:

```text
built .../examples/go_host/build/go_host
42
8
-1
cinder drop Trace(1)
cinder drop Trace(2)
cinder drop Trace(2)
Leibniz π with 1000000000 iterations
go: π ≈ 3.141592654588  (617.2 ms)
cinder: π ≈ 3.141592654588  (534.1 ms)
speedup: 1.2x (go / cinder)
```

What the script does:

1. `cinder emit-project lib.ci -o generated`
2. Compile `generated/cinder_gen/lib.c` and `cinder/runtime/cinder_runtime.c` to objects under `build/` with `-O2`
3. `go build` the cgo host into `build/go_host`
4. Run the binary

## Why not in Go?

- **Runtime speed** — the same Leibniz series in Cinder (readable C11, `-O2`)
  and optimized Go are both native; expect roughly similar times on this loop.
  Keep orchestration in Go; move hot numeric kernels behind `@export` when you
  want Cinder’s ownership and exhaustiveness story in the same binary.
- **Exhaustiveness** — Cinder `match` on `variant ExprKind` must cover every
  case. A Go type-switch on `interface{}` (or even a typed interface) will not
  fail the build when a new node kind is added.
- **Arena ownership** — Nodes live in `List`s; tree edges are small `NodeId`
  handles (owning variant payloads are rejected). When the `@export` returns,
  the arena drops deterministically. Go would use the GC or manual `free`, with
  no move/drop checking at the language level.
- **Flat FFI** — Go only sees `i32` arguments and an `i32`/`f64` result. The
  AST, `Result`, and drop glue stay inside Cinder.

## FFI notes

- Export only C primitives (`i32`, `f64`, `const char*`, opaque pointers, …).
  Do not put `String`, `List`, `Map`, or other Cinder runtime layouts on the
  public C API unless the host understands those layouts.
- Link `cinder_runtime.c` with the host. Lists, `print`, and range checks need
  runtime symbols.
- Cinder does not yet ship a shared-library build mode; the foreign host owns
  linking after `emit-project`.
- `build.sh` passes `-O2` so the timing demo measures optimized native code.
