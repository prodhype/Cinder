from __future__ import annotations

from dataclasses import dataclass

from cinder import ast
from cinder.checker import SemanticModel
from cinder.symbols import (
    ClassSymbol,
    EnumSymbol,
    FunctionSymbol,
    NominalSymbol,
    StructSymbol,
    UnionSymbol,
    VariableSymbol,
    VariantSymbol,
)
from cinder.types import (
    ArrayType,
    ClassType,
    DynType,
    EnumType,
    PointerType,
    ReferenceType,
    ResultType,
    SliceType,
    StructType,
    Type,
    UnionType,
    VariantType,
    is_void,
    strip_const,
    type_key,
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


@dataclass(frozen=True, slots=True)
class IRGlobal:
    symbol: VariableSymbol
    declaration: ast.GlobalDecl


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
    slice_types: tuple[SliceType, ...]
    sort_types: tuple[Type, ...]
    result_types: tuple[ResultType, ...]
    definition_order: tuple[Type, ...]


class Lowerer:
    def __init__(self, semantic: SemanticModel) -> None:
        self.semantic = semantic

    def lower(self) -> IRModule:
        structs = tuple(
            IRStruct(symbol, symbol.declaration)
            for symbol in self.semantic.structs.values()
        )
        classes = tuple(
            IRClass(symbol, symbol.declaration)
            for symbol in self.semantic.classes.values()
        )
        enums = tuple(
            IREnum(symbol, symbol.declaration)
            for symbol in self.semantic.enums.values()
        )
        unions = tuple(
            IRUnion(symbol, symbol.declaration)
            for symbol in self.semantic.unions.values()
        )
        variants = tuple(
            IRVariant(symbol, symbol.declaration)
            for symbol in self.semantic.variants.values()
        )

        functions: list[IRFunction] = []
        for struct in self.semantic.structs.values():
            for method in struct.methods.values():
                if method.declaration is not None:
                    functions.append(IRFunction(method, method.declaration))
        for class_ in self.semantic.classes.values():
            for method in class_.methods.values():
                if method.declaration is not None and not method.is_abstract:
                    functions.append(IRFunction(method, method.declaration))
        for function in self.semantic.functions.values():
            if function.declaration is not None:
                functions.append(IRFunction(function, function.declaration))

        globals_: list[IRGlobal] = []
        for declaration in self.semantic.module.globals:
            symbol = self.semantic.global_symbols.get(id(declaration))
            if symbol is not None:
                globals_.append(IRGlobal(symbol, declaration))

        slices = tuple(sorted(self._collect_slices(), key=type_key))
        sort_types = tuple(sorted(self._collect_sort_types(), key=type_key))
        results = tuple(sorted(self._collect_results(), key=type_key))
        definition_order = tuple(self._definition_order(results))
        return IRModule(
            semantic=self.semantic,
            structs=structs,
            classes=classes,
            enums=enums,
            unions=unions,
            variants=variants,
            functions=tuple(functions),
            globals=tuple(globals_),
            slice_types=slices,
            sort_types=sort_types,
            result_types=results,
            definition_order=definition_order,
        )

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
        values.extend(self.semantic.expr_types.values())
        for resolution in self.semantic.call_resolutions.values():
            values.extend(
                expected for expected in resolution.expected_types if expected is not None
            )
        return values

    def _collect_slices(self) -> set[SliceType]:
        result: set[SliceType] = set()

        def collect(type_: Type) -> None:
            raw = strip_const(type_)
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
                result.add(expected.inner)
        return result

    def _collect_results(self) -> set[ResultType]:
        result: set[ResultType] = set()

        def collect(type_: Type) -> None:
            raw = strip_const(type_)
            if isinstance(raw, ResultType):
                if raw in result:
                    return
                result.add(raw)
                collect(raw.ok)
                collect(raw.error)
            elif isinstance(raw, (PointerType, ReferenceType, ArrayType, SliceType)):
                collect(raw.inner)

        for type_ in self._all_semantic_types():
            collect(type_)
        return result

    def _definition_order(self, result_types: tuple[ResultType, ...]) -> list[Type]:
        nominal_by_type: dict[Type, NominalSymbol] = {}
        nominal_by_type.update({symbol.type: symbol for symbol in self.semantic.structs.values()})
        nominal_by_type.update({symbol.type: symbol for symbol in self.semantic.classes.values()})
        nominal_by_type.update({symbol.type: symbol for symbol in self.semantic.unions.values()})
        nominal_by_type.update({symbol.type: symbol for symbol in self.semantic.variants.values()})
        nodes: set[Type] = {*nominal_by_type, *result_types}
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
            for dependency in sorted(self._definition_dependencies(type_, nominal_by_type), key=type_key):
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

        symbol = nominal_by_type.get(type_)
        fields: list[Type] = []
        if isinstance(symbol, (StructSymbol, ClassSymbol, UnionSymbol)):
            if isinstance(symbol, ClassSymbol) and symbol.primary_base is not None:
                fields.append(symbol.primary_base.type)
            fields.extend(field.type for field in symbol.fields.values())
        elif isinstance(symbol, VariantSymbol):
            for case in symbol.cases.values():
                fields.extend(field.type for field in case.fields.values())
        result: set[Type] = set()
        for field_type in fields:
            result.update(self._by_value_definition_types(field_type))
        return result

    def _by_value_definition_types(self, type_: Type) -> set[Type]:
        raw = strip_const(type_)
        if is_void(raw):
            return set()
        if isinstance(raw, (StructType, ClassType, UnionType, VariantType, ResultType)):
            return {raw}
        if isinstance(raw, ArrayType):
            return self._by_value_definition_types(raw.inner)
        if isinstance(raw, (PointerType, ReferenceType, SliceType, EnumType)):
            return set()
        return set()


def lower(semantic: SemanticModel) -> IRModule:
    return Lowerer(semantic).lower()
