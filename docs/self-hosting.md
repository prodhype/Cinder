# Self-hosting

## Current status

Python 3.14 remains Cinder's stage0 compiler implementation. The native compiler
lives in `compiler_selfhost/` as a Cinder project. GitHub Actions bootstraps that
project to gen3 and publishes platform artifacts. Those gen3 binaries do not need
Python at run time.

The owned `String` type supplies the text ownership the compiler needs: retain
source text, construct identifiers and diagnostics, and pass text across module
and C-toolchain boundaries without manually managed `const char*` buffers.
Move-only UTF-8 String values, explicit cloning, byte lengths, checked
UTF-8-boundary slicing, and incremental `StringBuilder` construction establish
that base.

## Bootstrap chain

Stage0 builds gen1. Gen1 builds gen2. Gen2 builds gen3.

```sh
mkdir -p build/bootstrap
cinder build compiler_selfhost \
  -o build/bootstrap/cinder-gen1 \
  --build-dir build/gen1
./build/bootstrap/cinder-gen1 build compiler_selfhost \
  -o build/bootstrap/cinder-gen2 \
  --build-dir build/gen2
./build/bootstrap/cinder-gen2 build compiler_selfhost \
  -o build/bootstrap/cinder-gen3 \
  --build-dir build/gen3
```

## What exists

`compiler_selfhost/src/` contains the Cinder implementation of the compiler
pipeline: lexer, parser, checker, typed IR and C11 code generation, plus project
and toolchain support. That tree is what the bootstrap commands above compile.

## Ownership constraints that still apply

Self-hosting still operates under ownership limits beyond the String foundation.
Owning union and variant payloads are currently unsupported. Payload bindings
from owning `Option` and `Result` matches may be inspected or borrowed but cannot
currently be transferred out of the binding.

The self-hosted compiler works within those rules. AST-shaped ownership keeps
values in arena lists and puts non-owning IDs or ranges in union and variant
payloads; see `examples/ast_arena.ci` and [`docs/language-design.md`](language-design.md).
Later work may lift the restrictions or keep designs that respect them. Neither
change is required for the current bootstrap.
