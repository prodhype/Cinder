# Cinder

Cinder is a statically typed systems language with Python-shaped syntax and a transparent C11 backend. It uses indentation for blocks, newlines for statements, explicit types at public boundaries, C-compatible data layouts, deterministic cleanup, and ordinary native toolchains.

The compiler requires Python 3.14+, emits readable portable C11, and can invoke GCC, Clang, or MSVC-compatible toolchains.

## Status

Cinder 0.5.0 completes the first five language milestones.

The procedural core includes indentation-aware parsing, primitive and C ABI types, typed globals, inferred locals, functions, named arguments, native control flow, structs and methods, pointers and references, fixed arrays, slices, explicit allocation, scoped `defer`, C imports, exported C functions, and readable C11 generation.

Native collection support includes heterogeneous value tuples and specialized owning Lists, Maps, and Sets. Maps preserve insertion order and expose live views; Sets support hash membership and algebra. Optional lookup uses tagged `Option[T]` values.

The project system includes deterministic `cinder.toml` manifests, local imports, dotted module paths, dependency ordering, cycle diagnostics, one generated header and translation unit per module, deterministic internal symbols, content-stable generated files, and optional amalgamated output.

The algebraic-data layer includes C enums, plain unions, tagged variants, exhaustive `match`, `Result[T, E]`, contextual `Ok` and `Err`, and postfix `?` propagation that preserves active cleanups.

Cinder 0.4 adds classes, constructors, destructors, private fields, one implementation base, multiple abstract interfaces, checked abstract-method implementation, signature-checked overrides, direct static dispatch, explicit `&dyn Interface` dispatch, deterministic derived-before-base destruction, move-only destructor-bearing values, and cross-module class ABI generation.

Cinder 0.5 adds opt-in `@reflect` metadata, runtime type/field/method inspection, dynamic runtime type names, compile-time type and member queries, top-level `static_assert`, and unrolled `comptime` field and method loops.

The implementation remains alpha software. User-defined generics, function pointer types, closures, exceptions, aggregate ownership for owning collections or destructor-bearing classes, copy/move hooks, object-file caching, and a stable pre-1.0 binary ABI remain future work.

## Installation

From the project root:

```sh
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

On Windows PowerShell:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

A C11 compiler must be on `PATH`. Cinder checks `CC`, then common compiler commands for the host platform. A specific compiler can be selected with `--cc`.

## Commands

Every command accepts a `.ci` entry file, a project directory, or a `cinder.toml` manifest.

```sh
cinder check examples/classes.ci
cinder emit-c examples/reflection.ci -o reflection.c
cinder emit-project examples/class_project -o generated
cinder build examples/class_project -o class-demo
cinder run examples/class_project
```

`emit-c` writes one amalgamated C translation unit. `emit-project` writes the normal per-module `.c` and `.cinder.h` tree. `build` writes that same tree under `.cinder/<project-name>/` unless `--build-dir` is supplied, then compiles and links every generated translation unit.

Compiler and linker flags can be forwarded explicitly:

```sh
cinder build app.ci --cc clang --cflag=-O3 --ldflag=-pthread -I vendor/include
```

Arguments after `--` are passed to programs run with `cinder run`:

```sh
cinder run app.ci -- first second
```

## Language example

```python
import stdio
import math


@reflect
abstract class Shape:
    name: const char*

    def __init__(self, name: const char*):
        self.name = name

    @abstractmethod
    def area(self) -> f64:
        pass

    def describe(self) -> void:
        stdio.printf("%s: %.2f\n", self.name, self.area())


@reflect
class Circle(Shape):
    radius: f64

    def __init__(self, radius: f64):
        super().__init__("circle")
        self.radius = radius

    @override
    def area(self) -> f64:
        return math.pi * self.radius * self.radius


def describe(shape: &dyn Shape) -> void:
    stdio.printf("runtime type: %s\n", type_name(shape))
    shape.describe()


def main() -> i32:
    circle = Circle(radius=4.0)
    describe(circle)

    for field in fields(circle):
        stdio.printf("field: %s at %zu\n", field.name, field.offset)

    return 0
```

Concrete calls remain direct C function calls. Only a value whose type is explicitly `&dyn Shape` uses an interface table.

## Classes and object layout

Classes are values, not implicit heap objects. `Circle(4.0)` zero-initializes a `Circle` value, invokes its generated constructor, and returns the value by ordinary C value semantics.

A class with one implementation base stores that base as its first member:

```python
class Entity:
    id: u64

class Player(Entity):
    score: i32
