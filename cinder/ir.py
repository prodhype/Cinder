from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum

from cinder import ast
from cinder.checker import SemanticModel
from cinder.ownership import ValueUseKind
from cinder.symbols import (
    AtomicCallResolution,
    AtomicIntrinsicKind,
    ClassSymbol,
    EnumSymbol,
    FunctionSymbol,
    LockSymbol,
    NominalSymbol,
    StructSymbol,
    UnionSymbol,
    VariableSymbol,
    VariantSymbol,
)
from cinder.types import (
    BOOL,
    STRING,
    U8,
    VOID,
    ArrayType,
    AtomicCompareExchangeResultType,
    AtomicType,
    ClassType,
    ClosureType,
    ConstType,
    DynType,
    EnumType,
    FileType,
    FunctionPointerType,
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
    UnionType,
    VariantType,
    can_assign,
    is_atomic_element_type,
    is_void,
    strip_const,
    type_key,
    value_type,
)


class AtomicMemoryOrder(StrEnum):
    SEQ_CST = "seq_cst"


class AtomicFetchKind(StrEnum):
    ADD = "add"
    SUB = "sub"
    AND = "and"
    OR = "or"
    XOR = "xor"


@dataclass(frozen=True, slots=True)
class IRAtomicInit:
    declaration: ast.VarDeclStmt | ast.GlobalDecl
    initializer: ast.Expression
    atomic_type: AtomicType


@dataclass(frozen=True, slots=True)
class IRAtomicLoad:
    call: ast.CallExpr
    receiver: ast.Expression
    atomic_type: AtomicType
    result_type: Type
    order: AtomicMemoryOrder = AtomicMemoryOrder.SEQ_CST


@dataclass(frozen=True, slots=True)
class IRAtomicStore:
    call: ast.CallExpr
    receiver: ast.Expression
    value: ast.Expression
    atomic_type: AtomicType
    result_type: Type
    source_order: tuple[int, ...]
    order: AtomicMemoryOrder = AtomicMemoryOrder.SEQ_CST


@dataclass(frozen=True, slots=True)
class IRAtomicExchange:
    call: ast.CallExpr
    receiver: ast.Expression
    value: ast.Expression
    atomic_type: AtomicType
    result_type: Type
    source_order: tuple[int, ...]
    order: AtomicMemoryOrder = AtomicMemoryOrder.SEQ_CST


@dataclass(frozen=True, slots=True)
class IRAtomicCompareExchange:
    call: ast.CallExpr
    receiver: ast.Expression
    expected: ast.Expression
    desired: ast.Expression
    atomic_type: AtomicType
    result_type: AtomicCompareExchangeResultType
    source_order: tuple[int, ...]
    success_order: AtomicMemoryOrder = AtomicMemoryOrder.SEQ_CST
    failure_order: AtomicMemoryOrder = AtomicMemoryOrder.SEQ_CST


@dataclass(frozen=True, slots=True)
class IRAtomicFetch:
    call: ast.CallExpr
    receiver: ast.Expression
    value: ast.Expression
    atomic_type: AtomicType
    result_type: Type
    fetch_kind: AtomicFetchKind
    source_order: tuple[int, ...]
    order: AtomicMemoryOrder = AtomicMemoryOrder.SEQ_CST


type IRAtomicOperation = (
    IRAtomicInit
    | IRAtomicLoad
    | IRAtomicStore
    | IRAtomicExchange
    | IRAtomicCompareExchange
    | IRAtomicFetch
)


@dataclass(frozen=True, slots=True)
class IRStruct:
    symbol: StructSymbol
    declaration: ast.StructDecl


@dataclass(frozen=True, slots=True)
class IRClass:
    symbol: ClassSymbol
    declaration: ast.ClassDecl


@dataclass(frozen=True, slots=True)
class IREnum:
    symbol: EnumSymbol
    declaration: ast.EnumDecl


@dataclass(frozen=True, slots=True)
class IRUnion:
    symbol: UnionSymbol
    declaration: ast.UnionDecl


@dataclass(frozen=True, slots=True)
class IRVariant:
    symbol: VariantSymbol
    declaration: ast.VariantDecl


@dataclass(frozen=True, slots=True)
class IRFunction:
    symbol: FunctionSymbol
    declaration: ast.FunctionDecl
    atomic_operations: tuple[IRAtomicOperation, ...]


@dataclass(frozen=True, slots=True)
class IRGlobal:
    symbol: VariableSymbol
    declaration: ast.GlobalDecl
    atomic_init: IRAtomicInit | None


@dataclass(frozen=True, slots=True)
class IRLock:
    symbol: LockSymbol
    declaration: ast.LockDecl


@dataclass(frozen=True, slots=True)
class IRModule:
    semantic: SemanticModel
    structs: tuple[IRStruct, ...]
    classes: tuple[IRClass, ...]
    enums: tuple[IREnum, ...]
    unions: tuple[IRUnion, ...]
    variants: tuple[IRVariant, ...]
    functions: tuple[IRFunction, ...]
    globals: tuple[IRGlobal, ...]
    locks: tuple[IRLock, ...]
    atomic_operations: tuple[IRAtomicOperation, ...]
    atomic_types: tuple[AtomicType, ...]
    atomic_result_types: tuple[AtomicCompareExchangeResultType, ...]
    slice_types: tuple[SliceType, ...]
    tuple_types: tuple[TupleType, ...]
    closure_types: tuple[ClosureType, ...]
    list_types: tuple[ListType, ...]
    map_types: tuple[MapType, ...]
    set_types: tuple[SetType, ...]
    map_view_types: tuple[MapViewType, ...]
    sort_types: tuple[Type, ...]
    sorted_types: tuple[Type, ...]
    result_types: tuple[ResultType, ...]
    option_types: tuple[OptionType, ...]
    owned_types: tuple[OwnedType, ...]
    uses_file: bool
    definition_order: tuple[Type, ...]


