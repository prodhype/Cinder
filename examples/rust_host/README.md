# rust_host — Cinder as a Rust FFI library

Rust is the host. Cinder supplies `@export` functions with a C ABI. The host
declares those symbols with `extern "C"` and links the compiled C objects — the
same pattern as calling Cinder from Go (cgo) or C++.

Inside those exports, Cinder uses **`@reflect` runtime metadata** and
**`comptime fields_of` unrolling** to inspect a `Vec3` layout and compute a
schema fingerprint. That reflection story is what Rust does not provide in the
language itself (you need proc-macros or an external crate).

This example is manual; it is not part of the gen3 smoke suite.

## Layout

```text
lib.ci              # @export C-ABI surface (no main)
host/src/main.rs    # extern "C" caller
host/build.rs       # link prebuilt Cinder objects
host/Cargo.toml
build.sh            # emit → compile → cargo run
```

## Prerequisites

- `cinder` on `PATH`, or this repo importable via `PYTHONPATH` (the script falls back to `python3 -m cinder`)
- A C toolchain (`cc`)
- Rust with `cargo` (edition 2021). If you use rustup, ensure `~/.cargo/bin` is on
  `PATH` (`source "$HOME/.cargo/env"`), or rely on `build.sh`, which adds that
  directory when `cargo` is installed there but missing from `PATH`.

## Build and run

```sh
./build.sh
```

Expected output (each Cinder export that prints is flushed before Rust’s
`println`, so field lines appear before `schema_fingerprint`):

```text
built .../examples/rust_host/build/cargo/debug/rust_host
field_count=3
runtime field: x (i32)
runtime field: y (i32)
runtime field: z (i32)
schema_fingerprint=24
```

The fingerprint is `sum(offset + size)` over the three `i32` fields
(`0+4 + 4+4 + 8+4 = 24`) produced by a compile-time `fields_of` loop.

What the script does:

1. `cinder emit-project lib.ci -o generated`
2. Compile `generated/cinder_gen/lib.c` and `cinder/runtime/cinder_runtime.c` to objects under `build/`
3. `cargo build` the Rust host (build.rs links `build/lib.o` and `build/cinder_runtime.o`)
4. Run the binary

## Why not in Rust?

- **Runtime reflection** — Cinder `@reflect` emits `CinderTypeInfo` metadata;
  `type_info` / `fields` iterate names and types at runtime. Rust has no
  built-in equivalent; you reach for `#[derive]` crates or hand-maintained tables.
- **Compile-time field loops** — `for field in comptime fields_of(Vec3)` unrolls
  into ordinary C with layout literals. Rust has no language-level
  `fields_of`; the usual substitute is a proc-macro.
- **Flat FFI** — Rust only sees `i32` arguments and results. Reflection,
  `static_assert` schema checks, and the fingerprint stay inside Cinder.

## FFI notes

- Export only C primitives (`i32`, `f64`, `const char*`, opaque pointers, …).
  Do not put `String`, `List`, `Map`, or other Cinder runtime layouts on the
  public C API unless the host understands those layouts.
- Link `cinder_runtime.c` with the host. Lists, `print`, and reflection
  metadata helpers need runtime symbols.
- Cinder does not yet ship a shared-library build mode; the foreign host owns
  linking after `emit-project`.
- No bindgen: the surface is two `extern "C"` functions declared by hand so the
  flat ABI lesson stays obvious.