```

The generated layout is structurally equivalent to:

```c
typedef struct Player {
    Entity _base;
    int32_t score;
} Player;
```

There is no hidden virtual pointer in `Player`. Inherited field and receiver adjustment is explicit in generated C.

A concrete class may have one implementation base and multiple interface-only abstract bases. Multiple implementation inheritance is rejected.

A concrete call uses static dispatch:

```python
def area(circle: &Circle) -> f64:
    return circle.area()
```

An explicit dynamic call uses a two-word non-owning value:

```python
def area(shape: &dyn Shape) -> f64:
    return shape.area()
```

The generated representation is an object pointer plus a constant interface-table pointer. Each concrete implementation emits one table per implemented abstract interface. `&const dyn Interface` provides a read-only dynamic borrow.

See `docs/classes-and-interfaces.md` for constructor rules, interface-only bases, lifetime transfer, cleanup, and the generated ABI.

## Constructors, destructors, and moves

`__init__` initializes an existing value. A derived constructor with an implementation-base constructor must call `super().__init__(...)` first.

`__del__` is compiler-managed deterministic cleanup. Local destructor-bearing objects are dropped on normal block exit, `return`, `break`, `continue`, and propagated `Err` returns. Locals are dropped in reverse declaration order; a derived destructor runs before its implementation-base destructor.

Destructor-bearing classes are move-only in 0.5. They may be initialized from constructors or class-returning calls and transferred by return. Reassignment evaluates the replacement, drops the old value, and transfers the replacement. Implicit copies are rejected.

```python
class Resource:
    def __del__(self):
        release_native_resource()


def make() -> Resource:
    resource = Resource()
    return resource
```

Aggregate ownership of destructor-bearing classes is deliberately not implemented yet. Store borrowed references or explicit pointers when building ownership containers.

## Reflection

Runtime reflection is opt-in:

```python
@reflect
struct User:
    id: u64
    name: const char*
    active: bool
```

The compiler emits constant `CinderTypeInfo`, `CinderFieldInfo`, and `CinderMethodInfo` records. Metadata does not add fields to concrete objects and does not require startup registration.

```python
user = User(id=42, name="Cinder", active=true)
info = type_info(user)

for field in fields(user):
    stdio.printf("%s: %s\n", field.name, field.type_name)
```

`type_info`, `fields`, and `methods` require `@reflect`. Concrete `type_name(value)` is compile-time text and does not require metadata. Dynamic `type_name(value)` reads concrete metadata through a reflected interface table.

Compile-time queries include:

```python
static_assert(field_count(User) == 3)
static_assert(has_field(User, "name"))
static_assert(size_of(User) >= 17)

for field in comptime fields_of(User):
    stdio.printf("%s: %zu\n", field.name, field.offset)
```

The compiler implements `type_of`, `type_name`, `type_info`, `size_of`, `align_of`, `field_count`, `method_count`, `has_field`, `has_method`, `implements`, `fields`, `methods`, `fields_of`, and `methods_of`.

Compile-time member loops are unrolled. They do not require runtime metadata and do not emit a runtime loop.

See `docs/reflection.md` for metadata fields, binary-size costs, static-assert behavior, and current limits.

## Projects and modules

A project is described by `cinder.toml`:

```toml
[project]
name = "example"
source-root = "src"
entry = "main.ci"
```

A typical tree is:

```text
example/
    cinder.toml
    src/
        main.ci
        geometry.ci
        support/
            parsing.ci
```

Module names are derived from paths below the source root. `geometry.ci` is `geometry`; `support/parsing.ci` is `support.parsing`; `support/__init__.ci` is `support`.

```python
import geometry
import support.parsing as parsing
from geometry import Vec2, distance
```

Cinder resolves the complete acyclic dependency graph, then checks and emits modules in dependency order. Built-in modules such as `stdio` and `math` do not resolve to local files unless shadowed by a local module.

Generated module headers contain public nominal layouts, callable declarations, dynamic interface types and tables, class constructor/drop declarations, and reflected metadata declarations. Internal C names receive a deterministic project-and-module prefix. `main` in the entry module and functions marked `@export` retain externally callable C names.

For a project with modules `geometry` and `main`, `emit-project` produces:

```text
generated/
    cinder_gen/
        geometry.c
        geometry.cinder.h
        main.c
        main.cinder.h
```

Generated headers are valid C11 and include C++ linkage guards for callable declarations.

## Enums, unions, variants, and match

Enums are ordinary C enums with distinct integer values:

```python
enum ParseError:
    invalid
    overflow = 4
