from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Mapping

from cinder import ast
from cinder.diagnostics import CompilationFailed, DiagnosticBag, Span
from cinder.stdlib import builtin_global_functions, builtin_modules
from cinder.symbols import (
    AttributeResolution,
    CallResolution,
    ClassSymbol,
    ComptimeVariableSymbol,
    ConstantSymbol,
    EnumMemberSymbol,
    EnumSymbol,
    FieldSymbol,
    FunctionSymbol,
    MatchCaseResolution,
    MatchResolution,
    ModuleSymbol,
    NominalSymbol,
    ParameterSymbol,
    PatternBinding,
    PropagateResolution,
    RangeResolution,
    Scope,
    StructSymbol,
    Symbol,
    SymbolKind,
    UnionSymbol,
    VariableSymbol,
    VariantCaseSymbol,
    VariantSymbol,
)
from cinder.types import (
    ArrayType,
    BOOL,
    CHAR,
    ClassType,
    ComptimeCollectionType,
    ComptimeItemType,
    ConstType,
    DynType,
    EnumType,
    ERROR,
    F64,
    FunctionValueType,
    I32,
    I64,
    ListType,
    ModuleType,
    NULL,
    OpaqueType,
    PointerType,
    PRIMITIVES,
    RangeType,
    ReferenceType,
    ResultType,
    SliceType,
    StructType,
    Type,
    TypeValueType,
    TupleType,
    U64,
    UnionType,
    USIZE,
    VariantType,
    VOID,
    can_assign,
    common_type,
    is_condition_type,
    is_float,
    is_integer,
    is_numeric,
    is_pointer_like,
    is_scalar,
    is_void,
    string_type,
    strip_const,
    strip_reference,
    type_name,
    value_type,
)


_REFLECTION_BUILTINS = frozenset(
    {
        "type_of",
        "type_name",
        "type_info",
        "size_of",
        "align_of",
        "field_count",
        "method_count",
        "fields",
        "methods",
        "fields_of",
        "methods_of",
        "has_field",
        "has_method",
        "implements",
    }
)


type _ListStorage = tuple[VariableSymbol | None, bool]


@dataclass(slots=True)
class SemanticModel:
    module: ast.Module
    module_name: str
    c_prefix: str
    module_mode: bool
    global_scope: Scope
    types: dict[str, Type]
    modules: dict[str, ModuleSymbol]
    structs: OrderedDict[str, StructSymbol]
    classes: OrderedDict[str, ClassSymbol]
    enums: OrderedDict[str, EnumSymbol]
    unions: OrderedDict[str, UnionSymbol]
    variants: OrderedDict[str, VariantSymbol]
    functions: OrderedDict[str, FunctionSymbol]
    globals: OrderedDict[str, VariableSymbol]
    includes: list[str]
    libraries: list[str]
    expr_types: dict[int, Type] = field(default_factory=dict)
    type_nodes: dict[int, Type] = field(default_factory=dict)
    name_symbols: dict[int, Symbol] = field(default_factory=dict)
    attribute_resolutions: dict[int, AttributeResolution] = field(default_factory=dict)
    call_resolutions: dict[int, CallResolution] = field(default_factory=dict)
    range_resolutions: dict[int, RangeResolution] = field(default_factory=dict)
    match_resolutions: dict[int, MatchResolution] = field(default_factory=dict)
    propagate_resolutions: dict[int, PropagateResolution] = field(default_factory=dict)
    implicit_declarations: dict[int, VariableSymbol] = field(default_factory=dict)
    declaration_symbols: dict[int, VariableSymbol] = field(default_factory=dict)
    foreach_symbols: dict[int, VariableSymbol] = field(default_factory=dict)
    comptime_foreach_symbols: dict[int, ComptimeVariableSymbol] = field(default_factory=dict)
    function_symbols: dict[int, FunctionSymbol] = field(default_factory=dict)
    struct_symbols: dict[int, StructSymbol] = field(default_factory=dict)
    class_symbols: dict[int, ClassSymbol] = field(default_factory=dict)
    enum_symbols: dict[int, EnumSymbol] = field(default_factory=dict)
    union_symbols: dict[int, UnionSymbol] = field(default_factory=dict)
    variant_symbols: dict[int, VariantSymbol] = field(default_factory=dict)
    global_symbols: dict[int, VariableSymbol] = field(default_factory=dict)
    nominal_symbols: dict[Type, NominalSymbol] = field(default_factory=dict)
    static_assert_values: dict[int, bool | None] = field(default_factory=dict)

    def expression_type(self, expression: ast.Expression) -> Type:
        return self.expr_types.get(id(expression), ERROR)

    def module_symbol(self) -> ModuleSymbol:
        constants: dict[str, ConstantSymbol] = {}
        public_globals: dict[str, VariableSymbol] = {}
        for name, symbol in self.globals.items():
            if symbol.is_const:
                constants[name] = ConstantSymbol(
                    name,
                    symbol.span,
                    SymbolKind.CONSTANT,
                    symbol.type,
                    symbol.c_name or name,
                )
            else:
                public_globals[name] = symbol
        type_symbols: dict[str, NominalSymbol] = {}
        type_symbols.update(self.structs)
        type_symbols.update(self.classes)
        type_symbols.update(self.enums)
        type_symbols.update(self.unions)
        type_symbols.update(self.variants)
        return ModuleSymbol(
            name=self.module_name.rsplit(".", 1)[-1],
            span=self.module.span,
            kind=SymbolKind.MODULE,
            module_name=self.module_name,
            functions=dict(self.functions),
            constants=constants,
            globals=public_globals,
            types={name: symbol.type for name, symbol in type_symbols.items()},
            type_symbols=type_symbols,
            includes=tuple(self.includes),
            libraries=tuple(self.libraries),
        )