class Lowerer:
    def __init__(self, semantic: SemanticModel) -> None:
        self.semantic = semantic

    def lower(self) -> IRModule:
        structs = tuple(
            IRStruct(symbol, symbol.declaration) for symbol in self.semantic.structs.values()
        )
        classes = tuple(
            IRClass(symbol, symbol.declaration) for symbol in self.semantic.classes.values()
        )
        enums = tuple(IREnum(symbol, symbol.declaration) for symbol in self.semantic.enums.values())
        unions = tuple(
            IRUnion(symbol, symbol.declaration) for symbol in self.semantic.unions.values()
        )
        variants = tuple(
            IRVariant(symbol, symbol.declaration) for symbol in self.semantic.variants.values()
        )

        functions: list[IRFunction] = []
        for struct in self.semantic.structs.values():
            for method in struct.methods.values():
                if method.declaration is not None:
                    functions.append(self._lower_function(method, method.declaration))
        for class_ in self.semantic.classes.values():
            for method in class_.methods.values():
                if method.declaration is not None and not method.is_abstract:
                    functions.append(self._lower_function(method, method.declaration))
        for function in self.semantic.functions.values():
            if function.declaration is not None:
                functions.append(self._lower_function(function, function.declaration))

        globals_: list[IRGlobal] = []
        for declaration in self.semantic.module.globals:
            symbol = self.semantic.global_symbols.get(id(declaration))
            if symbol is not None:
                init_resolution = self.semantic.atomic_init_resolutions.get(id(declaration))
                atomic_init = (
                    IRAtomicInit(
                        declaration,
                        init_resolution.initializer,
                        init_resolution.atomic_type,
                    )
                    if init_resolution is not None
                    else None
                )
                globals_.append(IRGlobal(symbol, declaration, atomic_init))

        locks = tuple(
            IRLock(symbol, symbol.declaration)
            for symbol in self.semantic.locks.values()
            if symbol.declaration is not None
        )

        sorted_values = self._collect_sorted_types()
        sort_values = self._collect_sort_types() | sorted_values
        slice_values = set(self._collect_slices())
        for element in sort_values:
            slice_values.add(SliceType(element))
            slice_values.add(SliceType(ConstType(element)))
        uses_file = any(
            isinstance(strip_const(type_), FileType) for type_ in self._all_semantic_types()
        )
        if uses_file:
            slice_values.add(SliceType(ConstType(U8)))
            slice_values.add(SliceType(U8))
        slices = tuple(sorted(slice_values, key=type_key))
        list_values = self._collect_lists()
        # File helpers always include read_all under a shared include guard, so every
        # File-using module must emit List[u8] support alongside the File helper set.
        if uses_file:
            list_values.add(ListType(U8))
        list_values.update(ListType(element) for element in sorted_values)
        lists = tuple(sorted(list_values, key=type_key))
        maps = tuple(sorted(self._collect_maps(), key=type_key))
        sets = tuple(sorted(self._collect_sets(), key=type_key))
        map_view_values = self._collect_map_views()
        map_view_values.update(
            MapViewType(map_type, kind) for map_type in maps for kind in ("keys", "values", "items")
        )
        map_views = tuple(sorted(map_view_values, key=type_key))
        tuple_values = self._collect_tuples()
        tuple_values.update(TupleType((map_type.key, map_type.value)) for map_type in maps)
        tuples = tuple(sorted(tuple_values, key=type_key))
        closures = tuple(sorted(self._collect_closures(), key=type_key))
        sort_types = tuple(sorted(sort_values, key=type_key))
        sorted_types = tuple(sorted(sorted_values, key=type_key))
        results = tuple(sorted(self._collect_results(), key=type_key))
        option_values = self._collect_options()
        option_values.update(OptionType(map_type.value) for map_type in maps)
        option_values.update(OptionType(set_type.inner) for set_type in sets)
        # The shared File helper set always emits read_line, whose public
        # representation is Option[String], even in write-only modules.
        if uses_file:
            option_values.add(OptionType(STRING))
        options = tuple(sorted(option_values, key=type_key))
        owneds = tuple(sorted(self._collect_owned(), key=type_key))
        definition_order = tuple(self._definition_order(results, options, tuples, closures))
        atomic_operations = tuple(
            operation for function in functions for operation in function.atomic_operations
        ) + tuple(global_.atomic_init for global_ in globals_ if global_.atomic_init is not None)
        atomic_type_values = self._collect_atomic_types()
        atomic_type_values.update(operation.atomic_type for operation in atomic_operations)
        atomic_types = tuple(sorted(atomic_type_values, key=type_key))
        atomic_result_types = tuple(
            sorted(
                {
                    operation.result_type
                    for operation in atomic_operations
                    if isinstance(operation, IRAtomicCompareExchange)
                },
                key=type_key,
            )
        )
        module = IRModule(
            semantic=self.semantic,
            structs=structs,
            classes=classes,
            enums=enums,
            unions=unions,
            variants=variants,
            functions=tuple(functions),
            globals=tuple(globals_),
            locks=locks,
            atomic_operations=atomic_operations,
            atomic_types=atomic_types,
            atomic_result_types=atomic_result_types,
            slice_types=slices,
            tuple_types=tuples,
            closure_types=closures,
            list_types=lists,
            map_types=maps,
            set_types=sets,
            map_view_types=map_views,
            sort_types=sort_types,
            sorted_types=sorted_types,
            result_types=results,
            option_types=options,
            owned_types=owneds,
            uses_file=uses_file,
            definition_order=definition_order,
        )
        validate_ir(module)
        return module

    def _lower_function(
        self,
        symbol: FunctionSymbol,
        declaration: ast.FunctionDecl,
    ) -> IRFunction:
        operations: list[IRAtomicOperation] = []
        if declaration.body is not None:
            for node in _walk_ast_nodes(declaration.body):
                init_resolution = self.semantic.atomic_init_resolutions.get(id(node))
                if init_resolution is not None and isinstance(node, ast.VarDeclStmt):
                    operations.append(
                        IRAtomicInit(
                            node,
                            init_resolution.initializer,
                            init_resolution.atomic_type,
                        )
                    )
                if isinstance(node, ast.CallExpr):
                    call_resolution = self.semantic.atomic_call_resolutions.get(id(node))
                    if call_resolution is not None:
                        operations.append(self._lower_atomic_call(node, call_resolution))
        return IRFunction(symbol, declaration, tuple(operations))

    @staticmethod
    def _lower_atomic_call(
        call: ast.CallExpr,
        resolution: AtomicCallResolution,
    ) -> IRAtomicOperation:
        common = (
            call,
            resolution.receiver,
        )
        if resolution.intrinsic is AtomicIntrinsicKind.LOAD:
            return IRAtomicLoad(
                *common,
                resolution.atomic_type,
                resolution.result_type,
            )
        if resolution.intrinsic is AtomicIntrinsicKind.STORE:
            return IRAtomicStore(
                *common,
                resolution.operands[0],
                resolution.atomic_type,
                resolution.result_type,
                resolution.source_order,
            )
        if resolution.intrinsic is AtomicIntrinsicKind.EXCHANGE:
            return IRAtomicExchange(
                *common,
                resolution.operands[0],
                resolution.atomic_type,
                resolution.result_type,
                resolution.source_order,
            )
        if resolution.intrinsic is AtomicIntrinsicKind.COMPARE_EXCHANGE:
            result_type = resolution.result_type
            if not isinstance(result_type, AtomicCompareExchangeResultType):
                raise ValueError("atomic compare_exchange has malformed result type")
            return IRAtomicCompareExchange(
                *common,
                resolution.operands[0],
                resolution.operands[1],
                resolution.atomic_type,
                result_type,
                resolution.source_order,
            )
        fetch_kinds = {
            AtomicIntrinsicKind.FETCH_ADD: AtomicFetchKind.ADD,
            AtomicIntrinsicKind.FETCH_SUB: AtomicFetchKind.SUB,
            AtomicIntrinsicKind.FETCH_AND: AtomicFetchKind.AND,
            AtomicIntrinsicKind.FETCH_OR: AtomicFetchKind.OR,
            AtomicIntrinsicKind.FETCH_XOR: AtomicFetchKind.XOR,
        }
        fetch_kind = fetch_kinds.get(resolution.intrinsic)
        if fetch_kind is not None:
            return IRAtomicFetch(
                *common,
                resolution.operands[0],
                resolution.atomic_type,
                resolution.result_type,
                fetch_kind,
                resolution.source_order,
            )
        raise ValueError(f"unhandled atomic intrinsic {resolution.intrinsic.value}")

    def _all_semantic_types(self) -> list[Type]:
        values: list[Type] = []
        for struct in self.semantic.structs.values():
            values.extend(field.type for field in struct.fields.values())
            for method in struct.methods.values():
                values.append(method.return_type)
                values.extend(parameter.type for parameter in method.parameters)
        for class_ in self.semantic.classes.values():
            values.extend(field.type for field in class_.fields.values())
            for method in class_.methods.values():
                values.append(method.return_type)
                values.extend(parameter.type for parameter in method.parameters)
        for union in self.semantic.unions.values():
            values.extend(field.type for field in union.fields.values())
        for variant in self.semantic.variants.values():
            for case in variant.cases.values():
                values.extend(field.type for field in case.fields.values())
        for function in self.semantic.functions.values():
            values.append(function.return_type)
            values.extend(parameter.type for parameter in function.parameters)
        values.extend(global_.type for global_ in self.semantic.globals.values())
        values.extend(symbol.type for symbol in self.semantic.declaration_symbols.values())
        values.extend(symbol.type for symbol in self.semantic.implicit_declarations.values())
        values.extend(symbol.type for symbol in self.semantic.foreach_symbols.values())
        values.extend(symbol.type for symbol in self.semantic.with_symbols.values())
        values.extend(self.semantic.expr_types.values())
        for resolution in self.semantic.call_resolutions.values():
            values.extend(
                expected for expected in resolution.expected_types if expected is not None
            )
        return values

    def _collect_atomic_types(self) -> set[AtomicType]:
        result: set[AtomicType] = set()

        def collect(type_: Type) -> None:
            raw = strip_const(type_)
            if isinstance(raw, AtomicType):
                result.add(raw)
            elif isinstance(
                raw,
                (
                    PointerType,
                    ReferenceType,
                    ArrayType,
                    SliceType,
                    ListType,
                    SetType,
                    OptionType,
                    OwnedType,
                ),
            ):
                collect(raw.inner)
            elif isinstance(raw, MapType):
                collect(raw.key)
                collect(raw.value)
            elif isinstance(raw, MapViewType):
                collect(raw.map_type)
            elif isinstance(raw, ResultType):
                collect(raw.ok)
                collect(raw.error)
            elif isinstance(raw, TupleType):
                for element in raw.elements:
                    collect(element)
            elif isinstance(raw, FunctionPointerType):
                for parameter in raw.param_types:
                    collect(parameter)
                collect(raw.return_type)
            elif isinstance(raw, ClosureType):
                collect(raw.env_type)
                for parameter in raw.param_types:
                    collect(parameter)
                collect(raw.return_type)

        for type_ in self._all_semantic_types():
            collect(type_)
        return result

    def _collect_slices(self) -> set[SliceType]:
        result: set[SliceType] = set()

        def collect(type_: Type) -> None:
            raw = strip_const(type_)
            if isinstance(raw, (StringType, StringBuilderType)):
                return
            if isinstance(raw, SliceType):
                result.add(raw)
                collect(raw.inner)
            elif isinstance(raw, (PointerType, ReferenceType, ArrayType)):
                collect(raw.inner)
            elif isinstance(raw, DynType):
                collect(raw.interface)
            elif isinstance(raw, ResultType):
                collect(raw.ok)
                collect(raw.error)
            elif isinstance(raw, (OptionType, OwnedType)):
                collect(raw.inner)
            elif isinstance(raw, TupleType):
                for element in raw.elements:
                    collect(element)
            elif isinstance(raw, ClosureType):
                collect(raw.env_type)
                for parameter in raw.param_types:
                    collect(parameter)
                collect(raw.return_type)
            elif isinstance(raw, ListType):
                collect(raw.inner)
            elif isinstance(raw, MapType):
                collect(raw.key)
                collect(raw.value)
            elif isinstance(raw, SetType):
                collect(raw.inner)
            elif isinstance(raw, MapViewType):
                collect(raw.map_type)

        for type_ in self._all_semantic_types():
            collect(type_)
        return result

    def _collect_tuples(self) -> set[TupleType]:
        result: set[TupleType] = set()

        def collect(type_: Type) -> None:
            raw = strip_const(type_)
            if isinstance(raw, (StringType, StringBuilderType)):
                return
            if isinstance(raw, TupleType):
                if raw in result:
                    return
                result.add(raw)
                for element in raw.elements:
                    collect(element)
            elif isinstance(raw, ClosureType):
                collect(raw.env_type)
                for parameter in raw.param_types:
                    collect(parameter)
                collect(raw.return_type)
            elif isinstance(
                raw,
                (PointerType, ReferenceType, ArrayType, SliceType, ListType, OwnedType),
            ):
                collect(raw.inner)
            elif isinstance(raw, DynType):
                collect(raw.interface)
            elif isinstance(raw, ResultType):
                collect(raw.ok)
                collect(raw.error)
            elif isinstance(raw, OptionType):
                collect(raw.inner)
            elif isinstance(raw, MapType):
                collect(raw.key)
                collect(raw.value)
            elif isinstance(raw, SetType):
                collect(raw.inner)
            elif isinstance(raw, MapViewType):
                collect(raw.map_type)

        for type_ in self._all_semantic_types():
            collect(type_)
        return result

    def _collect_lists(self) -> set[ListType]:
        result: set[ListType] = set()

        def collect(type_: Type) -> None:
            raw = strip_const(type_)
            if isinstance(raw, (StringType, StringBuilderType)):
                return
            if isinstance(raw, ListType):
                normalized = ListType(raw.inner)
                if normalized in result:
                    return
                result.add(normalized)
                collect(raw.inner)
            elif isinstance(
                raw,
                (PointerType, ReferenceType, ArrayType, SliceType, OwnedType),
            ):
                collect(raw.inner)
            elif isinstance(raw, TupleType):
                for element in raw.elements:
                    collect(element)
            elif isinstance(raw, ClosureType):
                collect(raw.env_type)
                for parameter in raw.param_types:
                    collect(parameter)
                collect(raw.return_type)
            elif isinstance(raw, DynType):
                collect(raw.interface)
            elif isinstance(raw, ResultType):
                collect(raw.ok)
                collect(raw.error)
            elif isinstance(raw, OptionType):
                collect(raw.inner)
            elif isinstance(raw, MapType):
                collect(raw.key)
                collect(raw.value)
            elif isinstance(raw, SetType):
                collect(raw.inner)
            elif isinstance(raw, MapViewType):
                collect(raw.map_type)

        for type_ in self._all_semantic_types():
            collect(type_)
        return result

    def _collect_maps(self) -> set[MapType]:
        result: set[MapType] = set()

        def collect(type_: Type) -> None:
            raw = strip_const(type_)
            if isinstance(raw, (StringType, StringBuilderType)):
                return
            if isinstance(raw, MapType):
                if raw in result:
                    return
                result.add(raw)
                collect(raw.key)
                collect(raw.value)
            elif isinstance(
                raw,
                (
                    PointerType,
                    ReferenceType,
                    ArrayType,
                    SliceType,
                    ListType,
                    SetType,
                    OwnedType,
                ),
            ):
                collect(raw.inner)
            elif isinstance(raw, TupleType):
                for element in raw.elements:
                    collect(element)
            elif isinstance(raw, ClosureType):
                collect(raw.env_type)
                for parameter in raw.param_types:
                    collect(parameter)
                collect(raw.return_type)
            elif isinstance(raw, ResultType):
                collect(raw.ok)
                collect(raw.error)
            elif isinstance(raw, OptionType):
                collect(raw.inner)
            elif isinstance(raw, MapViewType):
                collect(raw.map_type)

        for type_ in self._all_semantic_types():
            collect(type_)
        return result

    def _collect_sets(self) -> set[SetType]:
        result: set[SetType] = set()

        def collect(type_: Type) -> None:
            raw = strip_const(type_)
            if isinstance(raw, (StringType, StringBuilderType)):
                return
            if isinstance(raw, SetType):
                if raw in result:
                    return
                result.add(raw)
                collect(raw.inner)
            elif isinstance(
                raw,
                (
                    PointerType,
                    ReferenceType,
                    ArrayType,
                    SliceType,
                    ListType,
                    OwnedType,
                ),
            ):
                collect(raw.inner)
            elif isinstance(raw, MapType):
                collect(raw.key)
                collect(raw.value)
            elif isinstance(raw, TupleType):
                for element in raw.elements:
                    collect(element)
            elif isinstance(raw, ClosureType):
                collect(raw.env_type)
                for parameter in raw.param_types:
                    collect(parameter)
                collect(raw.return_type)
            elif isinstance(raw, ResultType):
                collect(raw.ok)
                collect(raw.error)
            elif isinstance(raw, OptionType):
                collect(raw.inner)
            elif isinstance(raw, MapViewType):
                collect(raw.map_type)

        for type_ in self._all_semantic_types():
            collect(type_)
        return result

    def _collect_map_views(self) -> set[MapViewType]:
        result: set[MapViewType] = set()

        def collect(type_: Type) -> None:
            raw = strip_const(type_)
            if isinstance(raw, (StringType, StringBuilderType)):
                return
            if isinstance(raw, MapViewType):
                result.add(raw)
                collect(raw.map_type)
            elif isinstance(
                raw,
                (
                    PointerType,
                    ReferenceType,
                    ArrayType,
                    SliceType,
                    ListType,
                    SetType,
                    OptionType,
                    OwnedType,
                ),
            ):
                collect(raw.inner)
            elif isinstance(raw, MapType):
                collect(raw.key)
                collect(raw.value)
            elif isinstance(raw, TupleType):
                for element in raw.elements:
                    collect(element)
            elif isinstance(raw, ClosureType):
                collect(raw.env_type)
                for parameter in raw.param_types:
                    collect(parameter)
                collect(raw.return_type)
            elif isinstance(raw, ResultType):
                collect(raw.ok)
                collect(raw.error)

        for type_ in self._all_semantic_types():
            collect(type_)
        return result

    def _collect_options(self) -> set[OptionType]:
        result: set[OptionType] = set()

        def collect(type_: Type) -> None:
            raw = strip_const(type_)
            if isinstance(raw, (StringType, StringBuilderType)):
                return
            if isinstance(raw, OptionType):
                if raw in result:
                    return
                result.add(raw)
                collect(raw.inner)
            elif isinstance(
                raw,
                (
                    PointerType,
                    ReferenceType,
                    ArrayType,
                    SliceType,
                    ListType,
                    SetType,
                    OwnedType,
                ),
            ):
                collect(raw.inner)
            elif isinstance(raw, MapType):
                collect(raw.key)
                collect(raw.value)
            elif isinstance(raw, MapViewType):
                collect(raw.map_type)
            elif isinstance(raw, TupleType):
                for element in raw.elements:
                    collect(element)
            elif isinstance(raw, ClosureType):
                collect(raw.env_type)
                for parameter in raw.param_types:
                    collect(parameter)
                collect(raw.return_type)
            elif isinstance(raw, ResultType):
                collect(raw.ok)
                collect(raw.error)

        for type_ in self._all_semantic_types():
            collect(type_)
        return result

    def _collect_owned(self) -> set[OwnedType]:
        result: set[OwnedType] = set()

        def collect(type_: Type) -> None:
            raw = strip_const(type_)
            if isinstance(raw, (StringType, StringBuilderType)):
                return
            if isinstance(raw, OwnedType):
                if raw in result:
                    return
                result.add(raw)
                collect(raw.inner)
            elif isinstance(
                raw,
                (
                    PointerType,
                    ReferenceType,
                    ArrayType,
                    SliceType,
                    ListType,
                    SetType,
                    OptionType,
                ),
            ):
                collect(raw.inner)
            elif isinstance(raw, MapType):
                collect(raw.key)
                collect(raw.value)
            elif isinstance(raw, MapViewType):
                collect(raw.map_type)
            elif isinstance(raw, TupleType):
                for element in raw.elements:
                    collect(element)
            elif isinstance(raw, ClosureType):
                collect(raw.env_type)
                for parameter in raw.param_types:
                    collect(parameter)
                collect(raw.return_type)
            elif isinstance(raw, ResultType):
                collect(raw.ok)
                collect(raw.error)

        for type_ in self._all_semantic_types():
            collect(type_)
        return result

    def _collect_closures(self) -> set[ClosureType]:
        result: set[ClosureType] = set()

        def collect(type_: Type) -> None:
            raw = strip_const(type_)
            if isinstance(raw, (StringType, StringBuilderType)):
                return
            if isinstance(raw, ClosureType):
                if raw in result:
                    return
                result.add(raw)
                collect(raw.env_type)
                for parameter in raw.param_types:
                    collect(parameter)
                collect(raw.return_type)
            elif isinstance(raw, FunctionPointerType):
                for parameter in raw.param_types:
                    collect(parameter)
                collect(raw.return_type)
            elif isinstance(raw, (PointerType, ReferenceType, ArrayType, SliceType, OwnedType)):
                collect(raw.inner)
            elif isinstance(raw, TupleType):
                for element in raw.elements:
                    collect(element)
            elif isinstance(raw, ResultType):
                collect(raw.ok)
                collect(raw.error)
            elif isinstance(raw, (OptionType, ListType)):
                collect(raw.inner)
            elif isinstance(raw, MapType):
                collect(raw.key)
                collect(raw.value)
            elif isinstance(raw, SetType):
                collect(raw.inner)
            elif isinstance(raw, MapViewType):
                collect(raw.map_type)

        for type_ in self._all_semantic_types():
            collect(type_)
        return result

    def _collect_sort_types(self) -> set[Type]:
        result: set[Type] = set()
        for resolution in self.semantic.call_resolutions.values():
            if resolution.kind != "sort" or not resolution.expected_types:
                continue
            expected = resolution.expected_types[0]
            if isinstance(expected, SliceType):
                result.add(strip_const(expected.inner))
        return result

    def _collect_sorted_types(self) -> set[Type]:
        result: set[Type] = set()
        for resolution in self.semantic.call_resolutions.values():
            if resolution.kind != "sorted" or not resolution.expected_types:
                continue
            expected = resolution.expected_types[0]
            if isinstance(expected, SliceType):
                result.add(strip_const(expected.inner))
        return result

    def _collect_results(self) -> set[ResultType]:
        result: set[ResultType] = set()

        def collect(type_: Type) -> None:
            raw = strip_const(type_)
            if isinstance(raw, (StringType, StringBuilderType)):
                return
            if isinstance(raw, ResultType):
                if raw in result:
                    return
                result.add(raw)
                collect(raw.ok)
                collect(raw.error)
            elif isinstance(
                raw,
                (PointerType, ReferenceType, ArrayType, SliceType, OwnedType),
            ):
                collect(raw.inner)
            elif isinstance(raw, TupleType):
                for element in raw.elements:
                    collect(element)
            elif isinstance(raw, ClosureType):
                collect(raw.env_type)
                for parameter in raw.param_types:
                    collect(parameter)
                collect(raw.return_type)
            elif isinstance(raw, (ListType, OptionType)):
                collect(raw.inner)
            elif isinstance(raw, MapType):
                collect(raw.key)
                collect(raw.value)
            elif isinstance(raw, SetType):
                collect(raw.inner)
            elif isinstance(raw, MapViewType):
                collect(raw.map_type)

        for type_ in self._all_semantic_types():
            collect(type_)
        return result

    def _definition_order(
        self,
        result_types: tuple[ResultType, ...],
        option_types: tuple[OptionType, ...],
        tuple_types: tuple[TupleType, ...],
        closure_types: tuple[ClosureType, ...],
    ) -> list[Type]:
        nominal_by_type: dict[Type, NominalSymbol] = {}
        nominal_by_type.update({symbol.type: symbol for symbol in self.semantic.structs.values()})
        nominal_by_type.update({symbol.type: symbol for symbol in self.semantic.classes.values()})
        nominal_by_type.update({symbol.type: symbol for symbol in self.semantic.unions.values()})
        nominal_by_type.update({symbol.type: symbol for symbol in self.semantic.variants.values()})
        nodes: set[Type] = {
            *nominal_by_type,
            *result_types,
            *option_types,
            *tuple_types,
            *closure_types,
        }
        permanent: set[Type] = set()
        temporary: set[Type] = set()
        ordered: list[Type] = []

        def visit(type_: Type) -> None:
            if type_ in permanent:
                return
            if type_ in temporary:
                # The checker reports the source-level recursive layout diagnostic.
                return
            temporary.add(type_)
            for dependency in sorted(
                self._definition_dependencies(type_, nominal_by_type), key=type_key
            ):
                if dependency in nodes:
                    visit(dependency)
            temporary.remove(type_)
            permanent.add(type_)
            ordered.append(type_)

        for type_ in sorted(nodes, key=type_key):
            visit(type_)
        return ordered

    def _definition_dependencies(
        self,
        type_: Type,
        nominal_by_type: dict[Type, NominalSymbol],
    ) -> set[Type]:
        if isinstance(type_, ResultType):
            return {
                *self._by_value_definition_types(type_.ok),
                *self._by_value_definition_types(type_.error),
            }
        if isinstance(type_, OptionType):
            return self._by_value_definition_types(type_.inner)
        if isinstance(type_, TupleType):
            dependencies: set[Type] = set()
            for element in type_.elements:
                dependencies.update(self._by_value_definition_types(element))
            return dependencies
        if isinstance(type_, ClosureType):
            dependencies = set(self._by_value_definition_types(type_.env_type))
            dependencies.update(self._by_value_definition_types(type_.return_type))
            for parameter in type_.param_types:
                dependencies.update(self._by_value_definition_types(parameter))
            return dependencies

        symbol = nominal_by_type.get(type_)
        fields: list[Type] = []
        if isinstance(symbol, (StructSymbol, ClassSymbol, UnionSymbol)):
            if isinstance(symbol, ClassSymbol) and symbol.primary_base is not None:
                fields.append(symbol.primary_base.type)
            fields.extend(field.type for field in symbol.fields.values())
        elif isinstance(symbol, VariantSymbol):
            for case in symbol.cases.values():
                fields.extend(field.type for field in case.fields.values())
        dependencies = set()
        for field_type in fields:
            dependencies.update(self._by_value_definition_types(field_type))
        return dependencies

    def _by_value_definition_types(self, type_: Type) -> set[Type]:
        raw = strip_const(type_)
        if is_void(raw):
            return set()
        if isinstance(raw, (StringType, StringBuilderType)):
            # Runtime-owned ABI leaves are already complete via cinder_runtime.h.
            return set()
        if isinstance(
            raw,
            (
                StructType,
                ClassType,
                UnionType,
                VariantType,
                ResultType,
                OptionType,
                TupleType,
                ClosureType,
            ),
        ):
            return {raw}
        if isinstance(raw, ArrayType):
            return self._by_value_definition_types(raw.inner)
        if isinstance(
            raw,
            (
                PointerType,
                ReferenceType,
                SliceType,
                ListType,
                MapType,
                SetType,
                MapViewType,
                OwnedType,
                EnumType,
            ),
        ):
            return set()
        return set()


