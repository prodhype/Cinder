# Native test suite

Run the complete suite from the repository root:

```sh
./test.sh
```

The test path has no Python dependency. `test.sh` verifies the seed checksum,
bootstraps gen1 and gen2, checks their generated-C fixed point, compiles the
generated compiler C directly, runs both native generations without an external
language runtime, builds the Cinder test runner, and executes the smoke suite.

## Behavioral coverage

`native/src/main.ci` exercises the public compiler interface:

- valid and invalid `check` operations and rich source diagnostics, including
  stable codes, symbolic names, typed message values, and related spans
- self-contained and deterministic `emit-c` output
- per-module headers and sources from `emit-project`
- native `build`/`run` behavior
- multi-module loading and linking
- C11 atomic lowering
- `std.net` native lowering, diagnostics, local-module shadowing, and TCP
  loopback behavior including polling, nonblocking errors, bytes, and EOF
- deterministic `context` capsules and invalid-location diagnostics
- `impact` consumers, module dependents, reflection, and ABI exposure
- canonical `semantic-diff` output from an isolated temporary Git repository

`scripts/run-smoke.sh` builds and runs every top-level Cinder example plus the
class, module, and path-shadow projects. It supplies input to the three
interactive examples and checks the intentional nonzero exits from
`generics.ci` and `owned.ci`.

The former pytest suite also asserted private Python stage0 AST, semantic-model,
IR, and type object shapes. Those assertions were implementation-specific and
were intentionally removed with stage0. Observable behavior remains covered
through the native compiler CLI, generated C, native program results, bootstrap
proofs, and example corpus.
