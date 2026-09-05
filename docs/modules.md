# Modules and project builds

Cinder 0.2 replaces textual inclusion between Cinder source files with a checked module dependency graph. C headers remain available separately through `extern import`.

## Project discovery

Compiler commands accept a `.ci` file, a directory, or a `cinder.toml` path.

When given a manifest, the compiler reads the configured source root and entry file. When given a source file below a manifest, that file becomes the entry while the manifest still supplies the project name and source root. When no manifest exists, the source file's parent directory is the source root and the file is a single-file project.

A directory without a manifest is accepted only when it has exactly one conventional entry: `main.ci` or `src/main.ci`.

## Manifest

```toml
[project]
name = "physics_demo"
source-root = "src"
entry = "app/main.ci"

[native]
include-dirs = ["third_party/sdl2/include"]
library-dirs = ["third_party/sdl2/lib"]
libraries = ["SDL2", "SDL2_mixer"]
link-files = ["third_party/sdl2/lib/libSDL2.a"]
cflags = []
ldflags = []
```

`name` defaults to the project directory name. `source-root` defaults to `src`. `entry` defaults to `main.ci` relative to the source root.

Project names use ASCII letters, digits, `.`, `-`, and `_`, beginning with a letter or digit. Paths are required to remain inside the project root. Only the `[project]` and `[native]` top-level tables are allowed; unknown keys in either table are rejected.

### `[native]` (optional)

Native compile and link inputs for `cinder build` / `cinder run`. Relative paths resolve against the project root (the directory that contains `cinder.toml`). Paths need not exist at manifest-parse time so `cinder check` still works without dependencies installed.

| Key | Meaning |
|-----|---------|
| `include-dirs` | Extra `-I` / MSVC `/I` directories |
| `library-dirs` | Extra `-L` / MSVC `/LIBPATH:` directories |
| `libraries` | Short library names only (no `-l` prefix, no path separators) → `-lname` / `name.lib` |
| `link-files` | Explicit archive or object paths passed as linker inputs (useful for static single-binary builds) |
| `cflags` | Opaque extra compiler flags |
| `ldflags` | Opaque extra linker flags |

Merge order (manifest first, CLI last): automatic project include paths, then `[native]` include dirs / cflags / libraries / library dirs / link-files / ldflags, then CLI `-I` / `--cflag` / `--ldflag`. Semantic libraries from imports such as `math` (`-lm`) are merged with `[native].libraries`.

## Resolution

For a module named `engine.math`, the resolver checks these candidates beneath the source root:

```text
engine/math.ci
engine/math/__init__.ci
```

Exactly one may exist. The source path determines the canonical module name, so one file cannot be reached under two different names.

Compiler-provided modules such as `stdio`, `math`, `stdlib`, `string`, `cinder`, `process`, `std.atomic`, `std.net`, and `std.path` are resolved after local filesystem candidates. A local module can therefore intentionally shadow a built-in module.

## Dependency graph

Imports are discovered from parsed top-level declarations. The loader performs a depth-first traversal and records modules in dependency-first order. A cycle is diagnosed at the import that closes it, including the cycle path.

The checker receives only modules that have already been checked. Imported function signatures, global types, constants, nominal types, opaque C types from `extern "C"`, C includes, and per-module link libraries therefore come from semantic models rather than textual source concatenation. Project-wide native libraries and flags still come from the optional `[native]` table and the CLI.

## Imports

```python
import engine.math
import engine.math as math
from engine.math import Vec3, normalize
from engine.math import length as vector_length
```

An `import` binds a module namespace. Without `as`, a dotted import binds its final component. A `from` import clones the public semantic symbol into the importing module while retaining the original generated C symbol.

All top-level Cinder declarations are module-visible in 0.5. This is distinct from `@export`, which preserves a function name for external C callers.

## Generated files

Each source module produces one header and one C translation unit under `cinder_gen`:

```text
cinder_gen/engine/math.cinder.h
cinder_gen/engine/math.c
cinder_gen/app/main.cinder.h
cinder_gen/app/main.c
```

A generated header includes the generated headers of its direct local dependencies. Internal C names use a readable project/module prefix plus a short deterministic hash to avoid collisions between projects and modules.

Callable declarations are wrapped in C++ linkage guards, and the runtime header is valid in both C11 and C++17 consumers. The generated data layouts remain ordinary C-compatible declarations.

Class-bearing headers also contain complete public class layouts, dynamic interface value and table types, constructor and drop declarations, reflected metadata declarations, and concrete interface-table declarations. Imported classes and interfaces therefore use the same checked ABI across translation units.

Generated files are written through an atomic replacement only when content changes. This keeps timestamps stable for external build tools. Cinder 0.5 still invokes the host compiler for all generated translation units in one command; object-level caching is later work.

## Emission modes

`cinder emit-project` writes the per-module tree used by normal builds:

```sh
cinder emit-project . -o generated
```

`cinder emit-c` writes an amalgamation. It strips generated-header includes, then concatenates generated declarations and implementations in dependency order:

```sh
cinder emit-c . -o project.c
```

The amalgamation is useful for inspection, vendoring, or integration into a surrounding C build. The normal multi-file form is preferable for compiler diagnostics and future incremental object builds.
