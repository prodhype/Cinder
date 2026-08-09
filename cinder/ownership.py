from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto

from cinder.symbols import ClassSymbol, StructSymbol, VariableSymbol
from cinder.types import (
    ERROR,
    ArrayType,
    AtomicType,
    ClassType,
    ClosureType,
    ConstType,
    DynType,
    FileType,
    ListType,
    MapType,
    MapViewType,
    OptionType,
    OwnedType,
    PointerType,
    ReferenceType,
    ResultType,
    SetType,
    SliceType,
    StringBuilderType,
    StringType,
    StructType,
    TupleType,
    Type,
    is_void,
    strip_const,
)


def type_contains_atomic_storage(
    type_: Type,
    *,
    classes: Mapping[ClassType, ClassSymbol],
    structs: Mapping[StructType, StructSymbol],
    seen: frozenset[Type] | None = None,
) -> bool:
    raw = strip_const(type_)
    if raw is ERROR or is_void(raw):
        return False
    if isinstance(raw, (PointerType, ReferenceType, SliceType, DynType, MapViewType)):
        return False
    if isinstance(raw, AtomicType):
        return True
    current = seen if seen is not None else frozenset()
    if isinstance(raw, ClassType):
        if raw in current:
            return False
        class_ = classes.get(raw)
        if class_ is None:
            return False
        next_seen = current | {raw}
        return any(
            type_contains_atomic_storage(
                field.type,
                classes=classes,
                structs=structs,
                seen=next_seen,
            )
            for field in class_.fields.values()
        )
    if isinstance(raw, StructType):
        if raw in current:
            return False
        struct_ = structs.get(raw)
        if struct_ is None:
            return False
        next_seen = current | {raw}
        return any(
            type_contains_atomic_storage(
                field.type,
                classes=classes,
                structs=structs,
                seen=next_seen,
            )
            for field in struct_.fields.values()
        )
    if isinstance(raw, ClosureType):
        return type_contains_atomic_storage(
            raw.env_type,
            classes=classes,
            structs=structs,
            seen=current,
        )
    if isinstance(raw, (ArrayType, ListType, SetType, OptionType, OwnedType)):
        return type_contains_atomic_storage(
            raw.inner,
            classes=classes,
            structs=structs,
            seen=current,
        )
    if isinstance(raw, MapType):
        return type_contains_atomic_storage(
            raw.key,
            classes=classes,
            structs=structs,
            seen=current,
        ) or type_contains_atomic_storage(
            raw.value,
            classes=classes,
            structs=structs,
            seen=current,
        )
    if isinstance(raw, TupleType):
        return any(
            type_contains_atomic_storage(
                element,
                classes=classes,
                structs=structs,
                seen=current,
            )
            for element in raw.elements
        )
    if isinstance(raw, ResultType):
        return (
            not is_void(raw.ok)
            and type_contains_atomic_storage(
                raw.ok,
                classes=classes,
                structs=structs,
                seen=current,
            )
        ) or (
            not is_void(raw.error)
            and type_contains_atomic_storage(
                raw.error,
                classes=classes,
                structs=structs,
                seen=current,
            )
        )
    return False


def type_is_relocatable(
    type_: Type,
    *,
    classes: Mapping[ClassType, ClassSymbol],
    structs: Mapping[StructType, StructSymbol],
) -> bool:
    return not type_contains_atomic_storage(
        type_,
        classes=classes,
        structs=structs,
    )


def type_is_copyable(
    type_: Type,
    *,
    classes: Mapping[ClassType, ClassSymbol],
    structs: Mapping[StructType, StructSymbol],
) -> bool:
    return type_is_relocatable(
        type_,
        classes=classes,
        structs=structs,
    ) and not type_needs_drop(
        type_,
        classes=classes,
        structs=structs,
    )


