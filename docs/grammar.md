# Cinder 0.5 grammar and semantics

This document describes syntax accepted by the 0.5 compiler. It is a working language reference, not a promise that every spelling or generated symbol is stable before 1.0.

## Lexical rules

Source is UTF-8 text. Identifiers follow the compiler's Unicode identifier checks, while generated C identifiers are sanitized and module-prefixed. Keywords are reserved.

A logical statement ends at a newline unless the lexer is inside `()`, `[]`, or `{}`. A backslash is not a line-continuation operator. Indentation uses spaces; tabs in leading indentation are rejected. A block begins after `:` and must increase indentation. Blank lines and comments do not affect indentation.

Line comments begin with `#`. Integer literals support decimal, hexadecimal, octal, and binary spellings. Floating literals use decimal syntax. Character and string literals use Cinder escape decoding and are emitted as C literals.

## Project and module syntax

```text
module             := top_level_item* EOF

top_level_item     := import_decl
                    | from_import_decl
                    | extern_import_decl
                    | extern_block
                    | function_decl
                    | struct_decl
                    | class_decl
                    | enum_decl
                    | union_decl
                    | variant_decl
                    | global_decl
                    | static_assert_decl

import_decl        := "import" dotted_name ("as" NAME)? NEWLINE
from_import_decl   := "from" dotted_name "import" imported_name
                       ("," imported_name)* NEWLINE
imported_name      := NAME ("as" NAME)?
extern_import_decl := "extern" "import" STRING NEWLINE
extern_block       := "extern" STRING ":" external_suite

dotted_name        := NAME ("." NAME)*
```

A source file is one module. Local modules resolve below the configured project source root. Built-in modules such as `stdio`, `math`, `stdlib`, and `cinder` are supplied by the compiler.

Imports must form an acyclic graph. Dependencies are checked and emitted before importers. A normal build emits one header and one C translation unit per module.

## Decorators

```text
decorator          := "@" NAME NEWLINE
```

The accepted decorators are contextual:

```text
@export            top-level function
@reflect           struct, class, enum, union, or variant
@abstractmethod    method in an abstract class
@override          class method
```

Unknown decorators and decorators in an invalid position are source errors. Decorators do not execute at runtime.

## Top-level declarations

```text
global_decl        := "const"? NAME (":" type)? ("=" expression)? NEWLINE
function_decl      := decorator* "def" NAME type_params? parameters ("->" type)? ":" suite
struct_decl        := decorator* "struct" NAME type_params? ":" struct_suite
class_decl         := decorator* "abstract"? "class" NAME type_params? class_bases? ":" class_suite
enum_decl          := decorator* "enum" NAME type_params? ":" enum_suite
union_decl         := decorator* "union" NAME type_params? ":" union_suite
variant_decl       := decorator* "variant" NAME type_params? ":" variant_suite
static_assert_decl := "static_assert" "(" expression ("," STRING)? ")" NEWLINE

type_params        := "[" NAME ("," NAME)* ","? "]"
class_bases        := "(" type ("," type)* ","? ")"
```

Top-level globals require an explicit type annotation. A top-level `const` also requires an initializer. Global initializers must be representable as C static initializers.

`static_assert` accepts a compile-time expression. Checker-evaluable assertions fail during Cinder compilation. Target-layout assertions involving `size_of` or `align_of` remain C static assertions in generated output.

## Structs

```text
struct_suite       := NEWLINE INDENT struct_member+ DEDENT
struct_member      := decorator* function_decl
                    | "private"? NAME ":" type NEWLINE
```

Structs have ordinary C-compatible field layout. Methods use static dispatch. The first method parameter must be `self`; an omitted annotation is inferred as `&Owner`, while `&const Owner` declares a const method.

Struct construction is a checked field initializer:

```python
point = Point(y=20, x=10)
```

Named fields are reordered by the checker. Omitted fields are zero-initialized. Structs do not have inheritance, `__init__`, `__del__`, or dynamic dispatch.

## Classes

```text
class_suite        := NEWLINE INDENT class_member+ DEDENT
class_member       := decorator* function_decl
                    | "private"? NAME ":" type NEWLINE
                    | "pass" NEWLINE
```

A class may have one implementation base and any number of interface-only abstract bases. Multiple implementation bases are rejected.

```python
abstract class Shape:
    @abstractmethod
    def area(self) -> f64:
        pass

class Circle(Shape):
    radius: f64

    def __init__(self, radius: f64):
        self.radius = radius

    @override
    def area(self) -> f64:
        return self.radius * self.radius
```

