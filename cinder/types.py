from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class Type:
    pass


@dataclass(frozen=True, slots=True)
class PrimitiveType(Type):
    name: str
    c_name: str
    category: str
    bits: int | None = None
    signed: bool | None = None


@dataclass(frozen=True, slots=True)
class StructType(Type):
    name: str
    c_name: str | None = None
    type_args: tuple[Type, ...] = ()


@dataclass(frozen=True, slots=True)
class ClassType(Type):
    name: str
    c_name: str | None = None
    type_args: tuple[Type, ...] = ()


@dataclass(frozen=True, slots=True)
class EnumType(Type):
    name: str
    c_name: str | None = None
    type_args: tuple[Type, ...] = ()


@dataclass(frozen=True, slots=True)
class UnionType(Type):
    name: str
    c_name: str | None = None
    type_args: tuple[Type, ...] = ()


@dataclass(frozen=True, slots=True)
class VariantType(Type):
    name: str
    c_name: str | None = None
    type_args: tuple[Type, ...] = ()


@dataclass(frozen=True, slots=True)
class ResultType(Type):
    ok: Type
    error: Type

    @property
    def ok_type(self) -> Type:
        return self.ok

    @property
    def error_type(self) -> Type:
        return self.error


@dataclass(frozen=True, slots=True)
class OptionType(Type):
    inner: Type


@dataclass(frozen=True, slots=True)
class OwnedType(Type):
    inner: Type


@dataclass(frozen=True, slots=True)
class TupleType(Type):
    elements: tuple[Type, ...]


@dataclass(frozen=True, slots=True)
class ListType(Type):
    inner: Type


@dataclass(frozen=True, slots=True)
class MapType(Type):
    key: Type
    value: Type


@dataclass(frozen=True, slots=True)
class SetType(Type):
    inner: Type


@dataclass(frozen=True, slots=True)
class MapViewType(Type):
    map_type: MapType
    kind: str


@dataclass(frozen=True, slots=True)
class FileType(Type):
    pass


@dataclass(frozen=True, slots=True)
class OpaqueType(Type):
    name: str
    c_name: str


@dataclass(frozen=True, slots=True)
class ConstType(Type):
    inner: Type


@dataclass(frozen=True, slots=True)
class PointerType(Type):
    inner: Type


@dataclass(frozen=True, slots=True)
class ReferenceType(Type):
    inner: Type


@dataclass(frozen=True, slots=True)
class ArrayType(Type):
    inner: Type
    length: int


@dataclass(frozen=True, slots=True)
class SliceType(Type):
    inner: Type


@dataclass(frozen=True, slots=True)
class DynType(Type):
    interface: ClassType
    is_const: bool = False


@dataclass(frozen=True, slots=True)
class TypeValueType(Type):
    value: Type


@dataclass(frozen=True, slots=True)
class ComptimeCollectionType(Type):
    kind: str
    owner: Type


@dataclass(frozen=True, slots=True)
class ComptimeItemType(Type):
    kind: str
    owner: Type


@dataclass(frozen=True, slots=True)
class FunctionValueType(Type):
    name: str


@dataclass(frozen=True, slots=True)
class FunctionPointerType(Type):
    param_types: tuple[Type, ...]
    return_type: Type


@dataclass(frozen=True, slots=True)
class ModuleType(Type):
    name: str


@dataclass(frozen=True, slots=True)
class RangeType(Type):
    inner: Type


@dataclass(frozen=True, slots=True)
class NullType(Type):
    pass


@dataclass(frozen=True, slots=True)
class ErrorType(Type):
    pass