def type_needs_drop(
    type_: Type,
    *,
    classes: Mapping[ClassType, ClassSymbol],
    structs: Mapping[StructType, StructSymbol],
    seen: frozenset[Type] | None = None,
) -> bool:
    raw = strip_const(type_)
    if raw is ERROR or is_void(raw):
        return False
    if isinstance(raw, (PointerType, ReferenceType, SliceType, DynType, MapViewType)):
        return False
    if isinstance(
        raw,
        (
            FileType,
            ListType,
            MapType,
            SetType,
            StringType,
            StringBuilderType,
            OwnedType,
        ),
    ):
        return True
    if isinstance(raw, ConstType):
        return type_needs_drop(
            raw.inner,
            classes=classes,
            structs=structs,
            seen=seen,
        )
    if isinstance(raw, ClassType):
        class_ = classes.get(raw)
        if class_ is None:
            return False
        return class_needs_drop(class_, classes=classes, structs=structs, seen=seen)
    if isinstance(raw, ClosureType):
        return type_needs_drop(
            raw.env_type,
            classes=classes,
            structs=structs,
            seen=seen,
        )
    if isinstance(raw, StructType):
        struct_ = structs.get(raw)
        if struct_ is None:
            return False
        return struct_needs_drop(struct_, classes=classes, structs=structs, seen=seen)
    if isinstance(raw, ArrayType):
        return type_needs_drop(
            raw.inner,
            classes=classes,
            structs=structs,
            seen=seen,
        )
    if isinstance(raw, TupleType):
        return any(
            type_needs_drop(element, classes=classes, structs=structs, seen=seen)
            for element in raw.elements
        )
    if isinstance(raw, OptionType):
        return type_needs_drop(
            raw.inner,
            classes=classes,
            structs=structs,
            seen=seen,
        )
    if isinstance(raw, ResultType):
        ok_needs = (
            False
            if is_void(raw.ok)
            else type_needs_drop(raw.ok, classes=classes, structs=structs, seen=seen)
        )
        err_needs = (
            False
            if is_void(raw.error)
            else type_needs_drop(
                raw.error,
                classes=classes,
                structs=structs,
                seen=seen,
            )
        )
        return ok_needs or err_needs
    return False


def class_needs_drop(
    class_: ClassSymbol,
    *,
    classes: Mapping[ClassType, ClassSymbol],
    structs: Mapping[StructType, StructSymbol],
    seen: frozenset[Type] | None = None,
) -> bool:
    current: frozenset[Type] = seen if seen is not None else frozenset()
    if class_.type in current:
        return False
    next_seen = current | {class_.type}
    if class_.destructor is not None:
        return True
    for field in class_.fields.values():
        if type_needs_drop(
            field.type,
            classes=classes,
            structs=structs,
            seen=next_seen,
        ):
            return True
    return class_.primary_base is not None and class_needs_drop(
        class_.primary_base,
        classes=classes,
        structs=structs,
        seen=next_seen,
    )


def struct_needs_drop(
    struct_: StructSymbol,
    *,
    classes: Mapping[ClassType, ClassSymbol],
    structs: Mapping[StructType, StructSymbol],
    seen: frozenset[Type] | None = None,
) -> bool:
    current: frozenset[Type] = seen if seen is not None else frozenset()
    if struct_.type in current:
        return False
    next_seen = current | {struct_.type}
    return any(
        type_needs_drop(
            field.type,
            classes=classes,
            structs=structs,
            seen=next_seen,
        )
        for field in struct_.fields.values()
    )


def drop_fields(
    owner: ClassSymbol | StructSymbol,
) -> Sequence[tuple[str, Type]]:
    """Field names and types in declaration order for reverse-order drops."""
    return tuple((field.name, field.type) for field in owner.fields.values())


class ValueUseKind(Enum):
    COPY = auto()
    MOVE = auto()
    BORROW = auto()
    ADDRESS = auto()


@dataclass(frozen=True, slots=True)
class ValueUseResolution:
    kind: ValueUseKind
    source: VariableSymbol | None
