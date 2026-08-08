# Cinder language design

> Implementation status: Cinder 0.5 completes the procedural core, local modules, algebraic data, typed Results and Options, classes, abstract interfaces, explicit dynamic dispatch, deterministic class cleanup, opt-in runtime reflection, static assertions, compile-time member inspection, and specialized native collections. The accepted owned-text foundation adds move-only UTF-8 `String` and `StringBuilder`. User-defined generics are monomorphized into readable specialized C. The more expansive metaprogramming ideas remain proposals.

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
    name: String

    def __init__(self, name: String):
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
name = "Cinder"
c_name: const char* = "Cinder"
```

An ordinary string literal is an owning `String`.
Only an explicit `const char*` context selects the low-level C-interoperability form.

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

## Callable values

Plain function pointer values use `def(T...) -> R` and store non-capturing free
functions as ordinary C function pointers:

```python
def double(value: i32) -> i32:
    return value * 2


callback: def(i32) -> i32 = double
```

Closures are explicit about their environment. A closure type names a
user-declared environment struct, and `closure(env, adapter)` pairs an
environment value with a non-generic, non-variadic free function whose first
parameter is `&Env` or `&const Env`:

```python
struct AddEnv:
    delta: i32


def add_impl(env: &const AddEnv, value: i32) -> i32:
    return value + env.delta


callback: closure[const AddEnv](i32) -> i32 = closure(AddEnv(delta=2), add_impl)
```

Generated C represents each closure specialization as a readable struct with an
`env` field and a `call` function pointer. Calling the closure passes `&env`
automatically and exposes only the adapter's remaining parameters. Owning
environment fields follow the same move-only and deterministic drop rules as
ordinary structs. Inline closure bodies, inferred captures, bound method
closures, and conversion from closures to plain function pointers are not part
of this model.

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

## Strings and text

`String` is Cinder's primary UTF-8 text value. It is move-only and drops its active
storage deterministically. Its runtime shape is conceptually a data pointer, a byte
length, and a capacity, but that description does not freeze a pre-1.0 ABI.

Static literals use copy-on-write storage: a literal may refer to static bytes until
the first mutation needs writable capacity. Retaining an independent String is an
explicit operation:

```python
message = "hello"
copy = message.clone()
message.append(", Cinder")
message.reserve(64)
message.clear()
```

A String cannot contain an embedded NUL byte. This keeps implicit C-string borrows
lossless; arbitrary byte buffers remain `List[u8]`.

A `const` global String initialized directly from a literal can remain in static
storage. Other owning String globals still require runtime lifetime support that is
not available.

`len(message)` reports UTF-8 bytes. Direct String indexing is intentionally absent,
because a numeric index would be ambiguous between bytes, Unicode scalar values, and
grapheme clusters. `byte_at(index)` provides explicit byte access. A slice such as
`message[start:stop]` checks that the byte range is in bounds and that both endpoints
are UTF-8 boundaries, then returns a copied `String`.

Concatenation with `+` borrows both operands and returns a fresh String. It does not
consume either operand. `StringBuilder` supports `append`, ASCII `append_char`, and
`reserve`; `finish` consumes the builder and returns its completed String. These are
language-level operations—the generated C helper names are not part of the source API.

Text-oriented builtins follow the same ownership split. `input` and `to_string`
return String values. Numeric and boolean parse helpers borrow a String, as do
`print` and `open`; these calls do not consume their arguments. F-strings remain a
print-only facility rather than general String expressions.

## Native collections

`Tuple[...]` is a compiler-specialized heterogeneous value aggregate. Tuple layout is explicit in generated C, tuple elements are immutable, and indices must be compile-time integer literals.

```python
entry: Tuple[i32, String] = (7, "ready")
code = entry[0]
```

`List[T]` is a homogeneous owning buffer specialized for `T`. It is represented as a generated `{data, length, capacity}` struct and uses the small Cinder runtime only for checked allocation and growth.

```python
values: List[i32] = []
for value in range(0, 20):
    values.append(value)