VOID: Final = PrimitiveType("void", "void", "void")
BOOL: Final = PrimitiveType("bool", "bool", "bool", 1, False)
CHAR: Final = PrimitiveType("char", "char", "integer", 8, None)
I8: Final = PrimitiveType("i8", "int8_t", "integer", 8, True)
I16: Final = PrimitiveType("i16", "int16_t", "integer", 16, True)
I32: Final = PrimitiveType("i32", "int32_t", "integer", 32, True)
I64: Final = PrimitiveType("i64", "int64_t", "integer", 64, True)
U8: Final = PrimitiveType("u8", "uint8_t", "integer", 8, False)
U16: Final = PrimitiveType("u16", "uint16_t", "integer", 16, False)
U32: Final = PrimitiveType("u32", "uint32_t", "integer", 32, False)
U64: Final = PrimitiveType("u64", "uint64_t", "integer", 64, False)
F32: Final = PrimitiveType("f32", "float", "float", 32, True)
F64: Final = PrimitiveType("f64", "double", "float", 64, True)
ISIZE: Final = PrimitiveType("isize", "ptrdiff_t", "integer", None, True)
USIZE: Final = PrimitiveType("usize", "size_t", "integer", None, False)
C_INT: Final = PrimitiveType("c_int", "int", "integer", None, True)
C_LONG: Final = PrimitiveType("c_long", "long", "integer", None, True)
C_SIZE_T: Final = PrimitiveType("c_size_t", "size_t", "integer", None, False)
NULL: Final = NullType()
ERROR: Final = ErrorType()
FILE: Final = FileType()

PRIMITIVES: Final[dict[str, PrimitiveType]] = {
    value.name: value
    for value in (
        VOID,
        BOOL,
        CHAR,
        I8,
        I16,
        I32,
        I64,
        U8,
        U16,
        U32,
        U64,
        F32,
        F64,
        ISIZE,
        USIZE,
        C_INT,
        C_LONG,
        C_SIZE_T,
    )
}


def string_type() -> PointerType:
    return PointerType(ConstType(CHAR))


def nominal_c_name(
    type_: StructType | ClassType | EnumType | UnionType | VariantType,
) -> str:
    return type_.c_name or type_.name


def dyn_c_name(type_: DynType | ClassType) -> str:
    interface = type_.interface if isinstance(type_, DynType) else type_
    return f"CinderDyn_{type_key(interface)}"


def interface_vtable_c_name(interface: ClassType) -> str:
    return f"CinderVTable_{type_key(interface)}"


def result_c_name(type_: ResultType) -> str:
    return f"CinderResult_{type_key(type_.ok)}_{type_key(type_.error)}"


def option_c_name(type_: OptionType) -> str:
    return f"CinderOption_{type_key(type_.inner)}"


def owned_c_name(type_: OwnedType) -> str:
    return f"CinderOwned_{type_key(type_.inner)}"


def tuple_c_name(type_: TupleType) -> str:
    suffix = "_".join(type_key(element) for element in type_.elements)
    return f"CinderTuple_{len(type_.elements)}" + (f"_{suffix}" if suffix else "")


def list_c_name(type_: ListType) -> str:
    return f"CinderList_{type_key(type_.inner)}"


def file_c_name() -> str:
    return "CinderFile"


def map_c_name(type_: MapType) -> str:
    return f"CinderMap_{type_key(type_.key)}_{type_key(type_.value)}"


def set_c_name(type_: SetType) -> str:
    return f"CinderSet_{type_key(type_.inner)}"


def map_view_c_name(type_: MapViewType) -> str:
    prefix = {
        "keys": "CinderMapKeys",
        "values": "CinderMapValues",
        "items": "CinderMapItems",
    }[type_.kind]
    return (
        f"{prefix}_{type_key(type_.map_type.key)}_"
        f"{type_key(type_.map_type.value)}"
    )


