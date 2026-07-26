# Cinder language design

> Implementation status: Cinder 0.5 completes the procedural core, local modules, algebraic data, typed Results, classes, abstract interfaces, explicit dynamic dispatch, deterministic class cleanup, opt-in runtime reflection, static assertions, compile-time member inspection, native tuples, and owning lists. User-defined generics, maps, sets, and the more expansive metaprogramming ideas remain proposals.

This is a language that compiles to portable C11, not a modification of the C standard. Trying to make whitespace significant while remaining valid C would create a preprocessing mess and poor tooling compatibility.

## Design goals

Cinder preserves the useful parts of C:

* Predictable native performance
* Explicit, deterministic resource cleanup
* C-compatible structs, functions, pointers, and libraries
* No mandatory garbage collector
* Portable C11 output
* Straightforward generated code
* Easy embedding into existing C projects

The surface language borrows from Python:

* Indentation-based blocks
* Newline-terminated statements
* `def`, `class`, `if`, `elif`, `else`, `while`, and `for`
* Explicit `self`
* Type annotations
* Abstract base classes
* Constructors and destructors
* Opt-in runtime reflection
* Named arguments
* Method syntax
* Semantic imports between Cinder modules instead of textual source inclusion

It does not inherit Python's dynamic type system, monkey patching, reference counting, global interpreter lock, or unpredictable allocation behavior.

## Example

```python
import math
import stdio

struct Vec2:
    x: f32
    y: f32

    def length(self: &const Vec2) -> f32:
        return math.sqrt(self.x * self.x + self.y * self.y)


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


def print_shape(shape: &dyn Shape) -> void:
    shape.describe()
    stdio.printf("runtime type: %s\n", type_name(shape))


def main(argc: i32, argv: **char) -> i32:
    circle = Circle(radius=4.0)
    print_shape(circle)

    for field in fields(circle):
        stdio.printf("field: %s\n", field.name)

    return 0
```

## Type system

Typing is static. Top-level globals require explicit types. Parameters require
annotations except for a method's first `self` parameter, whose owner type is
inferred. An omitted function return type defaults to `void`.

```python
count: i32 = 10
temperature: f64 = 72.5
name: const char* = "Cinder"
```

Local variable types may be inferred:

```python
count = 10
temperature = 72.5
```

The primitive types are explicit:

```python
bool
char

i8
i16
i32
i64

u8
u16
u32
u64

f32
f64

isize
usize

void
```

C-compatible aliases are provided:

```python
c_int
c_long
c_size_t
```

This avoids platform-dependent surprises from C's `int`, `long`, and `char` rules while preserving exact C interoperability when needed.

## Pointers and references

Raw pointers are available:

```python
value: i32 = 10
pointer: *i32 = &value

pointer[0] = 20
```

References provide non-null borrowed access:

```python
def increment(value: &i32) -> void:
    value += 1
```

Const references:

```python
def magnitude(vector: &const Vec2) -> f32:
    return vector.length()
```

A reference is still represented as a pointer in generated C, but the compiler rejects null assignment and certain unsafe operations.

Casts between integers and pointers, or between unrelated pointer types, require an
explicit `unsafe` block:

```python
def write_byte(address: usize) -> void:
    unsafe:
        pointer = cast[*u8](address)
        pointer[4] = 255
```

Numeric casts and compatible pointer casts do not require `unsafe`. Raw pointer
access has no implicit bounds or lifetime checks; the block only makes dangerous
reinterpretation visible.

## Arrays and slices

Fixed arrays have a compile-time length and use ordinary C array storage:

```python
values: i32[4] = [1, 2, 3, 4]
```

They support indexing, iteration, `len`, and slicing. As in C, a fixed array cannot be
assigned after its declaration or returned by value.

A slice is a non-owning view represented by a pointer and a length:

```python
def sum(values: []const i32) -> i64:
    total: i64 = 0

    for value in values:
        total += value

    return total
```

The compiler generates a concrete C struct for each slice element type. For
`[]const i32`, that struct is equivalent to:

```c
typedef struct CinderSlice_const_i32 {
    const int32_t *data;
    size_t length;
} CinderSlice_const_i32;
```