An unannotated class `self` is inferred as `&Owner`. `self: &const Owner` declares a const method. A concrete class must implement every inherited abstract method with a compatible signature.

`__init__` is a value constructor. The generated helper zero-initializes a class value and invokes the method. A derived constructor whose implementation base has a constructor must call `super().__init__(...)` as its first executable statement.

`__del__` is deterministic compiler-managed cleanup. It cannot be called directly. A derived destructor runs before the implementation-base destructor.

Destructor-bearing classes and other types that need drop are move-only. They may be initialized from constructors or class-returning calls, transferred by return or by-value parameter passing, stored in struct/class fields, and replaced by move-style reassignment. Implicit copies are rejected; use-after-move is diagnosed. Owning globals and owning union/variant payloads remain unsupported.

Calls on concrete class types use static dispatch. Dynamic dispatch requires an explicit dynamic-reference type.

## Dynamic interface types

```text
dyn_type           := "&" "const"? "dyn" dotted_name
```

Examples:

```text
&dyn Shape
&const dyn Reader
```

A dynamic value is a non-owning pair of an object pointer and an interface-table pointer. Concrete-to-dynamic conversion requires an addressable concrete object. Constructor temporaries cannot be borrowed directly as `&dyn`.

Dynamic values do not allocate and do not change concrete object layout. They are not valid return types or owning aggregate fields in 0.5.

## Enums

```text
enum_suite         := NEWLINE INDENT enum_member+ DEDENT
enum_member        := NAME ("=" "-"? INTEGER)? NEWLINE
```

Implicit member values increase from the previous value, beginning at zero. Duplicate names and duplicate integer values are rejected. Explicit values must be integer literals.

## Plain unions

```text
union_suite        := NEWLINE INDENT union_field+ DEDENT
union_field        := "private"? NAME ":" type NEWLINE
```

A union value may be zero-initialized with an empty call or initialized with one named field:

```python
zero = Number()
number = Number(integer=42)
```

The checker records the initializer field, but the resulting object retains ordinary C union semantics. Reading a different field is not dynamically checked.

## Tagged variants

```text
variant_suite      := NEWLINE INDENT variant_case+ DEDENT
variant_case       := NAME ("(" payload_fields? ")")? NEWLINE
payload_fields     := payload_field ("," payload_field)* ","?
payload_field      := NAME ":" type
```

A variant case is constructed through its type namespace:

```python
token = Token.Integer(42)
end = Token.End()
```

The compiler emits an explicit tag enum, payload union, and enclosing struct. Construction does not allocate.

## Types

```text
type               := dyn_type
                    | prefix* "const"? (function_type | dotted_name generic_args? postfix*)
prefix             := "*" | "&" | "[]"
generic_args       := "[" (type ("," type)* ","?)? "]"
postfix            := "*" | "[" INTEGER "]"
function_type      := "def" "(" (type ("," type)* ","?)? ")" ("->" type)?
```

Examples:

```text
i32
*i32
**char
&const Vec2
[]const i32
i32[16]
Result[i32, ParseError]
Result[void, Error]
Option[i32]
Owned[i32]
Tuple[i32, const char*]
List[i32]
Map[const char*, i32]
Set[i32]
MapKeys[const char*, i32]
geometry.Vec2
&dyn geometry.Shape
def(i32) -> i32
def(i32, i32) -> i32
*def(i32) -> void
```

`*T` is a raw pointer. `&T` is a non-null transparent reference represented as a pointer in C. `T[N]` is a fixed array. `[]T` is a slice. `def(T…) -> R` is a non-null function pointer type represented as a C function pointer; omit `-> R` to default the return type to `void`. `Result[T, E]`, `Option[T]`, `Owned[T]`, `Tuple[...]`, `List[T]`, `Map[K, V]`, `Set[T]`, and the Map view types are compiler-provided generic families. User-defined generics use the same `Name[Args…]` application syntax and are monomorphized into readable specialized C types and functions.

References, dynamic references, slices, fixed arrays, class values, and plain `void` have placement restrictions that follow their generated C representations and lifetime rules.

## Function declarations

```text
parameters         := "(" parameter_list? ")"
parameter_list     := parameter ("," parameter)* ","?
parameter          := NAME (":" type)? | "..."
```

Top-level and external function parameters require annotations. A return annotation defaults to `void` when omitted. The variadic marker is valid only in external declarations and must be final.

External declarations may omit a body or use a body containing only `pass`:

```python
extern "C":
    def puts(text: const char*) -> c_int
```

Class and struct methods infer only the first unannotated `self` parameter. Other parameters require annotations.

## Statements

