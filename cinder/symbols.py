from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from enum import StrEnum

from cinder import ast
from cinder.diagnostics import Span
from cinder.types import ClassType, ResultType, Type


class SymbolKind(StrEnum):
    VARIABLE = "variable"
    FUNCTION = "function"
    STRUCT = "struct"
    CLASS = "class"
    ENUM = "enum"
    UNION = "union"
    VARIANT = "variant"
    MODULE = "module"
    TYPE = "type"
    CONSTANT = "constant"


@dataclass(slots=True)
class Symbol:
    name: str
    span: Span
    kind: SymbolKind


@dataclass(slots=True)
class VariableSymbol(Symbol):
    type: Type
    is_const: bool = False
    is_parameter: bool = False
    c_name: str | None = None
    is_module_public: bool = False


@dataclass(slots=True)
class ComptimeVariableSymbol(Symbol):
    type: Type
    owner: NominalSymbol
    collection_kind: str
    statement_id: int


@dataclass(slots=True)
class FieldSymbol(Symbol):
    type: Type
    is_private: bool = False
    owner: str = ""


@dataclass(slots=True)
class ParameterSymbol:
    name: str
    type: Type
    span: Span
    is_variadic: bool = False


@dataclass(slots=True)
class FunctionSymbol(Symbol):
    parameters: list[ParameterSymbol]
    return_type: Type
    c_name: str
    declaration: ast.FunctionDecl | None = None
    owner: str | None = None
    is_extern: bool = False
    is_exported: bool = False
    is_variadic: bool = False
    module: str | None = None
    is_module_public: bool = False
    is_abstract: bool = False
    is_override: bool = False
    owner_class: ClassSymbol | None = None


@dataclass(slots=True)
class StructSymbol(Symbol):
    type: Type
    declaration: ast.StructDecl
    c_name: str
    fields: OrderedDict[str, FieldSymbol] = field(default_factory=OrderedDict)
    methods: OrderedDict[str, FunctionSymbol] = field(default_factory=OrderedDict)
    reflected: bool = False


@dataclass(slots=True)
class ClassSymbol(Symbol):
    type: ClassType
    declaration: ast.ClassDecl
    c_name: str
    fields: OrderedDict[str, FieldSymbol] = field(default_factory=OrderedDict)
    methods: OrderedDict[str, FunctionSymbol] = field(default_factory=OrderedDict)
    bases: list[ClassSymbol] = field(default_factory=list)
    primary_base: ClassSymbol | None = None
    interfaces: list[ClassSymbol] = field(default_factory=list)
    is_abstract: bool = False
    is_interface_only: bool = False
    reflected: bool = False
    abstract_methods: OrderedDict[str, FunctionSymbol] = field(default_factory=OrderedDict)
    interface_methods: OrderedDict[str, FunctionSymbol] = field(default_factory=OrderedDict)
    constructor: FunctionSymbol | None = None
    destructor: FunctionSymbol | None = None


@dataclass(slots=True)
class EnumMemberSymbol:
    name: str
    value: int
    c_name: str
    span: Span


@dataclass(slots=True)
class EnumSymbol(Symbol):
    type: Type
    declaration: ast.EnumDecl
    c_name: str
    members: OrderedDict[str, EnumMemberSymbol] = field(default_factory=OrderedDict)
    reflected: bool = False


@dataclass(slots=True)
class UnionSymbol(Symbol):
    type: Type
    declaration: ast.UnionDecl
    c_name: str
    fields: OrderedDict[str, FieldSymbol] = field(default_factory=OrderedDict)
    reflected: bool = False


@dataclass(slots=True)
class VariantCaseSymbol:
    name: str
    tag_value: int
    c_name: str
    span: Span
    fields: OrderedDict[str, FieldSymbol] = field(default_factory=OrderedDict)


@dataclass(slots=True)
class VariantSymbol(Symbol):
    type: Type
    declaration: ast.VariantDecl
    c_name: str
    cases: OrderedDict[str, VariantCaseSymbol] = field(default_factory=OrderedDict)
    reflected: bool = False