Compatible arrays convert to slices automatically, and mutable slices convert to
const slices. `value[:]`, `value[start:]`, and `value[start:stop]` create subviews;
slice steps are not implemented. Indexing and slicing compile to direct C access and
pointer arithmetic, with no implicit bounds checks.

## Tuples and lists

`Tuple[...]` is a compiler-specialized heterogeneous value aggregate. Tuple layout is explicit in generated C, tuple elements are immutable, and indices must be compile-time integer literals.

```python
entry: Tuple[i32, const char*] = (7, "ready")
code = entry[0]
```

`List[T]` is a homogeneous owning buffer specialized for `T`. It is represented as a generated `{data, length, capacity}` struct and uses the small Cinder runtime only for checked allocation and growth.

```python
values: List[i32] = []
for value in range(0, 20):
    values.append(value)
last = values.pop()
```

List ownership follows the existing explicit move-only direction. A direct local owns its buffer, a direct return transfers it, replacement drops the previous buffer, and all normal scope exits free it. Generic element-processing functions can accept `[]T` or `[]const T`; addressable Lists, fixed arrays, and slices all pass to those parameters without copying. List-to-slice coercion is call-only so a borrowed view cannot be stored or returned implicitly. Mutable slices can update elements, while structural operations use `&List[T]`. Nested lists, aggregate list fields, globals, by-value parameters, and destructor-bearing elements wait for a broader aggregate ownership model.

Square-bracket literals infer lists in untyped contexts. An explicit array type still selects fixed C storage, so `values: i32[3] = [1, 2, 3]` remains an array declaration. Maps and sets are intentionally deferred until hashing and equality constraints are defined.

## Structs

A `struct` has no virtual dispatch or inheritance.

```python
struct Rectangle:
    width: f64
    height: f64

    def area(self: &const Rectangle) -> f64:
        return self.width * self.height
```

Methods use static dispatch and compile to namespaced functions. For example:

```c
double Rectangle_area(const Rectangle *self);
```

Structs can be initialized by named field. Arguments are reordered by the checker,
and omitted fields are zero-initialized:

```python
def make_rectangle() -> Rectangle:
    return Rectangle(
        width=20.0,
        height=10.0
    )
```

## Classes

Classes are values with constructors, destructors, private fields, and single
implementation inheritance. Constructing a class produces a zero-initialized value
and calls `__init__`; it does not allocate implicitly.

```python
import stdio

class File:
    private handle: *stdio.FILE

    def __init__(self, path: const char*, mode: const char*):
        self.handle = stdio.fopen(path, mode)

        if self.handle == null:
            panic("could not open file")

    def __del__(self):
        if self.handle != null:
            stdio.fclose(self.handle)
```

For a local destructor-bearing value, the compiler calls `__del__` on every normal
scope exit, including early returns and Result propagation. Such classes are
move-only in 0.5: implicit copies, by-value parameters, globals, arrays, variants,
Results, and other owning aggregates are rejected. `__del__` cannot be called
directly.

Cinder supports one implementation base. A stateful abstract base counts as that
base; additional abstract bases must be interface-only, with no fields, constructor,
or destructor. Each interface-only base uses a separate interface table rather than
adding another object subobject.

## Abstract base classes

```python
import stdio

abstract class Reader:
    @abstractmethod
    def read(self, output: []u8) -> usize:
        pass

    def read_exact(self, output: []u8) -> bool:
        offset: usize = 0

        while offset < output.length:
            count = self.read(output[offset:])

            if count == 0:
                return false

            offset += count

        return true
```

A concrete implementation must provide every abstract method:

```python
class FileReader(Reader):
    handle: *stdio.FILE

    def read(self, output: []u8) -> usize:
        return stdio.fread(
            output.data,
            1,
            output.length,
            self.handle
        )
```

Failure to implement an abstract method is a compile-time error.

Dynamic dispatch is explicit in function signatures:

```python
def consume(reader: &dyn Reader) -> void:
    buffer: u8[4096]
    count = reader.read(buffer[:])
```

