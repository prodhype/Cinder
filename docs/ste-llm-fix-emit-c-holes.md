# LLM task: Fix Cinder emit-c holes

**Language:** ASD-STE100 (Simplified Technical English).  
**Audience:** An LLM that changes the Cinder compiler.  
**Scope:** Fix the three verified holes and the related document errors. Do not change other features.

## 1. Purpose

Cinder must emit C11 that compiles.  
Cinder must keep move-only drop rules.  
These holes break those rules. You must remove the holes.

## 2. Words and names

Use these names only:

| Name | Meaning |
|---|---|
| Hole A1 | Unsafe cast of an aggregate type emits illegal C |
| Hole A2 | `type_key` gives one key to two different types |
| Hole B1 | A match binding moves an owning payload, then the parent drops the same value |
| Checker | Code in `cinder/checker.py` |
| Codegen | Code in `cinder/codegen_c.py` |
| Type key | String from `type_key()` in `cinder/types.py` |

Do not use synonyms for these names in this task.

## 3. Facts

### 3.1 Hole A1

The Checker permits a cast to or from a struct, class, union, variant, `Result`, or `File` in an `unsafe` block.  
Codegen always writes `((T)(expr))`.  
C11 does not permit that cast for an aggregate type.  
`cinder check` and `cinder emit-c` succeed. The C compiler fails.

Primary code:

- `cinder/checker.py` — function `_check_cast`
- `cinder/codegen_c.py` — case `ast.CastExpr`

### 3.2 Hole A2

`type_key(*i32)` is `"ptr_i32"`.  
`type_key` for a user type named `ptr_i32` is also `"ptr_i32"` when the type has no module prefix.  
Generic specializations and List helpers then share one C name.  
Module prefixes can hide the hole. The hole remains in unprefixed `Compiler.compile_source`.

Primary code:

- `cinder/types.py` — function `type_key`
- `cinder/generics.py` — function `specialization_suffix`
- List and Map helper names that use `type_key`

### 3.3 Hole B1

Match Codegen copies the subject.  
Match Codegen then copies the payload into a const binding.  
The Checker treats that binding as transferable.  
A return or assignment of the binding moves the header.  
The parent `Option` or `Result` still drops.  
This causes a double-free or a double `__del__`.  
`return o.value` is rejected with code C263.  
`return v` from `case Some(v)` is accepted. That difference is an error.

Primary code:

- `cinder/codegen_c.py` — `_emit_match`, `_emit_match_bindings`
- `cinder/checker.py` — `_is_transferable_drop_local` and match binding setup

### 3.4 Document errors

These statements do not match the code:

1. The README says `match` is only for enums, variants, and Results. The Checker also accepts `Option`. The README also shows an `Option` match.
2. The C298 note says Map values must be trivially copyable and non-owning. Owning Map values are supported.
3. Design text says all three collections hold destructor-bearing values. Set elements must be hashable scalars or `const char*` only.
4. Move-only text says implicit copies are rejected. Hole B1 copies owning payloads.

## 4. Required end state

After your change:

1. Hole A1 programs must fail in the Checker. They must not reach Codegen.
2. Hole A2 programs must emit distinct C names for `*i32` and a user type named `ptr_i32`, with or without a module prefix.
3. Hole B1 programs must not double-drop. Prefer a Checker reject that matches C263, unless you implement a true move-out of the parent and you clear the parent tag before drop.
4. Document text in Section 3.4 must match the code.
5. Existing tests must pass.
6. New tests must cover A1, A2, and B1.

## 5. Procedure

Do the steps in this order.

### Step 1 — Read the code

1. Read `_check_cast` in `cinder/checker.py`.
2. Read the `CastExpr` emit path in `cinder/codegen_c.py`.
3. Read `type_key` in `cinder/types.py`.
4. Read `_emit_match` and `_emit_match_bindings` in `cinder/codegen_c.py`.
5. Read `_is_transferable_drop_local` in `cinder/checker.py`.
6. Read the repro files in `.scratch/repros/` if they exist.

### Step 2 — Fix Hole A1

