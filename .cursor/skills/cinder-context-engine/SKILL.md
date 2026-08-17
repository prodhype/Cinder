---
name: cinder-context-engine
description: Uses Cinder's compiler-derived context, impact, and semantic-diff commands to select exact program context and assess semantic changes. Apply automatically when inspecting, modifying, debugging, or reviewing Cinder .ci source code.
---

# Cinder Context Engine

Use compiler facts before reasoning about non-trivial Cinder source changes. These commands complement source inspection and tests; they do not replace them.

## Compiler command

Prefer the repository compiler:

```sh
./.cinder/bootstrap/cinder-gen2
```

If it is unavailable, use `cinder` from `PATH`. Pass the project explicitly when the current directory is not its root.

## Required workflow

### 1. Select context before editing

For every target declaration, run:

```sh
./.cinder/bootstrap/cinder-gen2 context path/to/file.ci:LINE --depth 1
```

- Start at depth 1.
- Increase depth only when transitive calls, callers, types, or locks matter.
- Use depth 0 for a declaration-only question.
- Treat stable symbol keys as identities; do not substitute filename or text matching when the compiler provides a resolved edge.

Read the target source and any dependencies named by the capsule. Do not dump unrelated files into context.

### 2. Check impact before risky changes

Run `impact` before changing a signature, type/layout, ownership, call edge, lock acquisition/order, reflected declaration, export, extern boundary, or widely used symbol:

```sh
./.cinder/bootstrap/cinder-gen2 impact path/to/file.ci:LINE
```

Inspect direct and indirect callers, type/member consumers, module dependents, lock impact, and ABI/reflection exposure before deciding the edit scope.

### 3. Validate after editing

Run the normal project check and relevant tests. For semantic Cinder changes, also run:

```sh
./.cinder/bootstrap/cinder-gen2 semantic-diff HEAD --project path/to/project
```

Review every added, removed, and changed symbol or relation. Confirm ownership, ABI, reflection, locking, and reachable-caller changes are intended.

## Evidence rules

- Report compiler facts as facts.
- Treat `unknown` and unresolved edges as limits, never as proof of absence.
- Never invent allocation effects, thread/core affinity, physical ABI offsets, dynamic targets, or control-flow guarantees that the report does not provide.
- If analysis fails because the project is invalid, run `check`, diagnose the compiler error, and state that semantic context is incomplete.
- If a historical Git ref cannot compile under the current compiler, report that limitation; do not silently replace semantic-diff with a textual diff.
- Re-run `context` or `impact` after edits when symbol identity, line location, or graph relationships changed.

## Proportional use

- Documentation-only and non-Cinder changes do not require these commands.
- Small local edits need target context plus normal validation.
- Cross-module, ownership, locking, reflection, ABI, or public API edits require the full context → impact → semantic-diff workflow.
