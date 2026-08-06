# Gen3 TODOs

Fresh gen3 run: 24 examples passed and 12 examples failed. All failures were C toolchain errors from generated C. The failing targets were `aggregate_ownership.ci`, `anti_examples.ci`, `classes.ci`, `convert.ci`, `dijkstra_showcase.ci`, `expressive_match.ci`, `generics.ci`, `owned.ci`, `reflection.ci`, `strings.ci`, `class_project`, and `module_project`.

1. Add first-error gen3 smoke reports

Implement a smoke report mode that records the first non-warning C error for each failed target. Include the target name, generated file, generated line, source feature, and a short cause label. This will make later fixes easier because the current output has many cascade errors after the first bad lowering.

2. Monomorphize user generics

Fix gen3 so it substitutes concrete type arguments before it emits C for user generic structs, variants, functions, and abstract classes. The current output leaks names such as `T` in `Box[T]`, `Tagged[T]`, `identity[T]`, and `Writer[T]`. This blocks `generics.ci` and part of `anti_examples.ci`, and it can hide later type errors in specialized code.

3. Fix class and dyn lowering

Implement correct C lowering for `super().__init__`, abstract base calls, override dispatch, and `&dyn` arguments. The current output emits missing `super` functions and passes concrete class values where a dynamic receiver is required. This affects `classes.ci`, `class_project`, `dijkstra_showcase.ci`, and `anti_examples.ci`.

4. Implement reflection built-ins

Implement gen3 support for `@reflect`, `type_info`, `type_name`, `fields`, `fields_of`, `field_count`, `method_count`, `has_field`, `has_method`, and `implements`. The current output treats these forms as ordinary functions or emits raw type names as C expressions. This affects `reflection.ci`, `classes.ci`, `class_project`, `dijkstra_showcase.ci`, and `anti_examples.ci`.

5. Fix match binding lowering

Fix gen3 match lowering for nested patterns, guarded cases, capture patterns, and OR patterns. The current output uses names such as `score`, `original`, `parsed`, `value`, and `error` without declaring them in the selected case scope. This affects `expressive_match.ci`, `convert.ci`, `module_project`, and `anti_examples.ci`.

6. Lower enum and variant constructors correctly

Fix local and imported enum or variant constructors in expressions and result payloads. The current output emits forms such as `model.ParseError.negative`, `model.Token.Integer(value)`, and zero-payload variants as invalid C expressions. This affects `module_project`, `expressive_match.ci`, `convert.ci`, and `anti_examples.ci`.

7. Propagate expected aggregate types

Fix expected-type propagation for list literals, fixed-array initializers, struct fields, assignments, and function arguments. The current output emits generic `CinderList` values where `CinderList_i32`, `i32[36]`, or `List[i32][2]` is required. This affects `aggregate_ownership.ci`, `dijkstra_showcase.ci`, and `anti_examples.ci`.

8. Implement Owned lowering

Implement `Owned[T]` construction, dereference, field access through dereference, moves, and drop glue in gen3. The current output emits a missing nominal `Owned` constructor and then treats `CinderOwned_T` as if it were a pointer. This blocks `owned.ci` and can also affect examples that use owning wrappers inside `Option` or `Result`.

9. Complete String operations

Implement gen3 lowering for static `String` constants and `String` or `StringBuilder` methods such as `clone`, `reserve`, `append`, `append_char`, `clear`, and `finish`. The current output initializes a `const CinderString` with a runtime function call and emits method names such as `clone` and `reserve` as undeclared C functions. This affects `strings.ci`, `convert.ci`, and `anti_examples.ci`.
