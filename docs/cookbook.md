# Cinder cookbook

This is the short operational reference for the Cinder revision in this
repository. It covers the forms that are most useful when writing or reviewing
`.ci` code. The complete language contract is in
[`grammar.md`](grammar.md); runnable examples are under
[`examples/`](../examples/README.md).

Cinder is pre-1.0. Prefer the spellings and APIs here over Python, C++, or Rust
analogy. If this guide and the current compiler disagree, preserve the
documented contract, verify with the repository compiler, and update the guide.

## Smallest program

```python
def main() -> i32:
    print("Hello from Cinder!")
    return 0
```

Check, build, or run a file or manifest-backed project:

```sh
cinder check app.ci
cinder build app.ci -o app
cinder run app.ci -- first-argument
```

Inside this repository, prefer `./.cinder/bootstrap/cinder-gen2` when it is
available.

## Syntax at a glance

- Source is UTF-8. Blocks use spaces and indentation; leading tabs are errors.
- `#` starts a line comment. A newline ends a statement unless it is inside
  `()`, `[]`, or `{}`. Backslash continuation is not supported.
- Locals may infer their type. Globals and non-`self` parameters require type
  annotations. An omitted return type means `void`.
- A source file is a module. Imports must form an acyclic graph.

Unless a snippet declares a type or function, its unindented statements are a
function-body fragment.

```python
import math
from engine.geometry import Point as Point2D

limit: i32 = 10
const SCALE: f64 = 2.0

def clamp(value: i32, low: i32, high: i32) -> i32:
    if value < low:
        return low
    if value > high:
        return high
    return value

def total(values: []const i32) -> i32:
    result: i32 = 0
    for value in values:
        result += value
    return result
```

Named arguments may be reordered, but positional arguments cannot follow a
named argument.

### Common type spellings

```text
i32, u64, f32, f64, bool, char, usize, void  portable primitives
c_int, c_long, c_size_t                      C ABI aliases
*T, **T                                      raw pointers
&T, &const T                                 mutable and const references
&dyn Interface, &const dyn Interface         dynamic interface references
[]T, []const T                               mutable and const slices
T[N]                                         fixed array
List[T], Map[K, V], Set[T], Tuple[...]       owning collections and tuple
Option[T], Result[T, E], Owned[T]             tagged wrappers and heap owner
def(T) -> R                                  function pointer
closure[Env](T) -> R                         explicit-environment closure
```

`const char*` is also accepted in C declarations. References, slices, dynamic
references, and raw pointers do not own their targets.

### Aggregates and tagged values

Structs use C-compatible field layout and field initialization. Classes add
constructors, deterministic destructors, inheritance, and optional dynamic
dispatch. Use a `variant`, not a plain `union`, when code must inspect a tag.

```python
struct Point:
    x: i32
    y: i32

variant Token:
    Integer(value: i32)
    End

def token_value(token: Token) -> i32:
    match token:
        case Token.Integer(value):
            return value
        case Token.End:
            return 0
```

Matches over enums, variants, `Result`, and `Option` must be exhaustive.
Patterns support payload binding, `_`, guards, alternatives, and nested tagged
patterns. Literal, tuple, and struct patterns are not implemented.

## Ownership and cleanup

Cinder has deterministic cleanup, no garbage collector, and no automatic
ownership inference.

- Primitives and plain aggregates without drop-requiring fields are copyable.
- `String`, `StringBuilder`, `List`, `Map`, `Set`, `File`, `Owned`, and
  destructor-bearing values are move-only. Assignment, by-value arguments, and
  returns transfer them.
- `&T`, `&const T`, slices, dynamic references, map views, and raw pointers are
  non-owning. Do not return or store a view past its owner.
- `Atomic[T]` is immobile. Share it through `&Atomic[T]` or `*Atomic[T]`.
- Scope exit drops active owners. Replacement drops the previous value before
  storing the new one.

Use `clone()` when an independent `String` is required:

```python
name = "Cinder"
copy = name.clone()
copy.append(" language")
print(name)
print(copy)
```

`Owned[T]` allocates and owns one non-null heap value:

```python
struct Node:
    value: i32
    next: Option[Owned[Node]]

leaf: Owned[Node] = Owned(Node(value=10, next=None))
root: Owned[Node] = Owned(Node(value=20, next=Some(leaf)))
(*root).value += 1
borrowed: &Node = &*root
```

