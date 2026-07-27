# Algebraic data types and results

Cinder 0.3 adds enums, plain unions, tagged variants, exhaustive matching, and typed results. These features are designed around explicit C11 representations rather than hidden runtime objects.

## Enums

```python
enum State:
    idle
    running
    failed = 10
```

Implicit values begin at zero and advance from the preceding value. Duplicate values are rejected because exhaustive matching needs each member to be distinguishable.

Generated C uses a typedef enum with prefixed member names.

## Plain unions

```python
union Scalar:
    integer: i64
    real: f64
```

A union initializer chooses one field:

```python
value = Scalar(integer=42)
```

The generated representation is an ordinary C union. There is no active-field tag and no runtime protection against reading a different member.

## Tagged variants

```python
variant Token:
    Identifier(text: const char*)
    Integer(value: i64)
    Range(start: i64, stop: i64)
    End
```

Constructors are namespaced and statically checked:

```python
integer = Token.Integer(42)
range_token = Token.Range(stop=10, start=0)
end = Token.End()
```

The generated representation is equivalent in shape to:

```c
typedef enum Token_Tag {
    Token_Tag_Identifier = 0,
    Token_Tag_Integer = 1,
    Token_Tag_Range = 2,
    Token_Tag_End = 3
} Token_Tag;

typedef struct Token {
    Token_Tag tag;
    union {
        struct { const char *text; } Identifier;
        struct { int64_t value; } Integer;
        struct { int64_t start; int64_t stop; } Range;
        unsigned char _cinder_empty;
    } data;
} Token;
```

The exact emitter uses generated module prefixes where needed, but the tag and payload remain visible.

## Matching

```python
match token:
    case Token.Identifier(text):
        print_name(text)
    case Token.Integer(value):
        print_integer(value)
    case Token.Range(start, stop):
        print_range(start, stop)
    case Token.End:
        pass
```

The checker validates the subject type, case names, qualifiers, payload arity, duplicate cases, wildcard placement, and exhaustiveness. Each payload binding is a lexically scoped local with the declared payload field type.

Matching lowers to a single evaluated subject temporary followed by ordinary tag comparisons. There is no visitor allocation or runtime pattern engine.

## Results

`Result[T, E]` is a compiler-defined tagged type with `Ok` and `Err` cases. It was the first generic type implemented in 0.3; user-defined generic variants and other nominals are now monomorphized similarly.

```python
enum ParseError:
    invalid


def parse(value: i32) -> Result[i32, ParseError]:
    if value < 0:
        return Err(ParseError.invalid)
    return Ok(value)
```

Construction is contextual. `Ok(value)` and `Err(error)` do not define an independent type; the checker obtains `T` and `E` from the surrounding expected type.

`Result[void, E]` uses `Ok()` with no success payload. `Result[T, void]` is also representable and uses `Err()` with no error payload.

## Propagation

```python
def increment(value: i32) -> Result[i32, ParseError]:
    parsed = parse(value)?
    return Ok(parsed + 1)
```

The operand of `?` is evaluated once into a generated local. If its tag is `Err`, the compiler constructs a compatible error result for the enclosing function, executes active deferred calls in reverse order, and returns. Otherwise the expression yields the success payload.

The source and enclosing error types need not be identical when normal assignment compatibility permits conversion. Success types are independent because propagation unwraps the source success value.

Propagation is restricted in contexts where inserting an early-return statement would obscure short-circuit or repeated evaluation semantics. A result should first be assigned in a preceding statement when used near an `elif`, loop condition, C-style loop update, short-circuit right operand, or `defer`.

## Direct result access

A result value exposes:

```python
result.is_ok
result.value
result.error
```

`.value` and `.error` are direct payload accessors and do not perform a runtime tag check. Use `match` when the active side is not already established by program logic.