last = values.pop()
```

List ownership follows the existing explicit move-only direction. A value owns its buffer; return and by-value parameter passing transfer ownership and mark the source moved; replacement drops the previous buffer; and all normal scope exits free it. Nested lists, owning struct/class fields, and destructor-bearing elements are supported with generated drop glue. Generic element-processing functions can accept `[]T` or `[]const T`; addressable Lists, fixed arrays, and slices all pass to those parameters without copying. List-to-slice coercion is call-only so a borrowed view cannot be stored or returned implicitly. Mutable slices can update elements, while structural operations use `&List[T]`. Owning globals and owning union/variant payloads remain rejected; AST-like trees should keep ownership in an arena struct and put non-owning IDs or ranges in union/variant payloads.

Square-bracket literals infer lists in untyped contexts. An explicit array type still selects fixed C storage, so `values: i32[3] = [1, 2, 3]` remains an array declaration.

`Map[K, V]` and `Set[T]` are specialized owning hash tables. Map literals use `{key: value}` and preserve insertion order; Set literals use `{value, ...}` and expose unspecified iteration order. Empty Maps use contextual `{}`, while empty Sets use contextual `set()`.

Maps support key membership, indexed lookup/upsert, optional `get`/`pop`, live `keys`/`values`/`items` views, `clear`, and `update`. Sets support membership, mutation, optional `pop`, bulk update, algebra, equality, and subset/superset comparisons. `MapKeys`, `MapValues`, and `MapItems` contain a borrowed pointer to their Map, remain live across mutation, and carry the same lifetime responsibility as slices.

Hashable values are integer primitives, `bool`, `char`, enums, `String`, and low-level `const char*`. Maps and Sets hash and compare String keys or elements by UTF-8 byte content rather than allocation identity. Insertion clones a String key or element so later mutation of the source cannot change table membership. Outside that documented collection operation, keeping an independent String requires an explicit clone.

All three owning homogeneous collections remain move-only. Nested owning collections, struct/class fields, and by-value parameters/returns are supported. List elements and Map values may be destructor-bearing; Set elements may include String and the other supported hashable types. Sorting a mutable sequence of Strings uses lexicographic UTF-8 byte-content order. Owning globals and union/variant payloads remain rejected; use arena-owned lists plus non-owning scalar handles for recursive AST-shaped data. Known iterator aliases are diagnosed statically; generated Map/Set mutation helpers also guard active iterators at runtime.

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
with open("out.txt", "w") as file:
    file.write("hello\n")
```

`open` is a global builtin that returns the compiler-provided owning `File` type. `with`
binds that value in a nested scope so the handle closes automatically through ordinary
`File` drop cleanup. The same cleanup runs for `file = open(...)` at the end of the
enclosing scope. There is no `__enter__` / `__exit__` protocol in 0.5.

`open` borrows its String path and mode. `File.write` accepts String text or byte
slices without consuming them. `File.read_line` returns `Option[String]`: immediate EOF is `None`, while
a blank line is `Some("")`. `File.read_text` reads the remaining data, validates
UTF-8, and returns String. The byte-oriented `File.read_all` remains available and
returns `List[u8]`.

```python
import stdio

class File:
    private handle: *stdio.FILE

    def __init__(self, path: String, mode: String):
        self.handle = stdio.fopen(path, mode)

        if self.handle == null:
            panic("could not open file")

    def __del__(self):
        if self.handle != null:
            stdio.fclose(self.handle)
```

The illustrative user-written class above remains valid for wrapping raw `stdio.FILE`
handles when a custom type is preferable to the builtin `File`. For a local destructor-bearing value, the compiler calls `__del__` on every normal
scope exit, including early returns and Result propagation. Such classes are
move-only: implicit copies are rejected, while return and by-value parameter
passing transfer ownership and mark the source moved. Match payload bindings of
owning `Option` or `Result` values are not transferable; use a transferable
local or a returning call instead of moving the binding. Struct/class fields,
nested collections, and `Option`/`Result`/`Tuple` wrappers may own them.
Owning globals and owning union/variant payloads remain rejected. For
AST-shaped data, use an arena object with owning fields and store non-owning
indices or ranges in variant payloads. `__del__` cannot be called directly.

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
    name: String
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

String and StringBuilder storage also uses compiler-managed drop. Their internal
buffers are not raw allocations for user code to release with `free`.

`Owned[T]` is an explicit heap owner for a single value. `Owned(value)` allocates,
moves `value` onto the heap, and returns a move-only handle. Unary `*` yields an
addressable `T` lvalue. Drop frees the allocation after dropping `T` when needed.
Recursive layouts such as `Option[Owned[Node]]` are supported because `Owned`
stores a pointer. Raw `*T` from `alloc` remains manual; `Owned` does not wrap an
existing pointer.

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

