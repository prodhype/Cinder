# Changelog

## Unreleased

Cinder adds native heterogeneous `Tuple[...]` values and homogeneous growable `List[T]` buffers. Tuple literals use parenthesized comma syntax and support compile-time-checked indexing. Square-bracket literals now infer lists in untyped contexts while explicit fixed-array annotations preserve fixed C storage.

Lists provide deterministic move-only ownership, direct return transfer, indexing, iteration, `len`, `sort`, `append`, `pop`, and `clear`. Addressable Lists can also borrow as `[]T` or `[]const T` function arguments without copying, so slice-based APIs work across Lists, fixed arrays, and slices. The compiler emits readable per-element C specializations and uses a checked runtime growth helper. Cross-module generated headers share guarded tuple/list layouts and helpers.

Maps and Sets extend the native collection phase with specialized deterministic hash tables, brace literals, membership, insertion-ordered Map iteration, live `keys`/`values`/`items` views, optional lookup/removal, and Set algebra. Integer, boolean, character, enum, and `const char*` keys are hashable. String keys use content equality and are copied into the owning collection.

The release also adds general `Option[T]` values with `Some`, contextual `None`, exhaustive matching, state attributes, and checked payload access. Maps and Sets follow Lists' move-only ownership model, including direct return transfer, cleanup on all exits, and mutation guards during active iteration.

Aggregate ownership is now first-class for `List`/`Map`/`Set`/`File` and destructor-bearing classes: struct/class by-value owning fields, nested owning collections and owning elements, by-value owning parameters with use-after-move diagnostics, and `Option`/`Result`/`Tuple`(/array) drop glue. Owning globals and unions/user variants with owning members remain rejected.

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