def _walk_ast_nodes(value: object):
    if isinstance(value, ast.Node):
        yield value
        for field in fields(value):
            child = getattr(value, field.name)
            if isinstance(child, ast.Node):
                yield from _walk_ast_nodes(child)
            elif isinstance(child, (list, tuple)):
                for item in child:
                    if isinstance(item, ast.Node):
                        yield from _walk_ast_nodes(item)


def _atomic_receiver_type(
    semantic: SemanticModel,
    receiver: ast.Expression,
) -> tuple[AtomicType | None, bool]:
    receiver_type = strip_const(semantic.expression_type(receiver))
    indirect = isinstance(receiver_type, (PointerType, ReferenceType))
    target_type = strip_const(receiver_type.inner) if indirect else receiver_type
    return (
        target_type if isinstance(target_type, AtomicType) else None,
        indirect,
    )


def _atomic_receiver_is_addressable(
    semantic: SemanticModel,
    receiver: ast.Expression,
) -> bool:
    atomic_type, indirect = _atomic_receiver_type(semantic, receiver)
    if atomic_type is None:
        return False
    if indirect:
        return True
    if isinstance(receiver, ast.NameExpr):
        symbol = semantic.name_symbols.get(id(receiver))
        if isinstance(symbol, VariableSymbol):
            is_global = symbol in semantic.globals.values() or symbol.is_module_public
            if is_global:
                return True
            use = semantic.value_use(receiver)
            return use is not None and use.kind is ValueUseKind.ADDRESS
        return False
    if isinstance(receiver, ast.AttributeExpr):
        resolution = semantic.attribute_resolutions.get(id(receiver))
        return resolution is not None and resolution.kind == "module_global"
    return isinstance(receiver, ast.UnaryExpr) and receiver.operator == "*"


