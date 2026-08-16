# Changelog

## Unreleased

### Native bootstrap

Cinder now bootstraps from checked-in macOS ARM64 and Linux x86_64 native seeds.
The seed builds gen1, gen1 builds gen2, and bootstrap requires an exact match
between their generated-C trees. The canonical implementation remains the
Cinder source under `compiler_selfhost/`; seed checksums and provenance are
tracked under `bootstrap/`. The Linux x86_64 seed requires glibc 2.34 or newer,
and bootstrap now rejects older or non-glibc hosts before executing it.

The Python stage0 compiler, its packaging, implementation-specific pytest
suite, and incremental parity projects have been removed. Native Cinder tests,
direct generated-C compilation, runtime-independence checks, and the 41-target
example smoke suite now run through `./test.sh`. The C runtime has moved to the
top-level `runtime/` directory.

### Owned UTF-8 text

`String` becomes Cinder's primary text type. Ordinary literals produce move-only UTF-8 Strings with deterministic drop. Their runtime shape is conceptually data, byte length, and capacity; static literals use copy-on-write storage. Independent copies use explicit `clone`, addressable values support `append`, `reserve`, and `clear`, and `+` borrows its operands to return a fresh String.

String length and slicing use byte offsets. `len` reports bytes, direct indexing is unavailable, and `byte_at` makes byte access explicit. A String slice is an owned copy and requires an in-range span whose endpoints are UTF-8 boundaries. Embedded NUL bytes are rejected so FFI borrows preserve the complete text; arbitrary bytes remain `List[u8]`.

`StringBuilder` adds `append`, ASCII `append_char`, and `reserve`, with a consuming `finish` operation that returns String.

String equality, Map/Set hashing and membership, and String sorting use UTF-8 byte content rather than buffer identity.

At an extern or compiler-provided builtin call boundary, String may borrow implicitly as `const char*` for that call only. The pointer cannot be stored, and there is no implicit `const char*`-to-String conversion. Extern declarations continue to expose explicit C ABI types.

`File` source I/O now uses owned text alongside byte input: `read(buffer: []u8) -> usize` fills a mutable byte slice (`0` means EOF), `read_line() -> Option[String]` distinguishes immediate EOF (`None`) from a blank line (`Some("")`), `read_text() -> String` validates UTF-8, and `read_all() -> List[u8]` remains the arbitrary-byte operation. `File.write` accepts either borrowed String text or byte slices. Closed handles, invalid text, I/O errors, and allocation failure follow the existing panic convention.

Cinder's global Result-based conversion helpers borrow String. `parse_i32`, `parse_i64`, `parse_u32`, `parse_u64`, `parse_isize`, `parse_usize`, `parse_f32`, `parse_f64`, and `parse_bool` return `Result[T, ConvertError]` after a full-token parse, with compiler-provided `ConvertError.empty`, `.invalid`, and `.overflow` cases. `input()` and `to_string(value)` return String, so their results use ordinary deterministic drop rather than a manual free protocol. `to_string` supports integers, floats, `bool`, and `char`. `print` and `open` also borrow their String arguments. Print-only f-strings remain unchanged.

### Breaking changes

- Ordinary string literals infer `String`, not `const char*`. An explicit `const char*` context remains available for low-level C interop.
- String is move-only. Implicit copies are rejected; use `clone` when an independent value is required.
- `input` and `to_string` return String. Existing `free(cast[void*](text))` cleanup for those results must be removed.
- Parse helpers, `open`, and text printing consume no ownership and now use String at their language-facing boundaries. Raw `const char*` does not convert back to String implicitly.
- `File.write` additionally accepts borrowed String text. `File.read_line` returns `Option[String]` rather than a nullable owned `const char*`; callers must handle `None` for immediate EOF.
- String collection keys, elements, and sorting use content semantics. Code that depended on C-pointer identity or manual ownership transfer must move to explicit low-level pointer handling.

Cinder adds native heterogeneous `Tuple[...]` values and homogeneous growable `List[T]` buffers. Tuple literals use parenthesized comma syntax and support compile-time-checked indexing. Square-bracket literals now infer lists in untyped contexts while explicit fixed-array annotations preserve fixed C storage.

Lists provide deterministic move-only ownership, direct return transfer, indexing, iteration, `len`, `sort`, `append`, `pop`, and `clear`. Addressable Lists can also borrow as `[]T` or `[]const T` function arguments without copying, so slice-based APIs work across Lists, fixed arrays, and slices. The compiler emits readable per-element C specializations and uses a checked runtime growth helper. Cross-module generated headers share guarded tuple/list layouts and helpers.