1. In `_check_cast`, reject casts to or from these types: struct, class, union, variant, `Result`, `File`, and other aggregate or tagged wrapper types that Codegen cannot cast in C.
2. Keep the current rejects for arrays, slices, references, tuples, collections, `Option`, `Owned`, and void.
3. Keep safe numeric, enum-integer, pointer, and bool casts as they are.
4. Keep `unsafe` only for casts that emit valid C (for example pointer and integer reinterpret casts).
5. Do not teach Codegen to use `memcpy` for this task unless the language design document already requires that feature. Prefer a Checker reject.
6. Add a Checker test that uses the A1 program. The test must expect a diagnostic.
7. Run the A1 program through `cinder check`. The check must fail.

### Step 3 — Fix Hole A2

1. Change `type_key` so that constructed types and nominal types cannot share a key.
2. Use a stable kind prefix for pointers, references, arrays, slices, and other constructed forms. Example: keep `ptr_` for pointers, and do not let a nominal name alone equal that form.
3. If a nominal name can still clash with a constructed key, add a nominal marker (for example `n_` or `ty_`) for user types, or escape the constructed forms so they cannot equal a sanitized user name.
4. Update all C helper names that use `type_key` so they stay unique.
5. Add tests for:
   - `struct ptr_i32` with `id[ptr_i32]` and `id[*i32]`
   - `List[ptr_i32]` with `List[*i32]`
   - the same cases through unprefixed `Compiler.compile_source`
6. Emit C for those programs. The C must compile with the Cinder runtime.

### Step 4 — Fix Hole B1

Choose one method. Use Method A unless Method B is already started in the code.

**Method A (Checker reject) — preferred for this task**

1. Treat a match payload binding of a drop-bearing type as non-transferable.
2. Reject return, assignment, or call that moves that binding, with the same rule family as C263.
3. Permit read of fields or temporary use that does not move ownership, if the current type rules allow that for other const drop values.
4. Add tests that reject:
   - `return v` from `case Some(v)` when `v` needs drop
   - assignment of `v` into another owning local
   - the same patterns for `Result`, `Owned`, and a class with `__del__`
5. Add a test that still permits match on non-owning payloads.

**Method B (true move-out) — only if you can complete it fully**

1. When the binding is moved, remove ownership from the parent subject.
2. Clear or rewrite the parent tag so parent drop does not free the payload.
3. Do not leave a bitwise copy that shares a heap buffer.
4. Add runtime tests that run the former crash programs and exit with code 0.
5. Show one `__del__` call for one logical class value.

Do not ship a partial Method B.

### Step 5 — Fix the documents

1. In `README.md`, state that `match` accepts enums, variants, `Result`, and `Option`.
2. Remove or rewrite the sentence that limits `match` to enums, variants, and Results only.
3. In the Checker C298 note, remove “trivially copyable non-owning values”. Write a note that matches `_is_valid_container_element` and owning Map value rules.
4. In `docs/language-design.md`, do not say that Sets hold destructor-bearing values. Limit that claim to List elements and Map values.
5. Where move-only text exists, do not claim that match bindings of owning `Option` or `Result` payloads are safe to move unless Method B is complete.

### Step 6 — Verify

1. Run the unit tests for the project.
2. Run `cinder check` on each A1 and B1 reject case.
3. Run emit and C compile on each A2 case with unprefixed compile and with CLI emit-c.
4. If Method A is used, confirm the old B1 crash programs now fail in the Checker.
5. If Method B is used, run the old B1 crash programs and confirm a clean exit.
6. Confirm no new diagnostic text contradicts Section 4.

## 6. Constraints

1. You must not widen unsafe casts.
2. You must not remove move-only checks for `.value` on owning `Option` payloads.
3. You must not change intentional C hazards: untagged unions, missing bounds checks, dangling slices, unchecked `Result.value` / `Result.error`, or trusted FFI.
4. You must not edit the plan file for the audit.
5. You must keep generated C readable.
6. You must add tests near the existing Checker and integration tests.

## 7. Acceptance checks

The task is complete only when all items are true:

- [ ] A1: aggregate unsafe cast is a Checker error
- [ ] A2: `ptr_i32` struct and `*i32` never share one helper or specialization name
- [ ] B1: no double-free path through match bindings of owning payloads
- [ ] Documents in Section 3.4 match the code
- [ ] New tests fail on the old broken behavior and pass on the fix
- [ ] Full test suite passes

## 8. Report format

When you finish, write a short report with:

1. The method you used for Hole B1 (A or B).
2. The files you changed.
3. The new tests you added.
4. The commands you ran and their results.

Use short sentences. State facts. Do not add sales language.
