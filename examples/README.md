# Examples

`hello.ci` is the smallest native program.

`print.ci` demonstrates import-free `print`, multi-argument output, and f-strings with format specs.

`input.ci` demonstrates import-free `input` with a Python-style prompt.

`vectors.ci` demonstrates structs, named field initialization, const methods, and the checked math module.

`slices.ci` demonstrates fixed arrays, slicing, mutable-to-const slice conversion, collection iteration, and `.length`.

`collections.ci` demonstrates heterogeneous tuples, inferred and typed owning lists, deterministic list cleanup, mutation, sorting, iteration, and reference-based list parameters.

`pointers.ci` demonstrates address-of, raw pointers, transparent references, and pointer indexing.

`control_flow.ci` demonstrates range loops, C-style loops, `while`, and conditional branches.

`binary_sort.ci` implements stable binary insertion sort on a numeric array.

`long_string_sort.ci` demonstrates lexicographic sorting of C strings without importing `string`.

`algorithm_benchmarks.ci` times exact N-Queens, traveling-salesperson, and edit-distance
solutions. It reports both fractional wall-clock seconds and implementation-defined C CPU
ticks.

`defer.ci` demonstrates explicit allocation and cleanup before a returned value leaves scope.

`interop.ci` includes a system C header and supplies a checked external declaration.

`types_and_results.ci` demonstrates enums, plain unions, tagged variants, exhaustive matching, typed Results, and `?` propagation.

`classes.ci` demonstrates a reflected abstract class, a concrete subclass, constructor chaining, checked override implementation, direct class calls, and explicit `&dyn` dispatch.

`reflection.ci` demonstrates runtime type and field metadata, static assertions, compile-time field and method queries, and unrolled `comptime` layout inspection.

`anti_examples.ci` pairs commented-out code that Cinder rejects with explanations and live corrected versions. The file itself remains checkable and runnable.

`module_project/` is a complete manifest-driven multi-file project. It demonstrates dotted local modules, aliases, transitive imports, generated headers and translation units, cross-module nominal types, and Result propagation across module boundaries.

`class_project/` is a complete multi-file class ABI example. It defines a reflected abstract interface in one module, implements it in another, and performs dynamic dispatch from the entry module through separately generated headers and C translation units.