```text
statement          := variable_decl NEWLINE
                    | assignment NEWLINE
                    | expression NEWLINE
                    | return_stmt NEWLINE
                    | "break" NEWLINE
                    | "continue" NEWLINE
                    | "pass" NEWLINE
                    | "defer" expression NEWLINE
                    | with_stmt
                    | if_stmt
                    | while_stmt
                    | foreach_stmt
                    | c_for_stmt
                    | match_stmt
                    | unsafe_stmt

variable_decl      := "const"? NAME ":" type ("=" expression)?
assignment         := expression assignment_operator expression
return_stmt        := "return" expression?

if_stmt            := "if" expression ":" suite
                      ("elif" expression ":" suite)*
                      ("else" ":" suite)?
while_stmt         := "while" expression ":" suite
with_stmt          := "with" expression "as" NAME ":" suite
foreach_stmt       := "for" NAME (":" type)? "in" "comptime"? expression ":" suite
c_for_stmt         := "for" simple_stmt? ";" expression? ";"
                      simple_stmt? ":" suite
unsafe_stmt        := "unsafe" ":" suite
```

An untyped assignment to an unknown local name declares that local and infers its type. Later assignments update the existing symbol. Locals use lexical block scope.

`defer` accepts a call expression. Deferred calls run in reverse declaration order on normal scope exit, `return`, `break`, `continue`, and propagated error returns. Class destructor and owning-collection cleanup use the same control-flow cleanup paths.

`with expression as name:` opens a nested scope, binds `name` to the expression result, runs the suite, and runs ordinary scope cleanup for that binding on every normal exit. There is no `__enter__` / `__exit__` protocol; destructor-bearing and owning values such as `File` close through the same drop path used for locals.

A `comptime` foreach is valid only with `fields_of(...)` or `methods_of(...)`. The loop is unrolled and its binding cannot escape into runtime storage.

## Match statements

```text
match_stmt         := "match" expression ":" NEWLINE INDENT match_case+ DEDENT
match_case         := "case" match_pattern ":" suite
match_pattern      := "_"
                    | dotted_name ("(" binding_list? ")")?
binding_list       := NAME ("," NAME)* ","?
```

The subject must be an enum, variant, `Result`, or `Option`. Enum patterns have no bindings. Variant patterns bind one name for each payload field. Result patterns are `Ok`, `Ok(value)`, `Err`, or `Err(error)`, depending on whether the corresponding payload is `void`. Option patterns are `Some(value)` and `None`.

A match must be exhaustive. A wildcard covers all remaining cases and must be final. Duplicate or unreachable cases are rejected. Patterns do not support guards, alternatives, literal patterns, nested destructuring, or ignored fields inside a payload.

## Expressions

Postfix calls, member access, indexing, slicing, propagation, and method calls bind most tightly. Unary operators are `+`, `-`, `not`, `!`, `~`, `&`, and `*`.

Binary precedence from low to high is:

```text
or
and
|
^
&
== != < <= > >= in not in
<< >>
+ -
* / %
```

Calls accept positional or named arguments. Positional arguments cannot follow named arguments.

```python
rectangle = Rectangle(height=10.0, width=20.0)
circle = Circle(radius=4.0)
```

Special typed expressions are:

```python
cast[TargetType](value)
alloc[ElementType]()
alloc[ElementType](count)
generic_function[TypeArgs...](arguments)
```

User generic functions may also omit explicit type arguments when every type parameter is uniquely inferred from the call arguments.

List literals use square brackets. In an untyped local, `[1, 2]` infers `List[i32]`; an explicit fixed-array context such as `values: i32[2] = [1, 2]` retains C array storage. Slice expressions support `value[:]`, `value[start:]`, and `value[start:stop]`. Slice steps are not implemented.

Parenthesized comma expressions are tuple literals: `(left, right)`, `(single,)`, and `()`. Parentheses without a comma remain grouping.

Brace literals are Maps when entries contain colons and Sets otherwise: `{"ready": 1}` and `{1, 2}`. `{}` is an empty Map and requires a `Map[K, V]` context. `set()` is an empty Set and requires a `Set[T]` context. Mixed Map/Set entries are rejected.

`super().__init__(...)` and `super().method(...)` are recognized only inside a derived class method. Abstract base methods cannot be called directly through `super`.

## Native collections

Tuples are immutable heterogeneous value aggregates. Their element types and length are part of the type. `len(tuple)` is compile-time-known, and tuple indexing requires a non-negative integer literal:

```python
entry: Tuple[i32, const char*] = (7, "ready")
code = entry[0]
```

