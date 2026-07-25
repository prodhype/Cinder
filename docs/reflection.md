# Reflection and compile-time inspection

Cinder 0.5 provides two related facilities. Runtime reflection is opt-in through `@reflect` and emits explicit metadata objects. Compile-time inspection is available for nominal types without adding per-object state.

## Opt-in runtime metadata

```python
@reflect
struct User:
    id: u64
    name: const char*
    active: bool
```

`@reflect` is accepted on structs, classes, enums, unions, and variants. Class metadata includes inherited implementation fields and the effective method set. A reflected abstract interface requires each concrete implementation to use `@reflect`, because the interface table exposes the concrete runtime type metadata.

Reflection does not add a pointer to ordinary objects. The compiler emits constant metadata arrays and one `CinderTypeInfo` object for each reflected type. A reflected dynamic-interface table contains a pointer to the concrete type's metadata; an unreflected table stores `NULL` in that slot.

The runtime representation is declared in `cinder_runtime.h`:

```c
typedef struct CinderFieldInfo {
    const char *name;
    const char *type_name;
    size_t offset;
    size_t size;
    size_t alignment;
    bool is_private;
} CinderFieldInfo;

typedef struct CinderMethodInfo {
    const char *name;
    const char *signature;
    const char *return_type_name;
    size_t parameter_count;
    bool is_abstract;
    bool is_override;
} CinderMethodInfo;

typedef struct CinderTypeInfo {
    const char *name;
    CinderTypeKind kind;
    size_t size;
    size_t alignment;
    const CinderFieldInfo *fields;
    size_t field_count;
    const CinderMethodInfo *methods;
    size_t method_count;
} CinderTypeInfo;
```

Offsets use `offsetof`, sizes use `sizeof`, and alignments use the runtime's portable alignment macro. The metadata is therefore checked by the same C compiler that compiles the generated object layout.

## Runtime operations

`type_info(value)` returns `*const CinderTypeInfo`. `fields(value)` and `methods(value)` return const slices over the corresponding metadata arrays.

```python
info = type_info(user)
stdio.printf("%s: %zu fields\n", info.name, info.field_count)

for field in fields(user):
    stdio.printf("%s at %zu\n", field.name, field.offset)
```

These operations require the value's nominal type to use `@reflect`.

`type_name(value)` is compile-time text when the concrete static type is known, so it does not require metadata. For an `&dyn Interface` value, `type_name` reads the concrete metadata through the interface table and therefore requires a reflected interface.

```python
def report(shape: &dyn Shape) -> void:
    stdio.printf("runtime type: %s\n", type_name(shape))
```

The argument expression of a concrete runtime reflection operation is still evaluated once, even when the resulting metadata address is statically known. Reflection does not erase side effects.

## Compile-time type values

`type_of(expression)` produces a compiler-only type value. It may be used by other compile-time operations and in `static_assert`, but it cannot be stored in a runtime variable or emitted as a C value.

```python
static_assert(type_of(make_user()) == type_of(User(id=0, name="", active=false)))
```

The expression passed to `type_of` is type-checked but is not evaluated at runtime when the type value is used only at compile time.

## Compile-time queries

The following operations are implemented:

```python
type_of(expression)
type_name(expression)
size_of(Type)
align_of(Type)
field_count(Type)
method_count(Type)
has_field(Type, "name")
has_method(Type, "serialize")
implements(Concrete, Interface)
fields_of(Type)
methods_of(Type)
```

`size_of` and `align_of` lower to C `sizeof` and alignment expressions. This preserves target-specific layout rather than trying to guess it in Python. Field and method counts, member existence, and interface implementation are resolved by the Cinder checker.

`field_count`, `method_count`, `has_field`, `has_method`, `fields_of`, and `methods_of` accept nominal types. `implements` requires two class types and reports whether the source implements the abstract target.

## Static assertions

A top-level static assertion has an optional message:

```python
static_assert(field_count(User) == 3, "User schema changed")
static_assert(size_of(User) >= 24)
```

Assertions that Cinder can fully evaluate are checked immediately and emitted as a true C static assertion. Assertions involving target layout are emitted with `sizeof`, `offsetof`, or alignment expressions so the native compiler verifies them for the selected target ABI.

A failed Cinder-evaluable assertion is a source diagnostic. A target-dependent assertion can fail later as a normal C compiler error.

## Compile-time member iteration

`fields_of` and `methods_of` are consumed by a `comptime` loop:

```python
def print_layout() -> void:
    for field in comptime fields_of(User):
        stdio.printf(
            "%s: offset=%zu size=%zu\n",
            field.name,
            field.offset,
            field.size,
        )
```

The loop is unrolled by the Cinder emitter. There is no runtime loop and no runtime metadata requirement. Each iteration is emitted as an ordinary C block with member properties substituted as literals or layout expressions.

Compile-time field bindings expose:

```text
name
type_name
offset
size
alignment
is_private
```

Compile-time method bindings expose:

```text
name
signature
return_type_name
parameter_count
is_abstract
is_override
```

The binding exists only in the compile-time loop body and cannot escape into runtime storage.

## Binary-size model

An unreflected concrete type has no runtime metadata arrays. An unreflected interface table still contains one nullable metadata pointer so reflected and unreflected tables have one uniform shape. A reflected type contributes its type record, one record per visible field, one record per effective method, and the referenced strings.

This cost is explicit in generated C and can be inspected with ordinary object-file tools. Reflection does not allocate at startup and does not maintain a global registry.

## Deliberate limits

Cinder 0.5 does not provide runtime field value access, mutation by field name, dynamic method invocation, metadata registries, attributes beyond the documented records, serializer generation syntax, compile-time AST rewriting, or user-defined macros. Runtime reflection describes layout; it does not turn statically typed values into dynamic Python objects.
