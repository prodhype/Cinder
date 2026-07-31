# Self-hosting roadmap

## Current status

Python 3.14 remains Cinder's stage0 compiler implementation. There is no self-hosted
Cinder compiler today, and this document describes milestones rather than completed
compiler components.

The owned `String` foundation is a prerequisite for self-hosting. A compiler must
retain source text, construct identifiers and diagnostics, and pass text across
module and C-toolchain boundaries without relying on manually managed `const char*`
buffers. Move-only UTF-8 String values, explicit cloning, byte lengths, checked
UTF-8-boundary slicing, and incremental `StringBuilder` construction establish that
base.

## Milestones

1. **Differential Cinder lexer.** Implement a lexer in Cinder and compare its tokens,
   spans, and diagnostics against the Python stage0 lexer over the same corpus.
2. **Parser, AST, and diagnostics.** Represent syntax and source locations in Cinder,
   then compare accepted programs and error output with stage0.
3. **Checker, IR, and code generation.** Port semantic analysis and the typed
   intermediate representation before producing equivalent readable C11.
4. **Fixed-point bootstrap.** Use stage0 to build a first Cinder compiler, use that
   compiler to build the next stage, and verify the expected fixed point before
   treating the bootstrap as self-hosting.

These milestones are ordered validation gates. They do not imply that a Cinder lexer,
parser, checker, or compiler implementation already exists.

## Current ownership constraints

Self-hosting also depends on ownership features beyond the String foundation.
Owning union and variant payloads are currently unsupported, which prevents a direct
translation of a conventional String-owning token or AST variant. In addition,
payload bindings from owning `Option` and `Result` matches may be inspected or
borrowed but cannot currently be transferred out of the binding.

A future self-hosting design must either lift those restrictions or choose
representations that respect them. The roadmap does not select or claim an
implementation for that work.