`Option[T]` is a separate tagged value for absence:

```python
def find_enabled(enabled: bool) -> Option[i32]:
    if enabled:
        return Some(42)
    return None
```

`Some(value)` may infer `T`; bare `None` requires an expected Option type. Matches are exhaustive over `Some(value)` and `None`. Option values expose `.is_some`, `.is_none`, and checked `.value`; accessing the payload of `None` panics. Option does not use postfix `?`.

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

Cinder implements exhaustive `match` for enums, variants, Results, and Options:

```python
match result:
    case Ok(value):
        use(value)

    case Err(error):
        report(error)
```

Every case must be covered. A final `_` wildcard can cover the remaining cases;
guards can refine a case but do not count toward exhaustiveness by themselves.
Patterns can destructure nested algebraic values, combine alternatives with `|`,
discard payload fields with `_`, and capture a value with `name @ pattern`.
Literal patterns, tuple destructuring, struct destructuring, and match expressions
are not implemented.

```python
match value:
    case Some(Ok(score)) if score > 0:
        use(score)
    case Some(Err(_)) | None:
        recover()
    case original @ Some(Ok(_)):
        inspect(original)
```

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

Owning variant payloads are not implemented, so this low-level example deliberately
uses `const char*`; a variant cannot carry an owning String yet. Likewise, a String
bound from an owning Option or Result match may be inspected or borrowed but cannot
currently be transferred out of that match binding.

## C interoperability

`extern import` emits a C `#include`:

```python
extern import "SDL2/SDL.h"
extern import "sqlite3.h"
```

The compiler does not parse arbitrary headers. An `extern "C"` block supplies the
signatures Cinder checks. Prefer an explicit opaque declaration; unknown names in
extern signatures are still inferred as opaque C types for compatibility:

```python
extern "C":
    type sqlite3
    def sqlite3_open(
        filename: const char*,
        database: **sqlite3
    ) -> c_int
```

Opaque types are exported with the defining module, so other modules can write
`*bindings.sqlite3` or `from bindings import sqlite3`. Do not give a Cinder
`struct`/`class` the same source name as a C header type you need in `extern`
signatures—the Cinder type would emit a mangled C name and break the ABI. Use a
distinct storage struct (for example `EventBlob`) when you need layout under a
different name.

`@export` preserves the C symbol name of a top-level Cinder function:

```python
@export
def seconds(milliseconds: f64) -> f64:
    return milliseconds / 1000.0
```

The generated symbol uses the C calling convention and remains callable from C,
C++, Rust, Python extensions, or other FFI-compatible languages.

Extern signatures remain written in C ABI types. A C parameter that receives text
still uses `const char*`, not `String`. Passing a String directly to an extern or
compiler-provided builtin call can create an implicit `const char*` borrow for that
call only; the pointer cannot be assigned, stored, or returned. Conversion in the
other direction is never implicit because Cinder must copy and validate external
bytes before they become owned UTF-8 text.

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
Python remains the stage0 implementation. The native self-hosted chain lives in
`compiler_selfhost/` and bootstraps to gen3. Bootstrap steps and the ownership
constraints that still apply are documented in
[`docs/self-hosting.md`](self-hosting.md).

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

The first usable compiler milestone established indentation parsing, primitive types, functions, native control flow, structs and methods, pointers, arrays, slices, C imports, and readable C11 generation. Cinder 0.2 added manifest-driven modules and per-module C output. Cinder 0.3 added enums, unions, variants, exhaustive matching, typed Results, and propagation. Cinder 0.4 established the class and interface ABI. Cinder 0.5 added opt-in runtime metadata and compile-time member inspection. Native tuples and lists extend those built-in type-specialization patterns. User-defined generics monomorphize the same way into readable named C specializations. Explicit-environment closures extend function pointers without inferred capture or hidden allocation. The owned String foundation supplies the text ownership and UTF-8 rules used by the native self-hosted compiler.

Copy/move hooks, inline/inferred closures, bound method closures, and broader compile-time execution remain later work.

The crucial constraint remains this: Cinder must be understandable by reading its
generated C. Hidden allocation, unpredictable dispatch, exception machinery, or
implicit object lifetimes would turn it from Python-shaped C into a much more
complicated systems language.