```

Plain unions retain ordinary C union semantics:

```python
union Number:
    integer: i64
    real: f64

number = Number(integer=42)
```

Variants use an explicit tag and payload union:

```python
variant Token:
    Identifier(text: const char*)
    Integer(value: i64)
    Plus
    End

token = Token.Integer(42)
```

`match` is restricted to enums, variants, and Results. Matches must be exhaustive unless the final case is a wildcard.

```python
match token:
    case Token.Identifier(text):
        consume_name(text)
    case Token.Integer(value):
        consume_integer(value)
    case Token.Plus:
        consume_plus()
    case Token.End:
        pass
```

Patterns do not yet support guards, alternatives, literals, or nested destructuring.

## Typed Results, Options, and propagation

`Result[T, E]`, `Option[T]`, `Tuple[...]`, `List[T]`, `Map[K, V]`, and `Set[T]` are compiler-provided generic families. User-defined generic declarations are not implemented.

```python
def parse(value: i32) -> Result[i32, ParseError]:
    if value < 0:
        return Err(ParseError.invalid)
    return Ok(value)


def increment(value: i32) -> Result[i32, ParseError]:
    parsed = parse(value)?
    return Ok(parsed + 1)
```

`Ok` and `Err` are contextual constructors. Postfix `?` evaluates its operand once, checks the explicit tag, runs active deferred calls, List cleanup, and class drops on error, and performs an ordinary early return.

To preserve straightforward C evaluation order, `?` is not accepted in `while` conditions, `elif` conditions, C-style loop conditions or updates, the right side of `and` or `or`, or deferred calls.

`Option[T]` represents an optional value without using pointer nullability. `Some(value)` infers its payload when possible, bare `None` requires an Option context, and matches must cover both cases. `.is_some`, `.is_none`, and checked `.value` access are available; postfix `?` remains Result-only.

## Types

Portable primitive types are:

```text
bool  char

i8  i16  i32  i64
u8  u16  u32  u64

f32  f64

isize  usize
void
```

C ABI aliases include `c_int`, `c_long`, and `c_size_t`.

Pointers and references use prefix syntax. C-style postfix pointer syntax is also accepted where it helps transcribe C declarations.

```python
pointer: *i32 = &value
argv: **char
name: const char* = "Cinder"


def increment(value: &i32) -> void:
    value += 1
```

References compile to pointers but are transparent inside Cinder expressions. The checker rejects null reference initialization and requires an addressable value when a reference is formed.

Fixed arrays and slices are distinct:

```python
values: i32[4] = [10, 20, 30, 40]
view: []i32 = values[1:]
```

A slice is emitted as a typed `{data, length}` struct. Mutable arrays and slices can be passed to const slice parameters without copying. Slicing and indexing currently perform no bounds checks.

Tuples are immutable heterogeneous values:

```python
entry: Tuple[i32, const char*] = (7, "ready")
code = entry[0]
```

Tuple indices must be integer literals. Empty and singleton tuples use `()` and `(value,)`.

Lists are homogeneous owning buffers. An untyped square-bracket literal infers a list, while an explicit fixed-array annotation keeps fixed storage:

```python
fixed: i32[3] = [3, 1, 2]
values = [3, 1, 2]
values.append(4)
sort(values)
last = values.pop()
```

Lists are move-only direct locals and return values, and are freed deterministically on every normal cleanup path. Addressable Lists may be passed without copying to `[]T` and `[]const T` parameters, letting one element-processing function accept Lists, fixed arrays, and slices. This coercion is call-only; structural operations still use `&List[T]`. Nested lists, list fields/globals, by-value list parameters, and destructor-bearing elements are intentionally deferred with broader aggregate ownership work.

Maps use `{key: value}` literals and preserve insertion order. Sets use `{value, ...}`; an empty Set uses contextual `set()`. Empty `{}` requires a `Map[K, V]` context.

```python
scores = {"Ada": 7, "Grace": 9}
scores["Ada"] += 1
score = scores.get("Ada")

match score:
    case Some(value):
        print(value)
    case None:
        pass

