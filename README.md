# Cinder

Cinder is a statically typed systems programming language with Python-like syntax and C-compatible semantics.

It gives you indentation-based blocks, newline-terminated statements, explicit types at public boundaries, deterministic cleanup, and predictable data layout.
Cinder compiles to readable C11, so the generated code can be inspected, debugged, and built with ordinary native toolchains such as GCC, Clang, and MSVC-compatible compilers.

Cinder is self-hosted. The canonical compiler implementation is Cinder source,
and the repository bootstraps it with a small, checked-in native seed. The
compiler, build, and test paths have no Python dependency.

## Project State

Cinder is pre-1.0, but the core language and toolchain are operational.
The compiler can type-check Cinder programs, generate readable C11, build multi-file projects, and bootstrap the native compiler from the self-hosted source tree.
The language is still evolving. Source syntax, CLI behavior, generated helper APIs, ABI details, and binary layout may change before the first stability release.

The core design goals are unlikely to change: readable generated C, explicit ownership, deterministic cleanup, C-compatible data, and compatibility with ordinary native toolchains.

## Installation

Download the latest gen2 bundle for your platform from
[GitHub Releases](https://github.com/prodhype/Cinder/releases/latest).
Each bundle contains the `cinder` executable and the `runtime/` files that it needs to build native programs.
Keep the extracted directory together.

Current gen2 bundles are:

- [macOS ARM64](https://github.com/prodhype/Cinder/releases/latest/download/cinder-gen2-macos-arm64.tar.gz)
  ([SHA-256](https://github.com/prodhype/Cinder/releases/latest/download/cinder-gen2-macos-arm64.tar.gz.sha256))
- [Linux x86_64](https://github.com/prodhype/Cinder/releases/latest/download/cinder-gen2-linux-x86_64.tar.gz)
  ([SHA-256](https://github.com/prodhype/Cinder/releases/latest/download/cinder-gen2-linux-x86_64.tar.gz.sha256))
- [Linux ARM64](https://github.com/prodhype/Cinder/releases/latest/download/cinder-gen2-linux-arm64.tar.gz)
  ([SHA-256](https://github.com/prodhype/Cinder/releases/latest/download/cinder-gen2-linux-arm64.tar.gz.sha256))
- [Linux ARMv7](https://github.com/prodhype/Cinder/releases/latest/download/cinder-gen2-linux-armv7.tar.gz)
  ([SHA-256](https://github.com/prodhype/Cinder/releases/latest/download/cinder-gen2-linux-armv7.tar.gz.sha256))

The macOS ARM64 bootstrap seed requires macOS 15.4 or newer.

The Linux x86_64 seed and compiler bundle require glibc 2.34 or newer. Ubuntu
22.04, Debian 12, and RHEL 9 meet that baseline; Ubuntu 20.04, Debian 11, and
RHEL 8 do not. Other C libraries such as musl are not supported by that binary.

After you extract the bundle, put the extracted directory on `PATH`, or call the executable by path:

```sh
tar -xzf cinder-gen2-linux-x86_64.tar.gz
./cinder-gen2-linux-x86_64/cinder check examples/module_project
```

Put a C11 compiler on `PATH`.
Cinder checks `CC` first.
Then it checks common compiler commands for the host platform.
Select a specific compiler with `--cc`.

To build the compiler from source on macOS ARM64 15.4 or newer, or Linux x86_64
with glibc 2.34 or newer, clone the repository, install a C11 compiler, and run:

```sh
./bootstrap.sh
```

The script verifies the platform seed against `bootstrap/SHA256SUMS`, uses it to
build gen1, uses gen1 to build gen2, and requires the two generated-C trees to
match exactly. Before executing a seed, it checks the macOS deployment baseline
or Linux glibc version. Outputs are written under `.cinder/bootstrap/`.

See [`docs/self-hosting.md`](docs/self-hosting.md) and
[`bootstrap/PROVENANCE.md`](bootstrap/PROVENANCE.md) for the trust boundary and
seed provenance.

## Commands

Each command accepts a `.ci` entry file, a project directory, or a `cinder.toml` manifest.

```sh
cinder check examples/classes.ci
cinder emit-c examples/reflection.ci -o reflection.c
cinder emit-project examples/class_project -o generated
cinder build examples/class_project -o class-demo
cinder run examples/class_project
cinder context examples/class_project/src/shapes.ci:11 --depth 2
cinder impact examples/class_project/src/shapes.ci:2
cinder semantic-diff HEAD --project examples/class_project
# See also examples/large_project for an SDL2 + SDL_mixer Breakout demo.
```

`emit-c` writes one amalgamated C translation unit.
`emit-project` writes the usual per-module `.c` and `.cinder.h` tree.
`build` writes that same tree under `.cinder/<project-name>/` unless you supply `--build-dir`.
Then `build` compiles and links each generated translation unit.

`context` emits a compact compiler-derived capsule for the declaration at a
source line. `impact` reports its resolved callers, consumers, module
dependents, lock relationships, and external exposure. `semantic-diff`
compares canonical semantic facts from the working tree with a detached Git
revision. See [`docs/context-engine.md`](docs/context-engine.md) for the output
contract and current limits.

You can send compiler and linker flags (these append after any `[native]` values in `cinder.toml`):

```sh
cinder build app.ci --cc clang --cflag=-O3 --ldflag=-pthread -I vendor/include
```

Arguments after `--` go to programs that `cinder run` starts:

```sh
cinder run app.ci -- first second
```

## Language example

```python
import math


@reflect
abstract class Shape:
    name: String

    def __init__(self, name: String):
        self.name = name

    @abstractmethod
    def area(self) -> f64:
        pass

    def describe(self) -> void:
        print(f"{self.name}: {self.area():.2f}")


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
    print(f"runtime type: {type_name(shape)}")
    shape.describe()


def main() -> i32:
    circle = Circle(radius=4.0)
    describe(circle)

    for field in fields(circle):
        print(f"field: {field.name} at {field.offset}")

    return 0
```

Concrete calls stay as direct C function calls.
Only a value with type `&dyn Shape` uses an interface table.

## Classes and object layout

Classes are values.
They are not implicit heap objects.
`Circle(4.0)` sets a `Circle` value to zero first.
Then it starts the generated constructor.
Then it returns the value with ordinary C value semantics.

A class with one implementation base stores that base as its first member:

```python
class Entity:
    id: u64

class Player(Entity):
    score: i32
```

The generated layout is equivalent to this structure:

```c
typedef struct Player {
    Entity _base;
    int32_t score;
} Player;
```

`Player` has no hidden virtual pointer.
Adjustment of inherited fields and receivers is explicit in generated C.

A concrete class can have one implementation base.
It can also have multiple abstract bases that are interface-only.
The compiler rejects multiple implementation inheritance.

A concrete call uses static dispatch:

```python
def area(circle: &Circle) -> f64:
    return circle.area()
```

An explicit dynamic call uses a two-word value that does not own the object:

```python
def area(shape: &dyn Shape) -> f64:
    return shape.area()
```

The generated form is an object pointer plus a constant interface-table pointer.
Each concrete implementation writes one table for each abstract interface that it implements.
`&const dyn Interface` gives a read-only dynamic borrow.

See `docs/classes-and-interfaces.md` for constructor rules, interface-only bases, lifetime transfer, cleanup, and the generated ABI.

## Constructors, destructors, and moves

`__init__` initializes a value that already exists.
A derived constructor that has an implementation-base constructor must call `super().__init__(...)` first.

`__del__` is deterministic cleanup that the compiler manages.
The compiler drops local objects that have destructors on:

- normal block exit
- `return`
- `break`
- `continue`
- propagated `Err` returns

Locals drop in reverse declaration order.
A derived destructor runs before its implementation-base destructor.

In 0.5, classes that have destructors are move-only.
You can initialize them from constructors or from calls that return a class.
You can transfer them by return.
Reassignment evaluates the replacement, drops the old value, and transfers the replacement.
The compiler rejects implicit copies.
Match payload bindings of owning `Option` or `Result` values are not transferable.

```python
class Resource:
    def __del__(self):
        release_native_resource()


def make() -> Resource:
    resource = Resource()
    return resource
```

You can nest classes that have destructors in:

- struct and class fields
- collections
- `Option`, `Result`, and `Tuple` wrappers

You can pass them by value.
The checker looks for use after move.
Owning globals stay unsupported.
Owning union and variant payloads stay unsupported.
For AST-shaped ownership, store nodes and side tables in an arena struct and put non-owning IDs or ranges in variant payloads.

## Reflection

Runtime reflection is opt-in:

```python
@reflect
struct User:
    id: u64
    name: String
    active: bool
```

The compiler writes constant `CinderTypeInfo`, `CinderFieldInfo`, and `CinderMethodInfo` records.
Metadata does not add fields to concrete objects.
Metadata does not need registration at startup.

```python
user = User(id=42, name="Cinder", active=true)
info = type_info(user)

for field in fields(user):
    print(f"{field.name}: {field.type_name}")
```

`type_info`, `fields`, and `methods` need `@reflect`.
Concrete `type_name(value)` is compile-time text.
It does not need metadata.
Dynamic `type_name(value)` reads concrete metadata through a reflected interface table.

Compile-time queries include:

```python
static_assert(field_count(User) == 3)
static_assert(has_field(User, "name"))
static_assert(size_of(User) >= 17)

for field in comptime fields_of(User):
    print(f"{field.name}: {field.offset}")
```

The compiler implements these queries:

- `type_of`
- `type_name`
- `type_info`
- `size_of`
- `align_of`
- `field_count`
- `method_count`
- `has_field`
- `has_method`
- `implements`
- `fields`
- `methods`
- `fields_of`
- `methods_of`

The compiler unrolls compile-time member loops.
These loops do not need runtime metadata.
They do not write a runtime loop.

See `docs/reflection.md` for metadata fields, binary-size costs, static-assert behavior, and current limits.

## Projects and modules

A project uses a `cinder.toml` file:

```toml
[project]
name = "example"
source-root = "src"
entry = "main.ci"

[native]
libraries = ["SDL2"]
include-dirs = ["third_party/sdl2/include"]
library-dirs = ["third_party/sdl2/lib"]
```

Optional `[native]` supplies include dirs, library search paths, short `-l` names, explicit `link-files` (static archives for single-binary builds), and raw `cflags` / `ldflags`. Relative paths resolve from the project root. CLI `-I` / `--cflag` / `--ldflag` append after the manifest. See `docs/modules.md`.

A usual tree is:

```text
example/
    cinder.toml
    src/
        main.ci
        geometry.ci
        support/
            parsing.ci
```

Module names come from paths below the source root.
`geometry.ci` is `geometry`.
`support/parsing.ci` is `support.parsing`.
`support/__init__.ci` is `support`.

```python
import geometry
import support.parsing as parsing
from geometry import Vec2, distance
```

Cinder finds the full acyclic dependency graph.
Then it checks and writes modules in dependency order.
Built-in modules such as `stdio` and `math` do not resolve to local files unless a local module shadows them.

Generated module headers contain:

- public nominal layouts
- callable declarations
- dynamic interface types and tables
- class constructor and drop declarations
- reflected metadata declarations

Internal C names get a deterministic project-and-module prefix.
`main` in the entry module keeps an externally callable C name.
Functions with `@export` also keep externally callable C names.

For a project with modules `geometry` and `main`, `emit-project` writes:

```text
generated/
    cinder_gen/
        geometry.c
        geometry.cinder.h
        main.c
        main.cinder.h
```

Generated headers are valid C11.
They include C++ linkage guards for callable declarations.

## Enums, unions, variants, and match

Enums are ordinary C enums with distinct integer values:

```python
enum ParseError:
    invalid
    overflow = 4
```

Plain unions keep ordinary C union semantics:

```python
union Number:
    integer: i64
    real: f64

number = Number(integer=42)
```

Variants use an explicit tag and a payload union:

```python
variant Token:
    Identifier(text: const char*)
    Integer(value: i64)
    Plus
    End

token = Token.Integer(42)
```

`match` accepts enums, variants, Results, and Options.
Matches must be exhaustive unless the remaining cases are covered by an
unguarded wildcard or equivalent pattern. Guards refine a case but do not count
toward exhaustiveness on their own.

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

Patterns can destructure nested algebraic payloads, use `_` discards, combine
alternatives with `|`, guard a case with `if`, and capture a value with
`name @ pattern`:

```python
match parsed:
    case Some(Ok(score)) if score > 0:
        consume_score(score)
    case Some(Err(_)) | None:
        recover()
    case original @ Some(Ok(_)):
        inspect(original)
```

Patterns do not yet support literals, tuple destructuring, struct destructuring,
or match expressions.

## Typed Results, Options, and propagation

The compiler supplies these built-in types and generic families:

- `Result[T, E]`
- `Option[T]`
- `Owned[T]`
- `Tuple[...]`
- `String`
- `List[T]`
- `Map[K, V]`
- `Set[T]`

User-defined generics on structs, classes, enums, unions, variants, and free functions become specialized C that you can read.

```python
def parse(value: i32) -> Result[i32, ParseError]:
    if value < 0:
        return Err(ParseError.invalid)
    return Ok(value)


def increment(value: i32) -> Result[i32, ParseError]:
    parsed = parse(value)?
    return Ok(parsed + 1)
```

`Ok` and `Err` are contextual constructors.
Postfix `?` evaluates its operand one time.
Then it checks the explicit tag.
On error it runs active deferred calls, List cleanup, and class drops.
Then it does an ordinary early return.

`?` is not accepted in these places, so C evaluation order stays clear:

- `while` conditions
- `elif` conditions
- C-style loop conditions or updates
- the right side of `and` or `or`
- deferred calls

`Option[T]` is an optional value.
It does not use pointer nullability.
`Some(value)` can infer its payload when possible.
Bare `None` needs an Option context.
Matches must cover both cases.
`.is_some`, `.is_none`, and checked `.value` access are available.
Postfix `?` stays Result-only.

`Owned[T]` is a move-only heap owner.
`Owned(value)` allocates and moves a value onto the heap.
Unary `*` gives an addressable payload.
Drop frees after it drops `T`.
Recursive layouts such as `Option[Owned[Node]]` are supported.

## Strings

`String` is Cinder's primary text type.
An ordinary string literal has type `String`.
An explicit `const char*` context still produces a low-level C string for interoperability:

```python
name = "Cinder"
c_name: const char* = "Cinder"
```

`String` owns UTF-8 text and is move-only.
Its runtime shape is conceptually a data pointer, byte length, and capacity; that description is not a stable pre-1.0 ABI promise.
Scope exit drops the active value deterministically.
A static literal can share static storage until a mutation needs an owned buffer, so creating a literal does not require an immediate allocation.
Copying is explicit with `clone()`.

`len(text)` returns the number of UTF-8 bytes, not the number of Unicode scalar values or grapheme clusters.
Owned Strings cannot contain embedded NUL bytes, so every FFI borrow preserves the complete text; use `List[u8]` for arbitrary bytes.
Strings do not support direct indexing.
Use `byte_at(index)` for one byte.
A slice such as `text[start:stop]` creates a copied `String`; both indices must be in range and on UTF-8 boundaries.

```python
text = "Cin"
text.append("der")
text.reserve(32)
copy = text.clone()
joined = text + " language"
text.clear()
```

`append`, `reserve`, and `clear` mutate an addressable `String`.
Concatenation with `+` borrows both operands and returns a fresh `String`.
String comparisons and `sort` use lexicographic UTF-8 byte content.

`StringBuilder` supports `append`, ASCII `append_char`, and `reserve` for incremental construction.
`finish()` consumes the builder and returns its completed `String`.

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

Pointers and references use prefix syntax.
C-style postfix pointer syntax is also accepted when it helps you copy C declarations.

```python
pointer: *i32 = &value
argv: **char
c_name: const char* = "Cinder"


def increment(value: &i32) -> void:
    value += 1
```

References compile to pointers.
Inside Cinder expressions they are transparent.
The checker rejects null reference initialization.
It needs an addressable value when you form a reference.

Function pointer types use `def` parameter and return syntax.
They compile to ordinary C function pointers.
Named free functions decay to that type without `&`.
You can store them, pass them, and call them like values:

```python
def double(n: i32) -> i32:
    return n * 2


def apply(f: def(i32) -> i32, x: i32) -> i32:
    return f(x)


callback = double
result = apply(callback, 21)
```

Closures use explicit environment structs and env-first adapter functions.
They are distinct from plain function pointers:

```python
struct AddEnv:
    delta: i32


def add_impl(env: &const AddEnv, value: i32) -> i32:
    return value + env.delta


callback: closure[const AddEnv](i32) -> i32 = closure(AddEnv(delta=2), add_impl)
result = callback(40)
```

The adapter must be a non-generic, non-variadic free function whose first
parameter is `&Env` or `&const Env`.
The closure owns its environment value; store borrowed state explicitly inside
the environment struct with reference fields.
Bound methods are not closure values yet.

Fixed arrays and slices are distinct:

```python
values: i32[4] = [10, 20, 30, 40]
view: []i32 = values[1:]
```

A slice is a typed `{data, length}` struct.
You can pass mutable arrays and slices to const slice parameters without a copy.
Slicing and indexing do no bounds checks at this time.

Tuples are immutable heterogeneous values:

```python
entry: Tuple[i32, String] = (7, "ready")
code = entry[0]
```

Tuple indices must be integer literals.
Empty and singleton tuples use `()` and `(value,)`.

Lists are homogeneous owning buffers.
An untyped square-bracket literal infers a list.
An explicit fixed-array annotation keeps fixed storage:

```python
fixed: i32[3] = [3, 1, 2]
values = [3, 1, 2]
values.append(4)
sort(values)
last = values.pop()
```

Lists are move-only owners of their buffers.
The runtime frees them on each normal cleanup path.
You can nest them.
You can store them in struct and class fields.
You can pass and return them by value.
They can hold other owning values.
Transfers mark the source as moved.
You can also pass addressable Lists without a copy to `[]T` and `[]const T` parameters.
This coercion is for calls only.
Structural operations still use `&List[T]`.
Owning globals stay unsupported.
Use arena-owned lists plus non-owning IDs/ranges for AST-like recursive data.

Maps use `{key: value}` literals and keep insertion order.
Sets use `{value, ...}`.
An empty Set uses contextual `set()`.
Empty `{}` needs a `Map[K, V]` context.

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

`in` and `not in` test Map keys and Set elements.
Maps give `keys()`, `values()`, and `items()` as live views that do not own.
Default Map iteration yields keys.
Sets give union, intersection, difference, symmetric difference, and subset and superset comparisons.

Hashable types are integers, `bool`, `char`, enums, `String`, and low-level `const char*`.
Maps and Sets hash and compare `String` values by UTF-8 byte content, not buffer identity.
They clone String keys or elements on insertion so later mutation of the source cannot change collection membership.
Removing a `String` from an owning collection transfers the value; its eventual cleanup remains deterministic.

Maps and Sets use the same move-only ownership model as Lists.
This includes nested and aggregate ownership and by-value parameters.
Owning globals stay unsupported.
Owning union and variant payloads stay unsupported.
AST-shaped data should use arena-owned storage with non-owning payload handles.
Map views are borrowed values with slice-like lifetime duty.
Structural mutation is rejected or guarded while an iterator is active.

## Structs and methods

Structs have layout that is compatible with C.
They have no inheritance and no dynamic dispatch.

```python
struct Counter:
    value: i32

    def add(self, amount: i32) -> void:
        self.value += amount
```

An omitted `self` annotation is inferred as `&Counter`.
`self: &const Counter` makes a const method.
Calls compile to direct C functions.

Struct construction checks field initialization:

```python
counter = Counter(value=0)
```

Named arguments are reordered at compile time.
Omitted fields are set to zero.

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

`range` accepts one, two, or three integer arguments.
Expressions evaluate one time before the loop.
A zero step is rejected when it is a literal.
A zero step starts `panic` when the runtime finds it.

Locals use lexical block scope.
This matches generated C.
It does not match Python function-wide local scope.

## Compile-time lock ordering

Declare lock relationships as a partial-order graph:

```python
lock database
lock cache after database

def update() -> void:
    CriticalSection database:
        CriticalSection cache:
            pass
```

The compiler infers safe nested relationships and checks function lock effects.
It rejects reverse acquisition and graph cycles.
Use `lockorder module.first before other.second` to add a cross-module relationship.

Use `sorted(locks)` before a dynamic critical section.
Cinder uses a hidden canonical order and ignores duplicate lock identities during acquisition.
It releases locks in reverse order.
The language does not expose a numeric lock rank.

```python
CriticalSection sorted(locks):
    work()
```

All critical sections use the normal lexical cleanup paths.

## Allocation and `defer`

Cinder has no garbage collector.
It has no ownership inference.

```python
values = alloc[i32](count)
defer free(values)
```

`alloc[T](count)` calls the small runtime allocation helper.
It checks multiplication overflow and allocation failure.
It returns `*T`.
`alloc[T]()` allocates one element.
Memory is not initialized, as with C `malloc`.

`defer` registers a call for the end of the current lexical scope.
Deferred calls run in reverse declaration order on normal exit and on all supported early exits.
Return values go into a temporary before cleanup runs.
Deferred call arguments evaluate when cleanup runs.
They do not evaluate when `defer` is found.

## C interoperability

You can include a C header directly:

```python
extern import "sqlite3.h"
```

Checked declarations use an explicit ABI block:

```python
extern "C":
    type sqlite3
    def sqlite3_open(filename: const char*, database: **sqlite3) -> c_int
```

The compiler does not parse arbitrary C headers.
`extern import` controls inclusion.
`extern "C"` supplies the signatures that Cinder checks.
Declare opaque C types with `type Name`, or let unknown names in extern signatures become opaque automatically.
Opaque types are exported across modules like other module types.
The compiler writes their C names without change.

External signatures remain explicit C ABI types.
`String` does not replace `const char*` in an `extern "C"` declaration.
At an extern or compiler-provided builtin call boundary, a `String` argument can implicitly borrow as `const char*`.
That pointer exists only for the call: it cannot be assigned, stored, or returned.
There is no implicit conversion from `const char*` to `String`; use an API that explicitly copies and validates external text.

Built-in modules map common C APIs into checked namespaces.
`math` is one example; `stdio` remains available when you need the C API directly:

```python
import math

print(f"{math.sqrt(9.0):.2f}")
```

For common console output, `print(...)` is available without an import:

```python
name = "Ada"
score: i32 = 42
values = [1, 2, 3]
print(f"{name}: {score:x}")
print(values)
```

`print` separates multiple arguments with spaces.
It adds a newline.
It supports f-string replacement fields with simple format specs.
Lists, Maps, Sets, and Tuples print with Python-like collection syntax when their nested element types are printable.
`String` arguments are borrowed rather than consumed.
F-strings are limited to `print` arguments at this time.

For console input, `input()` is also available without an import.
`input(prompt)` writes the prompt without a newline.
It reads one line.
It returns that line without the trailing newline:

```python
name = input("name: ")
print("hello", name)
```

Parsing and formatting helpers are also global.
`input` returns a `String`.
These functions return `Result[T, ConvertError]` after a full-token parse:

- `parse_i32`
- `parse_i64`
- `parse_u32`
- `parse_u64`
- `parse_isize`
- `parse_usize`
- `parse_f32`
- `parse_f64`
- `parse_bool`

Failure cases are `empty`, `invalid`, or `overflow`.
The parse helpers borrow their `String` argument.
`to_string(value)` formats integers, floats, `bool`, and `char` into a `String`:

```python
match parse_i32(name):
    case Ok(value):
        text = to_string(value)
        print(text)
    case Err(error):
        print(cast[i32](error))
```

`open(path, mode)` borrows its `String` arguments and returns a move-only `File`.
`File.write` accepts borrowed `String` text as well as byte slices.
`File.read_line()` returns `Option[String]`: immediate EOF is `None`, while a blank line is `Some("")`.
`File.read_text()` reads the remaining bytes and validates UTF-8 before returning `String`.
Use `File.read_all()` when arbitrary bytes are required; it continues to return `List[u8]`.

The builtin `process` module runs shell-free argv vectors and captures the
child's exit status, stdout, and stderr as owned values:

```python
import process

command: List[String] = ["cc", "--version"]
result = process.run(command)
if result.exit_code != 0:
    print(result.stderr)
```

The initial runtime implementation supports POSIX platforms. Windows builds
compile the API but currently return an unsupported result.

`@export` keeps the C symbol name of a top-level function:

```python
@export
def engine_update(delta_time: f64) -> void:
    update_world(delta_time)
```

## Unsafe casts

Numeric casts and compatible pointer casts are allowed directly.
Pointer and integer casts need an explicit block.
Unrelated pointer reinterpretation also needs an explicit block:

```python
unsafe:
    byte_pointer = cast[*u8](address)
```

This makes dangerous code visible.
It does not make raw pointer operations safe in memory.
See `examples/unsafe.ci` for a runnable raw-address example.

## Project layout

The repository layout is:

```text
bootstrap/
    darwin-arm64/cinder
    linux-x86_64/cinder
    SHA256SUMS
    PROVENANCE.md
compiler_selfhost/
    cinder.toml
    src/
runtime/
    cinder_runtime.h
    cinder_runtime.c
examples/
tests/
docs/
```

## Self-hosting

The checked-in platform seed builds gen1 from `compiler_selfhost/`; gen1 builds
gen2 from the same sources. Bootstrap succeeds only when gen1 and gen2 emit
identical generated-C project trees. The seed is a trusted construction
artifact; the Cinder source is the compiler implementation. GitHub Actions uses
the fixed-point gen2 compiler to publish native bundles.

See [`docs/self-hosting.md`](docs/self-hosting.md) for the complete proof and
ownership constraints that still apply.

## Development

Run the native bootstrap, fixed-point proofs, Cinder test runner, and 41-target
example smoke suite with:

```sh
./test.sh
```

The suite compiles generated C and runs native programs. It also checks:

- seed integrity and the gen1/gen2 generated-C fixed point
- direct compilation of the generated compiler sources
- native compiler execution without an external language runtime
- cross-module class and interface ABI behavior
- deterministic C emission and key generated-C properties

CI runs the native suite on macOS ARM64 and Linux x86_64. Separate workflows
build gen2 bundles for macOS ARM64 and Linux x86_64, ARM64, and ARMv7; the ARM
Linux bundles are cross-built from the verified Linux x86_64 compiler.

## Design constraint

Readers must understand Cinder from the generated C.
Features that need hidden allocation are excluded for now.
Features that need unpredictable dispatch are excluded for now.
Features that need exception unwinding are excluded for now.
Features that need implicit object lifetimes are excluded for now.
Features that need a mandatory garbage collector are excluded for now.
Such features stay out until a design can keep that rule.
