# Examples

`hello.ci` is the smallest native program.

`vectors.ci` demonstrates structs, named field initialization, const methods, the checked math module, and C varargs promotion.

`slices.ci` demonstrates fixed arrays, slicing, mutable-to-const slice conversion, collection iteration, and `.length`.

`pointers.ci` demonstrates address-of, raw pointers, transparent references, and pointer indexing.

`control_flow.ci` demonstrates range loops, C-style loops, `while`, and conditional branches.

`binary_sort.ci` demonstrates the import-free stable `sort` builtin on a numeric array.

`long_string_sort.ci` demonstrates lexicographic sorting of C strings without importing `string`.

`defer.ci` demonstrates explicit allocation and cleanup before a returned value leaves scope.

`interop.ci` includes a system C header and supplies a checked external declaration.

`types_and_results.ci` demonstrates enums, plain unions, tagged variants, exhaustive matching, typed Results, and `?` propagation.

`classes.ci` demonstrates a reflected abstract class, a concrete subclass, constructor chaining, checked override implementation, direct class calls, and explicit `&dyn` dispatch.

`reflection.ci` demonstrates runtime type and field metadata, static assertions, compile-time field and method queries, and unrolled `comptime` layout inspection.

`anti_examples.ci` pairs commented-out code that Cinder rejects with explanations and live corrected versions. The file itself remains checkable and runnable.

`module_project/` is a complete manifest-driven multi-file project. It demonstrates dotted local modules, aliases, transitive imports, generated headers and translation units, cross-module nominal types, and Result propagation across module boundaries.

`class_project/` is a complete multi-file class ABI example. It defines a reflected abstract interface in one module, implements it in another, and performs dynamic dispatch from the entry module through separately generated headers and C translation units.