def type_name(type_: Type) -> str:
    match type_:
        case PrimitiveType(name=name):
            return name
        case StructType(name=name, type_args=type_args) | ClassType(name=name, type_args=type_args) | EnumType(name=name, type_args=type_args) | UnionType(name=name, type_args=type_args) | VariantType(name=name, type_args=type_args):
            if type_args:
                return (
                    f"{name}["
                    + ", ".join(type_name(argument) for argument in type_args)
                    + "]"
                )
            return name
        case ResultType(ok=ok, error=error):
            return f"Result[{type_name(ok)}, {type_name(error)}]"
        case OptionType(inner=inner):
            return f"Option[{type_name(inner)}]"
        case OwnedType(inner=inner):
            return f"Owned[{type_name(inner)}]"
        case TupleType(elements=elements):
            return "Tuple[" + ", ".join(type_name(element) for element in elements) + "]"
        case ListType(inner=inner):
            return f"List[{type_name(inner)}]"
        case MapType(key=key, value=value):
            return f"Map[{type_name(key)}, {type_name(value)}]"
        case SetType(inner=inner):
            return f"Set[{type_name(inner)}]"
        case FileType():
            return "File"
        case MapViewType(map_type=map_type, kind=kind):
            view_name = {
                "keys": "MapKeys",
                "values": "MapValues",
                "items": "MapItems",
            }[kind]
            return (
                f"{view_name}[{type_name(map_type.key)}, "
                f"{type_name(map_type.value)}]"
            )
        case OpaqueType(name=name):
            return name
        case ConstType(inner=inner):
            return f"const {type_name(inner)}"
        case PointerType(inner=inner):
            return f"*{type_name(inner)}"
        case ReferenceType(inner=inner):
            return f"&{type_name(inner)}"
        case ArrayType(inner=inner, length=length):
            return f"{type_name(inner)}[{length}]"
        case SliceType(inner=inner):
            return f"[]{type_name(inner)}"
        case DynType(interface=interface, is_const=is_const):
            qualifier = "const " if is_const else ""
            return f"&{qualifier}dyn {type_name(interface)}"
        case TypeValueType(value=value):
            return f"type[{type_name(value)}]"
        case ComptimeCollectionType(kind=kind, owner=owner):
            return f"comptime {kind}[{type_name(owner)}]"
        case ComptimeItemType(kind=kind, owner=owner):
            return f"comptime {kind[:-1] if kind.endswith('s') else kind}[{type_name(owner)}]"
        case FunctionValueType(name=name):
            return f"function {name}"
        case FunctionPointerType(param_types=param_types, return_type=return_type):
            params = ", ".join(type_name(param) for param in param_types)
            return f"def({params}) -> {type_name(return_type)}"
        case ModuleType(name=name):
            return f"module {name}"
        case RangeType(inner=inner):
            return f"range[{type_name(inner)}]"
        case NullType():
            return "null"
        case ErrorType():
            return "<error>"
    raise AssertionError(f"unhandled type: {type_!r}")


def strip_const(type_: Type) -> Type:
    return type_.inner if isinstance(type_, ConstType) else type_


def strip_reference(type_: Type) -> Type:
    return type_.inner if isinstance(type_, ReferenceType) else type_


def value_type(type_: Type) -> Type:
    type_ = strip_reference(type_)
    return strip_const(type_)


def is_void(type_: Type) -> bool:
    return strip_const(type_) == VOID


def is_bool(type_: Type) -> bool:
    return strip_const(type_) == BOOL


def is_integer(type_: Type) -> bool:
    type_ = strip_const(type_)
    return isinstance(type_, PrimitiveType) and type_.category == "integer"


def is_float(type_: Type) -> bool:
    type_ = strip_const(type_)
    return isinstance(type_, PrimitiveType) and type_.category == "float"


def is_numeric(type_: Type) -> bool:
    return is_integer(type_) or is_float(type_)


def is_pointer_like(type_: Type) -> bool:
    return isinstance(strip_const(type_), (PointerType, ReferenceType))


def is_c_string(type_: Type) -> bool:
    raw = strip_const(type_)
    return (
        isinstance(raw, PointerType)
        and isinstance(raw.inner, ConstType)
        and strip_const(raw.inner) == CHAR
    )


def is_hashable(type_: Type) -> bool:
    raw = strip_const(type_)
    return (
        raw == BOOL
        or raw == CHAR
        or is_integer(raw)
        or isinstance(raw, EnumType)
        or is_c_string(raw)
    )


def is_equatable(type_: Type) -> bool:
    raw = strip_const(type_)
    return (
        is_numeric(raw)
        or raw == BOOL
        or isinstance(raw, (EnumType, PointerType, ReferenceType))
    )


def is_owning_container(type_: Type) -> bool:
    return isinstance(
        strip_const(type_),
        (ListType, MapType, SetType, FileType, OwnedType),
    )


def is_scalar(type_: Type) -> bool:
    type_ = strip_const(type_)
    return (
        isinstance(
            type_,
            (PrimitiveType, EnumType, PointerType, ReferenceType, DynType, NullType),
        )
        and not is_void(type_)
    )


def is_condition_type(type_: Type) -> bool:
    return is_scalar(type_) or isinstance(strip_const(type_), SliceType)