NominalSymbol = StructSymbol | ClassSymbol | EnumSymbol | UnionSymbol | VariantSymbol


@dataclass(slots=True)
class ConstantSymbol(Symbol):
    type: Type
    c_name: str


@dataclass(slots=True)
class ModuleSymbol(Symbol):
    module_name: str
    functions: dict[str, FunctionSymbol] = field(default_factory=dict)
    constants: dict[str, ConstantSymbol] = field(default_factory=dict)
    globals: dict[str, VariableSymbol] = field(default_factory=dict)
    types: dict[str, Type] = field(default_factory=dict)
    type_symbols: dict[str, NominalSymbol] = field(default_factory=dict)
    includes: tuple[str, ...] = ()
    libraries: tuple[str, ...] = ()
    generated_header: str | None = None


class Scope:
    def __init__(self, parent: Scope | None = None) -> None:
        self.parent = parent
        self.symbols: dict[str, Symbol] = {}

    def declare(self, symbol: Symbol) -> Symbol | None:
        previous = self.symbols.get(symbol.name)
        if previous is not None:
            return previous
        self.symbols[symbol.name] = symbol
        return None

    def lookup_local(self, name: str) -> Symbol | None:
        return self.symbols.get(name)

    def lookup(self, name: str) -> Symbol | None:
        scope: Scope | None = self
        while scope is not None:
            symbol = scope.symbols.get(name)
            if symbol is not None:
                return symbol
            scope = scope.parent
        return None


@dataclass(frozen=True, slots=True)
class AttributeResolution:
    kind: str
    field: FieldSymbol | None = None
    method: FunctionSymbol | None = None
    function: FunctionSymbol | None = None
    constant: ConstantSymbol | None = None
    global_: VariableSymbol | None = None
    owner_type: Type | None = None
    enum_member: EnumMemberSymbol | None = None
    variant_case: VariantCaseSymbol | None = None
    nominal: NominalSymbol | None = None
    class_: ClassSymbol | None = None
    access_path: tuple[str, ...] = ()
    compile_value: object | None = None


@dataclass(frozen=True, slots=True)
class CallResolution:
    kind: str
    function: FunctionSymbol | None = None
    struct: StructSymbol | None = None
    union: UnionSymbol | None = None
    variant: VariantSymbol | None = None
    variant_case: VariantCaseSymbol | None = None
    result_type: ResultType | None = None
    result_is_ok: bool | None = None
    argument_order: tuple[int, ...] = ()
    expected_types: tuple[Type | None, ...] = ()
    field_order: tuple[str, ...] = ()
    class_: ClassSymbol | None = None
    interface: ClassSymbol | None = None
    super_class: ClassSymbol | None = None
    compile_value: object | None = None


@dataclass(frozen=True, slots=True)
class IndexResolution:
    kind: str
    owner_type: Type


@dataclass(frozen=True, slots=True)
class BinaryResolution:
    kind: str
    owner_type: Type | None = None


@dataclass(frozen=True, slots=True)
class ComptimeBinding:
    kind: str
    owner: NominalSymbol
    index: int
    member: FieldSymbol | FunctionSymbol


@dataclass(frozen=True, slots=True)
class RangeResolution:
    start_index: int
    stop_index: int
    step_index: int | None
    element_type: Type


@dataclass(frozen=True, slots=True)
class PatternBinding:
    symbol: VariableSymbol
    field_name: str


@dataclass(frozen=True, slots=True)
class MatchCaseResolution:
    kind: str
    enum_member: EnumMemberSymbol | None = None
    variant_case: VariantCaseSymbol | None = None
    result_is_ok: bool | None = None
    option_is_some: bool | None = None
    bindings: tuple[PatternBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchResolution:
    value_type: Type
    cases: tuple[MatchCaseResolution, ...]
    exhaustive: bool


@dataclass(frozen=True, slots=True)
class PropagateResolution:
    source: ResultType
    enclosing: ResultType