`Owned(value)` moves the value into a fresh allocation. It does not adopt an
existing `*T`. For raw allocation, pair `alloc` with `free` immediately:

```python
def compute() -> i32:
    values = alloc[i32](2)
    defer free(values)
    values[0] = 20
    values[1] = 22
    return values[0] + values[1]
```

`alloc[T](count)` returns uninitialized `*T` storage. Deferred calls run in
reverse order on normal scope exit, `return`, `break`, `continue`, and `?`
propagation. A `defer` operand must be a call; its arguments are evaluated when
cleanup runs.

Owning globals are unsupported except for a `const String` initialized directly
from a literal. Owning union and variant payloads are also unsupported. For
recursive ASTs, put owners in an arena and store scalar IDs or ranges in tagged
payloads; see [`ast_arena.ci`](../examples/ast_arena.ci).

## Results, options, and conversions

`Ok` and `Err` need an expected `Result[T, E]` type. Bare `None` similarly needs
an `Option[T]` context.

```python
enum ParseError:
    negative

def parse(value: i32) -> Result[i32, ParseError]:
    if value < 0:
        return Err(ParseError.negative)
    return Ok(value)

def increment(value: i32) -> Result[i32, ParseError]:
    parsed = parse(value)?
    return Ok(parsed + 1)
```

`?` is Result-only. The enclosing function must return a compatible `Result`;
error propagation runs active cleanup. It is not allowed in `while` or `elif`
conditions, C-style loop conditions or updates, deferred calls, or the
right-hand side of `and` or `or`.

Match options instead of assuming a value:

```python
match scores.get("Ada"):
    case Some(score):
        print(score)
    case None:
        print("missing")
```

`.value` on `None` panics. Result values expose `.is_ok`, `.value`, and `.error`;
Option values expose `.is_some`, `.is_none`, and `.value`.

The global `parse_i32`, `parse_i64`, `parse_u32`, `parse_u64`, `parse_isize`,
`parse_usize`, `parse_f32`, `parse_f64`, and `parse_bool` functions borrow a
`String` and return `Result[T, ConvertError]`. Conversion errors are
`ConvertError.empty`, `.invalid`, and `.overflow`. `to_string` returns owned
text for numbers, `bool`, and `char`.

## Strings and common built-ins

`String` is owned UTF-8 text:

```python
text = "Aé中Z"
byte_count = len(text)
lead_byte = text.byte_at(1)
middle = text[1:6]

builder = StringBuilder()
builder.append("build")
builder.append_char('-')
builder.append("up")
built = builder.finish()
```

- `len(text)` counts bytes, not characters.
- Direct String indexing is rejected. `byte_at` reads one byte.
- A String slice is an owned copy whose endpoints must be valid UTF-8
  boundaries. Collection slices are borrowed views instead.
- `append`, `append_char`, `reserve`, and `clear` mutate addressable values.
  `StringBuilder.finish()` consumes the builder.
- `+` borrows both String operands and returns a fresh String.
- Owned Strings cannot contain embedded NUL. Use `List[u8]` for arbitrary bytes.

Frequently used globals need no import:

- `print(...)`, `input([prompt])`, `to_string(value)`, and the `parse_*` family
- `len(value)`, loop-only `range(...)`, `sort(value)`, and `sorted(value)`
- `open(path, mode)`, `alloc[T]([count])`, `free(pointer)`, and `panic(message)`
- built-in forms `String()`, `StringBuilder()`, `Some`, `None`, `Ok`, `Err`,
  `Owned`, and `set()`

`sort` is stable and in-place; `sorted` returns a new `List`. Neither accepts
Python-style `key` or `reverse` arguments. F-strings are currently accepted
only as arguments to `print`.

Common compiler-provided modules are `math`, `process`, `std.atomic`, `std.path`,
`stdio`, `stdlib`, `string`, and `cinder`. Local modules may shadow them.

```python
import math
import process
from std.atomic import Atomic
from std.path import Path

root = math.sqrt(9.0)
command: List[String] = ["cc", "--version"]
completed = process.run(command)
counter: Atomic[u64] = 0
previous = counter.fetch_add(1)
output = Path.join("build", "output.txt")
```

`process.run` takes a shell-free argv `List[String]` and returns owned
`exit_code`, `stdout`, and `stderr` fields. Its runtime implementation is POSIX;
Windows currently returns an unsupported result.