def element_type(type_: Type) -> Type | None:
    type_ = strip_const(type_)
    if isinstance(type_, (ArrayType, SliceType, ListType, PointerType, ReferenceType)):
        return type_.inner
    if isinstance(type_, SetType):
        return type_.inner
    if isinstance(type_, MapType):
        return type_.key
    if isinstance(type_, MapViewType):
        if type_.kind == "keys":
            return type_.map_type.key
        if type_.kind == "values":
            return type_.map_type.value
        return TupleType((type_.map_type.key, type_.map_type.value))
    return None


def common_numeric_type(left: Type, right: Type) -> Type:
    left = strip_const(left)
    right = strip_const(right)
    if left == ERROR or right == ERROR:
        return ERROR
    if not isinstance(left, PrimitiveType) or not isinstance(right, PrimitiveType):
        return ERROR

    if left.category == "float" or right.category == "float":
        if left == F64 or right == F64:
            return F64
        return F32

    if left.bits is None or right.bits is None:
        if left in (USIZE, C_SIZE_T) or right in (USIZE, C_SIZE_T):
            return USIZE
        if left == ISIZE or right == ISIZE:
            return ISIZE
        if left == C_LONG or right == C_LONG:
            return C_LONG
        return C_INT

    def promote(value: PrimitiveType) -> PrimitiveType:
        if value.bits is not None and value.bits < 32:
            return I32
        return value

    left = promote(left)
    right = promote(right)
    if left == right:
        return left
    assert left.bits is not None and right.bits is not None

    mapping = {
        (32, True): I32,
        (64, True): I64,
        (32, False): U32,
        (64, False): U64,
    }

    if left.signed == right.signed:
        return mapping[(max(left.bits, right.bits), bool(left.signed))]

    signed_type = left if left.signed else right
    unsigned_type = right if left.signed else left
    assert signed_type.bits is not None and unsigned_type.bits is not None
    if unsigned_type.bits >= signed_type.bits:
        return mapping[(unsigned_type.bits, False)]
    if signed_type.bits > unsigned_type.bits:
        return mapping[(signed_type.bits, True)]
    return mapping[(signed_type.bits, False)]


def common_type(left: Type, right: Type) -> Type:
    if left == ERROR or right == ERROR:
        return ERROR
    if left == right:
        return left
    if is_numeric(left) and is_numeric(right):
        return common_numeric_type(left, right)
    if can_assign(left, right):
        return left
    if can_assign(right, left):
        return right
    return ERROR


def can_assign(target: Type, source: Type) -> bool:
    if target == ERROR or source == ERROR:
        return True
    if target == source:
        return True

    if isinstance(target, ConstType):
        return can_assign(target.inner, strip_const(source))
    if isinstance(source, ConstType) and not isinstance(
        target, (PointerType, ReferenceType, SliceType)
    ):
        return can_assign(target, source.inner)

    if is_numeric(target) and is_numeric(source):
        return True
    if target == BOOL and is_scalar(source):
        return True

    if isinstance(target, PointerType):
        if source == NULL:
            return True
        if isinstance(source, ReferenceType):
            return can_borrow_elements(target.inner, source.inner)
        if isinstance(source, PointerType):
            return can_borrow_elements(target.inner, source.inner)
        if isinstance(source, ArrayType):
            return can_borrow_elements(target.inner, source.inner)
        return False

    if isinstance(target, ReferenceType):
        if source == NULL:
            return False
        if isinstance(source, ReferenceType):
            return can_borrow_elements(target.inner, source.inner)
        if isinstance(source, PointerType):
            return can_borrow_elements(target.inner, source.inner)
        return can_assign(target.inner, source)

    if isinstance(target, SliceType):
        if isinstance(source, SliceType):
            return can_borrow_elements(target.inner, source.inner)
        if isinstance(source, ArrayType):
            return can_borrow_elements(target.inner, source.inner)
        return False

    if isinstance(target, DynType) and isinstance(source, DynType):
        return (
            target.interface == source.interface
            and (target.is_const or not source.is_const)
        )

    if isinstance(target, ArrayType) and isinstance(source, ArrayType):
        return target.length == source.length and can_assign(target.inner, source.inner)

    if isinstance(target, TupleType) and isinstance(source, TupleType):
        return target == source

    if isinstance(target, ListType) and isinstance(source, ListType):
        return target == source

    if isinstance(target, OptionType) and isinstance(source, OptionType):
        return target == source

    if isinstance(target, OwnedType) and isinstance(source, OwnedType):
        return target == source

    if isinstance(target, MapType) and isinstance(source, MapType):
        return target == source

    if isinstance(target, SetType) and isinstance(source, SetType):
        return target == source

    if isinstance(target, FileType) and isinstance(source, FileType):
        return True

    if isinstance(target, MapViewType) and isinstance(source, MapViewType):
        return target == source

    if isinstance(target, FunctionPointerType) and isinstance(source, FunctionPointerType):
        if len(target.param_types) != len(source.param_types):
            return False
        if target.return_type != source.return_type:
            return False
        return all(
            target_param == source_param
            for target_param, source_param in zip(
                target.param_types, source.param_types, strict=True
            )
        )

    return False


