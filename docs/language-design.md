# Cinder language design

> Implementation status: Cinder 0.5 completes the procedural core, local modules, algebraic data, typed Results, classes, abstract interfaces, explicit dynamic dispatch, deterministic class cleanup, opt-in runtime reflection, static assertions, and compile-time member inspection. General-purpose generics and the more expansive metaprogramming ideas remain proposals.

This should be a new language that compiles to portable C11, not a modification of the C standard. Trying to make whitespace significant while remaining valid C would create a preprocessing mess and poor tooling compatibility.

Call it `Cinder` for now.

## Design goals

Cinder should preserve the useful parts of C:

* Predictable native performance
* Deterministic memory management
* C-compatible structs, functions, pointers, and libraries
* No mandatory garbage collector
* Portable C11 output
* Straightforward generated code
* Easy embedding into existing C projects

The surface language should borrow from Python:

* Indentation-based blocks
* Newline-terminated statements
* `def`, `class`, `if`, `elif`, `else`, `while`, and `for`
* Explicit `self`
* Type annotations
* Abstract base classes
* Constructors and destructors
* Optional runtime introspection
* Named arguments
* Method syntax
* Modules instead of header files

It should not inherit Python's dynamic type system, monkey patching, reference counting, global interpreter lock, or unpredictable allocation behavior.

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


def main(argc: i32, argv: **char) -> i32:
    circle = Circle(radius=4.0)
    circle.describe()

    stdio.printf("runtime type: %s\n", type_name(circle))

    for field in fields(circle):
        stdio.printf("field: %s\n", field.name)

    return 0
```

## Type system

Typing should be static and mandatory for public declarations.

```python
count: i32 = 10
temperature = 72.5
name: const char* = "Cinder"
```

Local variable types may be inferred:

```python
count = 10
temperature = 72.5
```

The primitive types should be explicit:

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

C-compatible aliases can still exist:

```python
c_int
c_long
c_size_t
```

This avoids platform-dependent surprises from C's `int`, `long`, and `char` rules while preserving exact C interoperability when needed.

## Pointers and references

Raw pointers should remain available:

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

Unsafe pointer operations should be explicit:

```python
unsafe:
    pointer = cast[*u8](address)
    pointer[4] = 255
```

This is not intended to make C memory-safe. It merely makes dangerous operations visible.

## Arrays and slices

C arrays remain fixed-size values:

```python
values: i32[16]
```

Slices should be built into the language:

```python
def sum(values: []const i32) -> i64:
    total: i64 = 0

    for value in values:
        total += value

    return total
```

A slice compiles to something equivalent to:

```c
typedef struct {
    const int32_t *data;
    size_t length;
} CinderSliceI32;
```

This eliminates the constant `pointer, length` pairing found in normal C APIs.

## Structs

A `struct` has no virtual dispatch or inheritance.

```python
struct Rectangle:
    width: f64
    height: f64

    def area(self: &const Rectangle) -> f64:
        return self.width * self.height
```

Methods are syntax sugar for namespaced functions. The generated function might look like:

```c
double Rectangle_area(const Rectangle *self);
```

Structs can be initialized by field:

```python
rectangle = Rectangle(
    width=20.0,
    height=10.0
)
```

## Classes

Classes add constructors, destructors, private fields, inheritance, and virtual methods.

```python
class File:
    private handle: *FILE

    def __init__(self, path: const char*, mode: const char*):
        self.handle = stdio.fopen(path, mode)

        if self.handle == null:
            panic("could not open file")

    def __del__(self):
        if self.handle != null:
            stdio.fclose(self.handle)
```

Cinder should support single implementation inheritance only. Multiple inheritance creates layout, destructor, pointer-adjustment, and ABI problems that are not worth importing into a C-oriented language.

Multiple abstract base classes can be supported because they are represented as interface tables rather than inherited object layouts.

## Abstract base classes

```python
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
    handle: *FILE

    def read(self, output: []u8) -> usize:
        return stdio.fread(
            output.data,
            1,
            output.length,
            self.handle
        )
```

Failure to implement an abstract method is a compile-time error.

Dynamic dispatch should be explicit in function signatures:

```python
def consume(reader: &dyn Reader) -> void:
    buffer: u8[4096]
    count = reader.read(buffer[:])
```

Using `dyn` tells the programmer that a vtable call is involved. Without `dyn`, the compiler uses static dispatch whenever the concrete type is known.

## Introspection

Full Python-style introspection is incompatible with zero-overhead C unless the compiler emits runtime metadata. Cinder therefore separates opt-in runtime reflection from compile-time inspection.

```python
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