`std.path.Path` is a namespace of borrowed-String path and filesystem
operations:

```python
from std.path import Path

output_dir = Path.join("build", "generated")
Path.create_dir_all(output_dir)
file_path = Path.join(output_dir, "result.tmp")
with open(file_path, "wb") as file:
    file.write("ready\n")
final_path = Path.with_suffix(file_path, ".txt")
Path.rename(file_path, final_path)
```

- `exists`, `is_file`, and `is_dir` return `bool` and follow symlinks.
- `parent`, `name`, `stem`, `join`, and `with_suffix` return owned `String`
  values using POSIX `/` lexical rules. A non-empty suffix must begin with `.`;
  a leading dot alone does not give a filename a suffix.
- `create_dir`, `create_dir_all`, `remove_file`, and `rename` return `void` and
  panic on failure. `create_dir_all` accepts existing directory components and
  treats an empty path as a no-op. `rename` uses native POSIX replacement
  behavior.
- Filesystem operations are implemented directly in the runtime with
  `stat`/`mkdir`/`unlink`/`rename`; they do not start shell utilities. Windows
  builds compile the API, but filesystem operations currently panic as
  unsupported.

Integer atomics provide `load`, `store`, `exchange`, `compare_exchange`, and
`fetch_add`, `fetch_sub`, `fetch_and`, `fetch_or`, and `fetch_xor`. Bool atomics
omit the fetch operations. `compare_exchange` returns `.exchanged` and
`.observed`.

Use `with` to bound a move-only file handle:

```python
with open(path, "rb") as file:
    line = file.read_line()
    match line:
        case Some(text):
            print(text)
        case None:
            print("end of file")
```

`File` provides `write(String)`, `write([]const u8)`, `read([]u8)`,
`read_line()`, `read_text()`, `read_all()`, `flush()`, and `close()`. I/O
failures panic; `read_line` uses `None` only for immediate EOF.

## Collections

### List and slices

```python
def summarize(values: []const i32) -> Tuple[i32, usize]:
    total: i32 = 0
    for value in values:
        total += value
    return (total, len(values))

values: List[i32] = [5, 1, 4]
values.append(2)
sort(values)
summary = summarize(values)
last = values.pop()
```

An empty List needs context: `values: List[i32] = []`. `append` moves an
element in; `pop` returns the final element and panics when empty; `clear`
releases all elements. An addressable `List[T]` coerces to `[]T` or `[]const T`
only for a call. The borrowed slice cannot be stored or returned.

Fixed arrays use `values: i32[3] = [1, 2, 3]`. Array, List, and slice slicing
creates a view, and no step syntax exists. Array, slice, and List indexing does
not insert bounds checks.

### Map

```python
scores: Map[String, i32] = {"Ada": 3}
scores["Ada"] += 4

match scores.get("Grace"):
    case Some(score):
        print(score)
    case None:
        print("missing")

for entry in scores.items():
    print(f"{entry[0]}={entry[1]}")
```

Maps preserve insertion order. `map[key]` panics when absent; assignment inserts
or replaces. `get` and `pop` return `Option[V]`. Iteration yields keys by
default; `keys()`, `values()`, and `items()` are live non-owning views. String
keys are cloned on insertion so later source mutation cannot corrupt the map.

### Set and tuple

```python
primes: Set[i32] = {2, 3, 5}
odd = {1, 3, 5, 7}
combined = primes | odd
empty: Set[i32] = set()

entry: Tuple[i32, String] = (7, "ready")
code = entry[0]
```

Sets provide `add`, `discard`, missing-element-panicking `remove`, optional
`pop`, `clear`, and `update`. `|`, `&`, `-`, and `^` create the usual set
combinations. `{}` is an empty Map, not an empty Set. Tuple shape is part of its
type, and tuple indices must be non-negative integer literals.

Do not structurally mutate, replace, or sort a List, Map, or Set while iterating
that same storage. This restriction includes aliases and live Map views.

## C interoperability

`extern import` emits a C include. It does not parse the header. Supply every
signature Cinder should check:

```python
extern import "sqlite3.h"

extern "C":
    type sqlite3
    def sqlite3_open(filename: const char*, database: **sqlite3) -> c_int
```