Lists are homogeneous, owning, growable buffers represented in generated C by `data`, `length`, and `capacity`. They support `len`, indexing and element assignment, `for` iteration, `sort`, and the mutating methods `append`, `pop`, and `clear`.

```python
values: List[i32] = []
values.append(3)
values.append(1)
sort(values)
last = values.pop()
```

An empty list needs a contextual `List[T]` type. List values are move-only owners of their buffers: locals, fields, by-value parameters, and returns transfer ownership; replacement drops the previous buffer; and scope exit frees the active buffer. Nested lists and destructor-bearing elements are allowed. An addressable `List[T]` may be passed without copying to a `[]T` or `[]const T` function parameter; this call-only coercion does not permit storing or returning a List-backed slice. Mutable slices may update elements, while structural operations still require `&List[T]`. Owning List globals remain unsupported. Bind a returned or literal List to a local before indexing, iterating, sorting, calling `len`, or borrowing it as a slice.

List indexing follows the current array/slice model and does not insert bounds checks. `pop` does check for an empty list and panics. While a `for` loop iterates a List, the same storage cannot be structurally modified, replaced, sorted, or borrowed as mutable `[]T`, including through recognized aliases. Read-only `[]const T` helpers and provably unrelated Lists remain available.

Maps are insertion-ordered owning hash tables. `map[key]` panics when the key is absent; direct assignment inserts or replaces. `get(key)` and `pop(key)` return `Option[V]`. Default iteration yields keys, and `keys()`, `values()`, and `items()` return live first-class `MapKeys[K,V]`, `MapValues[K,V]`, and `MapItems[K,V]` views. Items iterate as `Tuple[K,V]`. Maps also provide `clear()` and `update(other)`; `update` is rejected when `V` needs drop because it would copy owned values.

Sets are unordered owning hash tables. They provide `add`, `discard`, missing-element-panicking `remove`, optional `pop`, `clear`, and `update`. `union`, `intersection`, `difference`, and `symmetric_difference` return fresh Sets; `|`, `&`, `-`, `^`, their compound forms, equality, and subset/superset comparisons provide the operator forms.

`in` and `not in` test Map keys, Set elements, and Map views. Hashable types are integers, `bool`, `char`, enums, and `const char*`. String hashing/equality uses content, and Maps/Sets clone string keys. A popped string Set element transfers its allocation to the caller.

Maps and Sets use the same move-only direct-local/direct-return restrictions as Lists. Their structure cannot be mutated during active iteration, including through hidden aliases caught by runtime guards. Live Map views are non-owning and follow slice-like lifetime rules.

## Options

`Option[T]` is constructed with `Some(value)` or contextual bare `None`. `Some` infers its payload without a context when possible; `None` does not. Option matches must cover `Some` and `None`. `.is_some` and `.is_none` inspect the tag. `.value` requires an addressable Option and panics on `None`. Postfix `?` remains specific to `Result`.

## Owned heap values

`Owned[T]` is a move-only heap owner. `Owned(value)` allocates storage for `T`, moves `value` onto the heap, and returns a non-null owning handle. Unary `*` yields an addressable `T` lvalue for reads, writes, and borrowing as `&T` via `&*owned`. Scope exit, return transfer, and reassignment drop the inner value when needed and then free the allocation. Payloads cannot be void, const, references, arrays, pointers, slices, dyn, or map views. Owning globals and union/variant payloads remain rejected. `Owned` does not wrap an existing raw `*T`; use `alloc`/`free`/`defer` for that.

## Result construction and propagation

`Ok(...)` and `Err(...)` are contextual constructors. They require an expected `Result[T, E]` type from a variable annotation, return type, argument type, or another checked context.

```python
def parse(value: i32) -> Result[i32, ParseError]:
    if value < 0:
        return Err(ParseError.invalid)
    return Ok(value)
```

Postfix `?` requires a `Result` operand and an enclosing function returning a compatible `Result`. The error payload must be assignable to the enclosing error type.

```python
def increment(value: i32) -> Result[i32, ParseError]:
    parsed = parse(value)?
    return Ok(parsed + 1)
```

The generated code evaluates the operand once, checks its tag, runs active deferred calls and class drops on error, and performs an ordinary early return. To keep that transformation faithful to C evaluation order, propagation is rejected in `while` conditions, `elif` conditions, C-style loop conditions and updates, deferred calls, and the right side of short-circuit `and` or `or` expressions.

## Reflection built-ins

Runtime operations are:

```text
type_name(value)
type_info(value)
fields(value)
methods(value)
```

`type_info`, `fields`, and `methods` require a type marked `@reflect`. `type_name` is a compile-time string for a concrete static type; a dynamic-interface value requires a reflected interface.