def validate_ir(module: IRModule) -> None:
    semantic = module.semantic
    seen_call_ids: set[int] = set()
    seen_init_ids: set[int] = set()

    for operation in module.atomic_operations:
        if not is_atomic_element_type(operation.atomic_type.inner):
            raise ValueError(
                f"malformed atomic IR element type {type_key(operation.atomic_type.inner)}"
            )

        if isinstance(operation, IRAtomicInit):
            declaration_id = id(operation.declaration)
            if declaration_id in seen_init_ids:
                raise ValueError("duplicate atomic initialization IR")
            seen_init_ids.add(declaration_id)
            resolution = semantic.atomic_init_resolutions.get(declaration_id)
            if (
                resolution is None
                or resolution.atomic_type != operation.atomic_type
                or resolution.initializer is not operation.initializer
            ):
                raise ValueError("atomic initialization IR disagrees with semantics")
            initializer_type = semantic.expression_type(operation.initializer)
            if isinstance(value_type(initializer_type), AtomicType) or not can_assign(
                operation.atomic_type.inner,
                initializer_type,
            ):
                raise ValueError("atomic initialization IR has invalid initializer type")
            continue

        call_id = id(operation.call)
        if call_id in seen_call_ids:
            raise ValueError("duplicate atomic call IR")
        seen_call_ids.add(call_id)
        resolution = semantic.atomic_call_resolutions.get(call_id)
        if resolution is None:
            raise ValueError("atomic call IR has no semantic resolution")
        if (
            resolution.atomic_type != operation.atomic_type
            or resolution.receiver is not operation.receiver
        ):
            raise ValueError("atomic call IR disagrees with semantics")
        expected_intrinsic = {
            IRAtomicLoad: AtomicIntrinsicKind.LOAD,
            IRAtomicStore: AtomicIntrinsicKind.STORE,
            IRAtomicExchange: AtomicIntrinsicKind.EXCHANGE,
            IRAtomicCompareExchange: AtomicIntrinsicKind.COMPARE_EXCHANGE,
        }.get(type(operation))
        if isinstance(operation, IRAtomicFetch):
            expected_intrinsic = {
                AtomicFetchKind.ADD: AtomicIntrinsicKind.FETCH_ADD,
                AtomicFetchKind.SUB: AtomicIntrinsicKind.FETCH_SUB,
                AtomicFetchKind.AND: AtomicIntrinsicKind.FETCH_AND,
                AtomicFetchKind.OR: AtomicIntrinsicKind.FETCH_OR,
                AtomicFetchKind.XOR: AtomicIntrinsicKind.FETCH_XOR,
            }[operation.fetch_kind]
        if resolution.intrinsic is not expected_intrinsic:
            raise ValueError("atomic call IR has the wrong intrinsic kind")
        receiver_type, _ = _atomic_receiver_type(semantic, operation.receiver)
        if receiver_type != operation.atomic_type:
            raise ValueError("atomic call IR receiver has the wrong type")
        if not _atomic_receiver_is_addressable(semantic, operation.receiver):
            raise ValueError("atomic call IR receiver is not addressable")
        if isinstance(operation, IRAtomicCompareExchange):
            if (
                operation.success_order is not AtomicMemoryOrder.SEQ_CST
                or operation.failure_order is not AtomicMemoryOrder.SEQ_CST
            ):
                raise ValueError("atomic compare_exchange IR must be sequentially consistent")
        elif operation.order is not AtomicMemoryOrder.SEQ_CST:
            raise ValueError("atomic operation IR must be sequentially consistent")

        if isinstance(operation, IRAtomicLoad):
            if operation.result_type != operation.atomic_type.inner:
                raise ValueError("atomic load IR has the wrong result type")
            if operation.call.arguments:
                raise ValueError("atomic load IR has operands")
            continue

        if isinstance(
            operation,
            (IRAtomicStore, IRAtomicExchange, IRAtomicFetch),
        ):
            if len(operation.call.arguments) != 1 or operation.source_order != (0,):
                raise ValueError("atomic unary operation IR has malformed operands")
            operand_type = semantic.expression_type(operation.value)
            if not can_assign(operation.atomic_type.inner, operand_type):
                raise ValueError("atomic operation IR has the wrong operand type")

        if isinstance(operation, IRAtomicStore):
            if operation.result_type != VOID:
                raise ValueError("atomic store IR must return void")
        elif isinstance(operation, IRAtomicExchange):
            if operation.result_type != operation.atomic_type.inner:
                raise ValueError("atomic exchange IR has the wrong result type")
        elif isinstance(operation, IRAtomicFetch):
            if operation.atomic_type.inner == BOOL:
                raise ValueError("atomic bool fetch IR is invalid")
            if operation.result_type != operation.atomic_type.inner:
                raise ValueError("atomic fetch IR has the wrong result type")
        elif isinstance(operation, IRAtomicCompareExchange):
            if len(operation.call.arguments) != 2 or sorted(operation.source_order) != [0, 1]:
                raise ValueError("atomic compare_exchange IR has malformed operands")
            for operand in (operation.expected, operation.desired):
                if not can_assign(
                    operation.atomic_type.inner,
                    semantic.expression_type(operand),
                ):
                    raise ValueError("atomic compare_exchange IR has the wrong operand type")
            expected_result = AtomicCompareExchangeResultType(operation.atomic_type.inner)
            if operation.result_type != expected_result:
                raise ValueError("atomic compare_exchange IR has the wrong result type")

    if seen_call_ids != set(semantic.atomic_call_resolutions):
        raise ValueError("not all atomic semantic calls were lowered")
    if seen_init_ids != set(semantic.atomic_init_resolutions):
        raise ValueError("not all atomic semantic initializers were lowered")
    attached_operations = tuple(
        operation for function in module.functions for operation in function.atomic_operations
    ) + tuple(global_.atomic_init for global_ in module.globals if global_.atomic_init is not None)
    if len(attached_operations) != len(module.atomic_operations) or any(
        attached is not operation
        for attached, operation in zip(
            attached_operations,
            module.atomic_operations,
            strict=True,
        )
    ):
        raise ValueError("atomic operations are not attached consistently")
    expected_atomic_type_values = Lowerer(semantic)._collect_atomic_types()
    expected_atomic_type_values.update(
        operation.atomic_type for operation in module.atomic_operations
    )
    expected_atomic_types = tuple(sorted(expected_atomic_type_values, key=type_key))
    if module.atomic_types != expected_atomic_types:
        raise ValueError("atomic type collection is inconsistent")
    expected_result_types = tuple(
        sorted(
            {
                operation.result_type
                for operation in module.atomic_operations
                if isinstance(operation, IRAtomicCompareExchange)
            },
            key=type_key,
        )
    )
    if module.atomic_result_types != expected_result_types:
        raise ValueError("atomic result type collection is inconsistent")


def lower(semantic: SemanticModel) -> IRModule:
    return Lowerer(semantic).lower()