Use C ABI types in extern declarations. Unknown types there may be opaque, but
an explicit `type Name` is clearer. Declaring a function does not arrange its
link library.

A `String` passed directly to a `const char*` extern parameter is borrowed for
that call only. The pointer cannot be assigned, stored, or returned, and there
is no implicit `const char*`-to-`String` conversion.

Pointer/integer casts and unrelated pointer reinterpretation require an
explicit boundary:

```python
unsafe:
    bytes = cast[*u8](address)
```

`unsafe` makes the operation visible; it does not add memory safety.

Use `@export` to preserve a top-level C symbol:

```python
@export
def cinder_leibniz(iterations: i32) -> f64:
    # implementation
    return 0.0
```

Keep exported APIs flat: C primitives, C pointers, and opaque handles. Do not
expose `String`, `List`, `Map`, or other unstable Cinder runtime layouts unless
the host deliberately implements that ABI.

For normal builds, native dependencies belong in `cinder.toml`:

```toml
[native]
include-dirs = ["vendor/include"]
library-dirs = ["vendor/lib"]
libraries = ["sqlite3"]
link-files = []
cflags = []
ldflags = []
```

For a foreign host, run `cinder emit-project`, compile the generated
`cinder_gen/*.c` files and `runtime/cinder_runtime.c`, then link those objects
into the host. Cinder does not currently provide a shared-library build mode.
See the [`rust_host`](../examples/rust_host/README.md),
[`go_host`](../examples/go_host/README.md), and
[`python_host`](../examples/python_host/README.md) examples.

## Compiler pitfalls

1. **Follow the language contract even when a check is missing.** The current
   checker does not consistently reject every documented invalid form.
   In particular, do not rely on inferred top-level/parameter `i32`, incomplete
   matches, owning globals, unsafe casts outside `unsafe`, or use-after-move
   being accepted.
2. **One successful `check` is not a portability promise.** Cinder is pre-1.0;
   generated helpers, ABI details, and runtime layouts may change.
3. **Diagnostics are terse.** Most semantic failures are numeric
   `E code start length line column` records, and checking currently records at
   most one semantic diagnostic per module. Fix the first error and check again.
4. **A temporary owner is often not addressable.** Bind returned or literal
   Lists, classes, and other owners to a local before indexing, iterating,
   sorting, taking a reference, or converting a List to a slice.
5. **Borrowing is narrower than Python-style aliasing.** List-to-slice and
   String-to-C conversions are call-boundary borrows. Map views are live and
   non-owning.
6. **Some familiar Python forms mean something different or are absent.**
   `range` is loop-only, `{}` is a Map, String indices are bytes only through
   `byte_at`, f-strings are print-only, and exceptions do not exist.
7. **Bounds and panics are explicit tradeoffs.** Array/slice/List indexing has
   no inserted bounds check, while missing Map indexing, empty List `pop`,
   absent Option `.value`, and I/O failures panic.
8. **C headers are not bindings.** A wrong `extern "C"` declaration can compile
   and still violate the native ABI. Check the real header and link inputs.

[`anti_examples.ci`](../examples/anti_examples.ci) contains more WRONG/CORRECT
pairs. Its WRONG blocks are comments; use it as a contract catalog, not as proof
that every invalid block is mechanically regression-tested.

## Where to verify a detail

Escalate narrowly instead of searching the whole repository:

1. [`grammar.md`](grammar.md) for accepted syntax and semantics.
2. Focused references:
   [`modules.md`](modules.md),
   [`algebraic-types.md`](algebraic-types.md), and
   [`classes-and-interfaces.md`](classes-and-interfaces.md).
3. Checked examples:
   [`strings.ci`](../examples/strings.ci),
   [`collections.ci`](../examples/collections.ci),
   [`owned.ci`](../examples/owned.ci),
   [`types_and_results.ci`](../examples/types_and_results.ci), and
   [`interop.ci`](../examples/interop.ci).
4. Current implementation when behavior is version-sensitive:
   [`checker_types.ci`](../compiler_selfhost/src/checker_types.ci),
   [`ownership.ci`](../compiler_selfhost/src/ownership.ci), and
   [`runtime/cinder_runtime.h`](../runtime/cinder_runtime.h).

Use `cinder check` for acceptance, `cinder emit-c` for generated behavior, and
the compiler's `context`, `impact`, and `semantic-diff` commands for resolved
program relationships.
