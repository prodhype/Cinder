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
function_decl      := decorator* "def" NAME parameters ("->" type)? ":" suite
struct_decl        := decorator* "struct" NAME ":" struct_suite
class_decl         := decorator* "abstract"? "class" NAME class_bases? ":" class_suite
enum_decl          := decorator* "enum" NAME ":" enum_suite
union_decl         := decorator* "union" NAME ":" union_suite
variant_decl       := decorator* "variant" NAME ":" variant_suite
static_assert_decl := "static_assert" "(" expression ("," STRING)? ")" NEWLINE

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

Destructor-bearing classes are move-only. They may be initialized from constructors or class-returning calls, transferred by return, and replaced by move-style reassignment. Implicit copies and by-value parameters are rejected. Aggregate ownership of destructor-bearing classes is not implemented in 0.5.

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
                    | prefix* "const"? dotted_name generic_args? postfix*
prefix             := "*" | "&" | "[]"
generic_args       := "[" type ("," type)* "]"
postfix            := "*" | "[" INTEGER "]"
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
geometry.Vec2
&dyn geometry.Shape
```

`*T` is a raw pointer. `&T` is a non-null transparent reference represented as a pointer in C. `T[N]` is a fixed array. `[]T` is a slice. `Result[T, E]` is the only generic type implemented in 0.5; other generic applications are rejected.

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
foreach_stmt       := "for" NAME (":" type)? "in" "comptime"? expression ":" suite
c_for_stmt         := "for" simple_stmt? ";" expression? ";"
                      simple_stmt? ":" suite
unsafe_stmt        := "unsafe" ":" suite
```

An untyped assignment to an unknown local name declares that local and infers its type. Later assignments update the existing symbol. Locals use lexical block scope.

`defer` accepts a call expression. Deferred calls run in reverse declaration order on normal scope exit, `return`, `break`, `continue`, and propagated error returns. Class destructor cleanup uses the same control-flow cleanup paths.

A `comptime` foreach is valid only with `fields_of(...)` or `methods_of(...)`. The loop is unrolled and its binding cannot escape into runtime storage.

## Match statements

```text
match_stmt         := "match" expression ":" NEWLINE INDENT match_case+ DEDENT
match_case         := "case" match_pattern ":" suite
match_pattern      := "_"
                    | dotted_name ("(" binding_list? ")")?
binding_list       := NAME ("," NAME)* ","?
```

The subject must be an enum, variant, or `Result`. Enum patterns have no bindings. Variant patterns bind one name for each payload field. Result patterns are `Ok`, `Ok(value)`, `Err`, or `Err(error)`, depending on whether the corresponding payload is `void`.

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
== != < <= > >=
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
```

Array literals use square brackets. Slice expressions support `value[:]`, `value[start:]`, and `value[start:stop]`. Slice steps are not implemented.

`super().__init__(...)` and `super().method(...)` are recognized only inside a derived class method. Abstract base methods cannot be called directly through `super`.

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

`len(array)` and `len(slice)` return `usize`. `len(const char*)` emits `strlen`.

`sort(array_or_slice)` stably sorts mutable elements in ascending order and returns `void`. Fixed arrays are accepted directly when they refer to addressable storage; array literals are rejected. Slices may select a subrange to sort, but slicing a const array produces a const slice that cannot be sorted. Numeric primitives use numeric order, `bool` orders `false` before `true`, enums use their declared integer values, and `char*` or `const char*` values use lexicographic C-string order. Const elements and unordered aggregate or non-string pointer types are rejected. Unlike Python's list API, Cinder's builtin does not currently accept `key` or `reverse` arguments.

`print(...)` is globally available and emits to standard output without importing `stdio`. It accepts zero or more printable values, separates multiple arguments with a space, and appends a newline. Printable values are booleans, characters, integers, floats, and `const char*` strings.

`print` also accepts Python-style f-strings. Replacement fields use `{expression}` and may include simple format specs such as `{value:d}`, `{value:x}`, `{value:.2f}`, `{text:s}`, and `{letter:c}`. Literal braces are written as `{{` and `}}`. F-strings are currently supported only as `print` arguments.

`free(pointer)` and `panic(message)` are globally available. The corresponding namespaced APIs are available from `stdlib` and `cinder`.

Result values expose `.is_ok`, `.value`, and `.error`. Accessing a `void` payload is rejected.

## Deliberate omissions

The 0.5 grammar and checker do not implement multiple implementation inheritance, downcasting, runtime dynamic invocation by name, runtime field-value access, general-purpose generics, function pointer types, closures, exceptions, automatic ownership inference, aggregate ownership for destructor-bearing classes, copy or move hooks, nested match patterns, match guards, user-defined compile-time functions, AST macros, or multi-root package dependency graphs.
