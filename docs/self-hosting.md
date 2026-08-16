# Self-hosting

## Current status

Cinder's compiler implementation lives in `compiler_selfhost/` as a Cinder
project. A checked-in native seed for macOS ARM64 or Linux x86_64 builds gen1,
then gen1 builds gen2 from the same sources. No bootstrap, build, or test step
requires Python.

The owned `String` type supplies the text ownership the compiler needs: retain
source text, construct identifiers and diagnostics, and pass text across module
and C-toolchain boundaries without manually managed `const char*` buffers.
Move-only UTF-8 String values, explicit cloning, byte lengths, checked
UTF-8-boundary slicing, and incremental `StringBuilder` construction establish
that base.

## Bootstrap chain

The seed is a trusted construction artifact, not a second compiler
implementation:

```text
committed seed -> gen1 -> gen2
                   |        |
                   +--------+ exact generated-C tree match
```

From the repository root:

```sh
./bootstrap.sh
```

`bootstrap.sh` selects the host seed, verifies it against
`bootstrap/SHA256SUMS`, writes both generations under
`.cinder/bootstrap/`, and compares `gen1-build/cinder_gen` with
`gen2-build/cinder_gen`. Linked binaries are not compared because system
linkers may add host-specific metadata.

`./test.sh` adds a direct C build of the generated compiler, execution without
an external language runtime, native behavioral tests, and the example smoke
suite.

## What exists

`compiler_selfhost/src/` contains the Cinder implementation of the compiler
pipeline: lexer, parser, checker, typed IR and C11 code generation, plus project
and toolchain support. That tree is what the bootstrap commands above compile.

`bootstrap/` contains the two native seeds, checksums, and exact provenance.
Seeds are replaced only when an existing seed can no longer compile the
canonical compiler sources. See `bootstrap/PROVENANCE.md` for the refresh
procedure.

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