for field in comptime fields_of(User):
    stdio.printf("%s: %zu\n", field.name, field.offset)
```

Implemented operations include:

```python
type_of(expression)
type_name(expression)
type_info(expression)
size_of(Type)
align_of(Type)
field_count(Type)
method_count(Type)
fields(expression)
methods(expression)
fields_of(Type)
methods_of(Type)
implements(Type, Interface)
has_field(Type, "name")
has_method(Type, "serialize")
```

Runtime `type_info`, `fields`, and `methods` require `@reflect`. Concrete `type_name` is compile-time text; dynamic `type_name` requires a reflected interface. Compile-time member loops are unrolled into ordinary C. See `docs/reflection.md` for the exact metadata ABI and limits.

## Memory management

The initial language should not attempt automatic ownership inference. That would turn this into a Rust-scale project.

Use C allocation with better syntax:

```python
user = alloc[User]()
defer free(user)
```

Array allocation:

```python
values = alloc[i32](count)
defer free(values)
```

Scoped cleanup:

```python
def process_file(path: const char*) -> Result[void, Error]:
    file = File(path, "rb")
    defer file.close()

    buffer = alloc[u8](4096)
    defer free(buffer)

    return Ok()
```

`defer` is much more valuable for C code than pretending destructors alone can cover every resource-management case.

## Error handling

Native exceptions would require hidden control flow, unwinding metadata, or `setjmp` and `longjmp`. None of those fit the original goal well.

Use typed results:

```python
def parse_number(text: const char*) -> Result[i64, ParseError]:
    if text == null:
        return Err(ParseError.null_input)

    value = parse_i64(text)

    if not value.valid:
        return Err(ParseError.invalid_number)

    return Ok(value.number)
```

Propagation syntax:

```python
number = parse_number(text)?
```

This can compile into ordinary branches and tagged structs.

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

C-style loops should remain available for low-level code:

```python
for i: usize = 0; i < count; i += 1:
    process(values[i])
```

That is one of the few places where semicolons should remain syntactically meaningful.

## Pattern matching

A restricted `match` statement would work well for enums and tagged unions:

```python
match result:
    case Ok(value):
        use(value)

    case Err(error):
        report(error)
```

Enums:

```python
enum TokenKind:
    identifier
    integer
    string
    plus
    minus
```

Tagged unions:

```python
union TokenValue:
    integer: i64
    string: const char*
```

Safer combined form:

```python
variant Token:
    Identifier(text: const char*)
    Integer(value: i64)
    String(value: const char*)
    Plus
    Minus
```

## C interoperability

Existing C headers should be imported directly:

```python
extern import "SDL2/SDL.h"
extern import "sqlite3.h"
```

External declarations:

```python
extern "C":
    def sqlite3_open(
        filename: const char*,
        database: **sqlite3
    ) -> c_int
```

Cinder declarations should also be exportable:

```python
@export
def engine_update(delta_time: f64) -> void:
    world.update(delta_time)
```

The generated symbol would use the C calling convention and remain callable from C, C++, Rust, Python extensions, or any other FFI-compatible language.

## Modules

```python
from engine.math import Vec3
from engine.memory import Arena
import stdio
```

A source file is a module. There should be no textual `#include` equivalent in normal Cinder code.

The compiler emits generated headers only for exported declarations.

## Compiler architecture

The first compiler should be written in Python 3.12 and emit readable C11.

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

The implementation should have these core components:

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
    diagnostics.py
    compiler.py
    cli.py

runtime/
    cinder_runtime.h
    cinder_runtime.c
```

The compiler CLI should be simple:

```text
cinder build src/main.ci
cinder run src/main.ci
cinder check src/main.ci
cinder emit-c src/main.ci
```

## Implemented milestones

The first usable compiler milestone established indentation parsing, primitive types, functions, native control flow, structs and methods, pointers, arrays, slices, C imports, and readable C11 generation. Cinder 0.2 added manifest-driven modules and per-module C output. Cinder 0.3 added enums, unions, variants, exhaustive matching, typed Results, and propagation. Cinder 0.4 established the class and interface ABI. Cinder 0.5 added opt-in runtime metadata and compile-time member inspection.

General-purpose generics, function pointer types, richer ownership abstractions, closures, and broader compile-time execution remain later work.

The crucial constraint remains this: Cinder should be understandable by reading its generated C. Once the compiler begins hiding allocation, unpredictable dispatch, exception machinery, or implicit object lifetimes, it stops being Python-shaped C and becomes a much more complicated systems language.
