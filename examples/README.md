# Examples

`hello.ci` is the smallest native program.

`print.ci` demonstrates import-free `print`, multi-argument output, f-strings with format specs, and Python-like printing of Lists, Maps, Sets, and Tuples.

`input.ci` demonstrates import-free `input` with a Python-style prompt.

`convert.ci` demonstrates Result-returning `parse_*` helpers (`i32`, `u32`, `bool`, `f64`), `ConvertError` matching (`empty`, `invalid`, overflow), `?` propagation, and owned `to_string` formatting for integers, floats, `bool`, and `char`.

`vectors.ci` demonstrates structs, named field initialization, const methods, and the checked math module.

`slices.ci` demonstrates fixed arrays, slicing, mutable-to-const slice conversion, collection iteration, and `.length`.

`collections.ci` demonstrates heterogeneous tuples; inferred owning Lists, Maps, and Sets; `Option` lookup; live Map views; Set algebra; deterministic cleanup; sorting; iteration; zero-copy List-to-slice arguments; and Python-like `print` of whole collections.

`aggregate_ownership.ci` demonstrates aggregate ownership: struct/class fields owning Lists/Maps/Sets/Files and destructor-bearing classes; nested collections and owning elements; by-value parameters and returns; `Option`/`Result`/`Tuple`/array wrappers; field reassignment; and local moves.

`owned.ci` demonstrates `Owned[T]` heap ownership: construct with `Owned(value)`, mutate through `*`, borrow with `&*`, nest `Option[Owned[Node]]`, move-only transfer, and deterministic drop of destructor-bearing payloads.

`generics.ci` demonstrates user-defined generics: monomorphized `struct Box[T]`, `def identity[T]`, `variant Tagged[T]`, and `abstract class Writer[T]` specialized to readable C names such as `Box_i32`.

`pointers.ci` demonstrates address-of, raw pointers, transparent references, and pointer indexing.

`unsafe.ci` demonstrates explicit `unsafe` blocks for raw-address casts: store an array element address as `usize`, cast it back to `*u8`, and read a byte while keeping the dangerous boundary visible.

`function_pointers.ci` demonstrates transparent function pointer types: annotate with `def(T…) -> R`, pass a named function by name, store it, and call through the value.

`closures.ci` demonstrates explicit-environment closures: user-declared environment structs, env-first adapter functions, const and mutable environment calls, and first-class closure values.

`control_flow.ci` demonstrates range loops, C-style loops, `while`, and conditional branches.

`fizzbuzz.ci` prompts for an upper bound with `input` and `parse_i32`, then prints Fizz/Buzz/FizzBuzz for 1 through that number using a range loop, modulo, and `if`/`elif`/`else`.

`towers_of_hanoi.ci` prompts for a disk count with `input` and `parse_i32`, then prints the recursive move sequence.

`binary_sort.ci` implements stable binary insertion sort on a numeric List, then prints the sorted collection.

`long_string_sort.ci` demonstrates lexicographic sorting of C strings in a List without importing `string`, then prints the sorted collection.

`algorithm_benchmarks.ci` times exact N-Queens, traveling-salesperson, and edit-distance
solutions. It reports both fractional wall-clock seconds and implementation-defined C CPU
ticks.

`leibniz_pi.ci` approximates π with the Leibniz series over 1,000,000,000 iterations and
reports wall-clock elapsed time in milliseconds. The loop derives each term's sign from the
index so optimizing C compilers can auto-vectorize it.

`physics.ci` demonstrates common mechanics formulas with the checked math module: energy,
momentum, force, kinematics, projectile motion, pendulum period, and centripetal acceleration.

`write_jpg.ci` demonstrates import-free `open`, the `with ... as ...:` statement, and
`File.write` by creating a small valid JPEG on disk.

`read_file.ci` demonstrates Source-side File I/O: `File.read` into a fixed buffer,
`File.read_line` with owned string cleanup, and `File.read_all` into a `List[u8]`.

`defer.ci` demonstrates explicit allocation and cleanup before a returned value leaves scope.

`interop.ci` includes a system C header and supplies a checked external declaration.

`types_and_results.ci` demonstrates enums, plain unions, tagged variants, exhaustive matching, typed Results, and `?` propagation.

`classes.ci` demonstrates a reflected abstract class, a concrete subclass, constructor chaining, checked override implementation, direct class calls, and explicit `&dyn` dispatch.

`reflection.ci` demonstrates runtime type and field metadata, static assertions, compile-time field and method queries, and unrolled `comptime` layout inspection.

`anti_examples.ci` pairs commented-out code that Cinder rejects with explanations and live corrected versions. The file itself remains checkable and runnable.

`module_project/` is a complete manifest-driven multi-file project. It demonstrates dotted local modules, aliases, transitive imports, generated headers and translation units, cross-module nominal types, and Result propagation across module boundaries.

`class_project/` is a complete multi-file class ABI example. It defines a reflected abstract interface in one module, implements it in another, and performs dynamic dispatch from the entry module through separately generated headers and C translation units.

`large_project/` is a larger multi-module Breakout demo. It binds SDL2 and SDL_mixer via `extern import` / `extern "C"`, opens a window, draws paddle/ball/bricks across nested `sdl/` and `game/` modules, and plays WAV sound effects. See `large_project/README.md` for install and link flags (manual run; not part of CI).