class Checker:
    def __init__(
        self,
        module: ast.Module,
        source: str,
        *,
        available_modules: Mapping[str, ModuleSymbol] | None = None,
        module_name: str | None = None,
        c_prefix: str = "",
        module_mode: bool = False,
        is_entry: bool = True,
    ) -> None:
        self.module = module
        self.source = source
        self.path = module.path
        self.module_name = module_name or module.path.stem
        self.c_prefix = c_prefix
        self.module_mode = module_mode
        self.is_entry = is_entry
        self.diagnostics = DiagnosticBag()
        self.global_scope = Scope()
        self.types: dict[str, Type] = dict(PRIMITIVES)
        self.available_modules = builtin_modules(self.path)
        if available_modules is not None:
            self.available_modules.update(available_modules)
        self.imported_modules: dict[str, ModuleSymbol] = {}
        self.structs: OrderedDict[str, StructSymbol] = OrderedDict()
        self.classes: OrderedDict[str, ClassSymbol] = OrderedDict()
        self.enums: OrderedDict[str, EnumSymbol] = OrderedDict()
        self.unions: OrderedDict[str, UnionSymbol] = OrderedDict()
        self.variants: OrderedDict[str, VariantSymbol] = OrderedDict()
        self.nominal_symbols: dict[Type, NominalSymbol] = {}
        self.structs_by_type: dict[StructType, StructSymbol] = {}
        self.classes_by_type: dict[ClassType, ClassSymbol] = {}
        self.enums_by_type: dict[EnumType, EnumSymbol] = {}
        self.unions_by_type: dict[UnionType, UnionSymbol] = {}
        self.variants_by_type: dict[VariantType, VariantSymbol] = {}
        self.functions: OrderedDict[str, FunctionSymbol] = OrderedDict()
        self.globals: OrderedDict[str, VariableSymbol] = OrderedDict()
        self.includes: list[str] = []
        self.libraries: list[str] = []

        self.expr_types: dict[int, Type] = {}
        self.type_nodes: dict[int, Type] = {}
        self.name_symbols: dict[int, Symbol] = {}
        self.attribute_resolutions: dict[int, AttributeResolution] = {}
        self.call_resolutions: dict[int, CallResolution] = {}
        self.range_resolutions: dict[int, RangeResolution] = {}
        self.match_resolutions: dict[int, MatchResolution] = {}
        self.propagate_resolutions: dict[int, PropagateResolution] = {}
        self.implicit_declarations: dict[int, VariableSymbol] = {}
        self.declaration_symbols: dict[int, VariableSymbol] = {}
        self.foreach_symbols: dict[int, VariableSymbol] = {}
        self.comptime_foreach_symbols: dict[int, ComptimeVariableSymbol] = {}
        self.function_symbols: dict[int, FunctionSymbol] = {}
        self.struct_symbols: dict[int, StructSymbol] = {}
        self.class_symbols: dict[int, ClassSymbol] = {}
        self.enum_symbols: dict[int, EnumSymbol] = {}
        self.union_symbols: dict[int, UnionSymbol] = {}
        self.variant_symbols: dict[int, VariantSymbol] = {}
        self.global_symbols: dict[int, VariableSymbol] = {}
        self.static_assert_values: dict[int, bool | None] = {}

        self.current_scope = self.global_scope
        self.current_function: FunctionSymbol | None = None
        self.current_owner: StructSymbol | ClassSymbol | None = None
        self.loop_depth = 0
        self.unsafe_depth = 0
        self.active_list_iterators: list[_ListStorage] = []

    def check(self) -> SemanticModel:
        self._install_builtins()
        self._collect_imports()
        self._collect_type_names()
        self._collect_nominal_members()
        self._resolve_class_hierarchy()
        self._collect_functions()
        self._collect_globals()
        self._validate_lifetime_types()
        self._check_struct_layouts()
        self._check_global_initializers()
        self._check_functions()
        self._check_static_asserts()
        self._check_main()

        if self.diagnostics.has_errors:
            raise CompilationFailed(self.diagnostics.items, self.source)

        return SemanticModel(
            module=self.module,
            module_name=self.module_name,
            c_prefix=self.c_prefix,
            module_mode=self.module_mode,
            global_scope=self.global_scope,
            types=self.types,
            modules=self.imported_modules,
            structs=self.structs,
            classes=self.classes,
            enums=self.enums,
            unions=self.unions,
            variants=self.variants,
            functions=self.functions,
            globals=self.globals,
            includes=self.includes,
            libraries=self.libraries,
            expr_types=self.expr_types,
            type_nodes=self.type_nodes,
            name_symbols=self.name_symbols,
            attribute_resolutions=self.attribute_resolutions,
            call_resolutions=self.call_resolutions,
            range_resolutions=self.range_resolutions,
            match_resolutions=self.match_resolutions,
            propagate_resolutions=self.propagate_resolutions,
            implicit_declarations=self.implicit_declarations,
            declaration_symbols=self.declaration_symbols,
            foreach_symbols=self.foreach_symbols,
            comptime_foreach_symbols=self.comptime_foreach_symbols,
            function_symbols=self.function_symbols,
            struct_symbols=self.struct_symbols,
            class_symbols=self.class_symbols,
            enum_symbols=self.enum_symbols,
            union_symbols=self.union_symbols,
            variant_symbols=self.variant_symbols,
            global_symbols=self.global_symbols,
            nominal_symbols=self.nominal_symbols,
            static_assert_values=self.static_assert_values,
        )

    def _install_builtins(self) -> None:
        for symbol in builtin_global_functions(self.path).values():
            self.global_scope.declare(symbol)
        self._install_reflection_types()

    def _install_reflection_types(self) -> None:
        """Register the inspectable runtime metadata structs.

        The definitions live in cinder_runtime.h, so they participate in type
        checking like ordinary structs without being emitted as user types.
        """

        span = Span.point(self.path, 1, 1)

        def runtime_struct(
            name: str,
            fields: tuple[tuple[str, Type], ...],
        ) -> StructSymbol:
            type_ = StructType(name, name)
            declaration = ast.StructDecl(span, name, [], [], ())
            symbol = StructSymbol(
                name=name,
                span=span,
                kind=SymbolKind.STRUCT,
                type=type_,
                declaration=declaration,
                c_name=name,
            )
            for field_name, field_type in fields:
                symbol.fields[field_name] = FieldSymbol(
                    field_name,
                    span,
                    SymbolKind.VARIABLE,
                    field_type,
                    False,
                    name,
                )
            self.types[name] = type_
            self._register_nominal(type_, symbol)
            self.global_scope.declare(symbol)
            return symbol

        field_info = runtime_struct(
            "CinderFieldInfo",
            (
                ("name", string_type()),
                ("type_name", string_type()),
                ("offset", USIZE),
                ("size", USIZE),
                ("alignment", USIZE),
                ("is_private", BOOL),
            ),
        )
        method_info = runtime_struct(
            "CinderMethodInfo",
            (
                ("name", string_type()),
                ("signature", string_type()),
                ("return_type_name", string_type()),
                ("parameter_count", USIZE),
                ("is_abstract", BOOL),
                ("is_override", BOOL),
            ),
        )
        runtime_struct(
            "CinderTypeInfo",
            (
                ("name", string_type()),
                ("kind", I32),
                ("size", USIZE),
                ("alignment", USIZE),
                ("fields", PointerType(ConstType(field_info.type))),
                ("field_count", USIZE),
                ("methods", PointerType(ConstType(method_info.type))),
                ("method_count", USIZE),
            ),
        )

    def _collect_imports(self) -> None:
        for item in self.module.items:
            if isinstance(item, ast.ImportDecl):
                module = self.available_modules.get(item.module)
                if module is None:
                    self._error(
                        f"module {item.module!r} was not provided by the build graph",
                        item.span,
                        code="C001",
                    )
                    continue
                alias = item.alias or item.module.rsplit(".", 1)[-1]
                imported = ModuleSymbol(
                    name=alias,
                    span=item.span,
                    kind=SymbolKind.MODULE,
                    module_name=module.module_name,
                    functions=module.functions,
                    constants=module.constants,
                    globals=module.globals,
                    types=module.types,
                    type_symbols=module.type_symbols,
                    includes=module.includes,
                    libraries=module.libraries,
                    generated_header=module.generated_header,
                )
                self._declare_global(imported)
                self.imported_modules[alias] = imported
                self._add_module_requirements(imported)
                for name, type_ in imported.types.items():
                    self.types[f"{alias}.{name}"] = type_
                    nominal = imported.type_symbols.get(name)
                    if nominal is not None:
                        self._register_nominal(type_, nominal)

            elif isinstance(item, ast.FromImportDecl):
                module = self.available_modules.get(item.module)
                if module is None:
                    self._error(
                        f"module {item.module!r} was not provided by the build graph",
                        item.span,
                        code="C002",
                    )
                    continue
                self._add_module_requirements(module)
                for imported_name, alias in item.names:
                    public_name = alias or imported_name
                    if imported_name in module.functions:
                        original = module.functions[imported_name]
                        clone = FunctionSymbol(
                            name=public_name,
                            span=item.span,
                            kind=SymbolKind.FUNCTION,
                            parameters=original.parameters,
                            return_type=original.return_type,
                            c_name=original.c_name,
                            declaration=None,
                            owner=original.owner,
                            is_extern=True,
                            is_exported=True,
                            is_variadic=original.is_variadic,
                            module=module.module_name,
                            is_module_public=True,
                        )
                        self._declare_global(clone)
                    elif imported_name in module.constants:
                        original_constant = module.constants[imported_name]
                        self._declare_global(
                            ConstantSymbol(
                                public_name,
                                item.span,
                                SymbolKind.CONSTANT,
                                original_constant.type,
                                original_constant.c_name,
                            )
                        )
                    elif imported_name in module.globals:
                        original_global = module.globals[imported_name]
                        self._declare_global(
                            VariableSymbol(
                                public_name,
                                item.span,
                                SymbolKind.VARIABLE,
                                original_global.type,
                                original_global.is_const,
                                False,
                                original_global.c_name,
                                True,
                            )
                        )
                    elif imported_name in module.types:
                        imported_type = module.types[imported_name]
                        if public_name in self.types and self.types[public_name] != imported_type:
                            self._error(
                                f"type name {public_name!r} is already defined",
                                item.span,
                                code="C003",
                            )
                            continue
                        self.types[public_name] = imported_type
                        original_nominal = module.type_symbols.get(imported_name)
                        if original_nominal is not None:
                            alias_symbol = self._alias_nominal(original_nominal, public_name, item.span)
                            self._declare_global(alias_symbol)
                            self._register_nominal(imported_type, original_nominal)
                    else:
                        self._error(
                            f"module {item.module!r} has no exported name {imported_name!r}",
                            item.span,
                            code="C004",
                        )

            elif isinstance(item, ast.ExternImportDecl):
                include = f'"{item.header}"'
                if include not in self.includes:
                    self.includes.append(include)

    def _alias_nominal(self, symbol: NominalSymbol, name: str, span: Span) -> NominalSymbol:
        if isinstance(symbol, StructSymbol):
            return StructSymbol(
                name=name,
                span=span,
                kind=SymbolKind.STRUCT,
                type=symbol.type,
                declaration=symbol.declaration,
                c_name=symbol.c_name,
                fields=symbol.fields,
                methods=symbol.methods,
                reflected=symbol.reflected,
            )
        if isinstance(symbol, ClassSymbol):
            return ClassSymbol(
                name=name,
                span=span,
                kind=SymbolKind.CLASS,
                type=symbol.type,
                declaration=symbol.declaration,
                c_name=symbol.c_name,
                fields=symbol.fields,
                methods=symbol.methods,
                bases=symbol.bases,
                primary_base=symbol.primary_base,
                interfaces=symbol.interfaces,
                is_abstract=symbol.is_abstract,
                is_interface_only=symbol.is_interface_only,
                reflected=symbol.reflected,
                abstract_methods=symbol.abstract_methods,
                interface_methods=symbol.interface_methods,
                constructor=symbol.constructor,
                destructor=symbol.destructor,
            )
        if isinstance(symbol, EnumSymbol):
            return EnumSymbol(
                name=name,
                span=span,
                kind=SymbolKind.ENUM,
                type=symbol.type,
                declaration=symbol.declaration,
                c_name=symbol.c_name,
                members=symbol.members,
                reflected=symbol.reflected,
            )
        if isinstance(symbol, UnionSymbol):
            return UnionSymbol(
                name=name,
                span=span,
                kind=SymbolKind.UNION,
                type=symbol.type,
                declaration=symbol.declaration,
                c_name=symbol.c_name,
                fields=symbol.fields,
                reflected=symbol.reflected,
            )
        return VariantSymbol(
            name=name,
            span=span,
            kind=SymbolKind.VARIANT,
            type=symbol.type,
            declaration=symbol.declaration,
            c_name=symbol.c_name,
            cases=symbol.cases,
            reflected=symbol.reflected,
        )

    def _register_nominal(self, type_: Type, symbol: NominalSymbol) -> None:
        self.nominal_symbols[type_] = symbol
        if isinstance(type_, StructType) and isinstance(symbol, StructSymbol):
            self.structs_by_type[type_] = symbol
        elif isinstance(type_, ClassType) and isinstance(symbol, ClassSymbol):
            self.classes_by_type[type_] = symbol
        elif isinstance(type_, EnumType) and isinstance(symbol, EnumSymbol):
            self.enums_by_type[type_] = symbol
        elif isinstance(type_, UnionType) and isinstance(symbol, UnionSymbol):
            self.unions_by_type[type_] = symbol
        elif isinstance(type_, VariantType) and isinstance(symbol, VariantSymbol):
            self.variants_by_type[type_] = symbol

    def _add_module_requirements(self, module: ModuleSymbol) -> None:
        if module.generated_header is None:
            for include in module.includes:
                if include not in self.includes:
                    self.includes.append(include)
        for library in module.libraries:
            if library not in self.libraries:
                self.libraries.append(library)

    def _collect_type_names(self) -> None:
        for declaration in self.module.structs:
            self._collect_struct_name(declaration)
        for declaration in self.module.classes:
            self._collect_class_name(declaration)
        for declaration in self.module.enums:
            self._collect_enum_name(declaration)
        for declaration in self.module.unions:
            self._collect_union_name(declaration)
        for declaration in self.module.variants:
            self._collect_variant_name(declaration)

    def _ensure_type_name_available(self, name: str, span: Span, code: str) -> bool:
        if name not in self.types:
            return True
        self._error(f"type {name!r} is already defined", span, code=code)
        return False

    def _collect_struct_name(self, declaration: ast.StructDecl) -> None:
        self._validate_decorators(declaration.decorators, declaration.span, allowed=("reflect",))
        if not self._ensure_type_name_available(declaration.name, declaration.span, "C005"):
            return
        c_name = self._c_type_name(declaration.name)
        type_ = StructType(declaration.name, c_name)
        symbol = StructSymbol(
            name=declaration.name,
            span=declaration.span,
            kind=SymbolKind.STRUCT,
            type=type_,
            declaration=declaration,
            c_name=c_name,
            reflected="reflect" in declaration.decorators,
        )
        if self._declare_global(symbol) is not None:
            return
        self.types[declaration.name] = type_
        self.structs[declaration.name] = symbol
        self._register_nominal(type_, symbol)
        self.struct_symbols[id(declaration)] = symbol

    def _collect_class_name(self, declaration: ast.ClassDecl) -> None:
        self._validate_decorators(declaration.decorators, declaration.span, allowed=("reflect",))
        if not self._ensure_type_name_available(declaration.name, declaration.span, "C163"):
            return
        c_name = self._c_type_name(declaration.name)
        type_ = ClassType(declaration.name, c_name)
        symbol = ClassSymbol(
            name=declaration.name,
            span=declaration.span,
            kind=SymbolKind.CLASS,
            type=type_,
            declaration=declaration,
            c_name=c_name,
            is_abstract=declaration.is_abstract,
            reflected="reflect" in declaration.decorators,
        )
        if self._declare_global(symbol) is not None:
            return
        self.types[declaration.name] = type_
        self.classes[declaration.name] = symbol
        self._register_nominal(type_, symbol)
        self.class_symbols[id(declaration)] = symbol

    def _collect_enum_name(self, declaration: ast.EnumDecl) -> None:
        self._validate_decorators(declaration.decorators, declaration.span, allowed=("reflect",))
        if not self._ensure_type_name_available(declaration.name, declaration.span, "C108"):
            return
        c_name = self._c_type_name(declaration.name)
        type_ = EnumType(declaration.name, c_name)
        symbol = EnumSymbol(
            name=declaration.name,
            span=declaration.span,
            kind=SymbolKind.ENUM,
            type=type_,
            declaration=declaration,
            c_name=c_name,
            reflected="reflect" in declaration.decorators,
        )
        if self._declare_global(symbol) is not None:
            return
        self.types[declaration.name] = type_
        self.enums[declaration.name] = symbol
        self._register_nominal(type_, symbol)
        self.enum_symbols[id(declaration)] = symbol

    def _collect_union_name(self, declaration: ast.UnionDecl) -> None:
        self._validate_decorators(declaration.decorators, declaration.span, allowed=("reflect",))
        if not self._ensure_type_name_available(declaration.name, declaration.span, "C109"):
            return
        c_name = self._c_type_name(declaration.name)
        type_ = UnionType(declaration.name, c_name)
        symbol = UnionSymbol(
            name=declaration.name,
            span=declaration.span,
            kind=SymbolKind.UNION,
            type=type_,
            declaration=declaration,
            c_name=c_name,
            reflected="reflect" in declaration.decorators,
        )
        if self._declare_global(symbol) is not None:
            return
        self.types[declaration.name] = type_
        self.unions[declaration.name] = symbol
        self._register_nominal(type_, symbol)
        self.union_symbols[id(declaration)] = symbol

    def _collect_variant_name(self, declaration: ast.VariantDecl) -> None:
        self._validate_decorators(declaration.decorators, declaration.span, allowed=("reflect",))
        if not self._ensure_type_name_available(declaration.name, declaration.span, "C110"):
            return
        c_name = self._c_type_name(declaration.name)
        type_ = VariantType(declaration.name, c_name)
        symbol = VariantSymbol(
            name=declaration.name,
            span=declaration.span,
            kind=SymbolKind.VARIANT,
            type=type_,
            declaration=declaration,
            c_name=c_name,
            reflected="reflect" in declaration.decorators,
        )
        if self._declare_global(symbol) is not None:
            return
        self.types[declaration.name] = type_
        self.variants[declaration.name] = symbol
        self._register_nominal(type_, symbol)
        self.variant_symbols[id(declaration)] = symbol

    def _collect_nominal_members(self) -> None:
        self._collect_struct_members()
        self._collect_class_members()
        self._collect_enum_members()
        self._collect_union_members()
        self._collect_variant_members()

    def _collect_struct_members(self) -> None:
        for declaration in self.module.structs:
            struct = self.structs.get(declaration.name)
            if struct is None:
                continue
            for field_declaration in declaration.fields:
                field_type = self._resolve_type(field_declaration.annotation)
                if is_void(field_type):
                    self._error("struct fields cannot have type void", field_declaration.span, code="C006")
                    field_type = ERROR
                if field_declaration.name in struct.fields or field_declaration.name in struct.methods:
                    self._error(
                        f"duplicate member {field_declaration.name!r} in struct {struct.name}",
                        field_declaration.span,
                        code="C007",
                    )
                    continue
                struct.fields[field_declaration.name] = FieldSymbol(
                    field_declaration.name,
                    field_declaration.span,
                    SymbolKind.VARIABLE,
                    field_type,
                    field_declaration.is_private,
                    struct.name,
                )

            for method_declaration in declaration.methods:
                self._validate_decorators(method_declaration.decorators, method_declaration.span, allowed=())
                if method_declaration.name in struct.methods or method_declaration.name in struct.fields:
                    self._error(
                        f"duplicate member {method_declaration.name!r} in struct {struct.name}",
                        method_declaration.span,
                        code="C008",
                    )
                    continue
                method = self._make_function_symbol(method_declaration, owner=struct)
                struct.methods[method.name] = method
                self.function_symbols[id(method_declaration)] = method

    def _collect_class_members(self) -> None:
        for declaration in self.module.classes:
            class_ = self.classes.get(declaration.name)
            if class_ is None:
                continue

            for field_declaration in declaration.fields:
                field_type = self._resolve_type(field_declaration.annotation)
                if is_void(field_type) or isinstance(field_type, ReferenceType):
                    self._error(
                        f"invalid class field type {type_name(field_type)}",
                        field_declaration.span,
                        code="C164",
                    )
                    field_type = ERROR
                if field_declaration.name in class_.fields or field_declaration.name in class_.methods:
                    self._error(
                        f"duplicate member {field_declaration.name!r} in class {class_.name}",
                        field_declaration.span,
                        code="C165",
                    )
                    continue
                class_.fields[field_declaration.name] = FieldSymbol(
                    field_declaration.name,
                    field_declaration.span,
                    SymbolKind.VARIABLE,
                    field_type,
                    field_declaration.is_private,
                    class_.name,
                )

            for method_declaration in declaration.methods:
                allowed = ("abstractmethod", "override")
                self._validate_decorators(
                    method_declaration.decorators,
                    method_declaration.span,
                    allowed=allowed,
                )
                if method_declaration.name in class_.methods or method_declaration.name in class_.fields:
                    self._error(
                        f"duplicate member {method_declaration.name!r} in class {class_.name}",
                        method_declaration.span,
                        code="C166",
                    )
                    continue

                is_abstract = "abstractmethod" in method_declaration.decorators
                is_override = "override" in method_declaration.decorators
                if is_abstract and not declaration.is_abstract:
                    self._error(
                        "@abstractmethod is only valid in an abstract class",
                        method_declaration.span,
                        code="C167",
                    )
                if is_abstract and not self._is_pass_only(method_declaration.body):
                    self._error(
                        "abstract methods must have a pass-only body",
                        method_declaration.span,
                        code="C168",
                    )
                if method_declaration.name in ("__init__", "__del__") and is_abstract:
                    self._error(
                        f"{method_declaration.name} cannot be abstract",
                        method_declaration.span,
                        code="C169",
                    )

                method = self._make_function_symbol(method_declaration, owner=class_)
                method.is_abstract = is_abstract
                method.is_override = is_override
                method.owner_class = class_
                if method.is_variadic:
                    self._error(
                        "class methods cannot be variadic",
                        method.span,
                        code="C212",
                        note="explicit interface-table thunks cannot portably forward C varargs",
                    )
                if method.parameters:
                    self_type = strip_const(method.parameters[0].type)
                    if method.name in ("__init__", "__del__"):
                        valid_lifecycle_self = (
                            isinstance(self_type, ReferenceType)
                            and not isinstance(self_type.inner, ConstType)
                            and strip_const(self_type.inner) == class_.type
                        )
                        if not valid_lifecycle_self:
                            self._error(
                                f"{method.name} requires mutable self: &{class_.name}",
                                method.parameters[0].span,
                                code="C213",
                            )
                    elif isinstance(self_type, ClassType):
                        self._error(
                            "class methods cannot receive self by value",
                            method.parameters[0].span,
                            code="C214",
                            note="use self, &Class, &const Class, or &dyn Interface",
                        )
                class_.methods[method.name] = method
                self.function_symbols[id(method_declaration)] = method

                if method.name == "__init__":
                    if class_.constructor is not None:
                        self._error("class has more than one constructor", method.span, code="C170")
                    class_.constructor = method
                    if not is_void(method.return_type):
                        self._error("__init__ must return void", method.span, code="C171")
                elif method.name == "__del__":
                    if class_.destructor is not None:
                        self._error("class has more than one destructor", method.span, code="C172")
                    class_.destructor = method
                    if not is_void(method.return_type) or len(method.parameters) != 1:
                        self._error(
                            "__del__ must take only self and return void",
                            method.span,
                            code="C173",
                        )

    @staticmethod
    def _is_pass_only(body: ast.Block | None) -> bool:
        return (
            body is not None
            and len(body.statements) == 1
            and isinstance(body.statements[0], ast.PassStmt)
        )

    def _resolve_class_hierarchy(self) -> None:
        for declaration in self.module.classes:
            class_ = self.classes.get(declaration.name)
            if class_ is None:
                continue
            for base_node in declaration.bases:
                base_type = self._resolve_type(base_node)
                base = self.nominal_symbols.get(base_type)
                if not isinstance(base_type, ClassType) or not isinstance(base, ClassSymbol):
                    self._error(
                        f"class base must be a class, got {type_name(base_type)}",
                        base_node.span,
                        code="C174",
                    )
                    continue
                if base in class_.bases:
                    self._error(
                        f"duplicate base class {base.name!r}",
                        base_node.span,
                        code="C175",
                    )
                    continue
                class_.bases.append(base)

        self._check_class_cycles()

        for class_ in self._classes_in_base_order():
            class_.is_interface_only = (
                class_.is_abstract
                and not class_.fields
                and class_.constructor is None
                and class_.destructor is None
            )

            layout_bases = [base for base in class_.bases if not base.is_interface_only]
            if len(layout_bases) > 1:
                self._error(
                    f"class {class_.name} has multiple implementation bases",
                    class_.span,
                    code="C176",
                    note="Cinder supports one implementation base and any number of abstract interfaces",
                )
            if layout_bases:
                class_.primary_base = layout_bases[0]
                if class_.bases and class_.bases[0] is not class_.primary_base:
                    self._error(
                        "the implementation base must be listed first",
                        class_.span,
                        code="C177",
                    )
            class_.interfaces = [base for base in class_.bases if base is not class_.primary_base]

            if class_.primary_base is not None:
                for field in class_.fields.values():
                    inherited_field = self._lookup_class_field(class_.primary_base, field.name)
                    inherited_method = self._lookup_class_method(
                        class_.primary_base,
                        field.name,
                    )
                    if inherited_field is not None or inherited_method is not None:
                        self._error(
                            f"member {class_.name}.{field.name} shadows an inherited member",
                            field.span,
                            code="C215",
                        )
                for method in class_.methods.values():
                    if method.name in ("__init__", "__del__"):
                        continue
                    inherited_field = self._lookup_class_field(
                        class_.primary_base,
                        method.name,
                    )
                    if inherited_field is not None:
                        self._error(
                            f"method {class_.name}.{method.name} shadows an inherited field",
                            method.span,
                            code="C216",
                        )

            inherited_methods: OrderedDict[str, FunctionSymbol] = OrderedDict()
            for base in class_.bases:
                for name, method in base.interface_methods.items():
                    previous = inherited_methods.get(name)
                    if previous is not None and not self._method_signatures_match(
                        method,
                        previous,
                    ):
                        self._error(
                            f"base classes provide incompatible signatures for {name!r}",
                            class_.span,
                            code="C217",
                            note=(
                                f"{previous.owner}.{previous.name} conflicts with "
                                f"{method.owner}.{method.name}"
                            ),
                        )
                    inherited_methods.setdefault(name, method)

            effective_methods: OrderedDict[str, FunctionSymbol] = OrderedDict(inherited_methods)
            for name, method in class_.methods.items():
                if name in ("__init__", "__del__"):
                    continue
                inherited = inherited_methods.get(name)
                if method.is_override and inherited is None:
                    self._error(
                        f"method {class_.name}.{name} is marked @override but no base method exists",
                        method.span,
                        code="C178",
                    )
                if inherited is not None and not self._method_signatures_match(method, inherited):
                    self._error(
                        f"override {class_.name}.{name} does not match the base signature",
                        method.span,
                        code="C179",
                        note=f"base declaration is {inherited.owner}.{inherited.name}",
                    )
                effective_methods[name] = method

            class_.interface_methods = effective_methods
            class_.abstract_methods = OrderedDict(
                (name, method)
                for name, method in effective_methods.items()
                if method.is_abstract
            )
            if not class_.is_abstract and class_.abstract_methods:
                missing = ", ".join(class_.abstract_methods)
                self._error(
                    f"concrete class {class_.name} does not implement: {missing}",
                    class_.span,
                    code="C180",
                )

            if class_.reflected:
                for interface in self._implemented_interfaces(class_):
                    if interface.reflected:
                        continue
            else:
                reflected_interfaces = [
                    interface.name
                    for interface in self._implemented_interfaces(class_)
                    if interface.reflected
                ]
                if reflected_interfaces:
                    self._error(
                        f"class {class_.name} must use @reflect because it implements reflected interface(s): "
                        + ", ".join(reflected_interfaces),
                        class_.span,
                        code="C181",
                    )

            self._validate_constructor_chain(class_)

    def _check_class_cycles(self) -> None:
        visiting: list[ClassSymbol] = []
        visiting_types: set[ClassType] = set()
        visited: set[ClassType] = set()

        def visit(class_: ClassSymbol) -> None:
            if class_.type in visited:
                return
            if class_.type in visiting_types:
                start = next(
                    index
                    for index, item in enumerate(visiting)
                    if item.type == class_.type
                )
                cycle = " -> ".join(item.name for item in [*visiting[start:], class_])
                self._error(
                    f"cyclic class inheritance: {cycle}",
                    class_.span,
                    code="C182",
                )
                return
            visiting.append(class_)
            visiting_types.add(class_.type)
            for base in class_.bases:
                visit(base)
            visiting.pop()
            visiting_types.remove(class_.type)
            visited.add(class_.type)

        for class_ in self.classes.values():
            visit(class_)

    def _classes_in_base_order(self) -> list[ClassSymbol]:
        ordered: list[ClassSymbol] = []
        visited: set[ClassType] = set()

        def visit(class_: ClassSymbol) -> None:
            if class_.type in visited:
                return
            visited.add(class_.type)
            for base in class_.bases:
                visit(base)
            ordered.append(class_)

        for class_ in self.classes.values():
            visit(class_)
        return ordered

    def _method_signatures_match(self, method: FunctionSymbol, base: FunctionSymbol) -> bool:
        if method.return_type != base.return_type:
            return False
        method_parameters = method.parameters[1:] if method.parameters else []
        base_parameters = base.parameters[1:] if base.parameters else []
        return [parameter.type for parameter in method_parameters] == [
            parameter.type for parameter in base_parameters
        ]

    def _implemented_interfaces(self, class_: ClassSymbol) -> list[ClassSymbol]:
        result: list[ClassSymbol] = []
        seen: set[ClassType] = set()

        def add(candidate: ClassSymbol) -> None:
            if candidate.type in seen:
                return
            seen.add(candidate.type)
            if candidate.is_abstract:
                result.append(candidate)
            for base in candidate.bases:
                add(base)

        for base in class_.bases:
            add(base)
        if class_.is_abstract:
            add(class_)
        return result

    def _validate_constructor_chain(self, class_: ClassSymbol) -> None:
        base = class_.primary_base
        if base is None:
            return
        base_arguments = base.constructor.parameters[1:] if base.constructor else []
        if class_.constructor is None:
            if base_arguments:
                self._error(
                    f"class {class_.name} needs a constructor because base constructor "
                    f"{base.name}.__init__ requires arguments",
                    class_.span,
                    code="C183",
                )
            return
        body = class_.constructor.declaration.body if class_.constructor.declaration else None
        if body is None or not body.statements or not self._is_super_init_statement(body.statements[0]):
            self._error(
                f"constructor {class_.name}.__init__ must call super().__init__ first",
                class_.constructor.span,
                code="C184",
            )

    @staticmethod
    def _is_super_init_statement(statement: ast.Statement) -> bool:
        if not isinstance(statement, ast.ExpressionStmt):
            return False
        expression = statement.expression
        if not isinstance(expression, ast.CallExpr):
            return False
        return Checker._super_method_name(expression.callee) == "__init__"

    @staticmethod
    def _super_method_name(callee: ast.Expression) -> str | None:
        if not isinstance(callee, ast.AttributeExpr):
            return None
        base = callee.value
        if isinstance(base, ast.NameExpr) and base.name == "super":
            return callee.name
        if (
            isinstance(base, ast.CallExpr)
            and isinstance(base.callee, ast.NameExpr)
            and base.callee.name == "super"
            and not base.arguments
        ):
            return callee.name
        return None

    def _collect_enum_members(self) -> None:
        for declaration in self.module.enums:
            enum = self.enums.get(declaration.name)
            if enum is None:
                continue
            next_value = 0
            values: dict[int, EnumMemberSymbol] = {}
            for member_declaration in declaration.members:
                if member_declaration.name in enum.members:
                    self._error(
                        f"duplicate enum member {member_declaration.name!r}",
                        member_declaration.span,
                        code="C111",
                    )
                    continue
                value = next_value if member_declaration.value is None else member_declaration.value
                next_value = value + 1
                previous_value = values.get(value)
                if previous_value is not None:
                    self._error(
                        f"enum value {value} is already used by {previous_value.name!r}",
                        member_declaration.span,
                        code="C112",
                        note="enum aliases are not supported because match cases must be distinguishable",
                    )
                member = EnumMemberSymbol(
                    member_declaration.name,
                    value,
                    f"{enum.c_name}_{member_declaration.name}",
                    member_declaration.span,
                )
                enum.members[member_declaration.name] = member
                values.setdefault(value, member)

    def _collect_union_members(self) -> None:
        for declaration in self.module.unions:
            union = self.unions.get(declaration.name)
            if union is None:
                continue
            for field_declaration in declaration.fields:
                field_type = self._resolve_type(field_declaration.annotation)
                if is_void(field_type) or isinstance(field_type, ReferenceType):
                    self._error(
                        f"invalid union field type {type_name(field_type)}",
                        field_declaration.span,
                        code="C113",
                    )
                    field_type = ERROR
                if field_declaration.name in union.fields:
                    self._error(
                        f"duplicate union field {field_declaration.name!r}",
                        field_declaration.span,
                        code="C114",
                    )
                    continue
                union.fields[field_declaration.name] = FieldSymbol(
                    field_declaration.name,
                    field_declaration.span,
                    SymbolKind.VARIABLE,
                    field_type,
                    field_declaration.is_private,
                    union.name,
                )

    def _collect_variant_members(self) -> None:
        for declaration in self.module.variants:
            variant = self.variants.get(declaration.name)
            if variant is None:
                continue
            for tag_value, case_declaration in enumerate(declaration.cases):
                if case_declaration.name in variant.cases:
                    self._error(
                        f"duplicate variant case {case_declaration.name!r}",
                        case_declaration.span,
                        code="C115",
                    )
                    continue
                case = VariantCaseSymbol(
                    case_declaration.name,
                    tag_value,
                    f"{variant.c_name}_Tag_{case_declaration.name}",
                    case_declaration.span,
                )
                for field_declaration in case_declaration.fields:
                    field_type = self._resolve_type(field_declaration.annotation)
                    if is_void(field_type) or isinstance(field_type, ReferenceType):
                        self._error(
                            f"invalid variant payload type {type_name(field_type)}",
                            field_declaration.span,
                            code="C116",
                        )
                        field_type = ERROR
                    if field_declaration.name in case.fields:
                        self._error(
                            f"duplicate payload field {field_declaration.name!r}",
                            field_declaration.span,
                            code="C117",
                        )
                        continue
                    case.fields[field_declaration.name] = FieldSymbol(
                        field_declaration.name,
                        field_declaration.span,
                        SymbolKind.VARIABLE,
                        field_type,
                        False,
                        variant.name,
                    )
                variant.cases[case.name] = case

    def _collect_functions(self) -> None:
        for declaration in self.module.functions:
            self._validate_decorators(declaration.decorators, declaration.span, allowed=("export",))
            symbol = self._make_function_symbol(declaration, owner=None)
            previous = self._declare_global(symbol)
            if previous is not None:
                continue
            self.functions[symbol.name] = symbol
            self.function_symbols[id(declaration)] = symbol

    def _collect_globals(self) -> None:
        for declaration in self.module.globals:
            if declaration.annotation is None:
                self._error(
                    f"global {declaration.name!r} requires an explicit type annotation",
                    declaration.span,
                    code="C009",
                    note="public declarations are never inferred",
                )
                global_type = ERROR
            else:
                global_type = self._resolve_type(declaration.annotation)
            if is_void(global_type):
                self._error("global variables cannot have type void", declaration.span, code="C010")
                global_type = ERROR
            if declaration.is_const and declaration.initializer is None:
                self._error("constant globals require an initializer", declaration.span, code="C011")
            c_name = self._c_value_name(declaration.name)
            symbol = VariableSymbol(
                declaration.name,
                declaration.span,
                SymbolKind.VARIABLE,
                global_type,
                declaration.is_const,
                False,
                c_name,
                self.module_mode,
            )
            previous = self._declare_global(symbol)
            if previous is not None:
                continue
            self.globals[symbol.name] = symbol
            self.global_symbols[id(declaration)] = symbol

    def _validate_lifetime_types(self) -> None:
        for struct in self.structs.values():
            for field in struct.fields.values():
                self._validate_list_elements(field.type, field.span)
                if self._contains_list_value(field.type):
                    self._error(
                        f"field {struct.name}.{field.name} cannot own a List",
                        field.span,
                        code="C247",
                        note="store a pointer or reference; aggregate List ownership is not implemented",
                    )
                if self._contains_destructible_value(field.type):
                    self._error(
                        f"field {struct.name}.{field.name} contains a class with a destructor",
                        field.span,
                        code="C220",
                        note="destructor-bearing classes may currently be owned only by direct local variables",
                    )

        for class_ in self.classes.values():
            for field in class_.fields.values():
                self._validate_list_elements(field.type, field.span)
                if self._contains_list_value(field.type):
                    self._error(
                        f"field {class_.name}.{field.name} cannot own a List",
                        field.span,
                        code="C247",
                        note="store a pointer or reference; aggregate List ownership is not implemented",
                    )
                if self._contains_destructible_value(field.type):
                    self._error(
                        f"field {class_.name}.{field.name} contains a class with a destructor",
                        field.span,
                        code="C221",
                        note="use a pointer/reference field or manage the nested lifetime explicitly",
                    )

        for union in self.unions.values():
            for field in union.fields.values():
                self._validate_list_elements(field.type, field.span)
                if self._contains_list_value(field.type):
                    self._error(
                        f"union field {union.name}.{field.name} cannot own a List",
                        field.span,
                        code="C247",
                    )
                if self._contains_destructible_value(field.type):
                    self._error(
                        f"union field {union.name}.{field.name} contains a class with a destructor",
                        field.span,
                        code="C222",
                    )

        for variant in self.variants.values():
            for case in variant.cases.values():
                for field in case.fields.values():
                    self._validate_list_elements(field.type, field.span)
                    if self._contains_list_value(field.type):
                        self._error(
                            f"variant payload {variant.name}.{case.name}.{field.name} "
                            "cannot own a List",
                            field.span,
                            code="C247",
                        )
                    if self._contains_destructible_value(field.type):
                        self._error(
                            f"variant payload {variant.name}.{case.name}.{field.name} "
                            "contains a class with a destructor",
                            field.span,
                            code="C223",
                        )

        for global_ in self.globals.values():
            self._validate_list_elements(global_.type, global_.span)
            if self._contains_list_value(global_.type):
                self._error(
                    f"global {global_.name!r} cannot own a List",
                    global_.span,
                    code="C248",
                    note="portable C11 has no automatic global destruction phase",
                )
            if self._contains_destructible_value(global_.type):
                self._error(
                    f"global {global_.name!r} cannot own a class with a destructor",
                    global_.span,
                    code="C224",
                    note="portable C11 has no automatic global destruction phase",
                )

        functions: list[FunctionSymbol] = [*self.functions.values()]
        for struct in self.structs.values():
            functions.extend(struct.methods.values())
        for class_ in self.classes.values():
            functions.extend(class_.methods.values())

        for function in functions:
            for parameter in function.parameters:
                self._validate_list_elements(parameter.type, parameter.span)
                if self._owned_list(parameter.type) is not None:
                    self._error(
                        f"parameter {function.name}.{parameter.name} cannot own a List by value",
                        parameter.span,
                        code="C249",
                        note="pass List values by reference or pointer",
                    )
                elif self._contains_list_value(parameter.type):
                    self._error(
                        f"parameter {function.name}.{parameter.name} contains an owning List",
                        parameter.span,
                        code="C290",
                        note=(
                            "aggregate List ownership is not implemented; "
                            "pass the value by reference or pointer"
                        ),
                    )
                if self._destructible_class(parameter.type) is not None:
                    self._error(
                        f"parameter {function.name}.{parameter.name} cannot own a "
                        "destructor-bearing class by value",
                        parameter.span,
                        code="C225",
                        note="pass the class by reference, pointer, or &dyn interface",
                    )
                elif self._contains_destructible_value(parameter.type):
                    self._error(
                        f"parameter {function.name}.{parameter.name} contains a "
                        "class with a destructor",
                        parameter.span,
                        code="C225",
                        note="aggregate ownership of destructor-bearing classes is not implemented",
                    )
            self._validate_list_elements(function.return_type, function.span)
            return_list = self._owned_list(function.return_type)
            if return_list is None and self._contains_list_value(
                function.return_type
            ):
                self._error(
                    f"return type {type_name(function.return_type)} contains an owning List",
                    function.span,
                    code="C250",
                    note="only a direct List return currently transfers ownership",
                )
            return_class = self._destructible_class(function.return_type)
            if (
                return_class is None
                and self._contains_destructible_value(function.return_type)
            ):
                self._error(
                    f"return type {type_name(function.return_type)} contains a class "
                    "with a destructor",
                    function.span,
                    code="C226",
                    note="only a direct class return currently transfers ownership",
                )

    def _validate_list_elements(self, type_: Type, span: Span) -> None:
        raw = strip_const(type_)
        if isinstance(raw, (PointerType, ReferenceType, SliceType)):
            self._validate_list_elements(raw.inner, span)
            return
        if isinstance(raw, DynType):
            return
        if isinstance(raw, ListType):
            if self._contains_list_value(raw.inner):
                self._error(
                    f"List element type {type_name(raw.inner)} owns another List",
                    span,
                    code="C251",
                    note="nested owning containers are not implemented",
                )
            if self._contains_destructible_value(raw.inner):
                self._error(
                    f"List element type {type_name(raw.inner)} contains a class with a destructor",
                    span,
                    code="C252",
                    note="List currently supports only trivially copyable element values",
                )
            return
        if isinstance(raw, ArrayType):
            self._validate_list_elements(raw.inner, span)
            return
        if isinstance(raw, TupleType):
            for element in raw.elements:
                self._validate_list_elements(element, span)
            return
        if isinstance(raw, ResultType):
            self._validate_list_elements(raw.ok, span)
            self._validate_list_elements(raw.error, span)

    def _destructible_class(self, type_: Type) -> ClassSymbol | None:
        raw = strip_const(type_)
        if not isinstance(raw, ClassType):
            return None
        class_ = self.classes_by_type.get(raw)
        if class_ is None or not self._class_has_destructor(class_):
            return None
        return class_

    def _contains_destructible_value(
        self,
        type_: Type,
        seen: set[Type] | None = None,
    ) -> bool:
        raw = strip_const(type_)
        if isinstance(raw, (PointerType, ReferenceType, SliceType, DynType)):
            return False
        if self._destructible_class(raw) is not None:
            return True
        if isinstance(raw, ArrayType):
            return self._contains_destructible_value(raw.inner, seen)
        if isinstance(raw, ListType):
            return self._contains_destructible_value(raw.inner, seen)
        if isinstance(raw, TupleType):
            return any(
                self._contains_destructible_value(element, seen)
                for element in raw.elements
            )
        if isinstance(raw, ResultType):
            return self._contains_destructible_value(
                raw.ok,
                seen,
            ) or self._contains_destructible_value(raw.error, seen)
        return False

    def _owned_list(self, type_: Type) -> ListType | None:
        raw = strip_const(type_)
        return raw if isinstance(raw, ListType) else None

    def _contains_list_value(self, type_: Type) -> bool:
        raw = strip_const(type_)
        if isinstance(raw, (PointerType, ReferenceType, SliceType, DynType)):
            return False
        if isinstance(raw, ListType):
            return True
        if isinstance(raw, ArrayType):
            return self._contains_list_value(raw.inner)
        if isinstance(raw, TupleType):
            return any(self._contains_list_value(element) for element in raw.elements)
        if isinstance(raw, ResultType):
            return self._contains_list_value(raw.ok) or self._contains_list_value(
                raw.error
            )
        return False

    def _is_owned_class_source(
        self,
        expression: ast.Expression,
        class_: ClassSymbol,
    ) -> bool:
        expression_type = value_type(self.expr_types.get(id(expression), ERROR))
        return isinstance(expression, ast.CallExpr) and expression_type == class_.type

    def _is_owned_list_source(
        self,
        expression: ast.Expression,
        list_type: ListType,
    ) -> bool:
        expression_type = value_type(self.expr_types.get(id(expression), ERROR))
        return expression_type == list_type and isinstance(
            expression,
            (ast.ListLiteralExpr, ast.CallExpr),
        )

    def _is_transferable_local(
        self,
        expression: ast.Expression,
        class_: ClassSymbol,
    ) -> bool:
        if not isinstance(expression, ast.NameExpr):
            return False
        symbol = self.name_symbols.get(id(expression))
        if not isinstance(symbol, VariableSymbol) or symbol.is_parameter:
            return False
        if value_type(symbol.type) != class_.type:
            return False
        return not any(symbol is global_ for global_ in self.globals.values())

    def _is_transferable_list_local(
        self,
        expression: ast.Expression,
        list_type: ListType,
    ) -> bool:
        if not isinstance(expression, ast.NameExpr):
            return False
        symbol = self.name_symbols.get(id(expression))
        if not isinstance(symbol, VariableSymbol) or symbol.is_parameter:
            return False
        if value_type(symbol.type) != list_type:
            return False
        return not any(symbol is global_ for global_ in self.globals.values())

    def _validate_borrow_source(
        self,
        target: Type,
        source: Type,
        expression: ast.Expression,
    ) -> None:
        target_raw = strip_const(target)
        source_raw = strip_const(source)
        if (
            isinstance(target_raw, DynType)
            and not isinstance(source_raw, DynType)
            and self._class_value_info(source_raw)[0] is not None
            and not self._is_addressable(expression)
        ):
            self._error(
                "concrete-to-dyn conversion requires an addressable object",
                expression.span,
                code="C238",
                note="bind the class value to a local before borrowing it as &dyn",
            )

    def _make_function_symbol(
        self,
        declaration: ast.FunctionDecl,
        owner: StructSymbol | ClassSymbol | None,
    ) -> FunctionSymbol:
        parameters: list[ParameterSymbol] = []
        variadic = False
        for index, parameter in enumerate(declaration.parameters):
            if parameter.is_variadic:
                variadic = True
                continue
            if parameter.annotation is None:
                if owner is not None and index == 0 and parameter.name == "self":
                    if (
                        isinstance(owner, ClassSymbol)
                        and owner.is_abstract
                        and declaration.name not in ("__init__", "__del__")
                    ):
                        parameter_type = DynType(owner.type)
                    else:
                        parameter_type = ReferenceType(owner.type)
                else:
                    self._error(
                        f"parameter {parameter.name!r} requires a type annotation",
                        parameter.span,
                        code="C012",
                    )
                    parameter_type = ERROR
            else:
                parameter_type = self._resolve_type(
                    parameter.annotation,
                    allow_opaque=declaration.is_extern,
                )
            if is_void(parameter_type):
                self._error(
                    f"parameter {parameter.name!r} cannot have type void",
                    parameter.span,
                    code="C013",
                )
                parameter_type = ERROR
            parameters.append(ParameterSymbol(parameter.name, parameter_type, parameter.span, False))

        if owner is not None:
            if not parameters or parameters[0].name != "self":
                self._error(
                    f"method {owner.name}.{declaration.name} must declare self as its first parameter",
                    declaration.span,
                    code="C014",
                )
            elif not self._self_type_matches(parameters[0].type, owner.type):
                self._error(
                    f"self parameter must refer to {owner.name}, not {type_name(parameters[0].type)}",
                    parameters[0].span,
                    code="C015",
                )

        return_type = (
            VOID
            if declaration.return_type is None
            else self._resolve_type(declaration.return_type, allow_opaque=declaration.is_extern)
        )
        if isinstance(return_type, (ArrayType, ReferenceType, DynType)):
            self._error(
                f"functions cannot return {type_name(return_type)}",
                declaration.return_type.span if declaration.return_type else declaration.span,
                code="C016",
                note="return a pointer, slice, result, or owned nominal value instead",
            )
            return_type = ERROR

        if declaration.is_extern:
            c_name = declaration.name
        elif owner is not None:
            c_name = f"{owner.c_name}_{declaration.name}"
        elif declaration.name == "main" or declaration.is_exported:
            c_name = declaration.name
        else:
            c_name = self._c_value_name(declaration.name)
        return FunctionSymbol(
            name=declaration.name,
            span=declaration.span,
            kind=SymbolKind.FUNCTION,
            parameters=parameters,
            return_type=return_type,
            c_name=c_name,
            declaration=declaration,
            owner=owner.name if owner else None,
            is_extern=declaration.is_extern,
            is_exported=declaration.is_exported,
            is_variadic=variadic,
            module=self.module_name if self.module_mode else None,
            is_module_public=self.module_mode and not declaration.is_extern,
            owner_class=owner if isinstance(owner, ClassSymbol) else None,
        )

    def _c_type_name(self, name: str) -> str:
        return f"{self.c_prefix}{name}" if self.c_prefix else name

    def _c_value_name(self, name: str) -> str:
        return f"{self.c_prefix}{name}" if self.c_prefix else name

    def _self_type_matches(self, self_type: Type, owner_type: Type) -> bool:
        if isinstance(self_type, DynType):
            return self_type.interface == owner_type
        if isinstance(self_type, (ReferenceType, PointerType)):
            return strip_const(self_type.inner) == owner_type
        return strip_const(self_type) == owner_type

    def _can_assign(self, target: Type, source: Type) -> bool:
        if can_assign(target, source):
            return True

        if isinstance(target, DynType):
            if isinstance(source, DynType):
                return (
                    target.interface == source.interface
                    and (target.is_const or not source.is_const)
                )
            source_class, source_is_const = self._class_value_info(source)
            interface = self.classes_by_type.get(target.interface)
            if source_class is None or interface is None:
                return False
            return (
                self._class_implements(source_class, interface)
                and (target.is_const or not source_is_const)
            )

        target_raw = strip_const(target)
        source_raw = strip_const(source)
        if isinstance(target_raw, (ReferenceType, PointerType)):
            target_inner = strip_const(target_raw.inner)
            if not isinstance(target_inner, ClassType):
                return False
            target_class = self.classes_by_type.get(target_inner)
            source_class, source_is_const = self._class_value_info(source_raw)
            if target_class is None or source_class is None:
                return False
            target_accepts_const = isinstance(target_raw.inner, ConstType)
            if source_is_const and not target_accepts_const:
                return False
            return self._is_primary_subclass(source_class, target_class)

        return False

    def _class_value_info(self, type_: Type) -> tuple[ClassSymbol | None, bool]:
        outer_const = isinstance(type_, ConstType)
        raw = strip_const(type_)
        if isinstance(raw, (ReferenceType, PointerType)):
            inner_const = isinstance(raw.inner, ConstType)
            inner = strip_const(raw.inner)
            if isinstance(inner, ClassType):
                return self.classes_by_type.get(inner), outer_const or inner_const
            return None, False
        if isinstance(raw, ClassType):
            return self.classes_by_type.get(raw), outer_const
        return None, False

    @staticmethod
    def _is_primary_subclass(class_: ClassSymbol, base: ClassSymbol) -> bool:
        current: ClassSymbol | None = class_
        while current is not None:
            if current.type == base.type:
                return True
            current = current.primary_base
        return False

    def _class_implements(self, class_: ClassSymbol, interface: ClassSymbol) -> bool:
        if class_.type == interface.type:
            return True
        return any(
            candidate.type == interface.type
            for candidate in self._implemented_interfaces(class_)
        )

    def _lookup_class_field(
        self,
        class_: ClassSymbol,
        name: str,
    ) -> tuple[FieldSymbol, ClassSymbol, tuple[str, ...]] | None:
        field = class_.fields.get(name)
        if field is not None:
            return field, class_, ()
        if class_.primary_base is None:
            return None
        inherited = self._lookup_class_field(class_.primary_base, name)
        if inherited is None:
            return None
        field, owner, path = inherited
        return field, owner, ("_base", *path)

    @staticmethod
    def _lookup_class_method(
        class_: ClassSymbol,
        name: str,
    ) -> FunctionSymbol | None:
        return class_.interface_methods.get(name) or class_.methods.get(name)

    @staticmethod
    def _class_has_destructor(class_: ClassSymbol) -> bool:
        current: ClassSymbol | None = class_
        while current is not None:
            if current.destructor is not None:
                return True
            current = current.primary_base
        return False

    def _check_struct_layouts(self) -> None:
        aggregates: dict[Type, tuple[str, Span, list[FieldSymbol]]] = {}
        for symbol in self.structs.values():
            aggregates[symbol.type] = (symbol.name, symbol.span, list(symbol.fields.values()))
        for symbol in self.classes.values():
            fields = list(symbol.fields.values())
            if symbol.primary_base is not None:
                fields = [
                    FieldSymbol(
                        "_base",
                        symbol.span,
                        SymbolKind.VARIABLE,
                        symbol.primary_base.type,
                        True,
                        symbol.name,
                    ),
                    *fields,
                ]
            aggregates[symbol.type] = (symbol.name, symbol.span, fields)
        for symbol in self.unions.values():
            aggregates[symbol.type] = (symbol.name, symbol.span, list(symbol.fields.values()))
        for symbol in self.variants.values():
            fields = [field for case in symbol.cases.values() for field in case.fields.values()]
            aggregates[symbol.type] = (symbol.name, symbol.span, fields)

        visiting: set[Type] = set()
        visited: set[Type] = set()

        def visit(type_: Type, path: list[str]) -> None:
            if type_ in visited:
                return
            entry = aggregates.get(type_)
            if entry is None:
                return
            name, span, fields = entry
            if type_ in visiting:
                cycle = " -> ".join([*path, name])
                self._error(
                    f"recursive by-value aggregate layout: {cycle}",
                    span,
                    code="C017",
                    note="use a pointer, reference, or slice to break the cycle",
                )
                return
            visiting.add(type_)
            for field in fields:
                for dependency in self._by_value_aggregate_types(field.type):
                    visit(dependency, [*path, name])
            visiting.remove(type_)
            visited.add(type_)

        for type_ in aggregates:
            visit(type_, [])

    def _by_value_aggregate_types(self, type_: Type) -> set[Type]:
        type_ = strip_const(type_)
        if isinstance(type_, (StructType, ClassType, UnionType, VariantType)):
            return {type_}
        if isinstance(type_, ArrayType):
            return self._by_value_aggregate_types(type_.inner)
        if isinstance(type_, TupleType):
            result: set[Type] = set()
            for element in type_.elements:
                result.update(self._by_value_aggregate_types(element))
            return result
        if isinstance(type_, ResultType):
            return {
                *self._by_value_aggregate_types(type_.ok),
                *self._by_value_aggregate_types(type_.error),
            }
        return set()

    def _check_global_initializers(self) -> None:
        previous_scope = self.current_scope
        self.current_scope = self.global_scope
        try:
            for declaration in self.module.globals:
                symbol = self.global_symbols.get(id(declaration))
                if symbol is None or declaration.initializer is None:
                    continue
                initializer_type = self._check_expr(declaration.initializer, expected=symbol.type)
                if not self._can_assign(symbol.type, initializer_type):
                    self._type_mismatch(symbol.type, initializer_type, declaration.initializer.span)
                if not self._is_constant_expression(declaration.initializer):
                    self._error(
                        "global initializer must be a C constant expression",
                        declaration.initializer.span,
                        code="C018",
                    )
        finally:
            self.current_scope = previous_scope

    def _check_functions(self) -> None:
        for struct in self.structs.values():
            for method in struct.methods.values():
                self._check_function(method, struct)
        for class_ in self.classes.values():
            for method in class_.methods.values():
                if not method.is_abstract:
                    self._check_function(method, class_)
        for function in self.functions.values():
            if not function.is_extern:
                self._check_function(function, None)

    def _check_function(
        self,
        function: FunctionSymbol,
        owner: StructSymbol | ClassSymbol | None,
    ) -> None:
        declaration = function.declaration
        if declaration is None or declaration.body is None:
            return

        previous_scope = self.current_scope
        previous_function = self.current_function
        previous_owner = self.current_owner
        scope = Scope(self.global_scope)
        self.current_scope = scope
        self.current_function = function
        self.current_owner = owner
        try:
            for parameter in function.parameters:
                symbol = VariableSymbol(
                    parameter.name,
                    parameter.span,
                    SymbolKind.VARIABLE,
                    parameter.type,
                    False,
                    True,
                    parameter.name,
                )
                previous = scope.declare(symbol)
                if previous is not None:
                    self._error(
                        f"duplicate parameter {parameter.name!r}",
                        parameter.span,
                        code="C019",
                    )
            self._check_block(declaration.body, scope, create_scope=False)
            if not is_void(function.return_type) and not self._block_always_returns(declaration.body):
                self._error(
                    f"function {function.name!r} may reach the end without returning {type_name(function.return_type)}",
                    declaration.span,
                    code="C020",
                )
        finally:
            self.current_scope = previous_scope
            self.current_function = previous_function
            self.current_owner = previous_owner

    def _check_main(self) -> None:
        main = self.functions.get("main")
        if main is None:
            return
        if not self.is_entry:
            self._error(
                "only the project entry module may define main",
                main.span,
                code="C118",
            )
            return
        if main.return_type not in (I32, PRIMITIVES["c_int"]):
            self._error("main must return i32 or c_int", main.span, code="C021")
        parameters = main.parameters
        if not parameters:
            return
        valid = (
            len(parameters) == 2
            and parameters[0].type in (I32, PRIMITIVES["c_int"])
            and isinstance(parameters[1].type, PointerType)
            and isinstance(parameters[1].type.inner, PointerType)
            and strip_const(parameters[1].type.inner.inner) == CHAR
        )
        if not valid:
            self._error(
                "main parameters must be empty or (argc: i32, argv: **char)",
                main.span,
                code="C022",
            )

    def _check_static_asserts(self) -> None:
        previous_scope = self.current_scope
        self.current_scope = self.global_scope
        try:
            for declaration in self.module.static_asserts:
                condition_type = self._check_expr(declaration.condition, expected=BOOL)
                if not is_condition_type(value_type(condition_type)):
                    self._error(
                        "static_assert condition must be scalar",
                        declaration.condition.span,
                        code="C212",
                    )
                    continue
                if not self._is_comptime_expression(declaration.condition):
                    self._error(
                        "static_assert condition is not a compile-time expression",
                        declaration.condition.span,
                        code="C213",
                    )
                    continue
                value = self._eval_comptime_expression(declaration.condition)
                if value is not None and not bool(value):
                    self._error(
                        declaration.message or "static assertion failed",
                        declaration.condition.span,
                        code="C214",
                    )
                    self.static_assert_values[id(declaration)] = False
                elif value is None:
                    self.static_assert_values[id(declaration)] = None
                else:
                    self.static_assert_values[id(declaration)] = True
        finally:
            self.current_scope = previous_scope

    def _is_comptime_expression(self, expression: ast.Expression) -> bool:
        if isinstance(expression, ast.LiteralExpr):
            return True
        if isinstance(expression, ast.UnaryExpr):
            return self._is_comptime_expression(expression.operand)
        if isinstance(expression, ast.BinaryExpr):
            return self._is_comptime_expression(expression.left) and self._is_comptime_expression(
                expression.right
            )
        if isinstance(expression, ast.CastExpr):
            return self._is_comptime_expression(expression.value)
        if isinstance(expression, ast.CallExpr):
            resolution = self.call_resolutions.get(id(expression))
            return resolution is not None and resolution.kind in {
                "compile_bool",
                "compile_integer",
                "compile_string",
                "size_of",
                "align_of",
                "type_of",
            }
        if isinstance(expression, ast.NameExpr):
            symbol = self.name_symbols.get(id(expression))
            return isinstance(symbol, ConstantSymbol)
        if isinstance(expression, ast.AttributeExpr):
            resolution = self.attribute_resolutions.get(id(expression))
            return resolution is not None and resolution.kind in {
                "module_constant",
                "enum_member",
            }
        return False

    def _eval_comptime_expression(self, expression: ast.Expression) -> object | None:
        if isinstance(expression, ast.LiteralExpr):
            return expression.value
        if isinstance(expression, ast.UnaryExpr):
            value = self._eval_comptime_expression(expression.operand)
            if value is None:
                return None
            if expression.operator == "not":
                return not bool(value)
            if expression.operator == "+":
                return +value  # type: ignore[operator]
            if expression.operator == "-":
                return -value  # type: ignore[operator]
            if expression.operator == "~":
                return ~value  # type: ignore[operator]
            return None
        if isinstance(expression, ast.BinaryExpr):
            left = self._eval_comptime_expression(expression.left)
            right = self._eval_comptime_expression(expression.right)
            if left is None or right is None:
                return None
            operator = expression.operator
            try:
                return {
                    "and": lambda: bool(left) and bool(right),
                    "or": lambda: bool(left) or bool(right),
                    "==": lambda: left == right,
                    "!=": lambda: left != right,
                    "<": lambda: left < right,  # type: ignore[operator]
                    "<=": lambda: left <= right,  # type: ignore[operator]
                    ">": lambda: left > right,  # type: ignore[operator]
                    ">=": lambda: left >= right,  # type: ignore[operator]
                    "+": lambda: left + right,  # type: ignore[operator]
                    "-": lambda: left - right,  # type: ignore[operator]
                    "*": lambda: left * right,  # type: ignore[operator]
                    "/": lambda: left / right,  # type: ignore[operator]
                    "%": lambda: left % right,  # type: ignore[operator]
                    "&": lambda: left & right,  # type: ignore[operator]
                    "|": lambda: left | right,  # type: ignore[operator]
                    "^": lambda: left ^ right,  # type: ignore[operator]
                    "<<": lambda: left << right,  # type: ignore[operator]
                    ">>": lambda: left >> right,  # type: ignore[operator]
                }[operator]()
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                return None
        if isinstance(expression, ast.CastExpr):
            return self._eval_comptime_expression(expression.value)
        if isinstance(expression, ast.CallExpr):
            resolution = self.call_resolutions.get(id(expression))
            if resolution is not None and resolution.kind in {
                "compile_bool",
                "compile_integer",
                "compile_string",
                "type_of",
            }:
                return resolution.compile_value
        return None

    def _check_block(self, block: ast.Block, scope: Scope, *, create_scope: bool = True) -> None:
        previous = self.current_scope
        active = Scope(scope) if create_scope else scope
        self.current_scope = active
        try:
            for statement in block.statements:
                self._check_statement(statement)
        finally:
            self.current_scope = previous

    def _check_statement(self, statement: ast.Statement) -> None:
        match statement:
            case ast.VarDeclStmt():
                self._check_var_decl(statement)
            case ast.AssignStmt():
                self._check_assignment(statement)
            case ast.ExpressionStmt(expression=expression):
                self._check_expr(expression)
                if not isinstance(expression, (ast.CallExpr, ast.AllocExpr, ast.PropagateExpr)):
                    self.diagnostics.warning(
                        "expression result is unused",
                        expression.span,
                        code="C023",
                    )
            case ast.ReturnStmt(value=value):
                self._check_return(statement, value)
            case ast.IfStmt(branches=branches, else_body=else_body):
                for branch_index, branch in enumerate(branches):
                    condition_type = self._check_expr(branch.condition)
                    if not is_condition_type(value_type(condition_type)):
                        self._error("if condition is not scalar", branch.condition.span, code="C024")
                    if branch_index > 0 and _contains_propagate(branch.condition):
                        self._error(
                            "'?' is not supported in elif conditions",
                            branch.condition.span,
                            code="C160",
                            note="evaluate the Result before the if statement",
                        )
                    self._check_block(branch.body, self.current_scope)
                if else_body is not None:
                    self._check_block(else_body, self.current_scope)
            case ast.WhileStmt(condition=condition, body=body):
                condition_type = self._check_expr(condition)
                if not is_condition_type(value_type(condition_type)):
                    self._error("while condition is not scalar", condition.span, code="C025")
                if _contains_propagate(condition):
                    self._error(
                        "'?' is not supported in while conditions",
                        condition.span,
                        code="C157",
                        note="evaluate the Result inside the loop body",
                    )
                self.loop_depth += 1
                try:
                    self._check_block(body, self.current_scope)
                finally:
                    self.loop_depth -= 1
            case ast.ForEachStmt():
                self._check_for_each(statement)
            case ast.ForCStmt():
                self._check_for_c(statement)
            case ast.MatchStmt():
                self._check_match(statement)
            case ast.BreakStmt():
                if self.loop_depth == 0:
                    self._error("break is only valid inside a loop", statement.span, code="C026")
            case ast.ContinueStmt():
                if self.loop_depth == 0:
                    self._error("continue is only valid inside a loop", statement.span, code="C027")
            case ast.PassStmt():
                pass
            case ast.DeferStmt(expression=expression):
                deferred_type = self._check_expr(expression)
                if not isinstance(expression, ast.CallExpr):
                    self._error("defer currently requires a function or method call", expression.span, code="C028")
                if isinstance(value_type(deferred_type), ListType):
                    self._error(
                        "cannot defer a call that returns an owning List",
                        expression.span,
                        code="C280",
                        note="bind the result to a local so deterministic cleanup can run",
                    )
                if _contains_propagate(expression):
                    self._error(
                        "'?' is not supported inside deferred calls",
                        expression.span,
                        code="C161",
                        note="propagate before registering the deferred cleanup",
                    )
            case ast.UnsafeStmt(body=body):
                self.unsafe_depth += 1
                try:
                    self._check_block(body, self.current_scope)
                finally:
                    self.unsafe_depth -= 1
            case _:
                raise AssertionError(f"unhandled statement: {statement!r}")

    def _check_var_decl(self, statement: ast.VarDeclStmt) -> None:
        declared_type = (
            self._resolve_type(statement.annotation)
            if statement.annotation is not None
            else None
        )
        initializer_type: Type | None = None
        if statement.initializer is not None:
            initializer_type = self._check_expr(statement.initializer, expected=declared_type)

        if declared_type is None:
            if initializer_type is None:
                self._error("inferred variable requires an initializer", statement.span, code="C029")
                declared_type = ERROR
            else:
                declared_type = self._inferred_storage_type(initializer_type, statement.initializer.span)
        elif initializer_type is not None and not self._can_assign(declared_type, initializer_type):
            self._type_mismatch(declared_type, initializer_type, statement.initializer.span)

        if is_void(declared_type):
            self._error("variables cannot have type void", statement.span, code="C030")
            declared_type = ERROR
        if isinstance(declared_type, ReferenceType):
            if statement.initializer is None:
                self._error("references require an initializer", statement.span, code="C031")
            elif not self._is_addressable(statement.initializer) and not isinstance(
                strip_const(initializer_type or ERROR), (ReferenceType, PointerType)
            ):
                self._error(
                    "reference initializer must be an addressable value",
                    statement.initializer.span,
                    code="C032",
                )
        if statement.is_const and statement.initializer is None:
            self._error("constants require an initializer", statement.span, code="C033")

        owned_list = self._owned_list(declared_type)
        destructible = self._destructible_class(declared_type)
        if owned_list is not None:
            self._validate_list_elements(owned_list, statement.span)
            if statement.initializer is None:
                self._error(
                    f"{type_name(owned_list)} requires an owning initializer",
                    statement.span,
                    code="C253",
                    note="initialize it with a list literal, including [] for an empty list",
                )
            elif not self._is_owned_list_source(statement.initializer, owned_list):
                self._error(
                    f"cannot copy move-only {type_name(owned_list)}",
                    statement.initializer.span,
                    code="C254",
                    note="initialize from a list literal or a List-returning call",
                )
            if statement.is_const or isinstance(declared_type, ConstType):
                self._error(
                    "List locals cannot be const",
                    statement.span,
                    code="C255",
                    note="borrow a List through &const List[T] for read-only access",
                )
        elif self._contains_list_value(declared_type):
            self._error(
                f"local type {type_name(declared_type)} contains an owning List",
                statement.span,
                code="C256",
            )
        elif destructible is not None:
            if statement.initializer is None:
                self._error(
                    f"{destructible.name} requires an owning initializer",
                    statement.span,
                    code="C227",
                    note="construct it or initialize it from a function that returns it by value",
                )
            elif not self._is_owned_class_source(statement.initializer, destructible):
                self._error(
                    f"cannot copy destructor-bearing class {destructible.name}",
                    statement.initializer.span,
                    code="C228",
                    note="destructor-bearing class values are move-only",
                )
            if statement.is_const:
                self._error(
                    "destructor-bearing class locals cannot be const",
                    statement.span,
                    code="C229",
                )
        elif self._contains_destructible_value(declared_type):
            self._error(
                f"local type {type_name(declared_type)} contains a class with a destructor",
                statement.span,
                code="C230",
            )

        if statement.initializer is not None and initializer_type is not None:
            self._validate_borrow_source(
                declared_type,
                initializer_type,
                statement.initializer,
            )

        symbol = VariableSymbol(
            statement.name,
            statement.span,
            SymbolKind.VARIABLE,
            declared_type,
            statement.is_const,
            False,
            statement.name,
        )
        previous = self.current_scope.declare(symbol)
        if previous is not None:
            self._duplicate_symbol(symbol, previous)
        self.declaration_symbols[id(statement)] = symbol

    def _inferred_storage_type(self, type_: Type, span: Span) -> Type:
        if isinstance(type_, ReferenceType):
            return type_.inner
        if isinstance(
            type_,
            (
                FunctionValueType,
                ModuleType,
                RangeType,
                TypeValueType,
                ComptimeCollectionType,
                ComptimeItemType,
            ),
        ) or type_ in (NULL, VOID):
            self._error(
                f"cannot infer a variable type from {type_name(type_)}",
                span,
                code="C034",
            )
            return ERROR
        return strip_const(type_)

    def _check_assignment(self, statement: ast.AssignStmt) -> None:
        if (
            statement.operator == "="
            and isinstance(statement.target, ast.NameExpr)
            and self.current_scope.lookup(statement.target.name) is None
        ):
            value_type_ = self._check_expr(statement.value)
            inferred = self._inferred_storage_type(value_type_, statement.value.span)
            symbol = VariableSymbol(
                statement.target.name,
                statement.target.span,
                SymbolKind.VARIABLE,
                inferred,
                False,
                False,
                statement.target.name,
            )
            self.current_scope.declare(symbol)
            self.name_symbols[id(statement.target)] = symbol
            self.expr_types[id(statement.target)] = symbol.type
            self.implicit_declarations[id(statement)] = symbol
            owned_list = self._owned_list(inferred)
            destructible = self._destructible_class(inferred)
            if owned_list is not None:
                self._validate_list_elements(owned_list, statement.value.span)
                if not self._is_owned_list_source(statement.value, owned_list):
                    self._error(
                        f"cannot copy move-only {type_name(owned_list)}",
                        statement.value.span,
                        code="C257",
                    )
            elif self._contains_list_value(inferred):
                self._error(
                    f"inferred type {type_name(inferred)} contains an owning List",
                    statement.value.span,
                    code="C258",
                )
            elif destructible is not None:
                if not self._is_owned_class_source(
                    statement.value,
                    destructible,
                ):
                    self._error(
                        f"cannot copy destructor-bearing class {destructible.name}",
                        statement.value.span,
                        code="C231",
                        note="initialize from a constructor or class-returning call",
                    )
            elif self._contains_destructible_value(inferred):
                self._error(
                    f"inferred type {type_name(inferred)} contains a class with a destructor",
                    statement.value.span,
                    code="C232",
                )
            return

        target_type, assignable, is_const_target = self._check_lvalue(statement.target)
        value_type_ = self._check_expr(statement.value, expected=target_type)
        if not assignable:
            self._error("assignment target is not assignable", statement.target.span, code="C035")
        if is_const_target:
            self._error("cannot assign to a constant value", statement.target.span, code="C036")

        effective_target = strip_reference(target_type)
        owned_list = self._owned_list(effective_target)
        destructible = self._destructible_class(effective_target)
        if owned_list is not None:
            if self._list_storage_is_active(statement.target):
                self._error(
                    "cannot replace a List while iterating over it",
                    statement.target.span,
                    code="C284",
                )
            if statement.operator != "=":
                self._error(
                    f"compound assignment is invalid for {type_name(owned_list)}",
                    statement.span,
                    code="C259",
                )
            if not isinstance(statement.target, ast.NameExpr):
                self._error(
                    "List assignment requires a direct local variable",
                    statement.target.span,
                    code="C260",
                )
            if not self._is_owned_list_source(statement.value, owned_list):
                self._error(
                    f"cannot copy move-only {type_name(owned_list)}",
                    statement.value.span,
                    code="C261",
                    note="assign a fresh list literal or a List-returning call",
                )
        elif self._contains_list_value(effective_target):
            self._error(
                f"assignment target {type_name(effective_target)} contains an owning List",
                statement.target.span,
                code="C262",
            )
        elif destructible is not None:
            if statement.operator != "=":
                self._error(
                    f"compound assignment is invalid for class {destructible.name}",
                    statement.span,
                    code="C233",
                )
            if not isinstance(statement.target, ast.NameExpr):
                self._error(
                    "destructor-bearing class assignment requires a direct local variable",
                    statement.target.span,
                    code="C234",
                )
            if not self._is_owned_class_source(statement.value, destructible):
                self._error(
                    f"cannot copy destructor-bearing class {destructible.name}",
                    statement.value.span,
                    code="C235",
                    note="assign a fresh value returned by a constructor or function",
                )
        elif self._contains_destructible_value(effective_target):
            self._error(
                f"assignment target {type_name(effective_target)} contains a class with a destructor",
                statement.target.span,
                code="C236",
            )
        if isinstance(strip_const(effective_target), ArrayType):
            self._error("fixed arrays cannot be assigned after declaration", statement.target.span, code="C037")
        if statement.operator == "=":
            if not self._can_assign(effective_target, value_type_):
                self._type_mismatch(effective_target, value_type_, statement.value.span)
            self._validate_borrow_source(
                effective_target,
                value_type_,
                statement.value,
            )
            if isinstance(effective_target, ReferenceType) and value_type_ == NULL:
                self._error("references cannot be assigned null", statement.value.span, code="C038")
            return

        operator = statement.operator[:-1]
        if operator in ("+", "-", "*", "/", "%"):
            if not (is_numeric(value_type(effective_target)) and is_numeric(value_type(value_type_))):
                if not (
                    operator in ("+", "-")
                    and isinstance(strip_const(effective_target), PointerType)
                    and is_integer(value_type(value_type_))
                ):
                    self._error(
                        f"operator {statement.operator!r} requires numeric operands",
                        statement.span,
                        code="C039",
                    )
        else:
            if not (is_integer(value_type(effective_target)) and is_integer(value_type(value_type_))):
                self._error(
                    f"operator {statement.operator!r} requires integer operands",
                    statement.span,
                    code="C040",
                )

    def _check_lvalue(self, expression: ast.Expression) -> tuple[Type, bool, bool]:
        type_ = self._check_expr(expression)
        if isinstance(expression, ast.NameExpr):
            symbol = self.name_symbols.get(id(expression))
            if isinstance(symbol, VariableSymbol):
                return symbol.type, True, self._lvalue_is_const(expression)
            return type_, False, False
        if isinstance(expression, ast.AttributeExpr):
            resolution = self.attribute_resolutions.get(id(expression))
            if resolution and resolution.kind in (
                "field",
                "class_field",
                "dyn_field",
                "union_field",
                "module_global",
            ):
                return type_, True, self._lvalue_is_const(expression)
            return type_, False, False
        if isinstance(expression, ast.IndexExpr):
            base_type = value_type(
                self.expr_types.get(id(expression.value), ERROR)
            )
            if isinstance(base_type, TupleType):
                return type_, False, True
            return type_, True, self._lvalue_is_const(expression)
        if isinstance(expression, ast.UnaryExpr) and expression.operator == "*":
            return type_, True, self._lvalue_is_const(expression)
        return type_, False, False

    def _lvalue_is_const(self, expression: ast.Expression) -> bool:
        if isinstance(expression, ast.NameExpr):
            symbol = self.name_symbols.get(id(expression)) or self.current_scope.lookup(expression.name)
            if not isinstance(symbol, VariableSymbol):
                return False
            if symbol.is_const:
                return True
            return (
                isinstance(symbol.type, (ReferenceType, PointerType))
                and isinstance(symbol.type.inner, ConstType)
            )

        if isinstance(expression, ast.AttributeExpr):
            resolution = self.attribute_resolutions.get(id(expression))
            if resolution is not None and resolution.kind == "module_global":
                return resolution.global_ is not None and resolution.global_.is_const
            if (
                resolution is None
                or resolution.kind not in ("field", "class_field", "dyn_field", "union_field")
                or resolution.field is None
            ):
                return False
            if isinstance(resolution.field.type, ConstType):
                return True
            base_type = strip_const(self.expr_types.get(id(expression.value), ERROR))
            if isinstance(base_type, (PointerType, ReferenceType)):
                return isinstance(base_type.inner, ConstType)
            return self._lvalue_is_const(expression.value)

        if isinstance(expression, ast.IndexExpr):
            base_type = value_type(self.expr_types.get(id(expression.value), ERROR))
            if isinstance(base_type, (ArrayType, ListType)):
                return isinstance(base_type.inner, ConstType) or self._lvalue_is_const(expression.value)
            if isinstance(base_type, (SliceType, PointerType)):
                return isinstance(base_type.inner, ConstType)
            return isinstance(base_type, TupleType)

        if isinstance(expression, ast.UnaryExpr) and expression.operator == "*":
            operand_type = value_type(self.expr_types.get(id(expression.operand), ERROR))
            return (
                isinstance(operand_type, (PointerType, ReferenceType))
                and isinstance(operand_type.inner, ConstType)
            )

        return False

    def _check_return(self, statement: ast.ReturnStmt, value: ast.Expression | None) -> None:
        if self.current_function is None:
            self._error("return is only valid inside a function", statement.span, code="C041")
            return
        expected = self.current_function.return_type
        if value is None:
            if not is_void(expected):
                self._error(
                    f"expected a return value of type {type_name(expected)}",
                    statement.span,
                    code="C042",
                )
            return
        actual = self._check_expr(value, expected=expected)
        if is_void(expected):
            self._error("void function cannot return a value", value.span, code="C043")
        elif not self._can_assign(expected, actual):
            self._type_mismatch(expected, actual, value.span)
        destructible = self._destructible_class(expected)
        owned_list = self._owned_list(expected)
        if owned_list is not None and not (
            self._is_owned_list_source(value, owned_list)
            or self._is_transferable_list_local(value, owned_list)
        ):
            self._error(
                f"returning {type_name(owned_list)} would copy a move-only value",
                value.span,
                code="C263",
                note="return a fresh list, a List-returning call, or a direct local",
            )
        elif destructible is not None and not (
            self._is_owned_class_source(value, destructible)
            or self._is_transferable_local(value, destructible)
        ):
            self._error(
                f"returning {destructible.name} would copy a move-only class value",
                value.span,
                code="C237",
                note="return a freshly constructed value, a class-returning call, or a direct local",
            )

    def _check_for_each(self, statement: ast.ForEachStmt) -> None:
        iterable_type = self._check_expr(statement.iterable)
        if statement.is_comptime:
            if not isinstance(iterable_type, ComptimeCollectionType):
                self._error(
                    f"comptime iteration requires fields_of(...) or methods_of(...), got {type_name(iterable_type)}",
                    statement.iterable.span,
                    code="C208",
                )
                return
            if statement.annotation is not None:
                self._error(
                    "comptime iteration variables cannot have explicit annotations",
                    statement.annotation.span,
                    code="C209",
                )
            nominal = self.nominal_symbols.get(iterable_type.owner)
            if nominal is None:
                self._error("comptime collection has no nominal owner", statement.span, code="C210")
                return
            loop_scope = Scope(self.current_scope)
            symbol = ComptimeVariableSymbol(
                statement.name,
                statement.span,
                SymbolKind.CONSTANT,
                ComptimeItemType(iterable_type.kind, iterable_type.owner),
                nominal,
                iterable_type.kind,
                id(statement),
            )
            loop_scope.declare(symbol)
            self.comptime_foreach_symbols[id(statement)] = symbol
            self._check_block(statement.body, loop_scope, create_scope=True)
            return

        iterable_value = value_type(iterable_type)
        if isinstance(iterable_value, ListType) and not self._is_addressable(
            statement.iterable
        ):
            self._error(
                "List iteration requires an addressable List",
                statement.iterable.span,
                code="C277",
                note="bind the List to a local before iterating",
            )
        if isinstance(iterable_value, RangeType):
            item_type = iterable_value.inner
        elif isinstance(iterable_value, (ArrayType, SliceType, ListType)):
            item_type = iterable_value.inner
        else:
            self._error(
                f"cannot iterate over {type_name(iterable_type)}",
                statement.iterable.span,
                code="C044",
            )
            item_type = ERROR

        if statement.annotation is not None:
            declared = self._resolve_type(statement.annotation)
            if not self._can_assign(declared, item_type):
                self._type_mismatch(declared, item_type, statement.annotation.span)
            item_type = declared

        loop_scope = Scope(self.current_scope)
        symbol = VariableSymbol(
            statement.name,
            statement.span,
            SymbolKind.VARIABLE,
            strip_const(item_type),
            False,
            False,
            statement.name,
        )
        loop_scope.declare(symbol)
        self.foreach_symbols[id(statement)] = symbol
        iterator_storage = (
            self._list_storage(statement.iterable)
            if isinstance(iterable_value, ListType)
            else None
        )
        if iterator_storage is not None:
            self.active_list_iterators.append(iterator_storage)
        self.loop_depth += 1
        try:
            self._check_block(statement.body, loop_scope, create_scope=True)
        finally:
            self.loop_depth -= 1
            if iterator_storage is not None:
                popped = self.active_list_iterators.pop()
                assert popped[0] is iterator_storage[0] and popped[1] == iterator_storage[1]

    def _check_for_c(self, statement: ast.ForCStmt) -> None:
        loop_scope = Scope(self.current_scope)
        previous = self.current_scope
        self.current_scope = loop_scope
        self.loop_depth += 1
        try:
            if statement.initializer is not None:
                self._check_statement(statement.initializer)
                if self._for_clause_owns_list(statement.initializer):
                    self._error(
                        "C-style for initializers cannot own or replace a List",
                        statement.initializer.span,
                        code="C282",
                        note="declare the List before the loop",
                    )
            if statement.condition is not None:
                condition_type = self._check_expr(statement.condition)
                if not is_condition_type(value_type(condition_type)):
                    self._error("for condition is not scalar", statement.condition.span, code="C045")
                if _contains_propagate(statement.condition):
                    self._error(
                        "'?' is not supported in C-style for conditions",
                        statement.condition.span,
                        code="C158",
                        note="evaluate the Result inside the loop body",
                    )
            if statement.update is not None:
                if isinstance(
                    statement.update,
                    (
                        ast.ReturnStmt,
                        ast.IfStmt,
                        ast.WhileStmt,
                        ast.ForEachStmt,
                        ast.ForCStmt,
                    ),
                ):
                    self._error("invalid C-style for update", statement.update.span, code="C046")
                else:
                    self._check_statement(statement.update)
                    if self._for_clause_owns_list(statement.update):
                        self._error(
                            "C-style for updates cannot own or replace a List",
                            statement.update.span,
                            code="C283",
                            note="update the List inside the loop body",
                        )
                    if _statement_contains_propagate(statement.update):
                        self._error(
                            "'?' is not supported in C-style for updates",
                            statement.update.span,
                            code="C158",
                            note="evaluate the Result inside the loop body",
                        )
            self._check_block(statement.body, loop_scope, create_scope=True)
        finally:
            self.loop_depth -= 1
            self.current_scope = previous

    def _for_clause_owns_list(self, statement: ast.Statement) -> bool:
        if isinstance(statement, ast.VarDeclStmt):
            symbol = self.declaration_symbols.get(id(statement))
            return symbol is not None and self._owned_list(symbol.type) is not None
        if isinstance(statement, ast.AssignStmt):
            implicit = self.implicit_declarations.get(id(statement))
            if implicit is not None:
                return self._owned_list(implicit.type) is not None
            target_type = self.expr_types.get(id(statement.target), ERROR)
            return self._owned_list(strip_reference(target_type)) is not None
        if isinstance(statement, ast.ExpressionStmt):
            expression_type = self.expr_types.get(id(statement.expression), ERROR)
            return self._owned_list(expression_type) is not None
        return False

    def _check_match(self, statement: ast.MatchStmt) -> None:
        subject_type = value_type(self._check_expr(statement.value))
        nominal = self.nominal_symbols.get(subject_type)
        enum = nominal if isinstance(nominal, EnumSymbol) else None
        variant = nominal if isinstance(nominal, VariantSymbol) else None
        is_result = isinstance(subject_type, ResultType)

        if enum is None and variant is None and not is_result:
            self._error(
                f"match requires an enum, variant, or Result value, got {type_name(subject_type)}",
                statement.value.span,
                code="C119",
            )

        if enum is not None:
            required = set(enum.members)
        elif variant is not None:
            required = set(variant.cases)
        elif is_result:
            required = {"Ok", "Err"}
        else:
            required = set()

        seen: set[str] = set()
        wildcard_seen = False
        case_resolutions: list[MatchCaseResolution] = []

        for case_index, case in enumerate(statement.cases):
            pattern = case.pattern
            if pattern.is_wildcard:
                if wildcard_seen:
                    self._error("match contains more than one wildcard case", pattern.span, code="C120")
                if case_index != len(statement.cases) - 1:
                    self._error("wildcard match case must be last", pattern.span, code="C121")
                if pattern.bindings:
                    self._error("wildcard case cannot bind values", pattern.span, code="C122")
                wildcard_seen = True
                case_resolutions.append(MatchCaseResolution("wildcard"))
                self._check_block(case.body, self.current_scope)
                continue

            assert pattern.path is not None
            pattern_name = pattern.path[-1]
            if pattern_name in seen:
                self._error(f"duplicate match case {pattern_name!r}", pattern.span, code="C123")
            seen.add(pattern_name)
            case_scope = Scope(self.current_scope)
            bindings: list[PatternBinding] = []

            if enum is not None:
                self._validate_pattern_owner_type(pattern, subject_type)
                member = enum.members.get(pattern_name)
                if member is None:
                    self._error(
                        f"enum {enum.name!r} has no member {pattern_name!r}",
                        pattern.span,
                        code="C124",
                    )
                    case_resolutions.append(MatchCaseResolution("invalid"))
                else:
                    if pattern.bindings:
                        self._error("enum match cases cannot bind payload values", pattern.span, code="C125")
                    case_resolutions.append(MatchCaseResolution("enum", enum_member=member))

            elif variant is not None:
                self._validate_pattern_owner_type(pattern, subject_type)
                variant_case = variant.cases.get(pattern_name)
                if variant_case is None:
                    self._error(
                        f"variant {variant.name!r} has no case {pattern_name!r}",
                        pattern.span,
                        code="C126",
                    )
                    case_resolutions.append(MatchCaseResolution("invalid"))
                else:
                    fields = list(variant_case.fields.values())
                    if len(pattern.bindings) != len(fields):
                        self._error(
                            f"case {variant.name}.{variant_case.name} expects {len(fields)} bindings, "
                            f"got {len(pattern.bindings)}",
                            pattern.span,
                            code="C127",
                        )
                    for index, binding_name in enumerate(pattern.bindings):
                        binding_type = fields[index].type if index < len(fields) else ERROR
                        symbol = VariableSymbol(
                            binding_name,
                            pattern.span,
                            SymbolKind.VARIABLE,
                            binding_type,
                            True,
                            False,
                            binding_name,
                        )
                        previous = case_scope.declare(symbol)
                        if previous is not None:
                            self._duplicate_symbol(symbol, previous)
                        field_name = fields[index].name if index < len(fields) else binding_name
                        bindings.append(PatternBinding(symbol, field_name))
                    case_resolutions.append(
                        MatchCaseResolution(
                            "variant",
                            variant_case=variant_case,
                            bindings=tuple(bindings),
                        )
                    )

            elif isinstance(subject_type, ResultType):
                self._validate_result_pattern_owner(pattern)
                if pattern_name not in {"Ok", "Err"}:
                    self._error(
                        "Result match cases must be Ok or Err",
                        pattern.span,
                        code="C128",
                    )
                    case_resolutions.append(MatchCaseResolution("invalid"))
                else:
                    is_ok = pattern_name == "Ok"
                    payload_type = subject_type.ok if is_ok else subject_type.error
                    expected_bindings = 0 if is_void(payload_type) else 1
                    if len(pattern.bindings) != expected_bindings:
                        self._error(
                            f"{pattern_name} expects {expected_bindings} bindings, got {len(pattern.bindings)}",
                            pattern.span,
                            code="C129",
                        )
                    if pattern.bindings:
                        binding_name = pattern.bindings[0]
                        symbol = VariableSymbol(
                            binding_name,
                            pattern.span,
                            SymbolKind.VARIABLE,
                            payload_type,
                            True,
                            False,
                            binding_name,
                        )
                        previous = case_scope.declare(symbol)
                        if previous is not None:
                            self._duplicate_symbol(symbol, previous)
                        bindings.append(PatternBinding(symbol, "value" if is_ok else "error"))
                    case_resolutions.append(
                        MatchCaseResolution(
                            "result",
                            result_is_ok=is_ok,
                            bindings=tuple(bindings),
                        )
                    )
            else:
                case_resolutions.append(MatchCaseResolution("invalid"))

            self._check_block(case.body, case_scope, create_scope=False)

        missing = required - seen
        exhaustive = wildcard_seen or not missing
        if required and not exhaustive:
            self._error(
                "non-exhaustive match; missing " + ", ".join(sorted(missing)),
                statement.span,
                code="C130",
            )
        self.match_resolutions[id(statement)] = MatchResolution(
            subject_type,
            tuple(case_resolutions),
            exhaustive,
        )

    def _validate_pattern_owner_type(
        self,
        pattern: ast.MatchPattern,
        subject_type: Type,
    ) -> None:
        if pattern.path is None or len(pattern.path) < 2:
            return
        owner_name = ".".join(pattern.path[:-1])
        owner_type = self.types.get(owner_name)
        if owner_type is None:
            self._error(
                f"unknown pattern owner {owner_name!r}",
                pattern.span,
                code="C142",
            )
            return
        if owner_type != subject_type:
            self._error(
                f"pattern owner {owner_name!r} has type {type_name(owner_type)}, "
                f"not {type_name(subject_type)}",
                pattern.span,
                code="C143",
            )

    def _validate_result_pattern_owner(self, pattern: ast.MatchPattern) -> None:
        if pattern.path is None or len(pattern.path) < 2:
            return
        owner_name = ".".join(pattern.path[:-1])
        if owner_name != "Result":
            self._error(
                f"Result pattern owner must be 'Result', not {owner_name!r}",
                pattern.span,
                code="C142",
            )

    def _check_expr(self, expression: ast.Expression, expected: Type | None = None) -> Type:
        match expression:
            case ast.LiteralExpr():
                result = self._check_literal(expression, expected)
            case ast.FStringExpr():
                result = self._check_fstring_outside_print(expression)
            case ast.NameExpr():
                result = self._check_name(expression)
            case ast.UnaryExpr():
                result = self._check_unary(expression)
            case ast.BinaryExpr():
                result = self._check_binary(expression)
            case ast.AttributeExpr():
                result = self._check_attribute(expression)
            case ast.IndexExpr():
                result = self._check_index(expression)
            case ast.SliceExpr():
                result = self._check_slice(expression)
            case ast.CallExpr():
                result = self._check_call(expression, expected)
            case ast.PropagateExpr():
                result = self._check_propagate(expression)
            case ast.ListLiteralExpr():
                result = self._check_list_literal(expression, expected)
            case ast.TupleLiteralExpr():
                result = self._check_tuple_literal(expression, expected)
            case ast.CastExpr():
                result = self._check_cast(expression)
            case ast.AllocExpr():
                result = self._check_alloc(expression)
            case _:
                raise AssertionError(f"unhandled expression: {expression!r}")
        self.expr_types[id(expression)] = result
        return result

    def _check_propagate(self, expression: ast.PropagateExpr) -> Type:
        operand_type = value_type(self._check_expr(expression.value))
        if not isinstance(operand_type, ResultType):
            self._error(
                f"'?' requires a Result value, got {type_name(operand_type)}",
                expression.value.span,
                code="C131",
            )
            return ERROR
        if self.current_function is None:
            self._error("'?' is only valid inside a function", expression.span, code="C132")
            return operand_type.ok
        return_type = value_type(self.current_function.return_type)
        if not isinstance(return_type, ResultType):
            self._error(
                "a function using '?' must return Result",
                expression.span,
                code="C133",
            )
            return operand_type.ok
        if not self._can_assign(return_type.error, operand_type.error):
            self._error(
                f"cannot propagate {type_name(operand_type.error)} through {type_name(return_type)}",
                expression.span,
                code="C134",
            )
        self.propagate_resolutions[id(expression)] = PropagateResolution(operand_type, return_type)
        return operand_type.ok

    def _check_literal(self, expression: ast.LiteralExpr, expected: Type | None) -> Type:
        if expression.literal_kind == "bool":
            return BOOL
        if expression.literal_kind == "char":
            return CHAR
        if expression.literal_kind == "string":
            return string_type()
        if expression.literal_kind == "null":
            return NULL
        if expression.literal_kind == "float":
            if expected is not None and is_float(value_type(expected)):
                return value_type(expected)
            return F64
        if expression.literal_kind == "integer":
            if expected is not None and is_integer(value_type(expected)):
                return value_type(expected)
            assert isinstance(expression.value, int)
            if -(2**31) <= expression.value <= 2**31 - 1:
                return I32
            if -(2**63) <= expression.value <= 2**63 - 1:
                return I64
            if 0 <= expression.value <= 2**64 - 1:
                return U64
            self._error("integer literal is outside the supported 64-bit range", expression.span, code="C047")
            return ERROR
        return ERROR

    def _check_fstring_outside_print(self, expression: ast.FStringExpr) -> Type:
        self._error("f-strings are only supported inside print(...)", expression.span, code="C220")
        self._check_fstring_parts(expression)
        return string_type()

    def _check_name(self, expression: ast.NameExpr) -> Type:
        symbol = self.current_scope.lookup(expression.name)
        if symbol is None:
            if expression.name in ("range", "len", "sort", "print", "input", "Ok", "Err") or expression.name in _REFLECTION_BUILTINS:
                return FunctionValueType(expression.name)
            if expression.name == "super" and isinstance(self.current_owner, ClassSymbol):
                return FunctionValueType("super")
            self._error(f"unknown name {expression.name!r}", expression.span, code="C048")
            return ERROR
        self.name_symbols[id(expression)] = symbol
        if isinstance(symbol, VariableSymbol):
            return symbol.type
        if isinstance(symbol, ComptimeVariableSymbol):
            return symbol.type
        if isinstance(symbol, FunctionSymbol):
            return FunctionValueType(symbol.name)
        if isinstance(symbol, (StructSymbol, ClassSymbol, EnumSymbol, UnionSymbol, VariantSymbol)):
            return symbol.type
        if isinstance(symbol, ModuleSymbol):
            return ModuleType(symbol.name)
        if isinstance(symbol, ConstantSymbol):
            return symbol.type
        self._error(f"name {expression.name!r} is not a value", expression.span, code="C049")
        return ERROR

    def _check_unary(self, expression: ast.UnaryExpr) -> Type:
        operand_type = self._check_expr(expression.operand)
        operand_value = value_type(operand_type)
        if expression.operator in ("+", "-"):
            if not is_numeric(operand_value):
                self._error(
                    f"unary {expression.operator!r} requires a numeric operand",
                    expression.span,
                    code="C050",
                )
                return ERROR
            return operand_value
        if expression.operator == "not":
            if not is_condition_type(operand_value):
                self._error("'not' requires a scalar operand", expression.span, code="C051")
            return BOOL
        if expression.operator == "~":
            if not is_integer(operand_value):
                self._error("'~' requires an integer operand", expression.span, code="C052")
                return ERROR
            return operand_value
        if expression.operator == "&":
            if not self._is_addressable(expression.operand):
                self._error("address-of requires an addressable value", expression.operand.span, code="C053")
                return ERROR
            if isinstance(operand_type, ReferenceType):
                return PointerType(operand_type.inner)
            return PointerType(operand_type)
        if expression.operator == "*":
            raw = strip_const(operand_type)
            if isinstance(raw, (PointerType, ReferenceType)):
                return raw.inner
            self._error("dereference requires a pointer or reference", expression.span, code="C054")
            return ERROR
        return ERROR

    def _check_binary(self, expression: ast.BinaryExpr) -> Type:
        left = self._check_expr(expression.left)
        right = self._check_expr(expression.right)
        left_value = value_type(left)
        right_value = value_type(right)
        operator = expression.operator

        if operator in ("and", "or"):
            if not is_condition_type(left_value) or not is_condition_type(right_value):
                self._error(f"operator {operator!r} requires scalar operands", expression.span, code="C055")
            if _contains_propagate(expression.right):
                self._error(
                    f"'?' is not supported on the right side of {operator!r}",
                    expression.right.span,
                    code="C159",
                    note="evaluate the Result before the short-circuit expression",
                )
            return BOOL

        if operator in ("==", "!="):
            if isinstance(
                left_value,
                (TupleType, ListType),
            ) or isinstance(right_value, (TupleType, ListType)):
                self._error(
                    f"operator {operator!r} is not implemented for "
                    f"{type_name(left_value)} and {type_name(right_value)}",
                    expression.span,
                    code="C276",
                )
                return BOOL
            if not (
                self._can_assign(left_value, right_value)
                or self._can_assign(right_value, left_value)
                or (is_pointer_like(left_value) and right_value == NULL)
                or (is_pointer_like(right_value) and left_value == NULL)
            ):
                self._error(
                    f"cannot compare {type_name(left)} and {type_name(right)}",
                    expression.span,
                    code="C056",
                )
            return BOOL

        if operator in ("<", "<=", ">", ">="):
            if not (
                (is_numeric(left_value) and is_numeric(right_value))
                or (is_pointer_like(left_value) and is_pointer_like(right_value))
            ):
                self._error(f"operator {operator!r} requires comparable operands", expression.span, code="C057")
            return BOOL

        if operator in ("+", "-"):
            if is_numeric(left_value) and is_numeric(right_value):
                return common_type(left_value, right_value)
            if isinstance(left_value, PointerType) and is_integer(right_value):
                return left_value
            if operator == "+" and isinstance(right_value, PointerType) and is_integer(left_value):
                return right_value
            if operator == "-" and isinstance(left_value, PointerType) and isinstance(right_value, PointerType):
                return PRIMITIVES["isize"]
            self._error(f"invalid operands for {operator!r}", expression.span, code="C058")
            return ERROR

        if operator in ("*", "/", "%"):
            if not (is_numeric(left_value) and is_numeric(right_value)):
                self._error(f"operator {operator!r} requires numeric operands", expression.span, code="C059")
                return ERROR
            if operator == "%" and (not is_integer(left_value) or not is_integer(right_value)):
                self._error("'%' requires integer operands", expression.span, code="C060")
                return ERROR
            return common_type(left_value, right_value)

        if operator in ("&", "|", "^", "<<", ">>"):
            if not (is_integer(left_value) and is_integer(right_value)):
                self._error(f"operator {operator!r} requires integer operands", expression.span, code="C061")
                return ERROR
            return common_type(left_value, right_value)

        return ERROR

    def _check_attribute(self, expression: ast.AttributeExpr) -> Type:
        base_type = self._check_expr(expression.value)
        if isinstance(base_type, ModuleType):
            module = self.imported_modules.get(base_type.name)
            if module is None:
                self._error(f"unknown module {base_type.name!r}", expression.value.span, code="C062")
                return ERROR
            if expression.name in module.functions:
                function = module.functions[expression.name]
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "module_function", function=function
                )
                return FunctionValueType(function.name)
            if expression.name in module.constants:
                constant = module.constants[expression.name]
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "module_constant", constant=constant
                )
                return constant.type
            if expression.name in module.globals:
                global_ = module.globals[expression.name]
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "module_global", global_=global_
                )
                return global_.type
            if expression.name in module.type_symbols:
                nominal = module.type_symbols[expression.name]
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "module_type", nominal=nominal, owner_type=nominal.type
                )
                return nominal.type
            self._error(
                f"module {module.module_name!r} has no member {expression.name!r}",
                expression.span,
                code="C063",
            )
            return ERROR

        if isinstance(base_type, ComptimeItemType):
            return self._check_comptime_item_attribute(expression, base_type)

        if isinstance(base_type, DynType):
            interface = self.classes_by_type.get(base_type.interface)
            if interface is None:
                return ERROR
            field_lookup = self._lookup_class_field(interface, expression.name)
            if field_lookup is not None:
                field, owner, path = field_lookup
                field_type = field.type
                if base_type.is_const and not isinstance(field_type, ConstType):
                    field_type = ConstType(field_type)
                if field.is_private and self.current_owner is not owner:
                    self._error(
                        f"field {owner.name}.{field.name} is private",
                        expression.span,
                        code="C187",
                    )
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "dyn_field",
                    field=field,
                    owner_type=base_type,
                    class_=owner,
                    access_path=path,
                )
                return field_type
            method = self._lookup_class_method(interface, expression.name)
            if method is not None:
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "dynamic_method",
                    method=method,
                    owner_type=base_type,
                    class_=interface,
                )
                return FunctionValueType(method.c_name)
            self._error(
                f"interface {interface.name!r} has no member {expression.name!r}",
                expression.span,
                code="C188",
            )
            return ERROR

        raw = strip_const(base_type)
        base_is_const = isinstance(base_type, ConstType)
        if isinstance(raw, (PointerType, ReferenceType)):
            base_is_const = base_is_const or isinstance(raw.inner, ConstType)
            raw = strip_const(raw.inner)

        if isinstance(raw, ListType):
            if expression.name in {"append", "pop", "clear"}:
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "list_method",
                    owner_type=base_type,
                    compile_value=expression.name,
                )
                return FunctionValueType(f"List.{expression.name}")
            self._error(
                f"type {type_name(base_type)} has no member {expression.name!r}",
                expression.span,
                code="C264",
            )
            return ERROR

        nominal = self.nominal_symbols.get(raw)
        if isinstance(nominal, StructSymbol):
            field = nominal.fields.get(expression.name)
            if field is not None:
                if field.is_private and self.current_owner is not nominal:
                    self._error(
                        f"field {nominal.name}.{field.name} is private",
                        expression.span,
                        code="C064",
                    )
                field_type = field.type
                if base_is_const and not isinstance(field_type, ConstType):
                    field_type = ConstType(field_type)
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "field", field=field, owner_type=base_type
                )
                return field_type
            method = nominal.methods.get(expression.name)
            if method is not None:
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "method", method=method, owner_type=base_type
                )
                return FunctionValueType(method.c_name)
            self._error(
                f"struct {nominal.name!r} has no member {expression.name!r}",
                expression.span,
                code="C066",
            )
            return ERROR

        if isinstance(nominal, ClassSymbol):
            if self._is_nominal_type_reference(expression.value):
                self._error(
                    f"class member {expression.name!r} requires an instance",
                    expression.span,
                    code="C189",
                )
                return ERROR
            field_lookup = self._lookup_class_field(nominal, expression.name)
            if field_lookup is not None:
                field, owner, path = field_lookup
                if field.is_private and self.current_owner is not owner:
                    self._error(
                        f"field {owner.name}.{field.name} is private",
                        expression.span,
                        code="C190",
                    )
                field_type = field.type
                if base_is_const and not isinstance(field_type, ConstType):
                    field_type = ConstType(field_type)
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "class_field",
                    field=field,
                    owner_type=base_type,
                    class_=owner,
                    access_path=path,
                )
                return field_type
            method = self._lookup_class_method(nominal, expression.name)
            if method is not None:
                if method.name in ("__init__", "__del__"):
                    self._error(
                        f"{method.name} is a compiler-managed lifecycle method",
                        expression.span,
                        code="C218",
                        note=(
                            "construct with the class name; destruction runs "
                            "automatically at scope exit"
                        ),
                    )
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "method",
                    method=method,
                    owner_type=base_type,
                    class_=nominal,
                )
                return FunctionValueType(method.c_name)
            self._error(
                f"class {nominal.name!r} has no member {expression.name!r}",
                expression.span,
                code="C191",
            )
            return ERROR

        if isinstance(nominal, UnionSymbol):
            field = nominal.fields.get(expression.name)
            if field is None:
                self._error(
                    f"union {nominal.name!r} has no field {expression.name!r}",
                    expression.span,
                    code="C136",
                )
                return ERROR
            if field.is_private and self.current_owner is not None:
                self._error(
                    f"union field {nominal.name}.{field.name} is private",
                    expression.span,
                    code="C137",
                )
            field_type = field.type
            if base_is_const and not isinstance(field_type, ConstType):
                field_type = ConstType(field_type)
            self.attribute_resolutions[id(expression)] = AttributeResolution(
                "union_field", field=field, owner_type=base_type
            )
            return field_type

        if isinstance(nominal, EnumSymbol) and self._is_nominal_type_reference(expression.value):
            member = nominal.members.get(expression.name)
            if member is None:
                self._error(
                    f"enum {nominal.name!r} has no member {expression.name!r}",
                    expression.span,
                    code="C138",
                )
                return ERROR
            self.attribute_resolutions[id(expression)] = AttributeResolution(
                "enum_member", enum_member=member, owner_type=raw, nominal=nominal
            )
            return raw

        if isinstance(nominal, VariantSymbol) and self._is_nominal_type_reference(expression.value):
            variant_case = nominal.cases.get(expression.name)
            if variant_case is None:
                self._error(
                    f"variant {nominal.name!r} has no case {expression.name!r}",
                    expression.span,
                    code="C139",
                )
                return ERROR
            self.attribute_resolutions[id(expression)] = AttributeResolution(
                "variant_case",
                variant_case=variant_case,
                owner_type=raw,
                nominal=nominal,
            )
            return FunctionValueType(f"{nominal.name}.{variant_case.name}")

        if isinstance(raw, ResultType):
            if expression.name == "is_ok":
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "result_is_ok", owner_type=base_type
                )
                return BOOL
            if expression.name == "value":
                if is_void(raw.ok):
                    self._error("Result[void, E] has no value payload", expression.span, code="C140")
                    return ERROR
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "result_value", owner_type=base_type
                )
                return raw.ok
            if expression.name == "error":
                if is_void(raw.error):
                    self._error("Result[T, void] has no error payload", expression.span, code="C141")
                    return ERROR
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "result_error", owner_type=base_type
                )
                return raw.error

        if isinstance(raw, SliceType):
            if expression.name == "data":
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "slice_data", owner_type=base_type
                )
                return PointerType(raw.inner)
            if expression.name == "length":
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "slice_length", owner_type=base_type
                )
                return USIZE

        if isinstance(raw, ArrayType):
            if expression.name == "data":
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "array_data", owner_type=base_type
                )
                return PointerType(raw.inner)
            if expression.name == "length":
                self.attribute_resolutions[id(expression)] = AttributeResolution(
                    "array_length", owner_type=base_type
                )
                return USIZE

        self._error(
            f"type {type_name(base_type)} has no member {expression.name!r}",
            expression.span,
            code="C067",
        )
        return ERROR

    def _check_comptime_item_attribute(
        self,
        expression: ast.AttributeExpr,
        item_type: ComptimeItemType,
    ) -> Type:
        field_attributes: dict[str, Type] = {
            "name": string_type(),
            "type_name": string_type(),
            "offset": USIZE,
            "size": USIZE,
            "alignment": USIZE,
            "is_private": BOOL,
        }
        method_attributes: dict[str, Type] = {
            "name": string_type(),
            "signature": string_type(),
            "return_type_name": string_type(),
            "parameter_count": USIZE,
            "is_abstract": BOOL,
            "is_override": BOOL,
        }
        attributes = field_attributes if item_type.kind == "fields" else method_attributes
        result = attributes.get(expression.name)
        if result is None:
            self._error(
                f"comptime {item_type.kind[:-1]} has no attribute {expression.name!r}",
                expression.span,
                code="C211",
            )
            return ERROR
        self.attribute_resolutions[id(expression)] = AttributeResolution(
            "comptime_member_attribute",
            compile_value=expression.name,
        )
        return result

    def _is_nominal_type_reference(self, expression: ast.Expression) -> bool:
        if isinstance(expression, ast.NameExpr):
            return isinstance(
                self.name_symbols.get(id(expression)),
                (StructSymbol, ClassSymbol, EnumSymbol, UnionSymbol, VariantSymbol),
            )
        if isinstance(expression, ast.AttributeExpr):
            resolution = self.attribute_resolutions.get(id(expression))
            return resolution is not None and resolution.kind == "module_type"
        return False

    def _check_index(self, expression: ast.IndexExpr) -> Type:
        base = self._check_expr(expression.value)
        index = self._check_expr(expression.index, expected=USIZE)
        if not is_integer(value_type(index)):
            self._error("index must be an integer", expression.index.span, code="C068")
        raw = value_type(base)
        if isinstance(raw, TupleType):
            if not (
                isinstance(expression.index, ast.LiteralExpr)
                and expression.index.literal_kind == "integer"
                and isinstance(expression.index.value, int)
            ):
                self._error(
                    "tuple index must be a non-negative integer literal",
                    expression.index.span,
                    code="C271",
                )
                return ERROR
            tuple_index = expression.index.value
            if not 0 <= tuple_index < len(raw.elements):
                self._error(
                    f"tuple index {tuple_index} is out of range for {type_name(raw)}",
                    expression.index.span,
                    code="C272",
                )
                return ERROR
            return raw.elements[tuple_index]
        if isinstance(raw, ListType):
            if not self._is_addressable(expression.value):
                self._error(
                    "List indexing requires an addressable List",
                    expression.value.span,
                    code="C278",
                    note="bind the List to a local before indexing",
                )
            return raw.inner
        if isinstance(raw, (ArrayType, SliceType, PointerType)):
            return raw.inner
        self._error(f"type {type_name(base)} is not indexable", expression.value.span, code="C069")
        return ERROR

    def _check_slice(self, expression: ast.SliceExpr) -> Type:
        base = self._check_expr(expression.value)
        raw = value_type(base)
        if not isinstance(raw, (ArrayType, SliceType)):
            self._error("slicing requires an array or slice", expression.value.span, code="C070")
            return ERROR
        for bound in (expression.start, expression.stop):
            if bound is not None:
                bound_type = self._check_expr(bound, expected=USIZE)
                if not is_integer(value_type(bound_type)):
                    self._error("slice bounds must be integers", bound.span, code="C071")
        element_type = raw.inner
        if (
            isinstance(raw, ArrayType)
            and not isinstance(element_type, ConstType)
            and self._lvalue_is_const(expression.value)
        ):
            element_type = ConstType(element_type)
        return SliceType(element_type)

    def _check_call(self, expression: ast.CallExpr, expected: Type | None = None) -> Type:
        if isinstance(expression.callee, ast.NameExpr):
            name = expression.callee.name
            if name == "range":
                return self._check_range_call(expression)
            if name == "len":
                return self._check_len_call(expression)
            if name == "sort":
                return self._check_sort_call(expression)
            if name == "print":
                return self._check_print_call(expression)
            if name == "input":
                return self._check_input_call(expression)
            if name in ("Ok", "Err"):
                self.expr_types[id(expression.callee)] = FunctionValueType(name)
                return self._check_result_constructor(expression, expected, is_ok=name == "Ok")
            if name in _REFLECTION_BUILTINS:
                self.expr_types[id(expression.callee)] = FunctionValueType(name)
                return self._check_reflection_call(expression, name)

            symbol = self.current_scope.lookup(name)
            if isinstance(symbol, FunctionSymbol):
                self.name_symbols[id(expression.callee)] = symbol
                self.expr_types[id(expression.callee)] = FunctionValueType(symbol.name)
                self._validate_function_call(expression, symbol, skip_parameters=0)
                return symbol.return_type
            if isinstance(symbol, StructSymbol):
                self.name_symbols[id(expression.callee)] = symbol
                self.expr_types[id(expression.callee)] = symbol.type
                return self._check_struct_constructor(expression, symbol)
            if isinstance(symbol, ClassSymbol):
                self.name_symbols[id(expression.callee)] = symbol
                self.expr_types[id(expression.callee)] = symbol.type
                return self._check_class_constructor(expression, symbol)
            if isinstance(symbol, UnionSymbol):
                self.name_symbols[id(expression.callee)] = symbol
                self.expr_types[id(expression.callee)] = symbol.type
                return self._check_union_constructor(expression, symbol)

        if isinstance(expression.callee, ast.AttributeExpr):
            super_method = self._super_method_name(expression.callee)
            if super_method is not None:
                return self._check_super_call(expression, super_method)
            self._check_expr(expression.callee)
            resolution = self.attribute_resolutions.get(id(expression.callee))
            if resolution is not None and resolution.kind == "module_function" and resolution.function:
                self._validate_function_call(expression, resolution.function, skip_parameters=0)
                return resolution.function.return_type
            if resolution is not None and resolution.kind == "method" and resolution.method:
                self._validate_method_receiver(expression.callee.value, resolution.method)
                self._validate_function_call(expression, resolution.method, skip_parameters=1)
                return resolution.method.return_type
            if resolution is not None and resolution.kind == "dynamic_method" and resolution.method:
                self._validate_method_receiver(expression.callee.value, resolution.method)
                self._validate_function_call(expression, resolution.method, skip_parameters=1)
                checked = self.call_resolutions[id(expression)]
                self.call_resolutions[id(expression)] = CallResolution(
                    "dynamic_method",
                    function=resolution.method,
                    interface=resolution.class_,
                    argument_order=checked.argument_order,
                    expected_types=checked.expected_types,
                )
                return resolution.method.return_type
            if (
                resolution is not None
                and resolution.kind == "list_method"
                and isinstance(resolution.compile_value, str)
            ):
                return self._check_list_method_call(
                    expression,
                    expression.callee.value,
                    resolution.compile_value,
                )
            if resolution is not None and resolution.kind == "module_type" and resolution.nominal:
                if isinstance(resolution.nominal, StructSymbol):
                    return self._check_struct_constructor(expression, resolution.nominal)
                if isinstance(resolution.nominal, ClassSymbol):
                    return self._check_class_constructor(expression, resolution.nominal)
                if isinstance(resolution.nominal, UnionSymbol):
                    return self._check_union_constructor(expression, resolution.nominal)
            if (
                resolution is not None
                and resolution.kind == "variant_case"
                and isinstance(resolution.nominal, VariantSymbol)
                and resolution.variant_case is not None
            ):
                return self._check_variant_constructor(
                    expression,
                    resolution.nominal,
                    resolution.variant_case,
                )

        callee_type = self._check_expr(expression.callee)
        self._error(
            f"value of type {type_name(callee_type)} is not callable",
            expression.callee.span,
            code="C072",
        )
        for argument in expression.arguments:
            self._check_expr(argument.value)
        return ERROR

    def _check_list_method_call(
        self,
        call: ast.CallExpr,
        receiver: ast.Expression,
        method: str,
    ) -> Type:
        receiver_storage = strip_const(
            self.expr_types.get(id(receiver), ERROR)
        )
        if isinstance(receiver_storage, (PointerType, ReferenceType)):
            receiver_type = strip_const(receiver_storage.inner)
        else:
            receiver_type = value_type(receiver_storage)
        if not isinstance(receiver_type, ListType):
            self._error(
                f"{method} requires a List receiver",
                receiver.span,
                code="C265",
            )
            return ERROR

        if self._list_storage_is_active(receiver):
            self._error(
                f"cannot call List.{method} while iterating over that List",
                receiver.span,
                code="C285",
            )
        if not self._is_addressable(receiver):
            self._error(
                f"List.{method} requires an addressable List",
                receiver.span,
                code="C266",
            )
        if self._lvalue_is_const(receiver):
            self._error(
                f"cannot call mutating method {method!r} on a const List",
                receiver.span,
                code="C267",
            )
        if any(argument.name is not None for argument in call.arguments):
            self._error(
                f"List.{method} does not accept named arguments",
                call.span,
                code="C268",
            )

        if method == "append":
            if len(call.arguments) != 1:
                self._error(
                    f"List.append expects one argument, got {len(call.arguments)}",
                    call.span,
                    code="C269",
                )
            expected_types: list[Type | None] = []
            for argument in call.arguments:
                actual = self._check_expr(
                    argument.value,
                    expected=receiver_type.inner,
                )
                if not self._can_assign(receiver_type.inner, actual):
                    self._type_mismatch(
                        receiver_type.inner,
                        actual,
                        argument.value.span,
                    )
                expected_types.append(receiver_type.inner)
            self.call_resolutions[id(call)] = CallResolution(
                "list_append",
                argument_order=tuple(range(len(call.arguments))),
                expected_types=tuple(expected_types),
                compile_value=receiver_type,
            )
            return VOID

        if call.arguments:
            self._error(
                f"List.{method} expects no arguments, got {len(call.arguments)}",
                call.span,
                code="C270",
            )
            for argument in call.arguments:
                self._check_expr(argument.value)
        self.call_resolutions[id(call)] = CallResolution(
            f"list_{method}",
            compile_value=receiver_type,
        )
        return receiver_type.inner if method == "pop" else VOID

    def _list_storage(
        self,
        expression: ast.Expression,
    ) -> _ListStorage:
        if (
            isinstance(expression, ast.UnaryExpr)
            and expression.operator == "*"
            and isinstance(expression.operand, ast.UnaryExpr)
            and expression.operand.operator == "&"
        ):
            return self._list_storage(expression.operand.operand)

        if isinstance(expression, ast.NameExpr):
            symbol = self.name_symbols.get(id(expression))
            if symbol is None:
                symbol = self.current_scope.lookup(expression.name)
            if isinstance(symbol, VariableSymbol):
                storage_type = strip_const(symbol.type)
                if isinstance(storage_type, ListType):
                    return symbol, False
                if isinstance(storage_type, (PointerType, ReferenceType)) and isinstance(
                    strip_const(storage_type.inner),
                    ListType,
                ):
                    return symbol, True

        return None, True

    @staticmethod
    def _list_storages_may_alias(
        left: _ListStorage,
        right: _ListStorage,
    ) -> bool:
        left_symbol, left_may_alias = left
        right_symbol, right_may_alias = right
        if left_symbol is not None and left_symbol is right_symbol:
            return True
        return left_may_alias or right_may_alias

    def _list_storage_is_active(self, expression: ast.Expression) -> bool:
        storage = self._list_storage(expression)
        return any(
            self._list_storages_may_alias(storage, active)
            for active in self.active_list_iterators
        )

    def _check_class_constructor(self, call: ast.CallExpr, class_: ClassSymbol) -> Type:
        if class_.is_abstract:
            self._error(
                f"abstract class {class_.name!r} cannot be constructed",
                call.span,
                code="C192",
            )

        constructor = class_.constructor
        if constructor is None:
            if call.arguments:
                self._error(
                    f"default constructor for {class_.name!r} takes no arguments",
                    call.span,
                    code="C193",
                )
                for argument in call.arguments:
                    self._check_expr(argument.value)
            self.call_resolutions[id(call)] = CallResolution(
                "class_constructor",
                class_=class_,
            )
            return class_.type

        self._validate_function_call(call, constructor, skip_parameters=1)
        checked = self.call_resolutions[id(call)]
        self.call_resolutions[id(call)] = CallResolution(
            "class_constructor",
            function=constructor,
            class_=class_,
            argument_order=checked.argument_order,
            expected_types=checked.expected_types,
        )
        return class_.type

    def _check_super_call(self, call: ast.CallExpr, method_name: str) -> Type:
        owner = self.current_owner
        if not isinstance(owner, ClassSymbol) or owner.primary_base is None:
            self._error(
                "super is only valid in a class with an implementation base",
                call.callee.span,
                code="C194",
            )
            for argument in call.arguments:
                self._check_expr(argument.value)
            return ERROR

        base = owner.primary_base
        if method_name == "__del__":
            self._error(
                "base destructors are compiler-managed and cannot be called directly",
                call.span,
                code="C219",
            )
            for argument in call.arguments:
                self._check_expr(argument.value)
            return VOID
        if method_name == "__init__":
            if self.current_function is None or self.current_function.name != "__init__":
                self._error(
                    "super().__init__ is only valid inside a constructor",
                    call.span,
                    code="C195",
                )
            function = base.constructor
            if function is None:
                if call.arguments:
                    self._error(
                        f"base class {base.name} has only a zero-argument default constructor",
                        call.span,
                        code="C196",
                    )
                    for argument in call.arguments:
                        self._check_expr(argument.value)
                self.call_resolutions[id(call)] = CallResolution(
                    "super_init",
                    super_class=base,
                )
                return VOID
            self._validate_function_call(call, function, skip_parameters=1)
            checked = self.call_resolutions[id(call)]
            self.call_resolutions[id(call)] = CallResolution(
                "super_init",
                function=function,
                super_class=base,
                argument_order=checked.argument_order,
                expected_types=checked.expected_types,
            )
            return VOID

        function = self._lookup_class_method(base, method_name)
        if function is None:
            self._error(
                f"base class {base.name!r} has no method {method_name!r}",
                call.span,
                code="C197",
            )
            for argument in call.arguments:
                self._check_expr(argument.value)
            return ERROR
        if function.is_abstract:
            self._error(
                f"cannot call abstract base method {base.name}.{method_name}",
                call.span,
                code="C198",
            )
        self._validate_function_call(call, function, skip_parameters=1)
        checked = self.call_resolutions[id(call)]
        self.call_resolutions[id(call)] = CallResolution(
            "super_method",
            function=function,
            super_class=base,
            argument_order=checked.argument_order,
            expected_types=checked.expected_types,
        )
        return function.return_type

    def _check_reflection_call(self, call: ast.CallExpr, name: str) -> Type:
        if name in {"type_of", "type_name", "type_info", "size_of", "align_of", "field_count", "method_count", "fields", "methods", "fields_of", "methods_of"}:
            expected_count = 1
        elif name in {"has_field", "has_method", "implements"}:
            expected_count = 2
        else:
            raise AssertionError(f"unknown reflection builtin {name}")

        if len(call.arguments) != expected_count:
            self._error(
                f"{name} expects {expected_count} argument(s), got {len(call.arguments)}",
                call.span,
                code="C199",
            )
        if any(argument.name is not None for argument in call.arguments):
            self._error(f"{name} does not accept named arguments", call.span, code="C200")

        if name == "type_of":
            if not call.arguments:
                return ERROR
            subject = self._check_expr(call.arguments[0].value)
            result = TypeValueType(value_type(subject))
            self.call_resolutions[id(call)] = CallResolution(
                "type_of",
                compile_value=result.value,
            )
            return result

        if name in {"size_of", "align_of", "field_count", "method_count", "fields_of", "methods_of"}:
            subject = self._reflection_type_argument(call.arguments[0].value) if call.arguments else ERROR
            nominal = self.nominal_symbols.get(value_type(subject))
            if name in {"field_count", "method_count", "fields_of", "methods_of"} and nominal is None:
                self._error(
                    f"{name} requires a nominal type",
                    call.span,
                    code="C201",
                )
            if name == "size_of":
                self.call_resolutions[id(call)] = CallResolution("size_of", compile_value=subject)
                return USIZE
            if name == "align_of":
                self.call_resolutions[id(call)] = CallResolution("align_of", compile_value=subject)
                return USIZE
            if name == "field_count":
                count = len(self._nominal_fields(nominal)) if nominal is not None else 0
                self.call_resolutions[id(call)] = CallResolution("compile_integer", compile_value=count)
                return USIZE
            if name == "method_count":
                count = len(self._nominal_methods(nominal)) if nominal is not None else 0
                self.call_resolutions[id(call)] = CallResolution("compile_integer", compile_value=count)
                return USIZE
            kind = "fields" if name == "fields_of" else "methods"
            self.call_resolutions[id(call)] = CallResolution(
                name,
                compile_value=nominal,
            )
            return ComptimeCollectionType(kind, value_type(subject))

        if name in {"has_field", "has_method"}:
            subject = self._reflection_type_argument(call.arguments[0].value) if call.arguments else ERROR
            nominal = self.nominal_symbols.get(value_type(subject))
            member_name = self._literal_string_argument(call, 1, name)
            if nominal is None:
                self._error(f"{name} requires a nominal type", call.span, code="C202")
                value = False
            elif name == "has_field":
                value = any(field.name == member_name for field, _, _ in self._nominal_fields(nominal))
            else:
                value = any(method.name == member_name for method in self._nominal_methods(nominal))
            self.call_resolutions[id(call)] = CallResolution("compile_bool", compile_value=value)
            return BOOL

        if name == "implements":
            source_type = self._reflection_type_argument(call.arguments[0].value) if call.arguments else ERROR
            target_type = self._reflection_type_argument(call.arguments[1].value) if len(call.arguments) > 1 else ERROR
            source = self.nominal_symbols.get(value_type(source_type))
            target = self.nominal_symbols.get(value_type(target_type))
            value = (
                isinstance(source, ClassSymbol)
                and isinstance(target, ClassSymbol)
                and target.is_abstract
                and self._class_implements(source, target)
            )
            if not isinstance(source, ClassSymbol) or not isinstance(target, ClassSymbol):
                self._error("implements requires two class types", call.span, code="C203")
            self.call_resolutions[id(call)] = CallResolution("compile_bool", compile_value=value)
            return BOOL

        # The remaining operations accept runtime values as well as type_of(...).
        if not call.arguments:
            return ERROR
        argument = call.arguments[0].value
        subject_type = self._check_expr(argument)
        if isinstance(subject_type, TypeValueType):
            inspected = subject_type.value
        else:
            inspected = value_type(subject_type)
        if isinstance(inspected, ListType) and not self._is_addressable(argument):
            self._error(
                f"{name} requires an addressable List value",
                argument.span,
                code="C281",
                note="bind the List to a local before inspecting its type",
            )
        nominal = self.nominal_symbols.get(inspected)

        if name == "type_name":
            if isinstance(subject_type, DynType):
                interface = self.classes_by_type.get(subject_type.interface)
                if interface is None or not interface.reflected:
                    self._error(
                        "runtime type_name on dyn requires a @reflect interface",
                        call.span,
                        code="C204",
                    )
                self.call_resolutions[id(call)] = CallResolution(
                    "dynamic_type_name",
                    interface=interface,
                )
            else:
                self.call_resolutions[id(call)] = CallResolution(
                    "compile_string",
                    compile_value=type_name(inspected),
                )
            return string_type()

        if name in {"type_info", "fields", "methods"}:
            interface: ClassSymbol | None = None
            if isinstance(subject_type, DynType):
                interface = self.classes_by_type.get(subject_type.interface)
                reflected = interface is not None and interface.reflected
            else:
                reflected = nominal is not None and nominal.reflected
            if not reflected:
                self._error(
                    f"{name} requires a value whose type uses @reflect",
                    call.span,
                    code="C205",
                )
            if name == "type_info":
                kind = "dynamic_type_info" if isinstance(subject_type, DynType) else "type_info"
                self.call_resolutions[id(call)] = CallResolution(
                    kind,
                    interface=interface,
                    compile_value=nominal,
                )
                type_info_type = self.types["CinderTypeInfo"]
                return PointerType(ConstType(type_info_type))
            item_type = self.types[
                "CinderFieldInfo" if name == "fields" else "CinderMethodInfo"
            ]
            kind = f"dynamic_{name}" if isinstance(subject_type, DynType) else name
            self.call_resolutions[id(call)] = CallResolution(
                kind,
                interface=interface,
                compile_value=nominal,
            )
            return SliceType(ConstType(item_type))

        raise AssertionError(f"unhandled reflection builtin {name}")

    def _reflection_type_argument(self, expression: ast.Expression) -> Type:
        if isinstance(expression, ast.NameExpr):
            type_ = self.types.get(expression.name)
            if type_ is not None:
                self.expr_types[id(expression)] = TypeValueType(type_)
                return type_
        if isinstance(expression, ast.AttributeExpr):
            resolved = self._check_expr(expression)
            resolution = self.attribute_resolutions.get(id(expression))
            if resolution is not None and resolution.kind == "module_type":
                self.expr_types[id(expression)] = TypeValueType(resolved)
                return resolved
        resolved = self._check_expr(expression)
        if isinstance(resolved, TypeValueType):
            return resolved.value
        self._error(
            "expected a type name or type_of(...) value",
            expression.span,
            code="C206",
        )
        return ERROR

    def _literal_string_argument(self, call: ast.CallExpr, index: int, function: str) -> str:
        if index >= len(call.arguments):
            return ""
        expression = call.arguments[index].value
        self._check_expr(expression, expected=string_type())
        if not isinstance(expression, ast.LiteralExpr) or expression.literal_kind != "string":
            self._error(
                f"{function} member name must be a string literal",
                expression.span,
                code="C207",
            )
            return ""
        assert isinstance(expression.value, str)
        return expression.value

    def _nominal_fields(
        self,
        nominal: NominalSymbol | None,
    ) -> list[tuple[FieldSymbol, NominalSymbol, tuple[str, ...]]]:
        if isinstance(nominal, ClassSymbol):
            result: list[tuple[FieldSymbol, NominalSymbol, tuple[str, ...]]] = []
            if nominal.primary_base is not None:
                for field, owner, path in self._nominal_fields(nominal.primary_base):
                    result.append((field, owner, ("_base", *path)))
            result.extend((field, nominal, ()) for field in nominal.fields.values())
            return result
        if isinstance(nominal, (StructSymbol, UnionSymbol)):
            return [(field, nominal, ()) for field in nominal.fields.values()]
        return []

    @staticmethod
    def _nominal_methods(nominal: NominalSymbol | None) -> list[FunctionSymbol]:
        if isinstance(nominal, ClassSymbol):
            return list(nominal.interface_methods.values())
        if isinstance(nominal, StructSymbol):
            return list(nominal.methods.values())
        return []

    def _check_result_constructor(
        self,
        call: ast.CallExpr,
        expected: Type | None,
        *,
        is_ok: bool,
    ) -> Type:
        result = value_type(expected) if expected is not None else None
        if not isinstance(result, ResultType):
            self._error(
                f"{'Ok' if is_ok else 'Err'} requires an expected Result[T, E] type",
                call.span,
                code="C143",
                note="add a Result annotation or use it directly in a Result-returning context",
            )
            for argument in call.arguments:
                self._check_expr(argument.value)
            return ERROR

        payload = result.ok if is_ok else result.error
        expected_count = 0 if is_void(payload) else 1
        if len(call.arguments) != expected_count:
            self._error(
                f"{'Ok' if is_ok else 'Err'} expects {expected_count} arguments, got {len(call.arguments)}",
                call.span,
                code="C144",
            )
        order: list[int] = []
        expected_types: list[Type | None] = []
        for index, argument in enumerate(call.arguments):
            allowed_name = "value" if is_ok else "error"
            if argument.name is not None and argument.name != allowed_name:
                self._error(
                    f"unexpected named argument {argument.name!r}; expected {allowed_name!r}",
                    argument.span,
                    code="C145",
                )
            actual = self._check_expr(argument.value, expected=payload)
            if not is_void(payload) and not self._can_assign(payload, actual):
                self._type_mismatch(payload, actual, argument.value.span)
            order.append(index)
            expected_types.append(payload if not is_void(payload) else None)
        self.call_resolutions[id(call)] = CallResolution(
            "result_constructor",
            result_type=result,
            result_is_ok=is_ok,
            argument_order=tuple(order),
            expected_types=tuple(expected_types),
        )
        return result

    def _check_union_constructor(self, call: ast.CallExpr, union: UnionSymbol) -> Type:
        if len(call.arguments) > 1:
            self._error(
                f"union {union.name!r} accepts at most one active field initializer",
                call.span,
                code="C146",
            )
        order: list[int] = []
        expected_types: list[Type | None] = []
        field_order: list[str] = []
        for index, argument in enumerate(call.arguments):
            if argument.name is None:
                self._error(
                    "union construction requires a named field initializer",
                    argument.span,
                    code="C147",
                )
                self._check_expr(argument.value)
                continue
            field = union.fields.get(argument.name)
            if field is None:
                self._error(
                    f"union {union.name!r} has no field {argument.name!r}",
                    argument.span,
                    code="C148",
                )
                self._check_expr(argument.value)
                continue
            if field.is_private:
                self._error(
                    f"field {union.name}.{field.name} is private",
                    argument.span,
                    code="C149",
                )
            actual = self._check_expr(argument.value, expected=field.type)
            if not self._can_assign(field.type, actual):
                self._type_mismatch(field.type, actual, argument.value.span)
            order.append(index)
            expected_types.append(field.type)
            field_order.append(field.name)
        self.call_resolutions[id(call)] = CallResolution(
            "union_constructor",
            union=union,
            argument_order=tuple(order),
            expected_types=tuple(expected_types),
            field_order=tuple(field_order),
        )
        return union.type

    def _check_variant_constructor(
        self,
        call: ast.CallExpr,
        variant: VariantSymbol,
        variant_case: VariantCaseSymbol,
    ) -> Type:
        fields = list(variant_case.fields.values())
        assigned: list[int | None] = [None] * len(fields)
        field_by_name = {field.name: index for index, field in enumerate(fields)}
        next_position = 0
        seen_named = False

        for argument_index, argument in enumerate(call.arguments):
            if argument.name is not None:
                seen_named = True
                field_index = field_by_name.get(argument.name)
                if field_index is None:
                    self._error(
                        f"case {variant.name}.{variant_case.name} has no field {argument.name!r}",
                        argument.span,
                        code="C150",
                    )
                    self._check_expr(argument.value)
                    continue
                if assigned[field_index] is not None:
                    self._error(
                        f"field {argument.name!r} was initialized more than once",
                        argument.span,
                        code="C151",
                    )
                assigned[field_index] = argument_index
                continue
            if seen_named:
                self._error(
                    "positional arguments cannot follow named arguments",
                    argument.span,
                    code="C152",
                )
            while next_position < len(assigned) and assigned[next_position] is not None:
                next_position += 1
            if next_position >= len(fields):
                self._error(
                    f"too many payload values for {variant.name}.{variant_case.name}",
                    argument.span,
                    code="C153",
                )
                self._check_expr(argument.value)
                continue
            assigned[next_position] = argument_index
            next_position += 1

        order: list[int] = []
        expected_types: list[Type | None] = []
        field_order: list[str] = []
        for field_index, field in enumerate(fields):
            argument_index = assigned[field_index]
            if argument_index is None:
                self._error(
                    f"missing payload field {field.name!r} for {variant.name}.{variant_case.name}",
                    call.span,
                    code="C154",
                )
                continue
            argument = call.arguments[argument_index]
            actual = self._check_expr(argument.value, expected=field.type)
            if not self._can_assign(field.type, actual):
                self._type_mismatch(field.type, actual, argument.value.span)
            order.append(argument_index)
            expected_types.append(field.type)
            field_order.append(field.name)

        self.call_resolutions[id(call)] = CallResolution(
            "variant_constructor",
            variant=variant,
            variant_case=variant_case,
            argument_order=tuple(order),
            expected_types=tuple(expected_types),
            field_order=tuple(field_order),
        )
        return variant.type

    def _validate_method_receiver(self, receiver: ast.Expression, method: FunctionSymbol) -> None:
        if not method.parameters:
            return
        expected = method.parameters[0].type
        actual = self.expr_types.get(id(receiver), ERROR)
        if isinstance(expected, ReferenceType):
            if isinstance(actual, (ReferenceType, PointerType)):
                if not self._can_assign(expected, actual):
                    self._type_mismatch(expected, actual, receiver.span)
            else:
                if not self._is_addressable(receiver):
                    self._error("method receiver must be addressable", receiver.span, code="C073")
                elif not self._can_assign(expected.inner, actual):
                    self._type_mismatch(expected.inner, actual, receiver.span)
        elif isinstance(strip_const(expected), DynType):
            if not self._can_assign(expected, actual):
                self._type_mismatch(expected, actual, receiver.span)
            self._validate_borrow_source(expected, actual, receiver)
        elif not self._can_assign(expected, actual):
            self._type_mismatch(expected, actual, receiver.span)

    def _validate_function_call(
        self,
        call: ast.CallExpr,
        function: FunctionSymbol,
        *,
        skip_parameters: int,
    ) -> None:
        parameters = function.parameters[skip_parameters:]
        assigned: list[int | None] = [None] * len(parameters)
        variadic_indices: list[int] = []
        seen_named = False
        next_position = 0
        parameter_by_name = {parameter.name: index for index, parameter in enumerate(parameters)}

        for argument_index, argument in enumerate(call.arguments):
            if argument.name is not None:
                seen_named = True
                parameter_index = parameter_by_name.get(argument.name)
                if parameter_index is None:
                    self._error(
                        f"function {function.name!r} has no parameter {argument.name!r}",
                        argument.span,
                        code="C074",
                    )
                    self._check_expr(argument.value)
                    continue
                if assigned[parameter_index] is not None:
                    self._error(
                        f"parameter {argument.name!r} was supplied more than once",
                        argument.span,
                        code="C075",
                    )
                assigned[parameter_index] = argument_index
                continue

            if seen_named:
                self._error(
                    "positional arguments cannot follow named arguments",
                    argument.span,
                    code="C076",
                )
            while next_position < len(assigned) and assigned[next_position] is not None:
                next_position += 1
            if next_position < len(assigned):
                assigned[next_position] = argument_index
                next_position += 1
            elif function.is_variadic:
                variadic_indices.append(argument_index)
            else:
                self._error(
                    f"too many arguments for {function.name!r}",
                    argument.span,
                    code="C077",
                )
                self._check_expr(argument.value)

        for parameter_index, argument_index in enumerate(assigned):
            if argument_index is None:
                self._error(
                    f"missing argument {parameters[parameter_index].name!r} for {function.name!r}",
                    call.span,
                    code="C078",
                )

        order: list[int] = []
        expected_types: list[Type | None] = []
        for parameter_index, argument_index in enumerate(assigned):
            if argument_index is None:
                continue
            order.append(argument_index)
            expected = parameters[parameter_index].type
            expected_types.append(expected)
            argument = call.arguments[argument_index]
            actual = self._check_expr(argument.value, expected=expected)
            if not self._can_assign(expected, actual):
                self._type_mismatch(expected, actual, argument.value.span)
            self._validate_borrow_source(expected, actual, argument.value)
            if isinstance(expected, ReferenceType):
                if actual == NULL:
                    self._error("references cannot receive null", argument.value.span, code="C079")
                elif not isinstance(actual, (ReferenceType, PointerType)) and not self._is_addressable(argument.value):
                    self._error(
                        "reference argument must be addressable",
                        argument.value.span,
                        code="C080",
                    )

        for argument_index in variadic_indices:
            argument = call.arguments[argument_index]
            actual = self._check_expr(argument.value)
            if not is_scalar(value_type(actual)) and not isinstance(value_type(actual), StructType):
                self._error(
                    f"type {type_name(actual)} cannot be passed through C varargs",
                    argument.value.span,
                    code="C081",
                )
            order.append(argument_index)
            expected_types.append(None)

        self.call_resolutions[id(call)] = CallResolution(
            "method" if skip_parameters else "function",
            function=function,
            argument_order=tuple(order),
            expected_types=tuple(expected_types),
        )

    def _check_struct_constructor(self, call: ast.CallExpr, struct: StructSymbol) -> Type:
        fields = list(struct.fields.values())
        assigned: list[int | None] = [None] * len(fields)
        field_by_name = {field.name: index for index, field in enumerate(fields)}
        next_position = 0
        seen_named = False

        for argument_index, argument in enumerate(call.arguments):
            if argument.name is not None:
                seen_named = True
                field_index = field_by_name.get(argument.name)
                if field_index is None:
                    self._error(
                        f"struct {struct.name!r} has no field {argument.name!r}",
                        argument.span,
                        code="C082",
                    )
                    self._check_expr(argument.value)
                    continue
                if assigned[field_index] is not None:
                    self._error(
                        f"field {argument.name!r} was initialized more than once",
                        argument.span,
                        code="C083",
                    )
                assigned[field_index] = argument_index
                continue

            if seen_named:
                self._error(
                    "positional arguments cannot follow named arguments",
                    argument.span,
                    code="C084",
                )
            while next_position < len(assigned) and assigned[next_position] is not None:
                next_position += 1
            if next_position >= len(fields):
                self._error(
                    f"too many initializers for struct {struct.name!r}",
                    argument.span,
                    code="C085",
                )
                self._check_expr(argument.value)
                continue
            assigned[next_position] = argument_index
            next_position += 1

        order: list[int] = []
        expected_types: list[Type | None] = []
        field_order: list[str] = []
        for field_index, argument_index in enumerate(assigned):
            if argument_index is None:
                continue
            field = fields[field_index]
            argument = call.arguments[argument_index]
            if field.is_private and self.current_owner is not struct:
                self._error(
                    f"field {struct.name}.{field.name} is private",
                    argument.span,
                    code="C086",
                )
            actual = self._check_expr(argument.value, expected=field.type)
            if not self._can_assign(field.type, actual):
                self._type_mismatch(field.type, actual, argument.value.span)
            order.append(argument_index)
            expected_types.append(field.type)
            field_order.append(field.name)

        self.call_resolutions[id(call)] = CallResolution(
            "constructor",
            struct=struct,
            argument_order=tuple(order),
            expected_types=tuple(expected_types),
            field_order=tuple(field_order),
        )
        return struct.type

    def _check_print_call(self, call: ast.CallExpr) -> Type:
        self.expr_types[id(call.callee)] = FunctionValueType("print")
        if "<stdio.h>" not in self.includes:
            self.includes.append("<stdio.h>")
        for argument in call.arguments:
            if argument.name is not None:
                self._error("print does not accept named arguments", argument.span, code="C221")
            self._check_print_argument(argument.value)
        self.call_resolutions[id(call)] = CallResolution("print")
        return VOID

    def _check_input_call(self, call: ast.CallExpr) -> Type:
        self.expr_types[id(call.callee)] = FunctionValueType("input")
        if len(call.arguments) > 1:
            self._error("input expects zero or one positional argument", call.span, code="C244")
        expected_types: list[Type | None] = []
        argument_order: list[int] = []
        for index, argument in enumerate(call.arguments):
            if argument.name is not None:
                self._error("input does not accept named arguments", argument.span, code="C245")
            expected = string_type() if index == 0 else None
            actual = self._check_expr(argument.value, expected=expected)
            if index == 0 and not self._can_assign(string_type(), actual):
                self._type_mismatch(string_type(), actual, argument.value.span)
            argument_order.append(index)
            expected_types.append(expected)
        self.call_resolutions[id(call)] = CallResolution(
            "input",
            argument_order=tuple(argument_order),
            expected_types=tuple(expected_types),
        )
        return string_type()

    def _check_print_argument(self, expression: ast.Expression) -> None:
        if isinstance(expression, ast.FStringExpr):
            self._check_fstring_parts(expression)
            self.expr_types[id(expression)] = string_type()
            return
        actual = self._check_expr(expression)
        self._validate_printable_type(actual, None, expression.span)

    def _check_fstring_parts(self, expression: ast.FStringExpr) -> None:
        for part in expression.parts:
            if isinstance(part, ast.FStringText):
                continue
            actual: Type
            if isinstance(part.expression, ast.FStringExpr):
                self._check_fstring_parts(part.expression)
                actual = string_type()
                self.expr_types[id(part.expression)] = actual
            else:
                actual = self._check_expr(part.expression)
            self._validate_printable_type(actual, part.format_spec, part.span)

    def _validate_printable_type(
        self,
        type_: Type,
        format_spec: str | None,
        span: Span,
    ) -> None:
        raw = value_type(type_)
        conversion = _print_conversion(format_spec)
        if conversion is None and format_spec not in (None, ""):
            self._error(f"unsupported print format specifier {format_spec!r}", span, code="C222")
            return

        if raw == BOOL:
            if conversion not in (None, "s"):
                self._error("bool print values support only the default format or :s", span, code="C223")
            return
        if raw == CHAR:
            if conversion not in (None, "c"):
                self._error("char print values support only the default format or :c", span, code="C224")
            return
        if _is_string_type(raw):
            if conversion not in (None, "s"):
                self._error("string print values support only the default format or :s", span, code="C225")
            return
        if is_float(raw):
            if conversion is None or conversion in "fFeEgG":
                return
            self._error(f"float print values do not support :{conversion}", span, code="C226")
            return
        if is_integer(raw):
            if conversion is None or conversion in "diuoxX":
                return
            self._error(f"integer print values do not support :{conversion}", span, code="C227")
            return

        self._error(f"type {type_name(type_)} cannot be printed", span, code="C228")

    def _check_range_call(self, call: ast.CallExpr) -> Type:
        if any(argument.name is not None for argument in call.arguments):
            self._error("range does not accept named arguments", call.span, code="C087")
        if not 1 <= len(call.arguments) <= 3:
            self._error("range expects one, two, or three arguments", call.span, code="C088")
        argument_types: list[Type] = []
        for argument in call.arguments:
            argument_type = self._check_expr(argument.value)
            if not is_integer(value_type(argument_type)):
                self._error("range arguments must be integers", argument.value.span, code="C089")
            argument_types.append(value_type(argument_type))
        element = I32
        for argument_type in argument_types:
            element = common_type(element, argument_type)
        if element == ERROR:
            element = I32

        if len(call.arguments) == 1:
            resolution = RangeResolution(-1, 0, None, element)
        elif len(call.arguments) == 2:
            resolution = RangeResolution(0, 1, None, element)
        else:
            resolution = RangeResolution(0, 1, 2, element)
            step = call.arguments[2].value
            if isinstance(step, ast.LiteralExpr) and step.literal_kind == "integer" and step.value == 0:
                self._error("range step cannot be zero", step.span, code="C090")
        self.range_resolutions[id(call)] = resolution
        self.call_resolutions[id(call)] = CallResolution("range")
        self.expr_types[id(call.callee)] = FunctionValueType("range")
        return RangeType(element)

    def _check_len_call(self, call: ast.CallExpr) -> Type:
        if len(call.arguments) != 1 or call.arguments[0].name is not None:
            self._error("len expects exactly one positional argument", call.span, code="C091")
            for argument in call.arguments:
                self._check_expr(argument.value)
            return USIZE
        argument_type = value_type(self._check_expr(call.arguments[0].value))
        if not isinstance(
            argument_type,
            (ArrayType, SliceType, ListType, TupleType),
        ) and argument_type != string_type():
            self._error(
                f"len does not support {type_name(argument_type)}",
                call.arguments[0].value.span,
                code="C092",
            )
        if isinstance(argument_type, ListType) and not self._is_addressable(
            call.arguments[0].value
        ):
            self._error(
                "len requires an addressable List",
                call.arguments[0].value.span,
                code="C279",
                note="bind the List to a local before calling len",
            )
        self.call_resolutions[id(call)] = CallResolution(
            "len", argument_order=(0,), expected_types=(None,)
        )
        self.expr_types[id(call.callee)] = FunctionValueType("len")
        return USIZE

    def _check_sort_call(self, call: ast.CallExpr) -> Type:
        if len(call.arguments) != 1 or call.arguments[0].name is not None:
            self._error("sort expects exactly one positional argument", call.span, code="C239")
            for call_argument in call.arguments:
                self._check_expr(call_argument.value)
            return VOID

        argument_expression = call.arguments[0].value
        argument_type = value_type(self._check_expr(argument_expression))
        if not isinstance(argument_type, (ArrayType, SliceType, ListType)):
            self._error(
                f"sort requires an array or slice, or List, got {type_name(argument_type)}",
                argument_expression.span,
                code="C240",
            )
            return VOID
        if isinstance(argument_type, (ArrayType, ListType)) and not self._is_addressable(
            argument_expression
        ):
            self._error(
                "sort requires an addressable fixed array or List",
                argument_expression.span,
                code="C243",
            )
        if (
            isinstance(argument_type, ListType)
            and self._list_storage_is_active(argument_expression)
        ):
            self._error(
                "cannot sort a List while iterating over it",
                argument_expression.span,
                code="C286",
            )

        element_type = argument_type.inner
        is_const_container = isinstance(
            argument_type,
            (ArrayType, ListType),
        ) and self._lvalue_is_const(argument_expression)
        if isinstance(element_type, ConstType) or is_const_container:
            self._error("sort requires mutable elements", argument_expression.span, code="C241")
        elif not self._is_sortable_element_type(element_type):
            self._error(
                f"sort does not support elements of type {type_name(element_type)}",
                argument_expression.span,
                code="C242",
            )

        slice_type = SliceType(element_type)
        self.call_resolutions[id(call)] = CallResolution(
            "sort", argument_order=(0,), expected_types=(slice_type,)
        )
        self.expr_types[id(call.callee)] = FunctionValueType("sort")
        return VOID

    @staticmethod
    def _is_sortable_element_type(type_: Type) -> bool:
        raw = strip_const(type_)
        if is_numeric(raw) or raw == BOOL or isinstance(raw, EnumType):
            return True
        return isinstance(raw, PointerType) and strip_const(raw.inner) == CHAR

    def _check_list_literal(
        self,
        expression: ast.ListLiteralExpr,
        expected: Type | None,
    ) -> Type:
        expected_value = value_type(expected) if expected is not None else None
        if isinstance(expected_value, ArrayType):
            if len(expression.elements) != expected_value.length:
                self._error(
                    f"expected {expected_value.length} array elements, got {len(expression.elements)}",
                    expression.span,
                    code="C093",
                )
            for element in expression.elements:
                actual = self._check_expr(element, expected=expected_value.inner)
                if not self._can_assign(expected_value.inner, actual):
                    self._type_mismatch(expected_value.inner, actual, element.span)
            return expected_value

        if isinstance(expected_value, SliceType):
            if not expression.elements:
                self._error(
                    "an empty list literal cannot initialize a slice",
                    expression.span,
                    code="C273",
                    note="bind an empty List[T] or provide an existing array/slice",
                )
                return ERROR
            for element in expression.elements:
                actual = self._check_expr(element, expected=expected_value.inner)
                if not self._can_assign(expected_value.inner, actual):
                    self._type_mismatch(
                        expected_value.inner,
                        actual,
                        element.span,
                    )
            return ArrayType(expected_value.inner, len(expression.elements))

        if isinstance(expected_value, ListType):
            for element in expression.elements:
                actual = self._check_expr(element, expected=expected_value.inner)
                if not self._can_assign(expected_value.inner, actual):
                    self._type_mismatch(
                        expected_value.inner,
                        actual,
                        element.span,
                    )
            return expected_value

        if not expression.elements:
            self._error(
                "cannot infer the element type of an empty list literal",
                expression.span,
                code="C094",
                note="add a List[T] annotation",
            )
            return ERROR
        inferred = value_type(self._check_expr(expression.elements[0]))
        for element in expression.elements[1:]:
            current = self._check_expr(element, expected=inferred)
            inferred = common_type(value_type(inferred), value_type(current))
            if inferred == ERROR:
                self._error("list elements do not have a common type", element.span, code="C095")
                break
        inferred = strip_const(inferred)
        if inferred != ERROR and (
            not self._is_collection_runtime_type(inferred)
            or isinstance(inferred, (ReferenceType, ArrayType, ListType))
            or self._contains_destructible_value(inferred)
        ):
            self._error(
                f"cannot infer a List element type from {type_name(inferred)}",
                expression.span,
                code="C287",
            )
            inferred = ERROR
        return ListType(inferred)

    def _check_tuple_literal(
        self,
        expression: ast.TupleLiteralExpr,
        expected: Type | None,
    ) -> Type:
        expected_value = value_type(expected) if expected is not None else None
        if isinstance(expected_value, TupleType):
            if len(expression.elements) != len(expected_value.elements):
                self._error(
                    f"expected {len(expected_value.elements)} tuple elements, "
                    f"got {len(expression.elements)}",
                    expression.span,
                    code="C274",
                )
            for index, element in enumerate(expression.elements):
                element_expected = (
                    expected_value.elements[index]
                    if index < len(expected_value.elements)
                    else None
                )
                actual = self._check_expr(element, expected=element_expected)
                if (
                    element_expected is not None
                    and not self._can_assign(element_expected, actual)
                ):
                    self._type_mismatch(
                        element_expected,
                        actual,
                        element.span,
                    )
            return expected_value

        elements: list[Type] = []
        for element in expression.elements:
            element_type = value_type(self._check_expr(element))
            if element_type != ERROR:
                if not self._is_collection_runtime_type(element_type):
                    self._error(
                        f"tuple literal cannot store {type_name(element_type)}",
                        element.span,
                        code="C288",
                    )
                    element_type = ERROR
                elif self._contains_destructible_value(element_type):
                    self._error(
                        f"tuple literal cannot own destructor-bearing "
                        f"{type_name(element_type)}",
                        element.span,
                        code="C289",
                    )
                    element_type = ERROR
                elif isinstance(element_type, (ArrayType, ListType)):
                    self._error(
                        f"tuple literal cannot own {type_name(element_type)}",
                        element.span,
                        code="C275",
                        note="tuple aggregate ownership for arrays and lists is not implemented",
                    )
                    element_type = ERROR
            elements.append(strip_const(element_type))
        return TupleType(tuple(elements))

    @staticmethod
    def _is_collection_runtime_type(type_: Type) -> bool:
        return type_ not in (ERROR, NULL, VOID) and not isinstance(
            type_,
            (
                FunctionValueType,
                ModuleType,
                RangeType,
                TypeValueType,
                ComptimeCollectionType,
                ComptimeItemType,
            ),
        )

    def _check_cast(self, expression: ast.CastExpr) -> Type:
        target = self._resolve_type(expression.target_type)
        source = self._check_expr(expression.value)
        source_value = value_type(source)
        if isinstance(
            target,
            (ArrayType, SliceType, ReferenceType, TupleType, ListType),
        ) or isinstance(source_value, (TupleType, ListType)) or is_void(target):
            self._error(
                f"cannot cast from {type_name(source_value)} to {type_name(target)}",
                expression.target_type.span,
                code="C096",
            )
            return ERROR
        safe = False
        if is_numeric(target) and is_numeric(source_value):
            safe = True
        elif isinstance(target, EnumType) and is_integer(source_value):
            safe = True
        elif is_integer(target) and isinstance(source_value, EnumType):
            safe = True
        elif isinstance(target, PointerType) and isinstance(source_value, PointerType):
            target_inner = strip_const(target.inner)
            source_inner = strip_const(source_value.inner)
            safe = target_inner == VOID or source_inner == VOID or target_inner == source_inner
        elif target == BOOL and is_scalar(source_value):
            safe = True
        if not safe and self.unsafe_depth == 0:
            self._error(
                f"cast from {type_name(source)} to {type_name(target)} requires an unsafe block",
                expression.span,
                code="C097",
            )
        return target

    def _check_alloc(self, expression: ast.AllocExpr) -> Type:
        element = self._resolve_type(expression.element_type)
        if is_void(element) or isinstance(
            element,
            (ReferenceType, SliceType, ArrayType, ListType),
        ):
            self._error(
                f"cannot allocate elements of type {type_name(element)}",
                expression.element_type.span,
                code="C098",
            )
            return ERROR
        if expression.count is not None:
            count = self._check_expr(expression.count, expected=USIZE)
            if not is_integer(value_type(count)):
                self._error("allocation count must be an integer", expression.count.span, code="C099")
        return PointerType(element)

    def _is_addressable(self, expression: ast.Expression) -> bool:
        if isinstance(expression, ast.NameExpr):
            symbol = self.name_symbols.get(id(expression)) or self.current_scope.lookup(expression.name)
            return isinstance(symbol, VariableSymbol)
        if isinstance(expression, ast.AttributeExpr):
            return True
        if isinstance(expression, ast.IndexExpr):
            base_type = value_type(
                self.expr_types.get(id(expression.value), ERROR)
            )
            return not isinstance(base_type, TupleType)
        return isinstance(expression, ast.UnaryExpr) and expression.operator == "*"

    def _is_constant_expression(self, expression: ast.Expression) -> bool:
        if isinstance(expression, ast.LiteralExpr):
            return True
        if isinstance(expression, ast.UnaryExpr):
            return self._is_constant_expression(expression.operand)
        if isinstance(expression, ast.BinaryExpr):
            return self._is_constant_expression(expression.left) and self._is_constant_expression(expression.right)
        if isinstance(expression, ast.ListLiteralExpr):
            expression_type = value_type(
                self.expr_types.get(id(expression), ERROR)
            )
            return isinstance(expression_type, ArrayType) and all(
                self._is_constant_expression(element)
                for element in expression.elements
            )
        if isinstance(expression, ast.TupleLiteralExpr):
            return all(
                self._is_constant_expression(element)
                for element in expression.elements
            )
        if isinstance(expression, ast.CallExpr):
            resolution = self.call_resolutions.get(id(expression))
            return resolution is not None and resolution.kind in {
                "constructor",
                "union_constructor",
                "variant_constructor",
                "result_constructor",
            } and all(self._is_constant_expression(argument.value) for argument in expression.arguments)
        if isinstance(expression, ast.CastExpr):
            return self._is_constant_expression(expression.value)
        if isinstance(expression, ast.NameExpr):
            symbol = self.name_symbols.get(id(expression))
            return isinstance(symbol, ConstantSymbol)
        if isinstance(expression, ast.AttributeExpr):
            resolution = self.attribute_resolutions.get(id(expression))
            return resolution is not None and resolution.kind in {"module_constant", "enum_member"}
        return False

    def _block_always_returns(self, block: ast.Block) -> bool:
        for statement in block.statements:
            if isinstance(statement, ast.ReturnStmt):
                return True
            if isinstance(statement, ast.IfStmt):
                if statement.else_body is not None and all(
                    self._block_always_returns(branch.body) for branch in statement.branches
                ) and self._block_always_returns(statement.else_body):
                    return True
            if isinstance(statement, ast.MatchStmt):
                resolution = self.match_resolutions.get(id(statement))
                if resolution is not None and resolution.exhaustive and all(
                    self._block_always_returns(case.body) for case in statement.cases
                ):
                    return True
            if isinstance(statement, ast.UnsafeStmt) and self._block_always_returns(statement.body):
                return True
        return False

    def _resolve_type(self, node: ast.TypeNode, *, allow_opaque: bool = False) -> Type:
        cached = self.type_nodes.get(id(node))
        if cached is not None:
            return cached

        match node:
            case ast.NamedTypeNode(name=name):
                result = self.types.get(name)
                if result is None and allow_opaque:
                    result = OpaqueType(name, name)
                    self.types[name] = result
                if result is None:
                    self._error(f"unknown type {name!r}", node.span, code="C100")
                    result = ERROR
            case ast.GenericTypeNode(base=base, arguments=arguments):
                if not isinstance(base, ast.NamedTypeNode):
                    self._error(
                        "generic type base must be a built-in type name",
                        node.span,
                        code="C155",
                    )
                    for argument in arguments:
                        self._resolve_type(argument, allow_opaque=allow_opaque)
                    result = ERROR
                elif base.name == "Result" and len(arguments) != 2:
                    self._error("Result requires exactly two type arguments", node.span, code="C156")
                    for argument in arguments:
                        self._resolve_type(argument, allow_opaque=allow_opaque)
                    result = ERROR
                elif base.name == "Result":
                    result = ResultType(
                        self._resolve_type(arguments[0], allow_opaque=allow_opaque),
                        self._resolve_type(arguments[1], allow_opaque=allow_opaque),
                    )
                elif base.name == "List" and len(arguments) != 1:
                    self._error("List requires exactly one type argument", node.span, code="C244")
                    for argument in arguments:
                        self._resolve_type(argument, allow_opaque=allow_opaque)
                    result = ERROR
                elif base.name == "List":
                    inner_type = self._resolve_type(
                        arguments[0],
                        allow_opaque=allow_opaque,
                    )
                    if (
                        is_void(inner_type)
                        or isinstance(
                            inner_type,
                            (ConstType, ReferenceType, ArrayType, ListType),
                        )
                    ):
                        self._error(
                            f"invalid List element type {type_name(inner_type)}",
                            arguments[0].span,
                            code="C245",
                            note=(
                                "list elements must be mutable, directly assignable values; "
                                "nested owning lists are not implemented"
                            ),
                        )
                        inner_type = ERROR
                    result = ListType(inner_type)
                elif base.name == "Tuple":
                    elements = tuple(
                        self._resolve_type(argument, allow_opaque=allow_opaque)
                        for argument in arguments
                    )
                    for argument, element in zip(arguments, elements, strict=True):
                        if (
                            is_void(element)
                            or isinstance(
                                element,
                                (ConstType, ReferenceType, ArrayType),
                            )
                            or self._contains_list_value(element)
                        ):
                            self._error(
                                f"invalid Tuple element type {type_name(element)}",
                                argument.span,
                                code="C246",
                                note=(
                                    "tuple elements cannot be directly const, void, "
                                    "references, arrays, or owning lists in this release"
                                ),
                            )
                    result = TupleType(elements)
                else:
                    self._error(
                        f"unsupported generic type {base.name!r}",
                        node.span,
                        code="C155",
                        note="implemented generic types are Result, Tuple, and List",
                    )
                    for argument in arguments:
                        self._resolve_type(argument, allow_opaque=allow_opaque)
                    result = ERROR
            case ast.ConstTypeNode(inner=inner):
                inner_type = self._resolve_type(inner, allow_opaque=allow_opaque)
                if is_void(inner_type):
                    self._error("void cannot be const-qualified here", node.span, code="C101")
                result = ConstType(inner_type)
            case ast.PointerTypeNode(inner=inner):
                result = PointerType(self._resolve_type(inner, allow_opaque=allow_opaque))
            case ast.ReferenceTypeNode(inner=inner):
                inner_type = self._resolve_type(inner, allow_opaque=allow_opaque)
                if is_void(inner_type):
                    self._error("references to void are not allowed", node.span, code="C102")
                result = ReferenceType(inner_type)
            case ast.ArrayTypeNode(inner=inner, length=length):
                inner_type = self._resolve_type(inner, allow_opaque=allow_opaque)
                if (
                    is_void(inner_type)
                    or isinstance(inner_type, ReferenceType)
                    or self._contains_list_value(inner_type)
                ):
                    self._error(
                        f"invalid array element type {type_name(inner_type)}",
                        node.span,
                        code="C103",
                    )
                result = ArrayType(inner_type, length)
            case ast.SliceTypeNode(inner=inner):
                inner_type = self._resolve_type(inner, allow_opaque=allow_opaque)
                if (
                    is_void(inner_type)
                    or isinstance(inner_type, ReferenceType)
                    or self._contains_list_value(inner_type)
                ):
                    self._error(
                        f"invalid slice element type {type_name(inner_type)}",
                        node.span,
                        code="C104",
                    )
                result = SliceType(inner_type)
            case ast.DynTypeNode(interface=interface, is_const=is_const):
                interface_type = self._resolve_type(interface, allow_opaque=False)
                interface_symbol = self.nominal_symbols.get(interface_type)
                if not isinstance(interface_type, ClassType) or not isinstance(
                    interface_symbol, ClassSymbol
                ):
                    self._error(
                        f"dyn requires an abstract class, got {type_name(interface_type)}",
                        node.span,
                        code="C185",
                    )
                    result = ERROR
                elif not interface_symbol.is_abstract:
                    self._error(
                        f"dyn target {interface_symbol.name} is not abstract",
                        node.span,
                        code="C186",
                    )
                    result = ERROR
                else:
                    result = DynType(interface_type, is_const)
            case _:
                raise AssertionError(f"unhandled type node: {node!r}")
        self.type_nodes[id(node)] = result
        return result

    def _declare_global(self, symbol: Symbol) -> Symbol | None:
        previous = self.global_scope.declare(symbol)
        if previous is not None:
            self._duplicate_symbol(symbol, previous)
        return previous

    def _duplicate_symbol(self, symbol: Symbol, previous: Symbol) -> None:
        self._error(
            f"name {symbol.name!r} is already defined",
            symbol.span,
            code="C105",
            note=f"previous definition is at {previous.span.start_line}:{previous.span.start_column}",
        )

    def _validate_decorators(
        self,
        decorators: tuple[str, ...],
        span: Span,
        *,
        allowed: tuple[str, ...],
    ) -> None:
        for decorator in decorators:
            if decorator not in allowed:
                self._error(
                    f"unsupported decorator @{decorator}",
                    span,
                    code="C106",
                )

    def _type_mismatch(self, expected: Type, actual: Type, span: Span) -> None:
        self._error(
            f"expected {type_name(expected)}, got {type_name(actual)}",
            span,
            code="C107",
        )

    def _error(
        self,
        message: str,
        span: Span,
        *,
        code: str,
        note: str | None = None,
    ) -> None:
        self.diagnostics.error(message, span, code=code, note=note)