def can_borrow_elements(target: Type, source: Type) -> bool:
    if target == source:
        return True
    target_unqualified = strip_const(target)
    source_unqualified = strip_const(source)
    if target_unqualified == VOID:
        return not isinstance(source_unqualified, FunctionValueType)
    if source_unqualified == VOID:
        return True
    if isinstance(target, ConstType):
        return can_assign(target.inner, strip_const(source))
    if isinstance(source, ConstType):
        return False
    return can_assign(target, source)


def type_key(type_: Type) -> str:
    match type_:
        case PrimitiveType(name=name):
            return name
        case StructType() | ClassType() | EnumType() | UnionType() | VariantType():
            return _sanitize_key(nominal_c_name(type_))
        case ResultType(ok=ok, error=error):
            return f"result_{type_key(ok)}_{type_key(error)}"
        case OptionType(inner=inner):
            return f"option_{type_key(inner)}"
        case OwnedType(inner=inner):
            return f"owned_{type_key(inner)}"
        case TupleType(elements=elements):
            suffix = "_".join(type_key(element) for element in elements)
            return f"tuple_{len(elements)}" + (f"_{suffix}" if suffix else "")
        case ListType(inner=inner):
            return f"list_{type_key(inner)}"
        case MapType(key=key, value=value):
            return f"map_{type_key(key)}_{type_key(value)}"
        case SetType(inner=inner):
            return f"set_{type_key(inner)}"
        case FileType():
            return "file"
        case MapViewType(map_type=map_type, kind=kind):
            return (
                f"map_{_sanitize_key(kind)}_{type_key(map_type.key)}_"
                f"{type_key(map_type.value)}"
            )
        case OpaqueType(c_name=c_name):
            return _sanitize_key(c_name)
        case ConstType(inner=inner):
            return f"const_{type_key(inner)}"
        case PointerType(inner=inner):
            return f"ptr_{type_key(inner)}"
        case ReferenceType(inner=inner):
            return f"ref_{type_key(inner)}"
        case ArrayType(inner=inner, length=length):
            return f"array_{length}_{type_key(inner)}"
        case SliceType(inner=inner):
            return f"slice_{type_key(inner)}"
        case DynType(interface=interface, is_const=is_const):
            prefix = "const_dyn" if is_const else "dyn"
            return f"{prefix}_{type_key(interface)}"
        case TypeValueType(value=value):
            return f"type_{type_key(value)}"
        case ComptimeCollectionType(kind=kind, owner=owner):
            return f"comptime_{_sanitize_key(kind)}_{type_key(owner)}"
        case ComptimeItemType(kind=kind, owner=owner):
            return f"comptime_item_{_sanitize_key(kind)}_{type_key(owner)}"
        case FunctionValueType(name=name):
            return f"fn_{_sanitize_key(name)}"
        case FunctionPointerType(param_types=param_types, return_type=return_type):
            params = "_".join(type_key(param) for param in param_types)
            suffix = f"_{params}" if params else ""
            return f"fnptr{suffix}_ret_{type_key(return_type)}"
        case ModuleType(name=name):
            return f"module_{_sanitize_key(name)}"
        case RangeType(inner=inner):
            return f"range_{type_key(inner)}"
        case NullType():
            return "null"
        case ErrorType():
            return "error"
    raise AssertionError(f"unhandled type: {type_!r}")


def _sanitize_key(value: str) -> str:
    cleaned = "".join(
        character
        if character.isascii() and (character.isalnum() or character == "_")
        else "_"
        for character in value
    )
    return cleaned or "anonymous"