Compile-time operations are:

```text
type_of(expression)
size_of(Type)
align_of(Type)
field_count(Type)
method_count(Type)
has_field(Type, STRING)
has_method(Type, STRING)
implements(Class, AbstractClass)
fields_of(Type)
methods_of(Type)
```

`type_of` produces a compiler-only type value. `fields_of` and `methods_of` are valid only as the iterable of a `comptime` loop.

Compile-time field bindings expose `name`, `type_name`, `offset`, `size`, `alignment`, and `is_private`. Compile-time method bindings expose `name`, `signature`, `return_type_name`, `parameter_count`, `is_abstract`, and `is_override`.

## Other built-ins

`range(stop)`, `range(start, stop)`, and `range(start, stop, step)` are valid only as loop iterables.

`len(array)`, `len(slice)`, `len(tuple)`, `len(list)`, `len(map)`, `len(set)`, and `len(map_view)` return `usize`. `len(const char*)` emits `strlen`.

`sort(array_or_slice_or_list)` stably sorts mutable elements in ascending order and returns `void`. Fixed arrays and lists must refer to addressable storage. Slices may select a subrange to sort, but slicing a const array produces a const slice that cannot be sorted. Numeric primitives use numeric order, `bool` orders `false` before `true`, enums use their declared integer values, and `char*` or `const char*` values use lexicographic C-string order. Const elements and unordered aggregate or non-string pointer types are rejected. Unlike Python's list API, Cinder's builtin does not currently accept `key` or `reverse` arguments.

`print(...)` is globally available and emits to standard output without importing `stdio`. It accepts zero or more printable values, separates multiple arguments with a space, and appends a newline. Printable values are booleans, characters, integers, floats, `const char*` strings, and collections whose nested element types are printable: `List`, `Map`, `Set`, and `Tuple`. Collection formatting uses Python-like brackets (`[1, 2]`, `{'a': 1}`, `{1, 2}` / `set()`, `(1, 2)`). Owning collections must be addressable locals, like `len`. Format specs are not supported on collections.

`print` also accepts Python-style f-strings. Replacement fields use `{expression}` and may include simple format specs such as `{value:d}`, `{value:x}`, `{value:.2f}`, `{text:s}`, and `{letter:c}`. Literal braces are written as `{{` and `}}`. F-strings are currently supported only as `print` arguments.

`input()` is globally available and reads a line from standard input without importing `stdio`. `input(prompt)` writes the `const char*` prompt to standard output without a newline, flushes it, then reads. The returned `const char*` excludes the trailing newline, strips a preceding carriage return for CRLF input, and owns a freshly allocated buffer; release it with `free(cast[void*](line))` when the value is no longer needed. Reaching EOF before any bytes are read panics, since Cinder does not currently have exceptions.

`parse_i32`, `parse_i64`, `parse_u32`, `parse_u64`, `parse_isize`, `parse_usize`, `parse_f32`, `parse_f64`, and `parse_bool` are globally available and return `Result[T, ConvertError]`. Leading whitespace is skipped, the entire remaining token must parse, and trailing non-whitespace is rejected. `ConvertError` is a compiler-provided enum with `empty`, `invalid`, and `overflow` members. `parse_bool` accepts only `true` and `false`.

`to_string(value)` is globally available and returns an owned `const char*` for integers (`i8`…`i64`, `u8`…`u64`, `isize`, `usize`), floats (`f32`, `f64`), `bool`, and `char`. Release the result with `free(cast[void*](text))`. Bool formats as `true`/`false`; numbers use decimal text (floats use `%g`-style formatting).

`open(path, mode)` is globally available and returns a move-only `File` without importing `stdio`. A null `fopen` result panics. `File` provides `write(data: []const u8) -> usize`, `flush()`, and `close()`. Scope exit closes any still-open handle. Prefer `with open(...) as file:` to limit the file's lifetime.

`free(pointer)` and `panic(message)` are globally available. The corresponding namespaced APIs are available from `stdlib` and `cinder`.

Result values expose `.is_ok`, `.value`, and `.error`. Accessing a `void` payload is rejected.

Option values expose `.is_some`, `.is_none`, and checked `.value`.

## Deliberate omissions

The grammar and checker do not implement multiple implementation inheritance, downcasting, runtime dynamic invocation by name, runtime field-value access, closures, exceptions, automatic ownership inference, copy or move hooks, nested match patterns, match guards, user-defined compile-time functions, AST macros, interface bounds on type parameters, or multi-root package dependency graphs. Owning globals and owning union/variant payloads remain intentionally rejected.