def _print_conversion(format_spec: str | None) -> str | None:
    if format_spec in (None, ""):
        return None
    spec = format_spec or ""
    if len(spec) == 1:
        return spec if spec in "diuoxXfFeEgGsc" else None
    if spec.startswith(".") and len(spec) > 2 and spec[-1] in "fFeEgG":
        precision = spec[1:-1]
        if precision.isdigit():
            return spec[-1]
    return None


def _is_string_type(type_: Type) -> bool:
    return isinstance(type_, PointerType) and strip_const(type_.inner) == CHAR


def _contains_propagate(expression: ast.Expression) -> bool:
    match expression:
        case ast.PropagateExpr():
            return True
        case ast.UnaryExpr(operand=operand):
            return _contains_propagate(operand)
        case ast.BinaryExpr(left=left, right=right):
            return _contains_propagate(left) or _contains_propagate(right)
        case ast.AttributeExpr(value=value):
            return _contains_propagate(value)
        case ast.IndexExpr(value=value, index=index):
            return _contains_propagate(value) or _contains_propagate(index)
        case ast.SliceExpr(value=value, start=start, stop=stop):
            return (
                _contains_propagate(value)
                or (start is not None and _contains_propagate(start))
                or (stop is not None and _contains_propagate(stop))
            )
        case ast.CallExpr(callee=callee, arguments=arguments):
            return _contains_propagate(callee) or any(
                _contains_propagate(argument.value) for argument in arguments
            )
        case ast.ListLiteralExpr(elements=elements) | ast.TupleLiteralExpr(
            elements=elements
        ):
            return any(_contains_propagate(element) for element in elements)
        case ast.CastExpr(value=value):
            return _contains_propagate(value)
        case ast.AllocExpr(count=count):
            return count is not None and _contains_propagate(count)
        case ast.FStringExpr(parts=parts):
            return any(
                isinstance(part, ast.FStringExpression)
                and _contains_propagate(part.expression)
                for part in parts
            )
        case ast.NameExpr() | ast.LiteralExpr():
            return False
    raise AssertionError(f"unhandled expression: {expression!r}")


def _statement_contains_propagate(statement: ast.Statement) -> bool:
    match statement:
        case ast.VarDeclStmt(initializer=initializer):
            return initializer is not None and _contains_propagate(initializer)
        case ast.AssignStmt(target=target, value=value):
            return _contains_propagate(target) or _contains_propagate(value)
        case ast.ExpressionStmt(expression=expression):
            return _contains_propagate(expression)
    return False

def check(
    module: ast.Module,
    source: str,
    *,
    available_modules: Mapping[str, ModuleSymbol] | None = None,
    module_name: str | None = None,
    c_prefix: str = "",
    module_mode: bool = False,
    is_entry: bool = True,
) -> SemanticModel:
    return Checker(
        module,
        source,
        available_modules=available_modules,
        module_name=module_name,
        c_prefix=c_prefix,
        module_mode=module_mode,
        is_entry=is_entry,
    ).check()
