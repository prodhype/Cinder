# Classes and interfaces

Cinder 0.4 adds classes, single implementation inheritance, abstract interfaces, explicit dynamic dispatch, constructors, destructors, and deterministic class lifetimes. The object model is designed around visible C11 layouts rather than hidden allocation or an implicit virtual-pointer field.

## Class declarations

```python
class File:
    private handle: *FILE

    def __init__(self, handle: *FILE):
        self.handle = handle

    def __del__(self):
        if self.handle != null:
            stdio.fclose(self.handle)
```

Class methods use an implicit `&Owner` type for an unannotated `self`. A method may declare `self: &const Owner` when it does not mutate the object. Fields may be marked `private`; only methods of the declaring class may access those fields.

Classes are values. `File(...)` constructs a `File` value and does not allocate memory. A local class value normally lives in the generated C stack frame. Raw allocation remains explicit through `alloc[File](...)`.

## Concrete layout

A class without an implementation base is emitted as an ordinary C struct. A class with one implementation base stores that base as its first member:

```python
class Entity:
    id: u64

class Player(Entity):
    score: i32
```

The generated representation is structurally equivalent to:

```c
typedef struct Entity {
    uint64_t id;
} Entity;

typedef struct Player {
    Entity _base;
    int32_t score;
} Player;
```

The implementation base is therefore a zero-offset prefix. Cinder adjusts inherited field and method receivers explicitly in generated C. It does not place a virtual-table pointer in each object.

Cinder permits one implementation base. Multiple implementation inheritance is rejected because it would require more complex layout, pointer adjustment, and destruction rules. A concrete class may implement multiple interface-only abstract bases because each interface uses a separate external table and does not add an object subobject.

## Constructors

`__init__` initializes an already allocated object. A constructor call lowers to a generated `Class__new(...)` helper that zero-initializes a local value, invokes `__init__`, and returns the value by ordinary C value semantics.

```python
class Point:
    x: i32
    y: i32

    def __init__(self, x: i32, y: i32):
        self.x = x
        self.y = y

point = Point(y=20, x=10)
```

Constructor arguments may be named and are reordered by the checker. A class without `__init__` has an empty constructor and begins zero-initialized.

When a derived class has an implementation base with a constructor, its explicit constructor must call `super().__init__(...)` as its first executable statement. This makes base initialization order visible and prevents derived fields from being used before the base is initialized.

Abstract classes cannot be constructed in Cinder source.

## Abstract classes and overrides

```python
abstract class Shape:
    @abstractmethod
    def area(self) -> f64:
        pass

    def scaled(self, factor: f64) -> f64:
        return self.area() * factor

class Circle(Shape):
    radius: f64

    def __init__(self, radius: f64):
        self.radius = radius

    @override
    def area(self) -> f64:
        return 3.141592653589793 * self.radius * self.radius
```

A concrete class must provide every inherited abstract method. The implementation must match the complete checked signature. `@override` asks the checker to verify that a base method exists and that the signature is compatible. Overriding without the decorator is accepted, but the decorator is recommended because it catches accidental renames.

An abstract class may contain fields, constructors, destructors, and concrete default methods. An abstract class containing state becomes the single implementation base when inherited. An abstract class with no instance fields and no implementation-layout requirement can serve as an interface-only base.

## Static dispatch

Calls on a concrete type are direct:

```python
def area(circle: &Circle) -> f64:
    return circle.area()
```

This lowers to a normal C call such as:

```c
return Circle_area(circle);
```

Inheritance alone does not make dispatch dynamic. The compiler uses the concrete method selected by static type resolution and emits any required base-pointer adjustment explicitly.

## Explicit dynamic dispatch

Dynamic dispatch appears in the type:

```python
def print_area(shape: &dyn Shape) -> void:
    stdio.printf("%.2f\n", shape.area())
```

A dynamic interface value is represented by two machine words in concept:

```c
typedef struct CinderDyn_Shape {
    void *object;
    const CinderVTable_Shape *vtable;
} CinderDyn_Shape;
```

Each concrete implementation has a constant interface table. Table entries are ordinary C function pointers with explicit object and table parameters. Default interface methods receive the dynamic pair, so calls they make to abstract methods remain dynamic. Concrete calls outside `&dyn` remain static.

`&const dyn Interface` creates a read-only dynamic borrow. The checker rejects calls to mutating methods through a const dynamic value.

A concrete-to-dynamic conversion borrows an addressable object. Constructor temporaries cannot be passed directly as `&dyn`; bind the object to a local first so its lifetime is explicit.

Dynamic interface values are non-owning. They cannot be returned by value or stored as owning aggregate state in 0.5. They are intended for call-boundary polymorphism whose concrete owner remains visible.

## Destructors and ownership transfer

`__del__` is deterministic cleanup, not garbage collection. For a local class value with a destructor, Cinder emits a generated `Class__drop(&value)` call on every normal scope exit and on `return`, `break`, `continue`, and Result propagation.

Local class values are destroyed in reverse declaration order. A derived destructor runs before the implementation-base destructor. Active `defer` calls and class drops share the same lexical cleanup path.

Destructor-bearing classes are move-only in 0.5. The checker accepts ownership from a constructor or a function returning the class, but rejects implicit copies:

```python
first = Resource()
second = first  # error: would copy one owned lifetime
```

Returning an owned local transfers its lifetime to the caller. Reassigning an owned local evaluates the replacement first, drops the old value, and then transfers the replacement. A discarded class-returning call is materialized and immediately dropped.

To keep generated cleanup direct and auditable, 0.5 rejects destructor-bearing classes inside globals, arrays, variants, Results, or other owning aggregates, and rejects by-value parameter passing for them. Use references for borrowed parameters and explicit pointer-based containers when aggregate ownership is needed.

`__del__` cannot be called directly. It is compiler-managed cleanup. There is no exception unwinding, reference counting, hidden heap ownership, or ownership inference.

## Cross-module ABI

Generated module headers contain complete public class layouts, interface value and table definitions, constructor and drop declarations, reflected metadata declarations, and concrete interface-table declarations. A module importing a class or interface includes the dependency's generated header.

All internal names receive deterministic project-and-module prefixes. Generated headers are valid C11 and are wrapped in `extern "C"` when included from C++.

## Deliberate limits

Cinder 0.5 does not implement multiple implementation inheritance, downcasting, runtime interface queries, class templates, automatic heap ownership, copy constructors, user-defined move hooks, exceptions, or a stable long-term binary ABI guarantee. The generated C representation is documented and tested, but the compiler remains alpha software and may revise mangled names before 1.0.