primes = {2, 3, 5}
small = primes | {1, 2}
```

`in` and `not in` test Map keys and Set elements. Maps provide `keys()`, `values()`, and `items()` as live non-owning views; default Map iteration yields keys. Sets provide union, intersection, difference, symmetric difference, and subset/superset comparisons.

Hashable types are integers, `bool`, `char`, enums, and `const char*`. String keys use null-safe content equality and are copied into the collection. A string removed by `Set[const char*].pop()` transfers its allocation to the caller, who must release it with `free(cast[void*](text))`.

Maps and Sets use the same move-only direct-local/direct-return ownership envelope as Lists. Nested owning collections, aggregate fields, globals, by-value parameters, and destructor-bearing elements remain unsupported. Map views are borrowed values with slice-like lifetime responsibility; structural mutation is rejected or guarded while an iterator is active.

## Structs and methods

Structs have C-compatible layout and no inheritance or dynamic dispatch.

```python
struct Counter:
    value: i32

    def add(self, amount: i32) -> void:
        self.value += amount
```

An omitted `self` annotation is inferred as `&Counter`. `self: &const Counter` creates a const method. Calls compile to direct C functions.

Struct construction is checked field initialization:

```python
counter = Counter(value=0)
```

Named arguments are reordered at compile time. Omitted fields are zero-initialized.

## Control flow

```python
if value < 0:
    handle_negative(value)
elif value == 0:
    handle_zero()
else:
    handle_positive(value)

while ready():
    poll()

for index in range(0, 10):
    process(index)

for value in values:
    process(value)

for index: usize = 0; index < count; index += 1:
    process(values[index])
```

`range` accepts one, two, or three integer arguments. Expressions are evaluated once before the loop. A zero step is rejected when literal and triggers `panic` when discovered at runtime.

Locals use lexical block scope, matching generated C rather than Python function-wide local scope.

## Allocation and `defer`

Cinder has no garbage collector or ownership inference.

```python
values = alloc[i32](count)
defer free(values)
```

`alloc[T](count)` calls the small runtime allocation helper, checks multiplication overflow and allocation failure, and returns `*T`. `alloc[T]()` allocates one element. Memory is uninitialized, as with C `malloc`.

`defer` registers a call for the end of the current lexical scope. Deferred calls run in reverse declaration order on normal exit and all supported early exits. Return values are evaluated into a temporary before cleanup runs. Deferred call arguments are evaluated when cleanup runs, not when `defer` is encountered.

## C interoperability

A C header can be included directly:

```python
extern import "sqlite3.h"
```

Checked declarations use an explicit ABI block:

```python
extern "C":
    def sqlite3_open(filename: const char*, database: **sqlite3) -> c_int
```

The compiler does not parse arbitrary C headers. `extern import` controls inclusion; `extern "C"` supplies the signatures Cinder checks. Unknown types in external signatures are treated as opaque C types and emitted unchanged.

Built-in modules map common C APIs into checked namespaces:

```python
import math
import stdio

stdio.printf("%.2f\n", math.sqrt(9.0))
```

For common console output, `print(...)` is available without an import:

```python
name = "Ada"
score: i32 = 42
print(f"{name}: {score:x}")
```

`print` separates multiple arguments with spaces, appends a newline, and supports f-string replacement fields with simple format specs. F-strings are currently limited to `print` arguments.

For console input, `input()` is also available without an import. `input(prompt)` writes the prompt without a newline, reads one line, and returns it without the trailing newline:

```python
name = input("name: ")
defer free(cast[void*](name))
print("hello", name)
```

`@export` preserves a top-level function's C symbol name:

```python
@export
def engine_update(delta_time: f64) -> void:
    update_world(delta_time)
```

## Unsafe casts

Numeric casts and compatible pointer casts are allowed directly. Pointer/integer casts and unrelated pointer reinterpretation require an explicit block:

```python
unsafe:
    byte_pointer = cast[*u8](address)
```

This makes dangerous code visible; it does not make raw pointer operations memory-safe.

## Project layout

```text
cinder/
    lexer.py
    parser.py
    ast.py
    types.py
    symbols.py
    checker.py
    ir.py
    codegen_c.py
    project.py
    diagnostics.py
    compiler.py
    toolchain.py
    cli.py
    runtime/
        cinder_runtime.h
        cinder_runtime.c
examples/
tests/
docs/
```

## Development

```sh
python -m pip install -e '.[dev]'
python -m compileall -q cinder tests
pytest
ruff check cinder tests
mypy cinder
```

Integration tests compile generated C and execute native programs. The test suite also validates GCC and Clang warnings-as-errors builds, cross-module class/interface ABI behavior, content-stable project emission, and generated-header use from C++17. CI runs on Linux, macOS, and Windows with Python 3.14.

## Design constraint

The governing rule is that Cinder must remain understandable by reading generated C. Features that require hidden allocation, unpredictable dispatch, exception unwinding, implicit object lifetimes, or a mandatory garbage collector are excluded until they can be designed without violating that rule.