Maps and Sets extend the native collection phase with specialized deterministic hash tables, brace literals, membership, insertion-ordered Map iteration, live `keys`/`values`/`items` views, optional lookup/removal, and Set algebra. Integer, boolean, character, enum, String, and low-level `const char*` keys are hashable. String keys use content equality, and insertion clones String keys or elements so later source mutation cannot invalidate membership.

The release also adds general `Option[T]` values with `Some`, contextual `None`, exhaustive matching, state attributes, and checked payload access. Maps and Sets follow Lists' move-only ownership model, including direct return transfer, cleanup on all exits, and mutation guards during active iteration.

Aggregate ownership is now first-class for `List`/`Map`/`Set`/`File` and destructor-bearing classes: struct/class by-value owning fields, nested owning collections and owning elements, by-value owning parameters with use-after-move diagnostics, and `Option`/`Result`/`Tuple`(/array) drop glue. Runtime-initialized owning globals and unions/user variants with owning members remain rejected; a `const` String initialized directly from a static literal is the narrow global exception. AST-shaped data can use arena-owned lists with non-owning IDs or ranges in variant payloads.

`Owned[T]` adds Box-style heap ownership: `Owned(value)` allocates and moves a value onto the heap, unary `*` yields an addressable payload, and drop frees after dropping `T`. Values are move-only, nest in aggregates and `Option`/`List`, and support recursive layouts such as `Option[Owned[Node]]`.

User-defined generics are monomorphized into readable specialized C. Type parameters may appear on `struct`, `class`, `enum`, `union`, `variant`, and free `def`. Instantiations such as `Box[i32]` and `identity[i32]` become named C artifacts (`Box_i32`, `identity_i32`) with ordinary concrete checking after substitution. Type parameters are unconstrained; bodies may use `static_assert` / comptime checks per specialization. Qualified calls to imported generic functions (`mod.identity(...)`) specialize the same way as bare/`from` imports. Cross-module instantiations share defining-module C names with include-guarded layouts and TU-local (`static`) specialized function bodies so duplicate specializations link cleanly.

## 0.5.0

Cinder 0.5.0 adds opt-in runtime reflection and compile-time type inspection.

Types marked `@reflect` emit explicit `CinderTypeInfo`, `CinderFieldInfo`, and `CinderMethodInfo` constants. Runtime operations include concrete and dynamic `type_name`, `type_info`, `fields`, and `methods`. Reflected interface tables identify their concrete runtime type without adding metadata pointers to ordinary objects.

Compile-time operations include `type_of`, `size_of`, `align_of`, `field_count`, `method_count`, `has_field`, `has_method`, `implements`, `fields_of`, and `methods_of`. Top-level `static_assert` evaluates language-level constants in the checker and preserves target-dependent layout expressions for the C compiler. `comptime` field and method loops are unrolled into ordinary C blocks.

The release adds reflection ABI documentation, runtime and compile-time examples, inherited class metadata, cross-module reflected interface tests, generated-header C++17 tests, and a fix for compile-time `type_of` comparisons inside static assertions.

## 0.4.0

Cinder 0.4.0 adds the class and abstract-interface ABI.

Classes support value construction through `__init__`, deterministic cleanup through `__del__`, private fields, one zero-offset implementation base, multiple interface-only abstract bases, `@abstractmethod`, optional signature-checked `@override`, explicit `super().__init__`, direct static dispatch, and explicit `&dyn Interface` or `&const dyn Interface` dispatch.

Concrete objects contain no hidden virtual pointer. A dynamic interface value is an explicit object-and-table pair, and each concrete implementation emits a constant table for every abstract interface it implements. Generated module headers expose complete layouts and interface tables for separate translation units.

Destructor-bearing classes are move-only. The compiler emits reverse-order cleanup on scope exit, return, loop control, and Result propagation; transfers ownership on return; drops replaced values after evaluating their replacements; destroys discarded class temporaries; and runs derived destructors before implementation-base destructors. Unsupported copies and aggregate ownership produce source diagnostics.

The release adds layout, receiver-adjustment, constructor-order, destructor-order, multiple-interface, cross-module ABI, GCC, Clang, and C++ header coverage.

## 0.3.0

Cinder 0.3.0 adds deterministic manifest-driven projects, local module resolution, dependency sorting and cycle diagnostics, generated per-module headers and C11 translation units, stable module symbol prefixes, incremental content-stable emission, C++-compatible generated headers, and the `emit-project` command.

The language adds C-compatible enums and unions, explicit tagged variants, exhaustive `match`, typed `Result[T, E]`, contextual `Ok` and `Err` constructors, Result payload access, and `?` propagation with deferred-cleanup preservation.

## 0.1.0

Initial procedural compiler milestone with indentation-aware syntax, static types, functions, native control flow, structs and methods, pointers and references, arrays and slices, C interoperability, allocation, scoped `defer`, readable C11 generation, and GCC, Clang, and MSVC toolchain support.
