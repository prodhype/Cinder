---
name: cinder-context-engine
description: Uses Cinder's authoritative language cookbook and compiler-derived context, impact, and semantic-diff commands to write correct code, select exact program context, and assess semantic changes. Apply automatically when authoring, inspecting, modifying, debugging, or reviewing Cinder .ci source code.
---

# Cinder Context Engine

Use compiler facts before reasoning about non-trivial Cinder source changes. These commands complement source inspection and tests; they do not replace them.

## Language cookbook

Before writing Cinder or broadly searching for syntax, standard APIs, FFI,
ownership, collections, or compiler pitfalls, read the repository-root
`docs/cookbook.md`. Use its focused source links only when the cookbook does not
answer the question or the behavior is version-sensitive. Preserve the
documented language contract when the current checker is more permissive.

## Compiler command

Prefer the repository compiler:

```sh
./.cinder/bootstrap/cinder-gen2
```

If it is unavailable, use `cinder` from `PATH`. Pass the project explicitly when the current directory is not its root.

## Token-disciplined workflow

### 1. Classify the change

- **Local body-only:** no signature, ownership, call edge, lock, type/layout, reflection, export, extern, or public API change.
- **Graph-facing:** any of those surfaces changes, or the symbol is widely used.

Use the graph-facing workflow only when the edit actually crosses one of those surfaces.

### 2. Select context once

For a local edit, run one target query at depth 0 or 1. For a graph-facing edit, run one depth-1 query per primary symbol being changed:

```sh
./.cinder/bootstrap/cinder-gen2 context path/to/file.ci:LINE --depth 1
```

- Use depth 0 when only the declaration is needed.
- Increase beyond depth 1 only when a specific unresolved transitive relationship blocks the task.
- Reuse a prior result while its stable symbol key and source revision are unchanged.
- Do not repeat a query merely because line numbers moved.
- Treat stable symbol keys as identities; do not substitute filename or text matching when the compiler provides a resolved edge.

Read the target source and any dependencies named by the capsule. Do not dump unrelated files into context.

### 3. Check impact only for graph-facing surfaces

For a local body-only edit, skip `impact`. Otherwise, run it once per affected signature, ownership, call, lock, layout, reflection, ABI, export, extern, public API, or widely used surface:

```sh
./.cinder/bootstrap/cinder-gen2 impact path/to/file.ci:LINE
```

Inspect direct and indirect callers, type/member consumers, module dependents, lock impact, and ABI/reflection exposure before deciding the edit scope.

After successful `context` or `impact`, do not grep, search, or read broadly for the same callers or consumers. Search only when unresolved edges are material to the requested change.

### 4. Batch edits, then validate once

Make the coherent patch before validation. Run the normal project check and relevant tests once. For graph-facing changes or tasks that require semantic review, run one final:

```sh
./.cinder/bootstrap/cinder-gen2 semantic-diff HEAD --project path/to/project
```

Review every added, removed, and changed symbol or relation. Confirm ownership, ABI, reflection, locking, and reachable-caller changes are intended.

Repeat a check, test, or semantic query only after a failure, a corrective edit, or a change to stable symbol identity or graph relationships. Batch fixes before rerunning validation.

### 5. Budget escape hatch

These are default budgets, not correctness limits. Exceed them only when an `unknown`, unresolved edge, contradictory result, failed validation, or newly changed semantic relationship directly blocks the task. State the reason before issuing an extra semantic query.

## Evidence rules

- Report compiler facts as facts.
- Treat `unknown` and unresolved edges as limits, never as proof of absence.
- Never invent allocation effects, thread/core affinity, physical ABI offsets, dynamic targets, or control-flow guarantees that the report does not provide.
- If analysis fails because the project is invalid, run `check`, diagnose the compiler error, and state that semantic context is incomplete.
- If a historical Git ref cannot compile under the current compiler, report that limitation; do not silently replace semantic-diff with a textual diff.
- Re-run `context` or `impact` after edits only when stable symbol identity or graph relationships changed and the final semantic diff is insufficient.

## Proportional use

- Documentation-only and non-Cinder changes do not require these commands.
- Small local edits need one target context plus normal validation.
- Graph-facing edits use context → impact → coherent edit → validation → one semantic-diff.
