from __future__ import annotations

from collections.abc import Mapping, Sequence

from cinder.symbols import ClassSymbol, StructSymbol
from cinder.types import (
    ERROR,
    ArrayType,
    ClassType,
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
    StructType,
    TupleType,
    Type,
    is_void,
    strip_const,
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
    if isinstance(raw, (FileType, ListType, MapType, SetType, OwnedType)):
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
    if class_.primary_base is not None and class_needs_drop(
        class_.primary_base,
        classes=classes,
        structs=structs,
        seen=next_seen,
    ):
        return True
    return False


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