Using `dyn` tells the programmer that an interface-table call is involved. A dynamic
value is a non-owning object-and-table pair, and conversion requires an addressable
concrete object. Methods declared on concrete classes, including override
implementations, use direct static calls. Default methods declared on an abstract
class receive dynamic `self`; calling one through a concrete value still uses the
interface table so calls it makes to abstract methods remain dynamic.

## Introspection

Full Python-style introspection is incompatible with zero-overhead C unless the compiler emits runtime metadata. Cinder therefore separates opt-in runtime reflection from compile-time inspection.

```python
import stdio

@reflect
class User:
    id: u64
    name: const char*
    active: bool
```

Runtime reflection is explicit and typed:

```python
def print_user(value: &const User) -> void:
    info = type_info(value)
    stdio.printf("type: %s\n", info.name)

    for field in fields(value):
        stdio.printf(
            "%s at offset %zu\n",
            field.name,
            field.offset,
        )
```

The compiler emits constant `CinderTypeInfo`, `CinderFieldInfo`, and `CinderMethodInfo` records. Metadata adds no field to concrete objects. A reflected dynamic interface stores the concrete type-info pointer in its interface table.

Compile-time inspection is broader because it does not require runtime metadata:

```python
static_assert(field_count(User) == 3)
static_assert(has_field(User, "name"))

def print_layout() -> void:
    for field in comptime fields_of(User):
        stdio.printf("%s: %zu\n", field.name, field.offset)
```

Runtime metadata operations are:

```python
type_name(expression)
type_info(expression)
fields(expression)
methods(expression)
```

Concrete `type_name` is compile-time text. Dynamic `type_name`, `type_info`, `fields`,
and `methods` require a reflected type or interface. Implementations of a reflected
abstract interface must also be marked `@reflect`.

Compile-time operations are:

```python
type_of(expression)
size_of(Type)
align_of(Type)
field_count(Type)
method_count(Type)
fields_of(Type)
methods_of(Type)
implements(ConcreteClass, AbstractClass)
has_field(Type, "name")
has_method(Type, "serialize")
```

Compile-time inspection does not emit per-object metadata. Member loops must appear
inside a function and are unrolled into ordinary C blocks. See `docs/reflection.md`
for the exact metadata ABI and limits.

## Memory management

Cinder does not perform automatic ownership inference or hide heap allocation.
`alloc[T]` returns uninitialized storage, and `free` releases it:

```python
def initialize(count: usize) -> void:
    values = alloc[i32](count)
    defer free(values)

    for index in range(0, count):
        values[index] = 0
```

`defer` accepts a call and runs deferred calls in reverse declaration order on normal
scope exit, `return`, `break`, `continue`, and Result propagation:

```python
enum ProcessError:
    empty_input


def process_values(count: usize) -> Result[void, ProcessError]:
    if count == 0:
        return Err(ProcessError.empty_input)

    buffer = alloc[u8](count)
    defer free(buffer)
    buffer[0] = 0

    return Ok()
```

Class values with `__del__` use compiler-managed scope cleanup instead. `defer` is
for resources that are not already owned by such a class.

## Error handling

Cinder does not implement native exceptions. Supporting them would require hidden
control flow, unwinding metadata, or `setjmp` and `longjmp`, none of which fit the
language's generated-C model.

Cinder uses typed Results:

```python
enum ParseError:
    negative
    too_large


def parse_number(value: i32) -> Result[i32, ParseError]:
    if value < 0:
        return Err(ParseError.negative)
    if value > 100:
        return Err(ParseError.too_large)

    return Ok(value)
```

The postfix `?` propagates a compatible error from a function that also returns a
Result:

```python
def increment(value: i32) -> Result[i32, ParseError]:
    number = parse_number(value)?
    return Ok(number + 1)
```

Results compile to tagged structs. Propagation evaluates its operand once, runs
active cleanup on error, and emits an ordinary early return. It is rejected in
expression contexts where inserting that return would obscure short-circuit or
repeated evaluation; see `docs/algebraic-types.md` for the complete rules.

## Control flow

```python
if value < 0:
    handle_negative(value)
elif value == 0:
    handle_zero()
else:
    handle_positive(value)
```

```python
while connection.is_open():
    connection.poll()
```

```python
for index in range(0, 10):
    stdio.printf("%d\n", index)
```

