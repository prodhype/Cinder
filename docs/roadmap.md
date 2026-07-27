# Roadmap

## 0.1: Procedural core - complete

The compiler implements a complete pipeline from Cinder source through tokens, AST, symbol resolution, static checking, typed IR, readable C11, and the host C compiler. The procedural language includes structs, methods, pointers, references, arrays, slices, native control flow, C interop, allocation, and scoped cleanup.

## 0.2: Modules and build graph - complete

The compiler resolves local `import` and `from` declarations from one configured source root. It builds an acyclic dependency graph, checks dependencies before importers, and emits one generated header and C translation unit per module. Missing modules, ambiguous file/package modules, and dependency cycles produce source diagnostics.

Projects use a deterministic `cinder.toml` manifest. Generated paths and internal symbol prefixes are stable. Generated files are rewritten only when their contents change. `emit-c` remains available as an amalgamated output path, while `emit-project` and native builds use the normal per-module tree.

Object-file caching and parallel native compilation are not part of 0.2. The current incremental guarantee is content-stable generated source output.

## 0.3: Enums, unions, variants, and results - complete

The compiler implements C-compatible enums, plain unions, tagged variants, exhaustive matching, built-in `Result[T, E]`, contextual `Ok` and `Err` construction, and postfix `?` propagation.

Every representation is explicit in generated C. Variants and results use a tag enum plus a payload union. Matching lowers to ordinary tag comparisons and branches. Propagation lowers to one evaluated temporary, a tag test, deferred cleanup, and an early return. There is no exception runtime or unwinding metadata.

Pattern matching remains intentionally restricted. It does not include nested patterns, guards, alternatives, or literals. `Result[T, E]` was the first compiler-provided generic family.

## 0.4: Classes and explicit interfaces - complete

Cinder implements classes with stack/value construction, one zero-offset implementation base, multiple interface-only abstract bases, abstract-method implementation checks, signature-checked overrides, private fields, constructor chaining, derived-before-base destruction, and move-only lifetime rules for destructor-bearing classes.

Concrete calls use static dispatch. Dynamic dispatch appears only through `&dyn Interface` or `&const dyn Interface`. Each dynamic value contains an explicit object pointer and interface-table pointer; ordinary objects contain no hidden virtual pointer. Separate interface tables support multiple abstract interfaces without changing concrete layout.

Generated module headers expose class layouts, interface value and table types, constructors, drop functions, and table instances. The test suite covers layout, receiver adjustment, dynamic and static calls, multiple interfaces, cleanup on all control-flow exits, destructor order, cross-module linking, and C++ header consumption.

The current ownership model is deliberately narrow. Destructor-bearing classes are move-only locals and return values. Aggregate ownership, copy constructors, move hooks, and automatic heap ownership are later work.

## 0.5: Reflection and compile-time facilities - complete

Runtime reflection is opt-in through `@reflect`. The compiler emits explicit constant field, method, and type records without adding per-object metadata. Reflected dynamic interfaces carry the concrete type-info pointer in their interface table.

The compiler implements `type_of`, `type_name`, `type_info`, `size_of`, `align_of`, `field_count`, `method_count`, `has_field`, `has_method`, `implements`, `fields`, `methods`, `fields_of`, and `methods_of`. Top-level `static_assert` supports both checker-evaluated conditions and target-dependent C layout expressions. `for ... in comptime fields_of(...)` and `methods_of(...)` are unrolled into ordinary C blocks.

Runtime metadata is inspectable in `cinder_runtime.h`, has no startup registration step, and has a measurable binary-size cost. Unreflected concrete types emit no metadata arrays.

## Native collections - Map/Set phase complete

Cinder implements specialized heterogeneous `Tuple[...]` values and homogeneous owning `List[T]`, `Map[K, V]`, and `Set[T]` collections. Maps preserve insertion order and expose live non-owning views; Sets provide membership and algebra. Optional collection lookups use the general tagged `Option[T]` family.

Collection ownership is explicit and move-only. Owning collections and destructor-bearing classes may nest, live in struct/class fields, and pass by value with use-after-move checking. Owning globals and union/variant payloads remain rejected. Hashable keys are integers, booleans, characters, enums, and copied `const char*` strings with content equality.

## 0.6 candidates

The next useful compiler milestone should focus on build and ABI maturity rather than expanding the surface language indiscriminately. Candidate work includes separate object compilation, dependency-aware object caching, parallel builds, depfiles, richer package configuration, stable exported-name controls, and ABI conformance fixtures for supported compilers.

Ownership work should remain explicit. Viable additions include opt-in copy operations, user-defined move hooks, owned pointer wrappers, and drop glue for unions/variants and globals. A full borrow checker or inferred ownership system is not currently planned.

Compile-time work may grow toward user-defined constant functions and serializer generation, but it should not become unrestricted AST macros. Runtime reflection may add field-value visitors only if the access rules, alignment requirements, and generated C remain straightforward.

## Later language work

Other plausible additions include function pointer types, closures with explicit environment structs, user-defined generic monomorphization, richer match patterns, package dependencies, and a documented stable C ABI for selected exported declarations.

## Non-goals

Cinder is not intended to become Python with native compilation, a borrow-checking Rust replacement, a garbage-collected application VM, or a C preprocessor dialect. The generated C must remain a useful debugging and integration artifact rather than an opaque implementation detail.
