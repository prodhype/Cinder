# Compiler semantic context

Cinder can describe the compiler-known part of a program around a source
location. These commands query the same parsed project, symbol tables, resolved
types, call bindings, ownership classifications, module graph, reflection
decorators, and lock model used by normal compilation. They do not invoke an
LLM and do not infer missing relationships.

## Context capsules

```sh
cinder context src/cache.ci:118
cinder context src/cache.ci:118 --depth 3
```

The target file determines the project: Cinder searches its parent directories
for `cinder.toml`, loads the manifest entry and all reachable modules, and then
selects the smallest semantic declaration containing the requested one-based
line. Files outside that project graph, ambiguous paths, invalid lines, and
projects that do not pass semantic checking are errors.

`--depth` is a semantic graph hop limit, not a source-file recursion limit:

- depth 0 reports only the target and its compiler facts
- depth 1, the default, includes immediate dependencies, calls, and callers
- larger values follow resolved edges transitively with cycle detection

Output is deterministic for a fixed project. The capsule contains the target
signature and stable key, semantic properties, dependencies, calls, callers,
lock order, ownership-use counts, and the target declaration's source. Related
declarations are represented by stable keys instead of copied source bodies.

## Impact reports

```sh
cinder impact src/cache.ci:118
```

An impact report groups the known blast radius of the selected declaration:

- direct and transitive static callers
- type, member, and value consumers
- reverse module dependencies
- lock acquisition and ordering relationships
- C export/extern and runtime-reflection exposure

Direct, transitive, and unresolved edges remain distinguishable. A dynamic call
or function value is not assigned a target unless the checker resolves it.
`impact` reports potential consumers; it does not claim that every possible
edit changes every listed consumer.

## Semantic diffs

```sh
cinder semantic-diff HEAD
cinder semantic-diff main --project path/to/project
```

The command compares the working project with the same repository-relative
project at a Git ref. It creates a detached temporary Git worktree, analyzes
the reference with the current compiler into an owned compact snapshot, and
removes the worktree. It then analyzes the working tree and compares the two
snapshots. It never checks out, resets, or modifies the user's index or working
tree.

The report covers added, removed, and changed declarations; canonical
signatures and function implementations; semantic types; private field and
abstract/override method modifiers; ownership classifications; source-level
nominal layout, including ordered struct, class, and union fields, enum members,
variant cases, and reflected struct/class methods; inheritance and interfaces;
calls and callers; lock effects and order; reflection; and C exports/externs.
Declaration signatures and function bodies are compared from parsed syntax
without source positions or whitespace, so formatting-only edits do not count
as semantic changes. Generated C and raw per-run symbol/type IDs are not
diffed.

The referenced source must parse and type-check with the current compiler. This
keeps both sides on one semantic schema. If a historical revision uses
incompatible language syntax, Cinder reports that failure instead of falling
back to a text diff.

## Stable identity and output

Facts use a key composed from module, owner path, symbol kind, and name. This
avoids exposing transient `SymbolId`, `TypeId`, or AST indexes. Collection
follows deterministic module and source order, and duplicate edges are removed.
The first output schema is identified as `cinder-semantic-v1`.

The query model is currently in memory. There is no semantic cache or database;
each command performs a normal project analysis. `semantic-diff` analyzes its
two sides sequentially and drops each parsed project and retained checker set
after producing its compact snapshot. Fact maps and relation sets accelerate
comparison without changing report order or schema.

## Current limits

Cinder prints `unknown` rather than fabricating a fact when the compiler lacks
a model. In particular:

- imported nominal types whose ownership cannot be classified locally are
  unknown
- indirect and dynamic calls can remain unresolved
- transitive caller search in `impact` is capped at 64 hops; reports that reach
  the cap explicitly say that additional callers may exist
- allocation, IO, and exception effects do not have a general effect model
- thread and core affinity are not language concepts yet
- physical size, alignment, and field offsets are finalized by the target C
  compiler and are not retained in the semantic graph
- control-flow graphs and reachability guarantees are not retained

Lock effects and canonical lock order are available from the project lock
model. Copy, move, borrow, and address uses are recorded at checker transfer
sites. `@reflect`, `@export`, and `extern` exposure are explicit facts.

As Cinder gains additional explicit semantic models, those facts can extend
all three commands without adding AI-specific language constructs.