```python
for value in values:
    process(value)
```

C-style loops are available for low-level code:

```python
for i: usize = 0; i < count; i += 1:
    process(values[i])
```

This is one of the few places where semicolons are syntactically meaningful.

## Pattern matching

Cinder implements exhaustive `match` for enums, variants, and Results:

```python
match result:
    case Ok(value):
        use(value)

    case Err(error):
        report(error)
```

Every case must be covered. A final `_` wildcard can cover the remaining cases;
guards, literal patterns, and nested patterns are not implemented.

Enums use distinct integer values:

```python
enum TokenKind:
    identifier
    integer
    string
    plus
    minus
```

Plain unions map directly to untagged C unions and cannot be matched:

```python
union TokenValue:
    integer: i64
    string: const char*
```

Variants combine a tag with checked payloads and support construction and matching:

```python
variant Token:
    Identifier(text: const char*)
    Integer(value: i64)
    String(value: const char*)
    Plus
    Minus

def integer_token(value: i64) -> Token:
    return Token.Integer(value)
```

## C interoperability

`extern import` emits a C `#include`:

```python
extern import "SDL2/SDL.h"
extern import "sqlite3.h"
```

The compiler does not parse arbitrary headers. An `extern "C"` block supplies the
signatures Cinder checks; otherwise unknown types in these declarations are emitted
as opaque C types:

```python
extern "C":
    def sqlite3_open(
        filename: const char*,
        database: **sqlite3
    ) -> c_int
```

`@export` preserves the C symbol name of a top-level Cinder function:

```python
@export
def seconds(milliseconds: f64) -> f64:
    return milliseconds / 1000.0
```

The generated symbol uses the C calling convention and remains callable from C,
C++, Rust, Python extensions, or other FFI-compatible languages.

## Modules

```python
from engine.math import Vec3
from engine.memory import Arena
import stdio
```

A source file is a module. Cinder imports are semantic rather than textual; Cinder
source has no `#include` equivalent.

Imports form a checked acyclic dependency graph. A `cinder.toml` manifest can define
the project name, source root, and entry module; file and directory inputs also use
the documented project-discovery rules.

Each source module emits one generated header and one C translation unit under
`cinder_gen`. All top-level Cinder declarations are module-visible in 0.5.
`@export` is separate: it preserves a top-level function name for external C callers.
C headers remain available through `extern import`.

## Compiler architecture

The compiler requires Python 3.14+ and emits readable C11.

```text
source
  -> indentation-aware tokenizer
  -> parser
  -> AST
  -> symbol resolution
  -> type checking
  -> typed intermediate representation
  -> C11 emitter
  -> system C compiler
```

The implementation has these core components:

```text
cinder/
    __init__.py
    __main__.py
    lexer.py
    parser.py
    ast.py
    types.py
    symbols.py
    checker.py
    ir.py
    codegen_c.py
    stdlib.py
    project.py
    diagnostics.py
    compiler.py
    toolchain.py
    cli.py
    runtime/
        cinder_runtime.h
        cinder_runtime.c
```

The CLI accepts a source file, project directory, or manifest:

```text
cinder build src/main.ci
cinder run src/main.ci
cinder check src/main.ci
cinder emit-c src/main.ci
cinder emit-project . -o generated
```

## Implemented milestones

The first usable compiler milestone established indentation parsing, primitive types, functions, native control flow, structs and methods, pointers, arrays, slices, C imports, and readable C11 generation. Cinder 0.2 added manifest-driven modules and per-module C output. Cinder 0.3 added enums, unions, variants, exhaustive matching, typed Results, and propagation. Cinder 0.4 established the class and interface ABI. Cinder 0.5 added opt-in runtime metadata and compile-time member inspection. Native tuples and lists extend those built-in type-specialization patterns without introducing user-defined generics.

User-defined generics, maps and sets, function pointer types, richer ownership abstractions, closures, and broader compile-time execution remain later work.

The crucial constraint remains this: Cinder must be understandable by reading its
generated C. Hidden allocation, unpredictable dispatch, exception machinery, or
implicit object lifetimes would turn it from Python-shaped C into a much more
complicated systems language.
