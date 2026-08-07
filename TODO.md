# Gen3 TODOs

Fresh gen3 run: 33 examples passed and 3 examples failed. The run covers `examples/*.ci`, `class_project`, and `module_project`. It excludes `large_project`.

1. Keep imported Result call types (done)

Gen3 must keep the return type when code uses `?` on an imported function such as `parser.parse(value)?`. It must emit the imported call and get the `Ok` value. This fixes `module_project`, where generated C now writes `token = 0` and then reads an `int` as a `Token`.

2. Emit nested Option and Result types in order (done)

Gen3 must emit a `Result` type before an `Option` stores it by value. `Option[Result[i32, ParseError]]` now puts an incomplete `Result` field in the C struct. This fixes `expressive_match.ci`.

3. Lower Result state fields

Gen3 must lower `.is_ok` and `.is_err` for `Result[T, E]`. Emit a tag check, like the existing `Option.is_some` code. This fixes `anti_examples.ci`.

4. Use correct f-string field types

Gen3 must not guess that a name such as `source` is a `String` when it is an `i32` match field. Use match field types, or semantic type data, before f-string lowering. This fixes `dijkstra_showcase.ci`.

5. Find the List mutation runtime trap

Record stdout, stderr, and signal data for `binary_sort.ci`. Then fix the fault when `binary_sort(values)` mutates a `List[i32]` passed by value. The example must print the sorted list and exit with 0.
