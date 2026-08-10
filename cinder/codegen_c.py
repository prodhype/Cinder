from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from textwrap import dedent

from cinder import ast
from cinder.ir import (
    AtomicFetchKind,
    IRAtomicCompareExchange,
    IRAtomicExchange,
    IRAtomicFetch,
    IRAtomicInit,
    IRAtomicLoad,
    IRAtomicOperation,
    IRAtomicStore,
    IRFunction,
    IRModule,
)
from cinder.ownership import (
    class_needs_drop as ownership_class_needs_drop,
)
from cinder.ownership import (
    drop_fields,
)
from cinder.ownership import (
    struct_needs_drop as ownership_struct_needs_drop,
)
from cinder.ownership import (
    type_needs_drop as ownership_type_needs_drop,
)
from cinder.symbols import (
    CallResolution,
    ClassSymbol,
    ComptimeVariableSymbol,
    ConstantSymbol,
    EnumSymbol,
    FieldSymbol,
    FunctionSymbol,
    ModuleSymbol,
    NominalSymbol,
    PatternAccessStep,
    PatternBinding,
    PatternResolution,
    StructSymbol,
    SymbolKind,
    UnionSymbol,
    VariableSymbol,
    VariantSymbol,
)
from cinder.types import (
    BOOL,
    CHAR,
    ERROR,
    F32,
    F64,
    I8,
    I16,
    I32,
    I64,
    ISIZE,
    U8,
    U16,
    U32,
    U64,
    USIZE,
    ArrayType,
    AtomicCompareExchangeResultType,
    AtomicType,
    ClassType,
    ClosureType,
    ComptimeCollectionType,
    ComptimeItemType,
    ConstType,
    DynType,
    EnumType,
    FileType,
    FunctionPointerType,
    FunctionValueType,
    ListType,
    MapType,
    MapViewType,
    ModuleType,
    NullType,
    OpaqueType,
    OptionType,
    OwnedType,
    PointerType,
    PrimitiveType,
    RangeType,
    ReferenceType,
    ResultType,
    SetType,
    SliceType,
    StringBuilderType,
    StringType,
    StructType,
    TupleType,
    Type,
    TypeValueType,
    UnionType,
    VariantType,
    atomic_c_name,
    atomic_compare_exchange_result_c_name,
    closure_c_name,
    dyn_c_name,
    file_c_name,
    interface_vtable_c_name,
    is_c_string,
    is_equatable,
    is_void,
    list_c_name,
    map_c_name,
    map_view_c_name,
    nominal_c_name,
    option_c_name,
    owned_c_name,
    result_c_name,
    set_c_name,
    string_builder_c_name,
    string_c_name,
    strip_const,
    strip_reference,
    tuple_c_name,
    type_key,
    type_name,
    value_type,
)

_PARSE_RUNTIME = {
    "parse_i32": "cinder_parse_i32",
    "parse_i64": "cinder_parse_i64",
    "parse_u32": "cinder_parse_u32",
    "parse_u64": "cinder_parse_u64",
    "parse_isize": "cinder_parse_isize",
    "parse_usize": "cinder_parse_usize",
    "parse_f32": "cinder_parse_f32",
    "parse_f64": "cinder_parse_f64",
    "parse_bool": "cinder_parse_bool",
}

_TO_STRING_RUNTIME = {
    BOOL: "cinder_bool_to_string",
    CHAR: "cinder_char_to_string",
    I8: "cinder_i8_to_string",
    I16: "cinder_i16_to_string",
    I32: "cinder_i32_to_string",
    I64: "cinder_i64_to_string",
    U8: "cinder_u8_to_string",
    U16: "cinder_u16_to_string",
    U32: "cinder_u32_to_string",
    U64: "cinder_u64_to_string",
    F32: "cinder_f32_to_string",
    F64: "cinder_f64_to_string",
    ISIZE: "cinder_isize_to_string",
    USIZE: "cinder_usize_to_string",
}

_C_KEYWORDS = {
    "auto",
    "break",
    "case",
    "char",
    "const",
    "continue",
    "default",
    "do",
    "double",
    "else",
    "enum",
    "extern",
    "float",
    "for",
    "goto",
    "if",
    "inline",
    "int",
    "long",
    "register",
    "restrict",
    "return",
    "short",
    "signed",
    "sizeof",
    "static",
    "struct",
    "switch",
    "typedef",
    "union",
    "unsigned",
    "void",
    "volatile",
    "while",
    "_Alignas",
    "_Alignof",
    "_Atomic",
    "_Bool",
    "_Complex",
    "_Generic",
    "_Imaginary",
    "_Noreturn",
    "_Static_assert",
    "_Thread_local",
}


class CWriter:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.indent = 0

    def line(self, text: str = "") -> None:
        if text:
            self.lines.append("    " * self.indent + text)
        else:
            self.lines.append("")

    def open(self, header: str) -> None:
        self.line(header)
        self.line("{")
        self.indent += 1

    def close(self, suffix: str = "") -> None:
        self.indent -= 1
        self.line("}" + suffix)

    def render(self) -> str:
        return "\n".join(self.lines).rstrip() + "\n"

    def raw(self, text: str) -> None:
        self.lines.extend(line.rstrip() for line in dedent(text).strip("\n").splitlines())


@dataclass(slots=True)
class _Cleanup:
    expression: ast.Expression | None = None
    variable: VariableSymbol | None = None
    class_: ClassSymbol | None = None
    container: ListType | MapType | SetType | FileType | None = None
    drop_type: Type | None = None
    iterator_end: tuple[str, str] | None = None
    drop_statement: str | None = None


@dataclass(slots=True)
class _ScopeFrame:
    cleanups: list[_Cleanup] = dataclass_field(default_factory=list)
    loop_body: bool = False


class CGenerator:
    def __init__(self, module: IRModule) -> None:
        self.ir = module
        self.semantic = module.semantic
        self.writer = CWriter()
        self.scope_frames: list[_ScopeFrame] = []
        self.temp_counter = 0
        self.current_function: FunctionSymbol | None = None
        self.current_ir_function: IRFunction | None = None
        self.atomic_calls: dict[int, IRAtomicOperation] = {
            id(operation.call): operation
            for operation in module.atomic_operations
            if not isinstance(operation, IRAtomicInit)
        }
        self.atomic_initializers: dict[int, IRAtomicInit] = {
            id(operation.declaration): operation
            for operation in module.atomic_operations
            if isinstance(operation, IRAtomicInit)
        }
        self.atomic_temp_indices: dict[int, int] = {}
        self.comptime_members: dict[int, object] = {}
        self._classes_by_type = {class_.type: class_ for class_ in self.semantic.classes.values()}
        self._structs_by_type = {
            type_: struct
            for type_, struct in self.semantic.nominal_symbols.items()
            if isinstance(type_, StructType) and isinstance(struct, StructSymbol)
        }

    def _generated_option_types(self) -> tuple[OptionType, ...]:
        options = set(self.ir.option_types)
        if self.ir.uses_file:
            # The complete File helper suite is shared behind one guard.  Every
            # module that can emit it therefore needs the read_line payload type,
            # even when that module only calls another File method.
            options.add(OptionType(StringType()))
        return tuple(sorted(options, key=type_key))

    def generate(self) -> str:
        self._emit_preamble()
        self._emit_atomic_type_definitions(header_mode=False)
        self._emit_forward_declarations()
        self._emit_enum_definitions()
        self._emit_slice_types()
        self._emit_list_type_definitions()
        self._emit_file_type_definition()
        self._emit_map_view_types()
        self._emit_map_set_type_definitions()
        self._emit_owned_type_definitions()
        self._emit_type_definitions()
        self._emit_interface_definitions()
        self._emit_class_support_declarations()
        self._emit_ownership_drop_prototypes()
        self._emit_aggregate_drop_helpers()
        self._emit_owned_helpers()
        self._emit_list_helpers()
        self._emit_file_helpers()
        self._emit_map_helpers()
        self._emit_set_helpers()
        self._emit_collection_print_helpers()
        self._emit_sort_helpers()
        self._emit_reflection_declarations()
        self._emit_function_prototypes()
        self._emit_static_asserts()
        self._emit_globals()
        self._emit_reflection_definitions()
        self._emit_class_support_definitions()
        self._emit_function_definitions()
        return self.writer.render()

    def generate_header(
        self,
        header_name: str,
        dependency_headers: tuple[str, ...] = (),
    ) -> str:
        guard = c_identifier(header_name).upper() + "_INCLUDED"
        self.writer.line("/* Generated by Cinder 0.5.0. */")
        self.writer.line(f"/* Public declarations for {self.semantic.module_name}. */")
        self.writer.line("/* This header is portable C11. */")
        self.writer.line()
        self.writer.line(f"#ifndef {guard}")
        self.writer.line(f"#define {guard}")
        self.writer.line()
        self.writer.line('#include "cinder_runtime.h"')
        self.writer.line("#include <stdlib.h>")
        self.writer.line("#include <string.h>")
        for dependency_header in dict.fromkeys(dependency_headers):
            self.writer.line(f'#include "{dependency_header}"')
        for include in self.semantic.includes:
            self.writer.line(f"#include {include}")
        if self.ir.atomic_types:
            self.writer.line("#ifndef __cplusplus")
            self.writer.line("#include <stdatomic.h>")
            self.writer.line("#endif")
        self.writer.line()
        self._emit_atomic_type_definitions(header_mode=True)
        self._emit_forward_declarations()
        self._emit_enum_definitions()
        self._emit_slice_types()
        self._emit_list_type_definitions()
        self._emit_file_type_definition()
        self._emit_map_view_types()
        self._emit_map_set_type_definitions()
        self._emit_owned_type_definitions()
        self._emit_type_definitions()
        self._emit_interface_definitions()
        self.writer.line("#ifdef __cplusplus")
        self.writer.line('extern "C" {')
        self.writer.line("#endif")
        self.writer.line()
        self._emit_class_support_declarations()
        self._emit_ownership_drop_prototypes()
        self._emit_aggregate_drop_helpers()
        self._emit_owned_helpers()
        self._emit_list_helpers()
        self._emit_file_helpers()
        self._emit_map_helpers()
        self._emit_set_helpers()
        self._emit_collection_print_helpers()
        self._emit_reflection_declarations()
        self._emit_function_prototypes()
        self._emit_global_declarations()
        self._emit_static_asserts()
        self.writer.line("#ifdef __cplusplus")
        self.writer.line("}")
        self.writer.line("#endif")
        self.writer.line()
        self.writer.line(f"#endif /* {guard} */")
        return self.writer.render()

    def generate_source(self, header_name: str) -> str:
        source_path = self.semantic.module.path.as_posix()
        self.writer.line("/* Generated by Cinder 0.5.0. */")
        self.writer.line(f"/* Source: {source_path} */")
        self.writer.line("/* This translation unit is portable C11. */")
        self.writer.line()
        self.writer.line(f'#include "{header_name}"')
        self.writer.line()
        self._emit_sort_helpers()
        self._emit_globals()
        self._emit_reflection_definitions()
        self._emit_class_support_definitions()
        self._emit_function_definitions()
        return self.writer.render()

    def _emit_preamble(self) -> None:
        source_path = self.semantic.module.path.as_posix()
        self.writer.line("/* Generated by Cinder 0.5.0. */")
        self.writer.line(f"/* Source: {source_path} */")
        self.writer.line("/* This file is portable C11 and may be read or compiled directly. */")
        self.writer.line()
        self.writer.line('#include "cinder_runtime.h"')
        self.writer.line("#include <stdlib.h>")
        self.writer.line("#include <string.h>")
        for module in self.semantic.modules.values():
            if module.generated_header is not None:
                self.writer.line(f'#include "{module.generated_header}"')
        for include in self.semantic.includes:
            self.writer.line(f"#include {include}")
        if self.ir.atomic_types:
            self.writer.line("#include <stdatomic.h>")
        self.writer.line()

    def _emit_atomic_type_definitions(self, *, header_mode: bool) -> None:
        emitted = False
        for atomic_type in self.ir.atomic_types:
            name = c_identifier(atomic_c_name(atomic_type))
            guard = f"CINDER_DECLARED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {name} {name};")
            if header_mode:
                self.writer.line("#ifndef __cplusplus")
            self.writer.line(f"struct {name}")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(f"_Atomic({c_type_expression(atomic_type.inner)}) value;")
            self.writer.indent -= 1
            self.writer.line("};")
            if header_mode:
                self.writer.line("#endif")
            self.writer.line("#endif")
            emitted = True

        for result_type in self.ir.atomic_result_types:
            name = c_identifier(atomic_compare_exchange_result_c_name(result_type))
            guard = f"CINDER_DEFINED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {name}")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line("bool exchanged;")
            self.writer.line(c_decl(result_type.inner, "observed") + ";")
            self.writer.indent -= 1
            self.writer.line(f"}} {name};")
            self.writer.line("#endif")
            emitted = True

        if emitted:
            self.writer.line()

    def _emit_forward_declarations(self) -> None:
        emitted = False
        for struct in self.ir.structs:
            name = c_identifier(struct.symbol.c_name)
            if struct.symbol.type_args or struct.symbol.template_name:
                guard = f"CINDER_DECLARED_{name.upper()}"
                self.writer.line(f"#ifndef {guard}")
                self.writer.line(f"#define {guard}")
                self.writer.line(f"typedef struct {name} {name};")
                self.writer.line("#endif")
            else:
                self.writer.line(f"typedef struct {name} {name};")
            emitted = True
        for class_ in self.ir.classes:
            name = c_identifier(class_.symbol.c_name)
            if class_.symbol.type_args or class_.symbol.template_name:
                guard = f"CINDER_DECLARED_{name.upper()}"
                self.writer.line(f"#ifndef {guard}")
                self.writer.line(f"#define {guard}")
                self.writer.line(f"typedef struct {name} {name};")
                self.writer.line("#endif")
            else:
                self.writer.line(f"typedef struct {name} {name};")
            emitted = True
        for union in self.ir.unions:
            name = c_identifier(union.symbol.c_name)
            if union.symbol.type_args or union.symbol.template_name:
                guard = f"CINDER_DECLARED_{name.upper()}"
                self.writer.line(f"#ifndef {guard}")
                self.writer.line(f"#define {guard}")
                self.writer.line(f"typedef union {name} {name};")
                self.writer.line("#endif")
            else:
                self.writer.line(f"typedef union {name} {name};")
            emitted = True
        for variant in self.ir.variants:
            name = c_identifier(variant.symbol.c_name)
            if variant.symbol.type_args or variant.symbol.template_name:
                guard = f"CINDER_DECLARED_{name.upper()}"
                self.writer.line(f"#ifndef {guard}")
                self.writer.line(f"#define {guard}")
                self.writer.line(f"typedef struct {name} {name};")
                self.writer.line("#endif")
            else:
                self.writer.line(f"typedef struct {name} {name};")
            emitted = True
        for tuple_type in self.ir.tuple_types:
            name = c_identifier(tuple_c_name(tuple_type))
            guard = f"CINDER_DECLARED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {name} {name};")
            self.writer.line("#endif")
            emitted = True
        for closure_type in self.ir.closure_types:
            name = c_identifier(closure_c_name(closure_type))
            guard = f"CINDER_DECLARED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {name} {name};")
            self.writer.line("#endif")
            emitted = True
        for list_type in self.ir.list_types:
            name = c_identifier(list_c_name(list_type))
            guard = f"CINDER_DECLARED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {name} {name};")
            self.writer.line("#endif")
            emitted = True
        if self.ir.uses_file:
            name = file_c_name()
            guard = f"CINDER_DECLARED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {name} {name};")
            self.writer.line("#endif")
            emitted = True
        for map_type in self.ir.map_types:
            name = c_identifier(map_c_name(map_type))
            guard = f"CINDER_DECLARED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {name} {name};")
            self.writer.line("#endif")
            emitted = True
        for set_type in self.ir.set_types:
            name = c_identifier(set_c_name(set_type))
            guard = f"CINDER_DECLARED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {name} {name};")
            self.writer.line("#endif")
            emitted = True
        for view_type in self.ir.map_view_types:
            name = c_identifier(map_view_c_name(view_type))
            guard = f"CINDER_DECLARED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {name} {name};")
            self.writer.line("#endif")
            emitted = True
        for result_type in self.ir.result_types:
            name = c_identifier(result_c_name(result_type))
            guard = f"CINDER_DECLARED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {name} {name};")
            self.writer.line("#endif")
            emitted = True
        for option_type in self._generated_option_types():
            name = c_identifier(option_c_name(option_type))
            guard = f"CINDER_DECLARED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {name} {name};")
            self.writer.line("#endif")
            emitted = True
        for owned_type in self.ir.owned_types:
            name = c_identifier(owned_c_name(owned_type))
            guard = f"CINDER_DECLARED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {name} {name};")
            self.writer.line("#endif")
            emitted = True
        for class_ in self.ir.classes:
            if not class_.symbol.is_abstract:
                continue
            vtable = c_identifier(interface_vtable_c_name(class_.symbol.type))
            dyn = c_identifier(dyn_c_name(class_.symbol.type))
            self.writer.line(f"typedef struct {vtable} {vtable};")
            self.writer.line(f"typedef struct {dyn}")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line("void *object;")
            self.writer.line(f"const {vtable} *vtable;")
            self.writer.indent -= 1
            self.writer.line(f"}} {dyn};")
            emitted = True
        if emitted:
            self.writer.line()

    def _emit_enum_definitions(self) -> None:
        for enum in self.ir.enums:
            name = c_identifier(enum.symbol.c_name)
            specialized = bool(enum.symbol.type_args or enum.symbol.template_name)
            if specialized:
                guard = f"CINDER_DEFINED_{name.upper()}"
                self.writer.line(f"#ifndef {guard}")
                self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef enum {name}")
            self.writer.line("{")
            self.writer.indent += 1
            for index, member in enumerate(enum.symbol.members.values()):
                suffix = "," if index + 1 < len(enum.symbol.members) else ""
                self.writer.line(f"{c_identifier(member.c_name)} = {member.value}{suffix}")
            self.writer.indent -= 1
            self.writer.line(f"}} {name};")
            if specialized:
                self.writer.line(f"#endif /* {guard} */")
            self.writer.line()

    def _emit_slice_types(self) -> None:
        available = set(self.ir.slice_types)

        for slice_type in self.ir.slice_types:
            name = self._slice_name(slice_type)
            guard = f"CINDER_DEFINED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {name} {{")
            self.writer.indent += 1
            self.writer.line(c_decl(PointerType(slice_type.inner), "data") + ";")
            self.writer.line("size_t length;")
            self.writer.indent -= 1
            self.writer.line(f"}} {name};")
            self.writer.line(f"#endif /* {guard} */")
            self.writer.line()

        for slice_type in self.ir.slice_types:
            name = self._slice_name(slice_type)
            guard = f"CINDER_HELPERS_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(
                f"static inline CINDER_MAYBE_UNUSED {name} {name}_from({name} value, size_t start)"
            )
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(
                f"return ({name}){{ .data = value.data + start, .length = value.length - start }};"
            )
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line()
            self.writer.line(
                f"static inline CINDER_MAYBE_UNUSED {name} {name}_sub({name} value, size_t start, size_t stop)"
            )
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(
                f"return ({name}){{ .data = value.data + start, .length = stop - start }};"
            )
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line(f"#endif /* {guard} */")
            self.writer.line()

        for slice_type in self.ir.slice_types:
            if not isinstance(slice_type.inner, ConstType):
                continue
            mutable = SliceType(slice_type.inner.inner)
            if mutable not in available:
                continue
            name = self._slice_name(slice_type)
            mutable_name = self._slice_name(mutable)
            guard = f"CINDER_CONVERT_{mutable_name.upper()}_TO_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(
                f"static inline CINDER_MAYBE_UNUSED {name} {name}_from_mutable({mutable_name} value)"
            )
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(f"return ({name}){{ .data = value.data, .length = value.length }};")
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line(f"#endif /* {guard} */")
            self.writer.line()

    def _emit_list_type_definitions(self) -> None:
        for list_type in self.ir.list_types:
            name = c_identifier(list_c_name(list_type))
            guard = f"CINDER_DEFINED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"struct {name}")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(c_decl(PointerType(list_type.inner), "data") + ";")
            self.writer.line("size_t length;")
            self.writer.line("size_t capacity;")
            self.writer.indent -= 1
            self.writer.line("};")
            self.writer.line(f"#endif /* {guard} */")
            self.writer.line()

    def _emit_file_type_definition(self) -> None:
        if not self.ir.uses_file:
            return
        name = file_c_name()
        guard = f"CINDER_DEFINED_{name.upper()}"
        self.writer.line(f"#ifndef {guard}")
        self.writer.line(f"#define {guard}")
        self.writer.line(f"struct {name}")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("FILE *handle;")
        self.writer.indent -= 1
        self.writer.line("};")
        self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_map_set_type_definitions(self) -> None:
        for map_type in self.ir.map_types:
            name = c_identifier(map_c_name(map_type))
            entry_name = f"{name}_Entry"
            guard = f"CINDER_DEFINED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {entry_name}")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(c_decl(map_type.key, "key") + ";")
            self.writer.line(c_decl(map_type.value, "value") + ";")
            self.writer.line("uint64_t hash;")
            self.writer.line("bool occupied;")
            self.writer.indent -= 1
            self.writer.line(f"}} {entry_name};")
            self.writer.line()
            self.writer.line(f"struct {name}")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(f"{entry_name} *entries;")
            self.writer.line("size_t entries_length;")
            self.writer.line("size_t entries_capacity;")
            self.writer.line("size_t *buckets;")
            self.writer.line("size_t capacity;")
            self.writer.line("size_t length;")
            self.writer.line("size_t tombstones;")
            self.writer.line("size_t active_iterators;")
            self.writer.indent -= 1
            self.writer.line("};")
            self.writer.line(f"#endif /* {guard} */")
            self.writer.line()

        for set_type in self.ir.set_types:
            name = c_identifier(set_c_name(set_type))
            entry_name = f"{name}_Entry"
            guard = f"CINDER_DEFINED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"typedef struct {entry_name}")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(c_decl(set_type.inner, "value") + ";")
            self.writer.line("uint64_t hash;")
            self.writer.line("unsigned char state;")
            self.writer.indent -= 1
            self.writer.line(f"}} {entry_name};")
            self.writer.line()
            self.writer.line(f"struct {name}")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(f"{entry_name} *entries;")
            self.writer.line("size_t capacity;")
            self.writer.line("size_t length;")
            self.writer.line("size_t tombstones;")
            self.writer.line("size_t active_iterators;")
            self.writer.indent -= 1
            self.writer.line("};")
            self.writer.line(f"#endif /* {guard} */")
            self.writer.line()

    def _emit_map_view_types(self) -> None:
        for view_type in self.ir.map_view_types:
            name = c_identifier(map_view_c_name(view_type))
            map_name = c_identifier(map_c_name(view_type.map_type))
            guard = f"CINDER_DEFINED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"struct {name}")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(f"const {map_name} *map;")
            self.writer.indent -= 1
            self.writer.line("};")
            self.writer.line(f"#endif /* {guard} */")
            self.writer.line()

    def _emit_owned_type_definitions(self) -> None:
        for owned_type in self.ir.owned_types:
            name = c_identifier(owned_c_name(owned_type))
            guard = f"CINDER_DEFINED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(f"struct {name}")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(c_decl(PointerType(owned_type.inner), "ptr") + ";")
            self.writer.indent -= 1
            self.writer.line("};")
            self.writer.line(f"#endif /* {guard} */")
            self.writer.line()

    def _emit_owned_helpers(self) -> None:
        for owned_type in self.ir.owned_types:
            name = c_identifier(owned_c_name(owned_type))
            guard = f"CINDER_HELPERS_{name.upper()}"
            inner = owned_type.inner
            inner_c_type = c_type_expression(inner)
            pointer_c_type = c_type_expression(PointerType(inner))
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(
                f"static inline CINDER_MAYBE_UNUSED {name} {name}_new({c_decl(inner, 'value')})"
            )
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(
                f"{pointer_c_type} ptr = ({pointer_c_type})cinder_alloc(1, sizeof({inner_c_type}));"
            )
            self.writer.line("*ptr = value;")
            self.writer.line(f"return ({name}){{ .ptr = ptr }};")
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line()
            self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *owned)")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line("if (owned == NULL || owned->ptr == NULL)")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line("return;")
            self.writer.indent -= 1
            self.writer.line("}")
            if self._type_needs_drop(inner):
                self.writer.line(self._drop_expression(inner, "(*owned->ptr)"))
            self.writer.line("free(owned->ptr);")
            self.writer.line("owned->ptr = NULL;")
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line(f"#endif /* {guard} */")
            self.writer.line()

    def _emit_type_definitions(self) -> None:
        emitted_options: set[OptionType] = set()
        for type_ in self.ir.definition_order:
            nominal = self.semantic.nominal_symbols.get(type_)
            if isinstance(nominal, StructSymbol):
                self._emit_struct_definition(nominal)
            elif isinstance(nominal, ClassSymbol):
                self._emit_class_definition(nominal)
            elif isinstance(nominal, UnionSymbol):
                self._emit_union_definition(nominal)
            elif isinstance(nominal, VariantSymbol):
                self._emit_variant_definition(nominal)
            elif isinstance(type_, ResultType):
                self._emit_result_definition(type_)
            elif isinstance(type_, OptionType):
                self._emit_option_definition(type_)
                emitted_options.add(type_)
            elif isinstance(type_, TupleType):
                self._emit_tuple_definition(type_)
            elif isinstance(type_, ClosureType):
                self._emit_closure_definition(type_)
            else:
                raise AssertionError(f"unhandled definition type: {type_!r}")
        for option_type in self._generated_option_types():
            if option_type not in emitted_options:
                self._emit_option_definition(option_type)

    def _emit_list_helpers(self) -> None:
        for list_type in self.ir.list_types:
            name = c_identifier(list_c_name(list_type))
            guard = f"CINDER_HELPERS_{name.upper()}"
            element = list_type.inner
            element_pointer = PointerType(element)
            const_element_pointer = PointerType(ConstType(element))
            element_c_type = c_type_expression(element)

            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
            self.writer.line(
                f"static inline CINDER_MAYBE_UNUSED {name} {name}_from_values("
                f"{c_decl(const_element_pointer, 'values')}, size_t length)"
            )
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(f"{name} result = {{ NULL, 0, 0 }};")
            self.writer.line("if (length == 0)")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line("return result;")
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line(
                f"result.data = ({c_type_expression(element_pointer)})"
                f"cinder_alloc(length, sizeof({element_c_type}));"
            )
            self.writer.line("memcpy(result.data, values, length * sizeof(*result.data));")
            self.writer.line("result.length = length;")
            self.writer.line("result.capacity = length;")
            self.writer.line("return result;")
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line()

            self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value)")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line("if (value == NULL)")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line("return;")
            self.writer.indent -= 1
            self.writer.line("}")
            if self._type_needs_drop(element):
                self.writer.line("for (size_t index = 0; index < value->length; ++index)")
                self.writer.line("{")
                self.writer.indent += 1
                self.writer.line(self._drop_expression(element, "value->data[index]"))
                self.writer.indent -= 1
                self.writer.line("}")
            self.writer.line("free(value->data);")
            self.writer.line("value->data = NULL;")
            self.writer.line("value->length = 0;")
            self.writer.line("value->capacity = 0;")
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line()

            self.writer.line(
                f"static inline CINDER_MAYBE_UNUSED void {name}_append("
                f"{name} *value, {c_decl(element, 'item')})"
            )
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line("if (value->length == SIZE_MAX)")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line('cinder_panic("List length overflow");')
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line(
                f"value->data = ({c_type_expression(element_pointer)})cinder_grow_array("
            )
            self.writer.indent += 1
            self.writer.line("value->data,")
            self.writer.line("&value->capacity,")
            self.writer.line("value->length + 1,")
            self.writer.line("sizeof(*value->data)")
            self.writer.indent -= 1
            self.writer.line(");")
            self.writer.line("value->data[value->length] = item;")
            self.writer.line("value->length += 1;")
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line()

            self.writer.line(
                f"static inline CINDER_MAYBE_UNUSED {c_decl(element, f'{name}_pop')}({name} *value)"
            )
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line("if (value->length == 0)")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line('cinder_panic("pop from empty List");')
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line("value->length -= 1;")
            self.writer.line(f"{c_decl(element, 'result')} = value->data[value->length];")
            if self._type_needs_drop(element):
                # Move out: invalidate the capacity slot so it is not a second
                # owner. Append may reuse the slot without drop glue.
                self.writer.line("memset(&value->data[value->length], 0, sizeof(*value->data));")
            self.writer.line("return result;")
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line()

            self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_clear({name} *value)")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line("if (value == NULL)")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line("return;")
            self.writer.indent -= 1
            self.writer.line("}")
            if self._type_needs_drop(element):
                self.writer.line("for (size_t index = 0; index < value->length; ++index)")
                self.writer.line("{")
                self.writer.indent += 1
                self.writer.line(self._drop_expression(element, "value->data[index]"))
                self.writer.indent -= 1
                self.writer.line("}")
            self.writer.line("value->length = 0;")
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line(f"#endif /* {guard} */")
            self.writer.line()

    def _emit_file_helpers(self) -> None:
        if not self.ir.uses_file:
            return
        name = file_c_name()
        guard = f"CINDER_HELPERS_{name.upper()}"
        slice_name = self._slice_name(SliceType(ConstType(U8)))
        line_option = OptionType(StringType())
        line_option_name = c_identifier(option_c_name(line_option))
        self.writer.line(f"#ifndef {guard}")
        self.writer.line(f"#define {guard}")
        self.writer.line(
            f"static inline CINDER_MAYBE_UNUSED {name} {name}_open("
            "const char *path, const char *mode)"
        )
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"{name} result;")
        self.writer.line("result.handle = fopen(path, mode);")
        self.writer.line("if (result.handle == NULL)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('cinder_panic("could not open file");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("return result;")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

        self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (value->handle != NULL)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("fclose(value->handle);")
        self.writer.line("value->handle = NULL;")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

        self.writer.line(
            f"static inline CINDER_MAYBE_UNUSED size_t {name}_write("
            f"{name} *value, {slice_name} data)"
        )
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (value->handle == NULL)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('cinder_panic("write on closed File");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("return fwrite(data.data, 1, data.length, value->handle);")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

        self.writer.line(
            f"static inline CINDER_MAYBE_UNUSED size_t {name}_write_string("
            f"{name} *value, const {string_c_name()} *data)"
        )
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (value->handle == NULL)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('cinder_panic("write on closed File");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("return fwrite(cinder_string_cstr(data), 1, data->length, value->handle);")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

        mutable_slice_name = self._slice_name(SliceType(U8))
        self.writer.line(
            f"static inline CINDER_MAYBE_UNUSED size_t {name}_read("
            f"{name} *value, {mutable_slice_name} buffer)"
        )
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (value->handle == NULL)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('cinder_panic("read on closed File");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("size_t counted = fread(buffer.data, 1, buffer.length, value->handle);")
        self.writer.line("if (counted < buffer.length && ferror(value->handle))")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('cinder_panic("File.read failed");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("return counted;")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

        self.writer.line(
            f"static inline CINDER_MAYBE_UNUSED {line_option_name} {name}_read_line({name} *value)"
        )
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (value->handle == NULL)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('cinder_panic("read_line on closed File");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line(f"{line_option_name} result = {{ {line_option_name}_Tag_None, {{ 0 }} }};")
        self.writer.line(f"{string_c_name()} line = {{ 0 }};")
        self.writer.line("if (!cinder_read_line(value->handle, &line))")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("return result;")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line(f"result.tag = {line_option_name}_Tag_Some;")
        self.writer.line("result.data.value = line;")
        self.writer.line("return result;")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

        self.writer.line(
            f"static inline CINDER_MAYBE_UNUSED {string_c_name()} {name}_read_text({name} *value)"
        )
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (value->handle == NULL)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('cinder_panic("read_text on closed File");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("return cinder_read_all_text(value->handle);")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

        list_u8 = ListType(U8)
        list_name = c_identifier(list_c_name(list_u8))
        self.writer.line(
            f"static inline CINDER_MAYBE_UNUSED {list_name} {name}_read_all({name} *value)"
        )
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (value->handle == NULL)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('cinder_panic("read_all on closed File");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line(f"{list_name} result = {{ NULL, 0, 0 }};")
        self.writer.line("for (;;)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (result.length == SIZE_MAX)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"{list_name}_drop(&result);")
        self.writer.line('cinder_panic("File.read_all length overflow");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("result.data = (uint8_t *)cinder_grow_array(")
        self.writer.indent += 1
        self.writer.line("result.data,")
        self.writer.line("&result.capacity,")
        self.writer.line("result.length + 1,")
        self.writer.line("sizeof(*result.data)")
        self.writer.indent -= 1
        self.writer.line(");")
        self.writer.line("size_t available = result.capacity - result.length;")
        self.writer.line(
            "size_t counted = fread(result.data + result.length, 1, available, value->handle);"
        )
        self.writer.line("result.length += counted;")
        self.writer.line("if (counted < available)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (ferror(value->handle))")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"{list_name}_drop(&result);")
        self.writer.line('cinder_panic("File.read_all failed");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("break;")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("return result;")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

        self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_flush({name} *value)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (value->handle == NULL)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('cinder_panic("flush on closed File");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("fflush(value->handle);")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

        self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_close({name} *value)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"{name}_drop(value);")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_map_helpers(self) -> None:
        for map_type in self.ir.map_types:
            self._emit_map_helper_suite(map_type)

    def _emit_map_helper_suite(self, map_type: MapType) -> None:
        name = c_identifier(map_c_name(map_type))
        entry_name = f"{name}_Entry"
        option_name = c_identifier(option_c_name(OptionType(map_type.value)))
        key_decl = c_decl(map_type.key, "key")
        value_decl = c_decl(map_type.value, "item_value")
        keys_decl = c_decl(PointerType(ConstType(map_type.key)), "keys")
        values_decl = c_decl(PointerType(ConstType(map_type.value)), "values")
        hash_key = self._hash_expression(map_type.key, "key")
        equal_key = self._equal_expression(
            map_type.key,
            "entry->key",
            "key",
        )
        clone_key = self._clone_expression(map_type.key, "key")
        drop_key = self._drop_expression(map_type.key, "entry->key")
        drop_value = self._drop_expression(map_type.value, "entry->value")
        get_value = (
            self._clone_expression(
                map_type.value,
                "value->entries[value->buckets[bucket]].value",
            )
            if isinstance(value_type(map_type.value), StringType)
            else "value->entries[value->buckets[bucket]].value"
        )
        clear_popped_value = (
            "memset(&entry->value, 0, sizeof(entry->value));"
            if self._type_needs_drop(map_type.value)
            else ""
        )
        drop_old_value = self._drop_expression(
            map_type.value,
            "value->entries[value->buckets[bucket]].value",
        )
        keys_view = c_identifier(map_view_c_name(MapViewType(map_type, "keys")))
        values_view = c_identifier(map_view_c_name(MapViewType(map_type, "values")))
        items_view = c_identifier(map_view_c_name(MapViewType(map_type, "items")))
        item_tuple = TupleType((map_type.key, map_type.value))
        item_tuple_name = c_identifier(tuple_c_name(item_tuple))
        view_membership_helpers = ""
        if is_equatable(map_type.value):
            needle_decl = c_decl(map_type.value, "needle")
            value_equal = self._equal_expression(
                map_type.value,
                "entry->value",
                "needle",
            )
            item_value_equal = self._equal_expression(
                map_type.value,
                "entry->value",
                "needle.item_1",
            )
            view_membership_helpers = dedent(
                f"""
                static inline CINDER_MAYBE_UNUSED bool {name}_values_contains(
                    const {name} *value,
                    {needle_decl}
                )
                {{
                    for (size_t index = 0; index < value->entries_length; ++index) {{
                        const {entry_name} *entry = &value->entries[index];
                        if (entry->occupied && {value_equal}) {{
                            return true;
                        }}
                    }}
                    return false;
                }}

                static inline CINDER_MAYBE_UNUSED bool {name}_items_contains(
                    const {name} *value,
                    {item_tuple_name} needle
                )
                {{
                    if (value == NULL || value->capacity == 0) {{
                        return false;
                    }}
                    bool found = false;
                    size_t bucket = {name}_find_bucket(
                        value,
                        needle.item_0,
                        {name}_hash(needle.item_0),
                        &found
                    );
                    if (!found) {{
                        return false;
                    }}
                    const {entry_name} *entry =
                        &value->entries[value->buckets[bucket]];
                    return {item_value_equal};
                }}
                """
            ).strip()
        guard = f"CINDER_HELPERS_{name.upper()}"

        self.writer.raw(
            f"""
            #ifndef {guard}
            #define {guard}
            #define {name}_BUCKET_EMPTY ((size_t)-1)
            #define {name}_BUCKET_TOMBSTONE ((size_t)-2)

            static inline CINDER_MAYBE_UNUSED uint64_t {name}_hash({key_decl})
            {{
                return {hash_key};
            }}

            static inline CINDER_MAYBE_UNUSED bool {name}_key_equal(
                const {entry_name} *entry,
                {key_decl}
            )
            {{
                return {equal_key};
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_rehash(
                {name} *value,
                size_t new_capacity
            )
            {{
                if (new_capacity < 8 || (new_capacity & (new_capacity - 1)) != 0) {{
                    cinder_panic("invalid Map capacity");
                }}

                size_t write_index = 0;
                for (size_t read_index = 0; read_index < value->entries_length; ++read_index) {{
                    if (!value->entries[read_index].occupied) {{
                        continue;
                    }}
                    if (write_index != read_index) {{
                        value->entries[write_index] = value->entries[read_index];
                    }}
                    write_index += 1;
                }}
                value->entries_length = write_index;

                size_t *new_buckets = (size_t *)cinder_alloc(
                    new_capacity,
                    sizeof(size_t)
                );
                for (size_t index = 0; index < new_capacity; ++index) {{
                    new_buckets[index] = {name}_BUCKET_EMPTY;
                }}
                for (size_t entry_index = 0; entry_index < value->entries_length; ++entry_index) {{
                    size_t bucket = value->entries[entry_index].hash & (new_capacity - 1);
                    while (new_buckets[bucket] != {name}_BUCKET_EMPTY) {{
                        bucket = (bucket + 1) & (new_capacity - 1);
                    }}
                    new_buckets[bucket] = entry_index;
                }}
                free(value->buckets);
                value->buckets = new_buckets;
                value->capacity = new_capacity;
                value->tombstones = 0;
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_ensure_capacity({name} *value)
            {{
                if (
                    value->capacity != 0
                    && value->length + value->tombstones
                        < value->capacity - value->capacity / 4
                    && value->entries_length - value->length
                        <= value->length + 8
                ) {{
                    return;
                }}
                size_t new_capacity = value->capacity == 0 ? 8 : value->capacity;
                if (
                    value->capacity != 0
                    && value->length + 1
                        >= value->capacity - value->capacity / 4
                ) {{
                    if (value->capacity > SIZE_MAX / 2) {{
                        cinder_panic("Map capacity overflow");
                    }}
                    new_capacity = value->capacity * 2;
                }}
                if (new_capacity > SIZE_MAX / sizeof(size_t)) {{
                    cinder_panic("Map capacity overflow");
                }}
                {name}_rehash(value, new_capacity);
            }}

            static inline CINDER_MAYBE_UNUSED size_t {name}_find_bucket(
                const {name} *value,
                {key_decl},
                uint64_t hash,
                bool *found
            )
            {{
                if (value->capacity == 0) {{
                    *found = false;
                    return {name}_BUCKET_EMPTY;
                }}
                size_t first_tombstone = {name}_BUCKET_EMPTY;
                size_t bucket = hash & (value->capacity - 1);
                for (;;) {{
                    size_t entry_index = value->buckets[bucket];
                    if (entry_index == {name}_BUCKET_EMPTY) {{
                        *found = false;
                        return first_tombstone == {name}_BUCKET_EMPTY
                            ? bucket
                            : first_tombstone;
                    }}
                    if (entry_index == {name}_BUCKET_TOMBSTONE) {{
                        if (first_tombstone == {name}_BUCKET_EMPTY) {{
                            first_tombstone = bucket;
                        }}
                    }} else {{
                        const {entry_name} *entry = &value->entries[entry_index];
                        if (
                            entry->occupied
                            && entry->hash == hash
                            && {name}_key_equal(entry, key)
                        ) {{
                            *found = true;
                            return bucket;
                        }}
                    }}
                    bucket = (bucket + 1) & (value->capacity - 1);
                }}
            }}

            static inline CINDER_MAYBE_UNUSED bool {name}_contains(
                const {name} *value,
                {key_decl}
            )
            {{
                if (value == NULL || value->capacity == 0) {{
                    return false;
                }}
                bool found = false;
                (void){name}_find_bucket(value, key, {name}_hash(key), &found);
                return found;
            }}

            {view_membership_helpers}

            static inline CINDER_MAYBE_UNUSED {option_name} {name}_get(
                const {name} *value,
                {key_decl}
            )
            {{
                {option_name} result = {{ {option_name}_Tag_None, {{ 0 }} }};
                if (value == NULL || value->capacity == 0) {{
                    return result;
                }}
                bool found = false;
                size_t bucket = {name}_find_bucket(
                    value,
                    key,
                    {name}_hash(key),
                    &found
                );
                if (!found) {{
                    return result;
                }}
                result.tag = {option_name}_Tag_Some;
                result.data.value = {get_value};
                return result;
            }}

            static inline CINDER_MAYBE_UNUSED {c_decl(map_type.value, f"{name}_lookup_or_panic")}(
                const {name} *value,
                {key_decl}
            )
            {{
                bool found = false;
                size_t bucket = {name}_find_bucket(
                    value,
                    key,
                    {name}_hash(key),
                    &found
                );
                if (!found) {{
                    cinder_panic("Map key not found");
                }}
                return {get_value};
            }}

            static inline CINDER_MAYBE_UNUSED {c_decl(PointerType(ConstType(map_type.value)), f"{name}_lookup_ptr_or_panic")}(
                const {name} *value,
                {key_decl}
            )
            {{
                bool found = false;
                size_t bucket = {name}_find_bucket(
                    value,
                    key,
                    {name}_hash(key),
                    &found
                );
                if (!found) {{
                    cinder_panic("Map key not found");
                }}
                return &value->entries[value->buckets[bucket]].value;
            }}

            static inline CINDER_MAYBE_UNUSED {c_decl(PointerType(map_type.value), f"{name}_lookup_mut_or_panic")}(
                {name} *value,
                {key_decl}
            )
            {{
                if (value == NULL) {{
                    cinder_panic("null Map receiver");
                }}
                if (value->active_iterators != 0) {{
                    cinder_panic("cannot mutate Map during iteration");
                }}
                bool found = false;
                size_t bucket = {name}_find_bucket(
                    value,
                    key,
                    {name}_hash(key),
                    &found
                );
                if (!found) {{
                    cinder_panic("Map key not found");
                }}
                return &value->entries[value->buckets[bucket]].value;
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_set(
                {name} *value,
                {key_decl},
                {value_decl}
            )
            {{
                if (value == NULL) {{
                    cinder_panic("null Map receiver");
                }}
                if (value->active_iterators != 0) {{
                    cinder_panic("cannot structurally mutate Map during iteration");
                }}
                uint64_t hash = {name}_hash(key);
                bool found = false;
                size_t bucket = {name}_find_bucket(value, key, hash, &found);
                if (found) {{
                    {drop_old_value}
                    value->entries[value->buckets[bucket]].value = item_value;
                    return;
                }}
                {name}_ensure_capacity(value);
                bucket = {name}_find_bucket(value, key, hash, &found);
                if (found) {{
                    {drop_old_value}
                    value->entries[value->buckets[bucket]].value = item_value;
                    return;
                }}
                if (value->entries_length == SIZE_MAX) {{
                    cinder_panic("Map length overflow");
                }}
                value->entries = ({entry_name} *)cinder_grow_array(
                    value->entries,
                    &value->entries_capacity,
                    value->entries_length + 1,
                    sizeof(*value->entries)
                );
                size_t entry_index = value->entries_length;
                value->entries_length += 1;
                {entry_name} *entry = &value->entries[entry_index];
                entry->key = {clone_key};
                entry->value = item_value;
                entry->hash = hash;
                entry->occupied = true;
                if (value->buckets[bucket] == {name}_BUCKET_TOMBSTONE) {{
                    value->tombstones -= 1;
                }}
                value->buckets[bucket] = entry_index;
                value->length += 1;
            }}

            static inline CINDER_MAYBE_UNUSED {name} {name}_from_values(
                {keys_decl},
                {values_decl},
                size_t length
            )
            {{
                {name} result = {{ NULL, 0, 0, NULL, 0, 0, 0, 0 }};
                if (length != 0 && (keys == NULL || values == NULL)) {{
                    cinder_panic("invalid Map literal storage");
                }}
                for (size_t index = 0; index < length; ++index) {{
                    {name}_set(&result, keys[index], values[index]);
                }}
                return result;
            }}

            static inline CINDER_MAYBE_UNUSED {option_name} {name}_pop(
                {name} *value,
                {key_decl}
            )
            {{
                {option_name} result = {{ {option_name}_Tag_None, {{ 0 }} }};
                if (value == NULL) {{
                    return result;
                }}
                if (value->active_iterators != 0) {{
                    cinder_panic("cannot structurally mutate Map during iteration");
                }}
                bool found = false;
                size_t bucket = {name}_find_bucket(
                    value,
                    key,
                    {name}_hash(key),
                    &found
                );
                if (!found) {{
                    return result;
                }}
                {entry_name} *entry = &value->entries[value->buckets[bucket]];
                result.tag = {option_name}_Tag_Some;
                result.data.value = entry->value;
                {clear_popped_value}
                {drop_key}
                entry->occupied = false;
                value->buckets[bucket] = {name}_BUCKET_TOMBSTONE;
                value->length -= 1;
                value->tombstones += 1;
                return result;
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value)
            {{
                if (value == NULL) {{
                    return;
                }}
                if (value->active_iterators != 0) {{
                    cinder_panic("cannot drop Map during iteration");
                }}
                for (size_t index = 0; index < value->entries_length; ++index) {{
                    {entry_name} *entry = &value->entries[index];
                    if (!entry->occupied) {{
                        continue;
                    }}
                    {drop_key}
                    {drop_value}
                }}
                free(value->entries);
                free(value->buckets);
                value->entries = NULL;
                value->entries_length = 0;
                value->entries_capacity = 0;
                value->buckets = NULL;
                value->capacity = 0;
                value->length = 0;
                value->tombstones = 0;
                value->active_iterators = 0;
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_clear({name} *value)
            {{
                if (value != NULL && value->active_iterators != 0) {{
                    cinder_panic("cannot structurally mutate Map during iteration");
                }}
                {name}_drop(value);
            }}

            static inline CINDER_MAYBE_UNUSED bool {name}_contains_owned(
                {name} value,
                {key_decl}
            )
            {{
                bool result = {name}_contains(&value, key);
                {name}_drop(&value);
                return result;
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_update(
                {name} *value,
                const {name} *other
            )
            {{
                if (value == other) {{
                    return;
                }}
                if (value == NULL || other == NULL) {{
                    cinder_panic("null Map update operand");
                }}
                if (value->active_iterators != 0) {{
                    cinder_panic("cannot structurally mutate Map during iteration");
                }}
                for (size_t index = 0; index < other->entries_length; ++index) {{
                    const {entry_name} *entry = &other->entries[index];
                    if (entry->occupied) {{
                        {name}_set(value, entry->key, entry->value);
                    }}
                }}
            }}

            static inline CINDER_MAYBE_UNUSED {keys_view} {name}_keys(
                const {name} *value
            )
            {{
                {keys_view} result = {{ value }};
                return result;
            }}

            static inline CINDER_MAYBE_UNUSED {values_view} {name}_values(
                const {name} *value
            )
            {{
                {values_view} result = {{ value }};
                return result;
            }}

            static inline CINDER_MAYBE_UNUSED {items_view} {name}_items(
                const {name} *value
            )
            {{
                {items_view} result = {{ value }};
                return result;
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_begin_iteration(
                const {name} *value
            )
            {{
                if (value == NULL) {{
                    cinder_panic("null Map iterator");
                }}
                {name} *mutable_value = ({name} *)(void *)value;
                if (mutable_value->active_iterators == SIZE_MAX) {{
                    cinder_panic("Map iterator count overflow");
                }}
                mutable_value->active_iterators += 1;
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_end_iteration(
                const {name} *value
            )
            {{
                {name} *mutable_value = ({name} *)(void *)value;
                if (mutable_value == NULL || mutable_value->active_iterators == 0) {{
                    cinder_panic("invalid Map iterator release");
                }}
                mutable_value->active_iterators -= 1;
            }}

            #undef {name}_BUCKET_EMPTY
            #undef {name}_BUCKET_TOMBSTONE
            #endif /* {guard} */
            """
        )
        self.writer.line()

    def _emit_set_helpers(self) -> None:
        for set_type in self.ir.set_types:
            self._emit_set_helper_suite(set_type)

    def _emit_set_helper_suite(self, set_type: SetType) -> None:
        name = c_identifier(set_c_name(set_type))
        entry_name = f"{name}_Entry"
        option_name = c_identifier(option_c_name(OptionType(set_type.inner)))
        item_decl = c_decl(set_type.inner, "item")
        values_decl = c_decl(
            PointerType(ConstType(set_type.inner)),
            "values",
        )
        hash_item = self._hash_expression(set_type.inner, "item")
        equal_item = self._equal_expression(
            set_type.inner,
            "entry->value",
            "item",
        )
        clone_item = self._clone_expression(set_type.inner, "item")
        drop_item = self._drop_expression(set_type.inner, "entry->value")
        clear_popped_item = (
            "memset(&entry->value, 0, sizeof(entry->value));"
            if self._type_needs_drop(set_type.inner)
            else ""
        )
        guard = f"CINDER_HELPERS_{name.upper()}"

        self.writer.raw(
            f"""
            #ifndef {guard}
            #define {guard}

            static inline CINDER_MAYBE_UNUSED uint64_t {name}_hash({item_decl})
            {{
                return {hash_item};
            }}

            static inline CINDER_MAYBE_UNUSED bool {name}_entry_equal(
                const {entry_name} *entry,
                {item_decl}
            )
            {{
                return {equal_item};
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_rehash(
                {name} *value,
                size_t new_capacity
            )
            {{
                if (new_capacity < 8 || (new_capacity & (new_capacity - 1)) != 0) {{
                    cinder_panic("invalid Set capacity");
                }}
                {entry_name} *new_entries = ({entry_name} *)cinder_alloc(
                    new_capacity,
                    sizeof({entry_name})
                );
                (void)memset(new_entries, 0, new_capacity * sizeof({entry_name}));
                for (size_t index = 0; index < value->capacity; ++index) {{
                    if (value->entries[index].state != 1) {{
                        continue;
                    }}
                    size_t target = value->entries[index].hash & (new_capacity - 1);
                    while (new_entries[target].state == 1) {{
                        target = (target + 1) & (new_capacity - 1);
                    }}
                    new_entries[target] = value->entries[index];
                }}
                free(value->entries);
                value->entries = new_entries;
                value->capacity = new_capacity;
                value->tombstones = 0;
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_ensure_capacity({name} *value)
            {{
                if (
                    value->capacity != 0
                    && value->length + value->tombstones
                        < value->capacity - value->capacity / 4
                ) {{
                    return;
                }}
                size_t new_capacity = value->capacity == 0 ? 8 : value->capacity;
                if (
                    value->capacity != 0
                    && value->length + 1
                        >= value->capacity - value->capacity / 4
                ) {{
                    if (value->capacity > SIZE_MAX / 2) {{
                        cinder_panic("Set capacity overflow");
                    }}
                    new_capacity = value->capacity * 2;
                }}
                {name}_rehash(value, new_capacity);
            }}

            static inline CINDER_MAYBE_UNUSED size_t {name}_find_slot(
                const {name} *value,
                {item_decl},
                uint64_t hash,
                bool *found
            )
            {{
                if (value->capacity == 0) {{
                    *found = false;
                    return SIZE_MAX;
                }}
                size_t first_tombstone = SIZE_MAX;
                size_t slot = hash & (value->capacity - 1);
                for (;;) {{
                    const {entry_name} *entry = &value->entries[slot];
                    if (entry->state == 0) {{
                        *found = false;
                        return first_tombstone == SIZE_MAX ? slot : first_tombstone;
                    }}
                    if (entry->state == 2) {{
                        if (first_tombstone == SIZE_MAX) {{
                            first_tombstone = slot;
                        }}
                    }} else if (
                        entry->hash == hash
                        && {name}_entry_equal(entry, item)
                    ) {{
                        *found = true;
                        return slot;
                    }}
                    slot = (slot + 1) & (value->capacity - 1);
                }}
            }}

            static inline CINDER_MAYBE_UNUSED bool {name}_contains(
                const {name} *value,
                {item_decl}
            )
            {{
                if (value == NULL || value->capacity == 0) {{
                    return false;
                }}
                bool found = false;
                (void){name}_find_slot(value, item, {name}_hash(item), &found);
                return found;
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_add(
                {name} *value,
                {item_decl}
            )
            {{
                if (value == NULL) {{
                    cinder_panic("null Set receiver");
                }}
                if (value->active_iterators != 0) {{
                    cinder_panic("cannot structurally mutate Set during iteration");
                }}
                uint64_t hash = {name}_hash(item);
                bool found = false;
                (void){name}_find_slot(value, item, hash, &found);
                if (found) {{
                    return;
                }}
                {name}_ensure_capacity(value);
                size_t slot = {name}_find_slot(value, item, hash, &found);
                if (found) {{
                    return;
                }}
                if (value->entries[slot].state == 2) {{
                    value->tombstones -= 1;
                }}
                value->entries[slot].value = {clone_item};
                value->entries[slot].hash = hash;
                value->entries[slot].state = 1;
                value->length += 1;
            }}

            static inline CINDER_MAYBE_UNUSED {name} {name}_from_values(
                {values_decl},
                size_t length
            )
            {{
                {name} result = {{ NULL, 0, 0, 0, 0 }};
                if (length != 0 && values == NULL) {{
                    cinder_panic("invalid Set literal storage");
                }}
                for (size_t index = 0; index < length; ++index) {{
                    {name}_add(&result, values[index]);
                }}
                return result;
            }}

            static inline CINDER_MAYBE_UNUSED bool {name}_discard(
                {name} *value,
                {item_decl}
            )
            {{
                if (value == NULL) {{
                    return false;
                }}
                if (value->active_iterators != 0) {{
                    cinder_panic("cannot structurally mutate Set during iteration");
                }}
                bool found = false;
                size_t slot = {name}_find_slot(
                    value,
                    item,
                    {name}_hash(item),
                    &found
                );
                if (!found) {{
                    return false;
                }}
                {entry_name} *entry = &value->entries[slot];
                {drop_item}
                entry->state = 2;
                value->length -= 1;
                value->tombstones += 1;
                return true;
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_remove(
                {name} *value,
                {item_decl}
            )
            {{
                if (!{name}_discard(value, item)) {{
                    cinder_panic("Set element not found");
                }}
            }}

            static inline CINDER_MAYBE_UNUSED {option_name} {name}_pop({name} *value)
            {{
                {option_name} result = {{ {option_name}_Tag_None, {{ 0 }} }};
                if (value == NULL) {{
                    return result;
                }}
                if (value->active_iterators != 0) {{
                    cinder_panic("cannot structurally mutate Set during iteration");
                }}
                for (size_t slot = 0; slot < value->capacity; ++slot) {{
                    {entry_name} *entry = &value->entries[slot];
                    if (entry->state != 1) {{
                        continue;
                    }}
                    result.tag = {option_name}_Tag_Some;
                    result.data.value = entry->value;
                    {clear_popped_item}
                    entry->state = 2;
                    value->length -= 1;
                    value->tombstones += 1;
                    return result;
                }}
                return result;
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value)
            {{
                if (value == NULL) {{
                    return;
                }}
                if (value->active_iterators != 0) {{
                    cinder_panic("cannot drop Set during iteration");
                }}
                for (size_t index = 0; index < value->capacity; ++index) {{
                    {entry_name} *entry = &value->entries[index];
                    if (entry->state == 1) {{
                        {drop_item}
                    }}
                }}
                free(value->entries);
                value->entries = NULL;
                value->capacity = 0;
                value->length = 0;
                value->tombstones = 0;
                value->active_iterators = 0;
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_clear({name} *value)
            {{
                if (value != NULL && value->active_iterators != 0) {{
                    cinder_panic("cannot structurally mutate Set during iteration");
                }}
                {name}_drop(value);
            }}

            static inline CINDER_MAYBE_UNUSED bool {name}_contains_owned(
                {name} value,
                {item_decl}
            )
            {{
                bool result = {name}_contains(&value, item);
                {name}_drop(&value);
                return result;
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_update(
                {name} *value,
                const {name} *other
            )
            {{
                if (value == other) {{
                    return;
                }}
                if (value == NULL || other == NULL) {{
                    cinder_panic("null Set update operand");
                }}
                if (value->active_iterators != 0) {{
                    cinder_panic("cannot structurally mutate Set during iteration");
                }}
                for (size_t index = 0; index < other->capacity; ++index) {{
                    if (other->entries[index].state == 1) {{
                        {name}_add(value, other->entries[index].value);
                    }}
                }}
            }}

            static inline CINDER_MAYBE_UNUSED {name} {name}_union(
                const {name} *left,
                const {name} *right
            )
            {{
                {name} result = {{ NULL, 0, 0, 0, 0 }};
                {name}_update(&result, left);
                {name}_update(&result, right);
                return result;
            }}

            static inline CINDER_MAYBE_UNUSED {name} {name}_intersection(
                const {name} *left,
                const {name} *right
            )
            {{
                {name} result = {{ NULL, 0, 0, 0, 0 }};
                for (size_t index = 0; index < left->capacity; ++index) {{
                    if (
                        left->entries[index].state == 1
                        && {name}_contains(right, left->entries[index].value)
                    ) {{
                        {name}_add(&result, left->entries[index].value);
                    }}
                }}
                return result;
            }}

            static inline CINDER_MAYBE_UNUSED {name} {name}_difference(
                const {name} *left,
                const {name} *right
            )
            {{
                {name} result = {{ NULL, 0, 0, 0, 0 }};
                for (size_t index = 0; index < left->capacity; ++index) {{
                    if (
                        left->entries[index].state == 1
                        && !{name}_contains(right, left->entries[index].value)
                    ) {{
                        {name}_add(&result, left->entries[index].value);
                    }}
                }}
                return result;
            }}

            static inline CINDER_MAYBE_UNUSED {name} {name}_symmetric_difference(
                const {name} *left,
                const {name} *right
            )
            {{
                {name} first = {name}_difference(left, right);
                {name} second = {name}_difference(right, left);
                {name} result = {name}_union(&first, &second);
                {name}_drop(&first);
                {name}_drop(&second);
                return result;
            }}

            static inline CINDER_MAYBE_UNUSED bool {name}_is_subset(
                const {name} *left,
                const {name} *right
            )
            {{
                if (left->length > right->length) {{
                    return false;
                }}
                for (size_t index = 0; index < left->capacity; ++index) {{
                    if (
                        left->entries[index].state == 1
                        && !{name}_contains(right, left->entries[index].value)
                    ) {{
                        return false;
                    }}
                }}
                return true;
            }}

            static inline CINDER_MAYBE_UNUSED bool {name}_equal(
                const {name} *left,
                const {name} *right
            )
            {{
                return left->length == right->length
                    && {name}_is_subset(left, right);
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_begin_iteration(
                const {name} *value
            )
            {{
                if (value == NULL) {{
                    cinder_panic("null Set iterator");
                }}
                {name} *mutable_value = ({name} *)(void *)value;
                if (mutable_value->active_iterators == SIZE_MAX) {{
                    cinder_panic("Set iterator count overflow");
                }}
                mutable_value->active_iterators += 1;
            }}

            static inline CINDER_MAYBE_UNUSED void {name}_end_iteration(
                const {name} *value
            )
            {{
                {name} *mutable_value = ({name} *)(void *)value;
                if (mutable_value == NULL || mutable_value->active_iterators == 0) {{
                    cinder_panic("invalid Set iterator release");
                }}
                mutable_value->active_iterators -= 1;
            }}

            #endif /* {guard} */
            """
        )
        self.writer.line()

    @staticmethod
    def _hash_expression(type_: Type, value: str) -> str:
        if isinstance(strip_const(type_), StringType):
            return f"cinder_string_hash_value(&({value}))"
        if is_c_string(type_):
            return f"cinder_hash_string({value})"
        return f"cinder_hash_u64((uint64_t)({value}))"

    @staticmethod
    def _equal_expression(type_: Type, left: str, right: str) -> str:
        if isinstance(strip_const(type_), StringType):
            return f"cinder_string_equal_value(&({left}), &({right}))"
        if is_c_string(type_):
            return f"cinder_string_equal({left}, {right})"
        return f"(({left}) == ({right}))"

    @staticmethod
    def _clone_expression(type_: Type, value: str) -> str:
        if isinstance(strip_const(type_), StringType):
            return f"cinder_string_clone(&({value}))"
        if is_c_string(type_):
            return f"cinder_clone_string({value})"
        return value

    def _drop_expression(self, type_: Type, value: str) -> str:
        raw = strip_const(type_)
        if isinstance(raw, StringType):
            return f"cinder_string_drop(&({value}));"
        if isinstance(raw, StringBuilderType):
            return f"cinder_string_builder_drop(&({value}));"
        if is_c_string(type_):
            return f"free((void *)({value}));"
        if self._type_needs_drop(type_):
            return self._drop_glue_call(type_, f"&({value})")
        return "(void)0;"

    def _type_needs_drop(self, type_: Type) -> bool:
        return ownership_type_needs_drop(
            type_,
            classes=self._classes_by_type,
            structs=self._structs_by_type,
        )

    def _class_needs_drop(self, class_: ClassSymbol) -> bool:
        return ownership_class_needs_drop(
            class_,
            classes=self._classes_by_type,
            structs=self._structs_by_type,
        )

    def _struct_needs_drop(self, struct_: StructSymbol) -> bool:
        return ownership_struct_needs_drop(
            struct_,
            classes=self._classes_by_type,
            structs=self._structs_by_type,
        )

    def _drop_glue_call(self, type_: Type, pointer_expr: str) -> str:
        raw = strip_const(type_)
        if isinstance(raw, StringType):
            return f"cinder_string_drop({pointer_expr});"
        if isinstance(raw, StringBuilderType):
            return f"cinder_string_builder_drop({pointer_expr});"
        if isinstance(raw, (ListType, MapType, SetType, FileType, OwnedType)):
            return f"{self._container_drop_name(raw)}({pointer_expr});"
        if isinstance(raw, ClassType):
            class_ = self._classes_by_type.get(raw)
            if class_ is None:
                raise AssertionError(f"missing class for drop: {raw!r}")
            return f"{self._class_drop_name(class_)}({pointer_expr});"
        if isinstance(raw, StructType):
            struct_ = self._structs_by_type.get(raw)
            if struct_ is None:
                raise AssertionError(f"missing struct for drop: {raw!r}")
            return f"{self._struct_drop_name(struct_)}({pointer_expr});"
        if isinstance(raw, OptionType):
            name = c_identifier(option_c_name(raw))
            return f"{name}_drop({pointer_expr});"
        if isinstance(raw, ResultType):
            name = c_identifier(result_c_name(raw))
            return f"{name}_drop({pointer_expr});"
        if isinstance(raw, TupleType):
            name = c_identifier(tuple_c_name(raw))
            return f"{name}_drop({pointer_expr});"
        if isinstance(raw, ClosureType):
            name = c_identifier(closure_c_name(raw))
            return f"{name}_drop({pointer_expr});"
        if isinstance(raw, ArrayType):
            return self._array_drop_statements(raw, pointer_expr)
        raise AssertionError(f"no drop glue for {type_name(raw)}")

    def _array_drop_statements(self, array_type: ArrayType, pointer_expr: str) -> str:
        if not self._type_needs_drop(array_type.inner):
            return "(void)0;"
        element_drop = self._drop_expression(
            array_type.inner,
            f"(*({pointer_expr}))[_cinder_i]",
        )
        lines = [
            "{",
            f"    for (size_t _cinder_i = {array_type.length}; _cinder_i-- > 0;)",
            "    {",
            f"        {element_drop}",
            "    }",
            "}",
        ]
        return "\n".join(lines)

    def _emit_drop_glue(self, type_: Type, pointer_expr: str) -> None:
        statement = self._drop_glue_call(type_, pointer_expr)
        if "\n" in statement:
            for line in statement.splitlines():
                self.writer.line(line)
        else:
            self.writer.line(statement)

    def _emit_tuple_definition(self, tuple_type: TupleType) -> None:
        name = c_identifier(tuple_c_name(tuple_type))
        guard = f"CINDER_DEFINED_{name.upper()}"
        self.writer.line(f"#ifndef {guard}")
        self.writer.line(f"#define {guard}")
        self.writer.line(f"struct {name}")
        self.writer.line("{")
        self.writer.indent += 1
        if not tuple_type.elements:
            self.writer.line("unsigned char _cinder_empty;")
        for index, element in enumerate(tuple_type.elements):
            self.writer.line(c_decl(element, f"item_{index}") + ";")
        self.writer.indent -= 1
        self.writer.line("};")
        self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_closure_definition(self, closure_type: ClosureType) -> None:
        name = c_identifier(closure_c_name(closure_type))
        guard = f"CINDER_DEFINED_{name.upper()}"
        env_parameter: Type = PointerType(
            ConstType(closure_type.env_type) if closure_type.env_is_const else closure_type.env_type
        )
        adapter_type = FunctionPointerType(
            (env_parameter, *closure_type.param_types),
            closure_type.return_type,
        )
        self.writer.line(f"#ifndef {guard}")
        self.writer.line(f"#define {guard}")
        self.writer.line(f"struct {name}")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(c_decl(closure_type.env_type, "env") + ";")
        self.writer.line(c_decl(adapter_type, "call") + ";")
        self.writer.indent -= 1
        self.writer.line("};")
        self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_collection_print_helpers(self) -> None:
        printable_tuples = [
            tuple_type
            for tuple_type in self.ir.tuple_types
            if self._is_printable_runtime_type(tuple_type)
        ]
        printable_lists = [
            list_type
            for list_type in self.ir.list_types
            if self._is_printable_runtime_type(list_type)
        ]
        printable_maps = [
            map_type for map_type in self.ir.map_types if self._is_printable_runtime_type(map_type)
        ]
        printable_sets = [
            set_type for set_type in self.ir.set_types if self._is_printable_runtime_type(set_type)
        ]
        if not (printable_tuples or printable_lists or printable_maps or printable_sets):
            return

        self.writer.line("#include <stdio.h>")
        self.writer.line()

        for tuple_type in printable_tuples:
            name = c_identifier(tuple_c_name(tuple_type))
            self.writer.line(
                f"static inline CINDER_MAYBE_UNUSED void {name}_print(const {name} *value);"
            )
        for list_type in printable_lists:
            name = c_identifier(list_c_name(list_type))
            self.writer.line(
                f"static inline CINDER_MAYBE_UNUSED void {name}_print(const {name} *value);"
            )
        for map_type in printable_maps:
            name = c_identifier(map_c_name(map_type))
            self.writer.line(
                f"static inline CINDER_MAYBE_UNUSED void {name}_print(const {name} *value);"
            )
        for set_type in printable_sets:
            name = c_identifier(set_c_name(set_type))
            self.writer.line(
                f"static inline CINDER_MAYBE_UNUSED void {name}_print(const {name} *value);"
            )
        self.writer.line()

        for tuple_type in printable_tuples:
            self._emit_tuple_print_helper(tuple_type)
        for list_type in printable_lists:
            self._emit_list_print_helper(list_type)
        for map_type in printable_maps:
            self._emit_map_print_helper(map_type)
        for set_type in printable_sets:
            self._emit_set_print_helper(set_type)

    @staticmethod
    def _is_printable_runtime_type(type_: Type) -> bool:
        raw = strip_const(type_)
        if raw in (BOOL, CHAR):
            return True
        if isinstance(raw, StringType):
            return True
        if _is_printf_string_type(raw):
            return True
        if isinstance(raw, PrimitiveType) and raw.category in {"float", "integer"}:
            return True
        if isinstance(raw, TupleType):
            return all(CGenerator._is_printable_runtime_type(element) for element in raw.elements)
        if isinstance(raw, ListType):
            return CGenerator._is_printable_runtime_type(raw.inner)
        if isinstance(raw, MapType):
            return CGenerator._is_printable_runtime_type(
                raw.key
            ) and CGenerator._is_printable_runtime_type(raw.value)
        if isinstance(raw, SetType):
            return CGenerator._is_printable_runtime_type(raw.inner)
        return False

    def _emit_print_helper_value(self, type_: Type, c_value: str) -> None:
        raw = strip_const(type_)
        if raw == BOOL:
            self.writer.line(f'printf("%s", ({c_value}) ? "true" : "false");')
            return
        if raw == CHAR:
            self.writer.line(f"cinder_print_repr_char({c_value});")
            return
        if isinstance(raw, StringType):
            self.writer.line(f"cinder_print_repr_string(cinder_string_cstr(&({c_value})));")
            return
        if _is_printf_string_type(raw):
            self.writer.line(f"cinder_print_repr_string({c_value});")
            return
        if isinstance(raw, PrimitiveType) and raw.category == "float":
            value = f"((double)({c_value}))" if raw == F32 else c_value
            self.writer.line(f'printf("%g", {value});')
            return
        if isinstance(raw, PrimitiveType) and raw.category == "integer":
            if raw.signed is False:
                self.writer.line(f'printf("%llu", (unsigned long long)({c_value}));')
            else:
                self.writer.line(f'printf("%lld", (long long)({c_value}));')
            return
        if isinstance(raw, TupleType):
            name = c_identifier(tuple_c_name(raw))
            self.writer.line(f"{name}_print(&({c_value}));")
            return
        if isinstance(raw, ListType):
            name = c_identifier(list_c_name(raw))
            self.writer.line(f"{name}_print(&({c_value}));")
            return
        if isinstance(raw, MapType):
            name = c_identifier(map_c_name(raw))
            self.writer.line(f"{name}_print(&({c_value}));")
            return
        if isinstance(raw, SetType):
            name = c_identifier(set_c_name(raw))
            self.writer.line(f"{name}_print(&({c_value}));")
            return
        raise AssertionError(f"type {type_name(type_)} cannot be printed")

    def _emit_tuple_print_helper(self, tuple_type: TupleType) -> None:
        name = c_identifier(tuple_c_name(tuple_type))
        guard = f"CINDER_PRINT_{name.upper()}"
        self.writer.line(f"#ifndef {guard}")
        self.writer.line(f"#define {guard}")
        self.writer.line(
            f"static inline CINDER_MAYBE_UNUSED void {name}_print(const {name} *value)"
        )
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('printf("(");')
        if len(tuple_type.elements) == 1:
            self._emit_print_helper_value(tuple_type.elements[0], "value->item_0")
            self.writer.line('printf(",");')
        else:
            for index, element in enumerate(tuple_type.elements):
                if index:
                    self.writer.line('printf(", ");')
                self._emit_print_helper_value(element, f"value->item_{index}")
        self.writer.line('printf(")");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_list_print_helper(self, list_type: ListType) -> None:
        name = c_identifier(list_c_name(list_type))
        guard = f"CINDER_PRINT_{name.upper()}"
        self.writer.line(f"#ifndef {guard}")
        self.writer.line(f"#define {guard}")
        self.writer.line(
            f"static inline CINDER_MAYBE_UNUSED void {name}_print(const {name} *value)"
        )
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('printf("[");')
        self.writer.line("for (size_t index = 0; index < value->length; ++index)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('if (index) printf(", ");')
        self._emit_print_helper_value(list_type.inner, "value->data[index]")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line('printf("]");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_map_print_helper(self, map_type: MapType) -> None:
        name = c_identifier(map_c_name(map_type))
        entry_name = f"{name}_Entry"
        guard = f"CINDER_PRINT_{name.upper()}"
        self.writer.line(f"#ifndef {guard}")
        self.writer.line(f"#define {guard}")
        self.writer.line(
            f"static inline CINDER_MAYBE_UNUSED void {name}_print(const {name} *value)"
        )
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('printf("{");')
        self.writer.line("bool first = true;")
        self.writer.line("for (size_t index = 0; index < value->entries_length; ++index)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"const {entry_name} *entry = &value->entries[index];")
        self.writer.line("if (!entry->occupied)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("continue;")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("if (!first)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('printf(", ");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("first = false;")
        self._emit_print_helper_value(map_type.key, "entry->key")
        self.writer.line('printf(": ");')
        self._emit_print_helper_value(map_type.value, "entry->value")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line('printf("}");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_set_print_helper(self, set_type: SetType) -> None:
        name = c_identifier(set_c_name(set_type))
        entry_name = f"{name}_Entry"
        guard = f"CINDER_PRINT_{name.upper()}"
        self.writer.line(f"#ifndef {guard}")
        self.writer.line(f"#define {guard}")
        self.writer.line(
            f"static inline CINDER_MAYBE_UNUSED void {name}_print(const {name} *value)"
        )
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (value->length == 0)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('printf("set()");')
        self.writer.line("return;")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line('printf("{");')
        self.writer.line("bool first = true;")
        self.writer.line("for (size_t index = 0; index < value->capacity; ++index)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"const {entry_name} *entry = &value->entries[index];")
        self.writer.line("if (entry->state != 1)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("continue;")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("if (!first)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('printf(", ");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("first = false;")
        self._emit_print_helper_value(set_type.inner, "entry->value")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line('printf("}");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_sort_helpers(self) -> None:
        for element_type in self.ir.sort_types:
            compare_name = self._sort_compare_name(element_type)
            pointer_type = PointerType(ConstType(element_type))
            pointer_c_type = c_type_expression(pointer_type)

            self.writer.line(
                f"static CINDER_MAYBE_UNUSED int {compare_name}("
                "const void *left_value, const void *right_value)"
            )
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(f"{c_decl(pointer_type, 'left')} = ({pointer_c_type})left_value;")
            self.writer.line(f"{c_decl(pointer_type, 'right')} = ({pointer_c_type})right_value;")
            raw = strip_const(element_type)
            if isinstance(raw, StringType):
                self.writer.line("return cinder_string_compare_value(left, right);")
            elif isinstance(raw, PointerType) and strip_const(raw.inner) == CHAR:
                self.writer.line("return strcmp(*left, *right);")
            else:
                self.writer.line("return (*left > *right) - (*left < *right);")
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line()

            helper_name = self._sort_helper_name(element_type)
            slice_type = SliceType(element_type)
            self.writer.line(
                f"static CINDER_MAYBE_UNUSED void {helper_name}("
                f"{self._slice_name(slice_type)} values)"
            )
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(
                f"cinder_sort(values.data, values.length, sizeof(*values.data), {compare_name});"
            )
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line()

    def _emit_class_definition(self, class_: ClassSymbol) -> None:
        name = c_identifier(class_.c_name)
        specialized = bool(class_.type_args or class_.template_name)
        if specialized:
            guard = f"CINDER_DEFINED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
        self.writer.line(f"struct {name}")
        self.writer.line("{")
        self.writer.indent += 1
        has_field = False
        if class_.primary_base is not None:
            self.writer.line(c_decl(class_.primary_base.type, "_base") + ";")
            has_field = True
        for field in class_.fields.values():
            self.writer.line(c_decl(field.type, c_identifier(field.name)) + ";")
            has_field = True
        if not has_field:
            self.writer.line("unsigned char _cinder_empty;")
        self.writer.indent -= 1
        self.writer.line("};")
        if specialized:
            self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_struct_definition(self, struct: StructSymbol) -> None:
        name = c_identifier(struct.c_name)
        specialized = bool(struct.type_args or struct.template_name)
        if specialized:
            guard = f"CINDER_DEFINED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
        self.writer.line(f"struct {name}")
        self.writer.line("{")
        self.writer.indent += 1
        if not struct.fields:
            self.writer.line("unsigned char _cinder_empty;")
        for field in struct.fields.values():
            self.writer.line(c_decl(field.type, c_identifier(field.name)) + ";")
        self.writer.indent -= 1
        self.writer.line("};")
        if specialized:
            self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_union_definition(self, union: UnionSymbol) -> None:
        name = c_identifier(union.c_name)
        specialized = bool(union.type_args or union.template_name)
        if specialized:
            guard = f"CINDER_DEFINED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
        self.writer.line(f"union {name}")
        self.writer.line("{")
        self.writer.indent += 1
        if not union.fields:
            self.writer.line("unsigned char _cinder_empty;")
        for field in union.fields.values():
            self.writer.line(c_decl(field.type, c_identifier(field.name)) + ";")
        self.writer.indent -= 1
        self.writer.line("};")
        if specialized:
            self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_variant_definition(self, variant: VariantSymbol) -> None:
        name = c_identifier(variant.c_name)
        specialized = bool(variant.type_args or variant.template_name)
        if specialized:
            guard = f"CINDER_DEFINED_{name.upper()}"
            self.writer.line(f"#ifndef {guard}")
            self.writer.line(f"#define {guard}")
        tag_name = f"{name}_Tag"
        self.writer.line(f"typedef enum {tag_name}")
        self.writer.line("{")
        self.writer.indent += 1
        for index, case in enumerate(variant.cases.values()):
            suffix = "," if index + 1 < len(variant.cases) else ""
            self.writer.line(f"{c_identifier(case.c_name)} = {case.tag_value}{suffix}")
        self.writer.indent -= 1
        self.writer.line(f"}} {tag_name};")
        self.writer.line()
        self.writer.line(f"struct {name}")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"{tag_name} tag;")
        self.writer.line("union")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("unsigned char _cinder_empty;")
        for case in variant.cases.values():
            if not case.fields:
                continue
            self.writer.line("struct")
            self.writer.line("{")
            self.writer.indent += 1
            for field in case.fields.values():
                self.writer.line(c_decl(field.type, c_identifier(field.name)) + ";")
            self.writer.indent -= 1
            self.writer.line(f"}} {c_identifier(case.name)};")
        self.writer.indent -= 1
        self.writer.line("} data;")
        self.writer.indent -= 1
        self.writer.line("};")
        if specialized:
            self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_result_definition(self, type_: ResultType) -> None:
        name = c_identifier(result_c_name(type_))
        guard = f"CINDER_DEFINED_{name.upper()}"
        tag_name = f"{name}_Tag"
        self.writer.line(f"#ifndef {guard}")
        self.writer.line(f"#define {guard}")
        self.writer.line(f"typedef enum {tag_name}")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"{name}_Tag_Ok = 0,")
        self.writer.line(f"{name}_Tag_Err = 1")
        self.writer.indent -= 1
        self.writer.line(f"}} {tag_name};")
        self.writer.line()
        self.writer.line(f"struct {name}")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"{tag_name} tag;")
        self.writer.line("union")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("unsigned char _cinder_empty;")
        if not is_void(type_.ok):
            self.writer.line(c_decl(type_.ok, "ok") + ";")
        if not is_void(type_.error):
            self.writer.line(c_decl(type_.error, "err") + ";")
        self.writer.indent -= 1
        self.writer.line("} data;")
        self.writer.indent -= 1
        self.writer.line("};")
        self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_option_definition(self, type_: OptionType) -> None:
        name = c_identifier(option_c_name(type_))
        guard = f"CINDER_DEFINED_{name.upper()}"
        tag_name = f"{name}_Tag"
        self.writer.line(f"#ifndef {guard}")
        self.writer.line(f"#define {guard}")
        self.writer.line(f"typedef enum {tag_name}")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"{name}_Tag_None = 0,")
        self.writer.line(f"{name}_Tag_Some = 1")
        self.writer.indent -= 1
        self.writer.line(f"}} {tag_name};")
        self.writer.line()
        self.writer.line(f"struct {name}")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"{tag_name} tag;")
        self.writer.line("union")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("unsigned char _cinder_empty;")
        self.writer.line(c_decl(type_.inner, "value") + ";")
        self.writer.indent -= 1
        self.writer.line("} data;")
        self.writer.indent -= 1
        self.writer.line("};")
        self.writer.line()
        self.writer.line(
            f"static inline CINDER_MAYBE_UNUSED "
            f"{c_decl(type_.inner, f'{name}_value_or_panic')}"
            f"(const {name} *option)"
        )
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"if (option == NULL || option->tag != {name}_Tag_Some)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('cinder_panic("attempted to read None.value");')
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("return option->data.value;")
        self.writer.indent -= 1
        self.writer.line("}")
        if isinstance(value_type(type_.inner), StringType):
            self.writer.line()
            self.writer.line(
                f"static inline CINDER_MAYBE_UNUSED "
                f"{c_decl(PointerType(ConstType(type_.inner)), f'{name}_value_ptr_or_panic')}"
                f"(const {name} *option)"
            )
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(f"if (option == NULL || option->tag != {name}_Tag_Some)")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line('cinder_panic("attempted to read None.value");')
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line("return &option->data.value;")
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line()
            self.writer.line(
                f"static inline CINDER_MAYBE_UNUSED "
                f"{c_decl(PointerType(type_.inner), f'{name}_value_mut_ptr_or_panic')}"
                f"({name} *option)"
            )
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(f"if (option == NULL || option->tag != {name}_Tag_Some)")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line('cinder_panic("attempted to read None.value");')
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line("return &option->data.value;")
            self.writer.indent -= 1
            self.writer.line("}")
        self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_interface_definitions(self) -> None:
        for class_ir in self.ir.classes:
            interface = class_ir.symbol
            if not interface.is_abstract:
                continue
            vtable = c_identifier(interface_vtable_c_name(interface.type))
            self.writer.line(f"struct {vtable}")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line("const CinderTypeInfo *type_info;")
            for method in interface.interface_methods.values():
                parameters = [
                    "void *object",
                    f"const {vtable} *vtable",
                    *(
                        c_decl(parameter.type, c_identifier(parameter.name))
                        for parameter in method.parameters[1:]
                    ),
                ]
                if method.is_variadic:
                    parameters.append("...")
                declarator = c_decl(
                    method.return_type,
                    f"(*{c_identifier(method.name)})",
                )
                self.writer.line(f"{declarator}({', '.join(parameters)});")
            self.writer.indent -= 1
            self.writer.line("};")
            self.writer.line()

    def _emit_reflection_declarations(self) -> None:
        reflected = [nominal for nominal in self._local_nominals() if nominal.reflected]
        for nominal in reflected:
            linkage = "static " if nominal.type_args or nominal.template_name else "extern "
            self.writer.line(f"{linkage}const CinderTypeInfo {self._type_info_name(nominal)};")
        if reflected:
            self.writer.line()

    def _emit_class_support_declarations(self) -> None:
        emitted = False
        for class_ir in self.ir.classes:
            class_ = class_ir.symbol
            self.writer.line(self._class_new_signature(class_, definition=False) + ";")
            emitted = True
            if self._class_needs_drop(class_):
                self.writer.line(self._class_drop_signature(class_, definition=False) + ";")
            if class_.is_abstract:
                continue
            for interface in self._implemented_interfaces(class_):
                linkage = "static " if class_.type_args or class_.template_name else "extern "
                self.writer.line(
                    f"{linkage}const {c_identifier(interface_vtable_c_name(interface.type))} "
                    f"{self._vtable_instance_name(class_, interface)};"
                )
        for struct in self.semantic.structs.values():
            if self._struct_needs_drop(struct):
                self.writer.line(self._struct_drop_signature(struct, definition=False) + ";")
                emitted = True
        if emitted:
            self.writer.line()

    def _emit_ownership_drop_prototypes(self) -> None:
        emitted = False
        for list_type in self.ir.list_types:
            name = c_identifier(list_c_name(list_type))
            self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value);")
            emitted = True
        if self.ir.uses_file:
            name = file_c_name()
            self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value);")
            emitted = True
        for map_type in self.ir.map_types:
            name = c_identifier(map_c_name(map_type))
            self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value);")
            emitted = True
        for set_type in self.ir.set_types:
            name = c_identifier(set_c_name(set_type))
            self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value);")
            emitted = True
        for option_type in self._generated_option_types():
            if self._type_needs_drop(option_type):
                name = c_identifier(option_c_name(option_type))
                self.writer.line(
                    f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value);"
                )
                emitted = True
        for owned_type in self.ir.owned_types:
            name = c_identifier(owned_c_name(owned_type))
            self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value);")
            emitted = True
        for result_type in self.ir.result_types:
            if self._type_needs_drop(result_type):
                name = c_identifier(result_c_name(result_type))
                self.writer.line(
                    f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value);"
                )
                emitted = True
        for tuple_type in self.ir.tuple_types:
            if self._type_needs_drop(tuple_type):
                name = c_identifier(tuple_c_name(tuple_type))
                self.writer.line(
                    f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value);"
                )
                emitted = True
        for closure_type in self.ir.closure_types:
            if self._type_needs_drop(closure_type):
                name = c_identifier(closure_c_name(closure_type))
                self.writer.line(
                    f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value);"
                )
                emitted = True
        if emitted:
            self.writer.line()

    def _emit_aggregate_drop_helpers(self) -> None:
        for option_type in self._generated_option_types():
            if self._type_needs_drop(option_type):
                self._emit_option_drop(option_type)
        for result_type in self.ir.result_types:
            if self._type_needs_drop(result_type):
                self._emit_result_drop(result_type)
        for tuple_type in self.ir.tuple_types:
            if self._type_needs_drop(tuple_type):
                self._emit_tuple_drop(tuple_type)
        for closure_type in self.ir.closure_types:
            if self._type_needs_drop(closure_type):
                self._emit_closure_drop(closure_type)

    def _emit_option_drop(self, type_: OptionType) -> None:
        name = c_identifier(option_c_name(type_))
        guard = f"CINDER_DROP_{name.upper()}"
        self.writer.line(f"#ifndef {guard}")
        self.writer.line(f"#define {guard}")
        self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (value == NULL)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("return;")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line(f"if (value->tag == {name}_Tag_Some)")
        self.writer.line("{")
        self.writer.indent += 1
        if self._type_needs_drop(type_.inner):
            self.writer.line(self._drop_expression(type_.inner, "value->data.value"))
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line(f"#endif /* {guard} */")
        self.writer.line()

    def _emit_result_drop(self, type_: ResultType) -> None:
        name = c_identifier(result_c_name(type_))
        self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (value == NULL)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("return;")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line(f"if (value->tag == {name}_Tag_Ok)")
        self.writer.line("{")
        self.writer.indent += 1
        if not is_void(type_.ok) and self._type_needs_drop(type_.ok):
            self.writer.line(self._drop_expression(type_.ok, "value->data.ok"))
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line(f"else if (value->tag == {name}_Tag_Err)")
        self.writer.line("{")
        self.writer.indent += 1
        if not is_void(type_.error) and self._type_needs_drop(type_.error):
            self.writer.line(self._drop_expression(type_.error, "value->data.err"))
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

    def _emit_tuple_drop(self, tuple_type: TupleType) -> None:
        name = c_identifier(tuple_c_name(tuple_type))
        self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (value == NULL)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("return;")
        self.writer.indent -= 1
        self.writer.line("}")
        for index in range(len(tuple_type.elements) - 1, -1, -1):
            element = tuple_type.elements[index]
            if self._type_needs_drop(element):
                self.writer.line(self._drop_expression(element, f"value->item_{index}"))
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

    def _emit_closure_drop(self, closure_type: ClosureType) -> None:
        name = c_identifier(closure_c_name(closure_type))
        self.writer.line(f"static inline CINDER_MAYBE_UNUSED void {name}_drop({name} *value)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (value == NULL)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("return;")
        self.writer.indent -= 1
        self.writer.line("}")
        if self._type_needs_drop(closure_type.env_type):
            self.writer.line(self._drop_expression(closure_type.env_type, "value->env"))
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

    def _emit_static_asserts(self) -> None:
        for declaration in self.semantic.module.static_asserts:
            evaluated = self.semantic.static_assert_values.get(id(declaration))
            condition = "true" if evaluated is True else self._emit_expr(declaration.condition)
            message = c_string(declaration.message or "static assertion failed")
            self.writer.line(f"CINDER_STATIC_ASSERT({condition}, {message});")
        if self.semantic.module.static_asserts:
            self.writer.line()

    def _emit_reflection_definitions(self) -> None:
        for nominal in self._local_nominals():
            if not nominal.reflected:
                continue
            fields = self._nominal_fields(nominal)
            methods = self._nominal_methods(nominal)
            field_array = self._field_info_array_name(nominal)
            method_array = self._method_info_array_name(nominal)

            if fields:
                self.writer.line(f"static const CinderFieldInfo {field_array}[] =")
                self.writer.line("{")
                self.writer.indent += 1
                for field, owner, path in fields:
                    offset = self._field_offset_expression(nominal, owner, path, field.name)
                    field_type = c_type_expression(field.type)
                    self.writer.line("{")
                    self.writer.indent += 1
                    self.writer.line(f".name = {c_string(field.name)},")
                    self.writer.line(f".type_name = {c_string(type_name(field.type))},")
                    self.writer.line(f".offset = {offset},")
                    self.writer.line(f".size = sizeof({field_type}),")
                    self.writer.line(f".alignment = CINDER_ALIGNOF({field_type}),")
                    self.writer.line(f".is_private = {'true' if field.is_private else 'false'},")
                    self.writer.indent -= 1
                    self.writer.line("},")
                self.writer.indent -= 1
                self.writer.line("};")
                self.writer.line()

            if methods:
                self.writer.line(f"static const CinderMethodInfo {method_array}[] =")
                self.writer.line("{")
                self.writer.indent += 1
                for method in methods:
                    signature = self._method_signature_text(method)
                    self.writer.line("{")
                    self.writer.indent += 1
                    self.writer.line(f".name = {c_string(method.name)},")
                    self.writer.line(f".signature = {c_string(signature)},")
                    self.writer.line(
                        f".return_type_name = {c_string(type_name(method.return_type))},"
                    )
                    self.writer.line(
                        f".parameter_count = {max(0, len(method.parameters) - (1 if method.owner else 0))},"
                    )
                    self.writer.line(f".is_abstract = {'true' if method.is_abstract else 'false'},")
                    self.writer.line(f".is_override = {'true' if method.is_override else 'false'},")
                    self.writer.indent -= 1
                    self.writer.line("},")
                self.writer.indent -= 1
                self.writer.line("};")
                self.writer.line()

            type_expression = c_type_expression(nominal.type)
            type_info_linkage = "static " if nominal.type_args or nominal.template_name else ""
            self.writer.line(
                f"{type_info_linkage}const CinderTypeInfo {self._type_info_name(nominal)} ="
            )
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(f".name = {c_string(nominal.name)},")
            self.writer.line(f".kind = {self._reflection_kind(nominal)},")
            self.writer.line(f".size = sizeof({type_expression}),")
            self.writer.line(f".alignment = CINDER_ALIGNOF({type_expression}),")
            self.writer.line(f".fields = {field_array if fields else 'NULL'},")
            self.writer.line(f".field_count = {len(fields)},")
            self.writer.line(f".methods = {method_array if methods else 'NULL'},")
            self.writer.line(f".method_count = {len(methods)},")
            self.writer.indent -= 1
            self.writer.line("};")
            self.writer.line()

    def _emit_class_support_definitions(self) -> None:
        for class_ir in self.ir.classes:
            class_ = class_ir.symbol
            self._emit_class_new_definition(class_)
            if self._class_needs_drop(class_):
                self._emit_class_drop_definition(class_)
            if class_.is_abstract:
                continue
            for interface in self._implemented_interfaces(class_):
                self._emit_interface_implementation(class_, interface)
        for struct in self.semantic.structs.values():
            if self._struct_needs_drop(struct):
                self._emit_struct_drop_definition(struct)

    def _emit_class_new_definition(self, class_: ClassSymbol) -> None:
        self.writer.line(self._class_new_signature(class_, definition=True))
        self.writer.line("{")
        self.writer.indent += 1
        class_name = c_identifier(class_.c_name)
        parameter_names = {
            c_identifier(parameter.name)
            for parameter in (
                class_.constructor.parameters[1:] if class_.constructor is not None else ()
            )
        }
        instance_name = "cinder_instance"
        suffix = 2
        while instance_name in parameter_names:
            instance_name = f"cinder_instance_{suffix}"
            suffix += 1
        self.writer.line(f"{class_name} {instance_name} = {{ 0 }};")
        if class_.constructor is not None:
            arguments = [f"&{instance_name}"]
            arguments.extend(
                c_identifier(parameter.name) for parameter in class_.constructor.parameters[1:]
            )
            self.writer.line(f"{c_identifier(class_.constructor.c_name)}({', '.join(arguments)});")
        elif class_.primary_base is not None:
            self.writer.line(
                f"{instance_name}._base = {self._class_new_name(class_.primary_base)}();"
            )
        self.writer.line(f"return {instance_name};")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

    def _emit_class_drop_definition(self, class_: ClassSymbol) -> None:
        self.writer.line(self._class_drop_signature(class_, definition=True))
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (self == NULL) {")
        self.writer.indent += 1
        self.writer.line("return;")
        self.writer.indent -= 1
        self.writer.line("}")
        if class_.destructor is not None:
            self.writer.line(f"{c_identifier(class_.destructor.c_name)}(self);")
        for field_name, field_type in reversed(drop_fields(class_)):
            if self._type_needs_drop(field_type):
                self.writer.line(
                    self._drop_expression(
                        field_type,
                        f"self->{c_identifier(field_name)}",
                    )
                )
        if class_.primary_base is not None and self._class_needs_drop(class_.primary_base):
            self.writer.line(f"{self._class_drop_name(class_.primary_base)}(&self->_base);")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

    def _emit_struct_drop_definition(self, struct_: StructSymbol) -> None:
        self.writer.line(self._struct_drop_signature(struct_, definition=True))
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line("if (self == NULL) {")
        self.writer.indent += 1
        self.writer.line("return;")
        self.writer.indent -= 1
        self.writer.line("}")
        for field_name, field_type in reversed(drop_fields(struct_)):
            if self._type_needs_drop(field_type):
                self.writer.line(
                    self._drop_expression(
                        field_type,
                        f"self->{c_identifier(field_name)}",
                    )
                )
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line()

    @staticmethod
    def _struct_drop_name(struct_: StructSymbol) -> str:
        return c_identifier(f"{struct_.c_name}__drop")

    def _struct_drop_signature(self, struct_: StructSymbol, *, definition: bool) -> str:
        del definition
        return (
            f"{self._class_support_linkage(struct_)}void {self._struct_drop_name(struct_)}"
            f"({c_identifier(struct_.c_name)} *self)"
        )

    def _emit_interface_implementation(
        self,
        class_: ClassSymbol,
        interface: ClassSymbol,
    ) -> None:
        vtable_type = c_identifier(interface_vtable_c_name(interface.type))
        for method in interface.interface_methods.values():
            implementation = class_.interface_methods[method.name]
            thunk_name = self._vtable_thunk_name(class_, interface, method.name)
            parameters = [
                "void *object",
                f"const {vtable_type} *vtable",
                *(
                    c_decl(parameter.type, c_identifier(parameter.name))
                    for parameter in method.parameters[1:]
                ),
            ]
            signature = c_decl(implementation.return_type, thunk_name)
            self.writer.line(f"static {signature}({', '.join(parameters)})")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line("(void)vtable;")
            arguments = [self._thunk_self_argument(class_, implementation)]
            arguments.extend(c_identifier(parameter.name) for parameter in method.parameters[1:])
            call = f"{c_identifier(implementation.c_name)}({', '.join(arguments)})"
            if is_void(implementation.return_type):
                self.writer.line(call + ";")
            else:
                self.writer.line("return " + call + ";")
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line()

        vtable_linkage = "static " if class_.type_args or class_.template_name else ""
        self.writer.line(
            f"{vtable_linkage}const {vtable_type} {self._vtable_instance_name(class_, interface)} ="
        )
        self.writer.line("{")
        self.writer.indent += 1
        type_info = f"&{self._type_info_name(class_)}" if class_.reflected else "NULL"
        self.writer.line(f".type_info = {type_info},")
        for method in interface.interface_methods.values():
            self.writer.line(
                f".{c_identifier(method.name)} = "
                f"{self._vtable_thunk_name(class_, interface, method.name)},"
            )
        self.writer.indent -= 1
        self.writer.line("};")
        self.writer.line()

    def _emit_function_prototypes(self) -> None:
        for function in self.ir.functions:
            self.writer.line(self._function_signature(function.symbol, definition=False) + ";")
        if self.ir.functions:
            self.writer.line()

    def _emit_global_declarations(self) -> None:
        for global_ in self.ir.globals:
            symbol = global_.symbol
            declaration_type = ConstType(symbol.type) if symbol.is_const else symbol.type
            declaration = c_decl(
                declaration_type,
                c_identifier(symbol.c_name or symbol.name),
            )
            self.writer.line(f"extern {declaration};")
        if self.ir.globals:
            self.writer.line()

    def _emit_globals(self) -> None:
        for global_ in self.ir.globals:
            symbol = global_.symbol
            storage = "" if symbol.is_module_public else "static CINDER_MAYBE_UNUSED "
            declaration_type = ConstType(symbol.type) if symbol.is_const else symbol.type
            declaration = c_decl(declaration_type, c_identifier(symbol.c_name or symbol.name))
            if global_.atomic_init is not None:
                initializer = self._emit_initializer(
                    global_.atomic_init.initializer,
                    global_.atomic_init.atomic_type.inner,
                )
                self.writer.line(
                    f"{storage}{declaration} = {{ .value = ATOMIC_VAR_INIT({initializer}) }};"
                )
            elif global_.declaration.initializer is None:
                self.writer.line(f"{storage}{declaration};")
            else:
                initializer = self._emit_initializer(global_.declaration.initializer, symbol.type)
                self.writer.line(f"{storage}{declaration} = {initializer};")
        if self.ir.globals:
            self.writer.line()

    def _emit_function_definitions(self) -> None:
        for function in self.ir.functions:
            if function.symbol.is_extern or function.declaration.body is None:
                continue
            self.current_function = function.symbol
            self.current_ir_function = function
            call_operations = tuple(
                operation
                for operation in function.atomic_operations
                if not isinstance(operation, IRAtomicInit)
            )
            self.atomic_temp_indices = {
                id(operation.call): index
                for index, operation in enumerate(call_operations, start=1)
            }
            self.writer.line(self._function_signature(function.symbol, definition=True))
            self.writer.line("{")
            self.writer.indent += 1
            self._emit_unused_parameters(function.symbol)
            self._emit_atomic_temporaries(call_operations)
            self._emit_block_contents(function.declaration.body, loop_body=False)
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.line()
            self.current_function = None
            self.current_ir_function = None
            self.atomic_temp_indices = {}

    def _emit_atomic_temporaries(
        self,
        operations: tuple[IRAtomicOperation, ...],
    ) -> None:
        if not operations:
            return
        for operation in operations:
            if isinstance(operation, IRAtomicInit):
                continue
            index = self.atomic_temp_indices[id(operation.call)]
            receiver_type: Type = operation.atomic_type
            if isinstance(operation, IRAtomicLoad):
                receiver_type = ConstType(receiver_type)
            self.writer.line(
                c_decl(
                    PointerType(receiver_type),
                    f"__cinder_atomic_receiver_{index}",
                )
                + ";"
            )
            if isinstance(
                operation,
                (IRAtomicStore, IRAtomicExchange, IRAtomicFetch),
            ):
                self.writer.line(
                    c_decl(
                        operation.atomic_type.inner,
                        f"__cinder_atomic_value_{index}",
                    )
                    + ";"
                )
            elif isinstance(operation, IRAtomicCompareExchange):
                self.writer.line(
                    c_decl(
                        operation.atomic_type.inner,
                        f"__cinder_atomic_expected_{index}",
                    )
                    + ";"
                )
                self.writer.line(
                    c_decl(
                        operation.atomic_type.inner,
                        f"__cinder_atomic_desired_{index}",
                    )
                    + ";"
                )
                self.writer.line(
                    c_decl(
                        operation.result_type,
                        f"__cinder_atomic_result_{index}",
                    )
                    + ";"
                )

    def _emit_unused_parameters(self, function: FunctionSymbol) -> None:
        if function.name == "main" and function.owner is None and not function.is_extern:
            if function.parameters:
                self.writer.line("(void)argc;")
                self.writer.line("(void)argv;")
            return
        for parameter in function.parameters:
            self.writer.line(f"(void){c_identifier(parameter.name)};")

    def _function_signature(self, function: FunctionSymbol, *, definition: bool) -> str:
        if function.name == "main" and function.owner is None and not function.is_extern:
            parameters = "void" if not function.parameters else "int argc, char **argv"
            return f"int main({parameters})"

        linkage = ""
        if function.is_extern:
            linkage = "extern "
        elif not function.is_exported and not function.is_module_public:
            linkage = "static CINDER_MAYBE_UNUSED "

        parameters: list[str] = [
            c_decl(parameter.type, c_identifier(parameter.name))
            for parameter in function.parameters
        ]
        if function.is_variadic:
            parameters.append("...")
        if not parameters:
            parameters.append("void")
        name = c_identifier(function.c_name)
        declarator_name = f"({name})" if function.is_extern else name
        return f"{linkage}{c_decl(function.return_type, declarator_name)}({', '.join(parameters)})"

    def _emit_block_contents(self, block: ast.Block, *, loop_body: bool) -> None:
        frame = _ScopeFrame(loop_body=loop_body)
        self.scope_frames.append(frame)
        if not loop_body and self.current_function is not None and len(self.scope_frames) == 1:
            for parameter in self.current_function.parameters:
                if self._type_needs_drop(parameter.type):
                    symbol = VariableSymbol(
                        parameter.name,
                        parameter.span,
                        SymbolKind.VARIABLE,
                        parameter.type,
                        False,
                        True,
                        parameter.name,
                    )
                    self._register_owned_cleanup(symbol)
        for statement in block.statements:
            self._emit_statement(statement)
        if not self._block_always_exits(block):
            self._emit_deferred(frame)
        self.scope_frames.pop()

    def _block_always_exits(self, block: ast.Block) -> bool:
        for statement in block.statements:
            if isinstance(statement, (ast.ReturnStmt, ast.BreakStmt, ast.ContinueStmt)):
                return True
            if (
                isinstance(statement, ast.IfStmt)
                and statement.else_body is not None
                and all(self._block_always_exits(branch.body) for branch in statement.branches)
                and self._block_always_exits(statement.else_body)
            ):
                return True
            if isinstance(statement, ast.MatchStmt):
                resolution = self.semantic.match_resolutions.get(id(statement))
                if (
                    resolution is not None
                    and resolution.exhaustive
                    and all(self._block_always_exits(case.body) for case in statement.cases)
                ):
                    return True
            if isinstance(statement, ast.UnsafeStmt) and self._block_always_exits(statement.body):
                return True
            if isinstance(statement, ast.WithStmt) and self._block_always_exits(statement.body):
                return True
        return False

    def _emit_statement(self, statement: ast.Statement) -> None:
        match statement:
            case ast.VarDeclStmt():
                self._emit_var_decl(statement)
            case ast.AssignStmt():
                self._emit_assignment(statement)
            case ast.ExpressionStmt(expression=expression):
                expr_type = self.semantic.expression_type(expression)
                if self._type_needs_drop(expr_type):
                    temporary = self._new_temp("discarded")
                    self.writer.line(
                        f"{c_decl(strip_const(expr_type), temporary)} = "
                        f"{self._emit_expr(expression)};"
                    )
                    self._emit_drop_glue(strip_const(expr_type), f"&{temporary}")
                else:
                    self.writer.line(self._emit_expr(expression) + ";")
            case ast.ReturnStmt():
                self._emit_return(statement)
            case ast.IfStmt():
                self._emit_if(statement)
            case ast.WhileStmt(condition=condition, body=body):
                self.writer.line(f"while {self._emit_condition(condition)}")
                self.writer.line("{")
                self.writer.indent += 1
                self._emit_block_contents(body, loop_body=True)
                self.writer.indent -= 1
                self.writer.line("}")
            case ast.ForEachStmt():
                self._emit_for_each(statement)
            case ast.ForCStmt():
                self._emit_for_c(statement)
            case ast.MatchStmt():
                self._emit_match(statement)
            case ast.BreakStmt():
                self._emit_loop_exit("break")
            case ast.ContinueStmt():
                self._emit_loop_exit("continue")
            case ast.PassStmt():
                self.writer.line("/* pass */")
            case ast.DeferStmt(expression=expression):
                if not self.scope_frames:
                    raise AssertionError("defer emitted outside a scope")
                self.scope_frames[-1].cleanups.append(_Cleanup(expression=expression))
            case ast.UnsafeStmt(body=body):
                self.writer.line("/* unsafe */")
                self.writer.line("{")
                self.writer.indent += 1
                self._emit_block_contents(body, loop_body=False)
                self.writer.indent -= 1
                self.writer.line("}")
            case ast.WithStmt():
                self._emit_with(statement)
            case _:
                raise AssertionError(f"unhandled statement: {statement!r}")

    def _emit_with(self, statement: ast.WithStmt) -> None:
        symbol = self.semantic.with_symbols[id(statement)]
        self.writer.line("{")
        self.writer.indent += 1
        frame = _ScopeFrame()
        self.scope_frames.append(frame)
        declaration = c_decl(symbol.type, c_identifier(symbol.name))
        initializer = self._emit_initializer(statement.context, symbol.type)
        self.writer.line(f"{declaration} = {initializer};")
        self._register_owned_cleanup(symbol)
        self._emit_block_contents(statement.body, loop_body=False)
        if not self._block_always_exits(statement.body):
            self._emit_deferred(frame)
        self.scope_frames.pop()
        self.writer.indent -= 1
        self.writer.line("}")

    def _emit_var_decl(self, statement: ast.VarDeclStmt) -> None:
        symbol = self.semantic.declaration_symbols[id(statement)]
        declaration_type = ConstType(symbol.type) if symbol.is_const else symbol.type
        declaration = c_decl(declaration_type, c_identifier(symbol.name))
        if statement.initializer is None:
            self.writer.line(declaration + ";")
            return
        atomic_init = self.atomic_initializers.get(id(statement))
        if atomic_init is not None:
            initializer = self._emit_with_expected(
                atomic_init.initializer,
                atomic_init.atomic_type.inner,
            )
            self.writer.line(declaration + ";")
            self.writer.line(f"atomic_init(&{c_identifier(symbol.name)}.value, {initializer});")
            return
        initializer = self._emit_initializer(statement.initializer, symbol.type)
        self.writer.line(f"{declaration} = {initializer};")
        self._register_owned_cleanup(symbol)
        self._exclude_moved_from_expression(statement.initializer)

    def _emit_assignment(self, statement: ast.AssignStmt) -> None:
        implicit = self.semantic.implicit_declarations.get(id(statement))
        if implicit is not None:
            declaration = c_decl(implicit.type, c_identifier(implicit.name))
            initializer = self._emit_initializer(statement.value, implicit.type)
            self.writer.line(f"{declaration} = {initializer};")
            self._register_owned_cleanup(implicit)
            self._exclude_moved_from_expression(statement.value)
            return
        expected = strip_reference(self.semantic.expression_type(statement.target))
        if isinstance(statement.target, ast.IndexExpr):
            base_type = value_type(self.semantic.expression_type(statement.target.value))
            if isinstance(base_type, MapType):
                self._emit_map_index_assignment(statement, base_type)
                return

        target = self._emit_lvalue(statement.target)
        value = self._emit_with_expected(statement.value, expected)
        container_type = value_type(expected)
        if isinstance(container_type, SetType) and statement.operator in {
            "|=",
            "&=",
            "-=",
            "^=",
        }:
            operation = {
                "|=": "union",
                "&=": "intersection",
                "-=": "difference",
                "^=": "symmetric_difference",
            }[statement.operator]
            name = c_identifier(set_c_name(container_type))
            result = self._new_temp("set_result")
            target_pointer = self._new_temp("set_target")
            self.writer.line(
                f"{c_decl(PointerType(container_type), target_pointer)} = &({target});"
            )
            right, right_temp = self._materialize_container_operand(
                statement.value,
                container_type,
            )
            self.writer.line(
                f"{c_decl(container_type, result)} = {name}_{operation}({target_pointer}, {right});"
            )
            if right_temp is not None:
                self.writer.line(f"{name}_drop(&{right_temp});")
            self.writer.line(f"{name}_drop({target_pointer});")
            self.writer.line(f"*{target_pointer} = {result};")
            return
        if (
            statement.operator == "="
            and self._type_needs_drop(expected)
            and isinstance(statement.target, (ast.NameExpr, ast.AttributeExpr))
        ):
            temporary = self._new_temp("move")
            self.writer.line(f"{c_decl(strip_const(expected), temporary)} = {value};")
            self._emit_drop_glue(strip_const(expected), f"&({target})")
            self.writer.line(f"{target} = {temporary};")
            self._exclude_moved_from_expression(statement.value)
            return
        self.writer.line(f"{target} {statement.operator} {value};")

    def _emit_return(self, statement: ast.ReturnStmt) -> None:
        if statement.value is None:
            self._emit_all_deferred()
            self.writer.line("return;")
            return

        assert self.current_function is not None
        value = self._emit_with_expected(statement.value, self.current_function.return_type)
        has_deferred = any(frame.cleanups for frame in self.scope_frames)
        if not has_deferred:
            self.writer.line(f"return {value};")
            return

        temporary = self._new_temp("return")
        self.writer.line(f"{c_decl(self.current_function.return_type, temporary)} = {value};")
        self._emit_all_deferred(exclude_variable=self._returned_local_symbol(statement.value))
        self.writer.line(f"return {temporary};")

    def _emit_if(self, statement: ast.IfStmt) -> None:
        for index, branch in enumerate(statement.branches):
            keyword = "if" if index == 0 else "else if"
            self.writer.line(f"{keyword} {self._emit_condition(branch.condition)}")
            self.writer.line("{")
            self.writer.indent += 1
            self._emit_block_contents(branch.body, loop_body=False)
            self.writer.indent -= 1
            self.writer.line("}")
        if statement.else_body is not None:
            self.writer.line("else")
            self.writer.line("{")
            self.writer.indent += 1
            self._emit_block_contents(statement.else_body, loop_body=False)
            self.writer.indent -= 1
            self.writer.line("}")

    def _emit_match(self, statement: ast.MatchStmt) -> None:
        resolution = self.semantic.match_resolutions[id(statement)]
        subject_type = resolution.value_type
        subject_name = self._new_temp("match")
        matched_name = self._new_temp("match_found")
        subject_value = self._emit_with_expected(statement.value, subject_type)

        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"{c_decl(subject_type, subject_name)} = {subject_value};")
        self.writer.line(f"bool {matched_name} = false;")

        for case, case_resolution in zip(statement.cases, resolution.cases, strict=True):
            patterns = [
                pattern for pattern in case_resolution.patterns if pattern.kind != "invalid"
            ]
            if not patterns:
                continue
            case_matched_name = self._new_temp("case_match")
            self.writer.line(f"if (!{matched_name})")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line(f"bool {case_matched_name} = false;")
            self._emit_match_binding_declarations(case_resolution.bindings)
            for pattern in patterns:
                condition = self._match_pattern_condition(subject_name, pattern)
                self.writer.line(f"if (!{case_matched_name} && {condition})")
                self.writer.line("{")
                self.writer.indent += 1
                self._emit_match_binding_assignments(subject_name, pattern)
                self.writer.line(f"{case_matched_name} = true;")
                self.writer.indent -= 1
                self.writer.line("}")
            self.writer.line(f"if ({case_matched_name})")
            self.writer.line("{")
            self.writer.indent += 1
            if case.guard is not None:
                guard = self._emit_condition(case.guard)
                self.writer.line(f"if {guard}")
                self.writer.line("{")
                self.writer.indent += 1
                self.writer.line(f"{matched_name} = true;")
                self._emit_block_contents(case.body, loop_body=False)
                self.writer.indent -= 1
                self.writer.line("}")
            else:
                self.writer.line(f"{matched_name} = true;")
                self._emit_block_contents(case.body, loop_body=False)
            self.writer.indent -= 1
            self.writer.line("}")
            self.writer.indent -= 1
            self.writer.line("}")

        final_wildcard = (
            bool(statement.cases)
            and statement.cases[-1].guard is None
            and isinstance(statement.cases[-1].pattern, ast.WildcardPattern)
        )
        if resolution.exhaustive and not final_wildcard:
            self.writer.line(f"if (!{matched_name})")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line('cinder_panic("invalid tag in exhaustive match");')
            self.writer.indent -= 1
            self.writer.line("}")

        self.writer.indent -= 1
        self.writer.line("}")

    def _match_pattern_condition(self, source: str, pattern: PatternResolution) -> str:
        if pattern.kind in {"wildcard", "binding"}:
            return "true"
        if pattern.kind == "capture":
            if not pattern.arguments:
                return "true"
            return self._match_pattern_condition(source, pattern.arguments[0])
        if pattern.kind == "enum":
            assert pattern.enum_member is not None
            return f"{source} == {c_identifier(pattern.enum_member.c_name)}"
        if pattern.kind == "variant":
            assert pattern.variant_case is not None
            parts = [f"{source}.tag == {c_identifier(pattern.variant_case.c_name)}"]
            fields = list(pattern.variant_case.fields.values())
            for argument, field in zip(pattern.arguments, fields, strict=False):
                nested = (
                    f"{source}.data.{c_identifier(pattern.variant_case.name)}."
                    f"{c_identifier(field.name)}"
                )
                parts.append(self._match_pattern_condition(nested, argument))
            return "(" + " && ".join(parts) + ")"
        if pattern.kind == "result":
            assert isinstance(pattern.type, ResultType)
            suffix = "Ok" if pattern.result_is_ok else "Err"
            parts = [f"{source}.tag == {self._result_tag(pattern.type, suffix)}"]
            if pattern.arguments:
                nested = f"{source}.data.{'ok' if pattern.result_is_ok else 'err'}"
                parts.append(self._match_pattern_condition(nested, pattern.arguments[0]))
            return "(" + " && ".join(parts) + ")"
        if pattern.kind == "option":
            assert isinstance(pattern.type, OptionType)
            suffix = "Some" if pattern.option_is_some else "None"
            name = c_identifier(option_c_name(pattern.type))
            parts = [f"{source}.tag == {name}_Tag_{suffix}"]
            if pattern.arguments:
                parts.append(
                    self._match_pattern_condition(f"{source}.data.value", pattern.arguments[0])
                )
            return "(" + " && ".join(parts) + ")"
        raise AssertionError(f"invalid match pattern resolution {pattern.kind!r}")

    def _emit_match_binding_declarations(
        self,
        bindings: tuple[PatternBinding, ...],
    ) -> None:
        emitted: set[str] = set()
        for binding in bindings:
            binding_name = c_identifier(binding.symbol.c_name or binding.symbol.name)
            if binding_name in emitted:
                continue
            emitted.add(binding_name)
            self.writer.line(f"{c_decl(binding.symbol.type, binding_name)};")

    def _emit_match_binding_assignments(
        self,
        subject_name: str,
        pattern: PatternResolution,
    ) -> None:
        emitted: set[str] = set()
        for binding in pattern.bindings:
            if binding.symbol.name == "_":
                continue
            binding_name = c_identifier(binding.symbol.c_name or binding.symbol.name)
            if binding_name in emitted:
                continue
            emitted.add(binding_name)
            source = self._pattern_access_expr(subject_name, binding.access)
            self.writer.line(f"{binding_name} = {source};")

    def _pattern_access_expr(
        self,
        subject_name: str,
        access: tuple[PatternAccessStep, ...],
    ) -> str:
        source = subject_name
        for step in access:
            if step.kind == "variant_field":
                assert step.case_name is not None and step.field_name is not None
                source = (
                    f"{source}.data.{c_identifier(step.case_name)}.{c_identifier(step.field_name)}"
                )
            elif step.kind == "result_ok":
                source = f"{source}.data.ok"
            elif step.kind == "result_err":
                source = f"{source}.data.err"
            elif step.kind == "option_value":
                source = f"{source}.data.value"
            else:
                raise AssertionError(f"unknown pattern access step {step.kind!r}")
        return source

    def _emit_for_each(self, statement: ast.ForEachStmt) -> None:
        if statement.is_comptime:
            self._emit_comptime_for_each(statement)
            return
        iterable_type = value_type(self.semantic.expression_type(statement.iterable))
        symbol = self.semantic.foreach_symbols[id(statement)]
        if isinstance(iterable_type, RangeType):
            self._emit_range_loop(statement, symbol)
            return

        self.writer.line("{")
        self.writer.indent += 1
        index_name = self._new_temp("index")
        skip_condition: str | None = None
        iterator_cleanup: _Cleanup | None = None
        if isinstance(iterable_type, SliceType):
            iterator_name = self._new_temp("slice")
            iterator_value = self._emit_with_expected(statement.iterable, iterable_type)
            self.writer.line(f"{c_decl(iterable_type, iterator_name)} = {iterator_value};")
            length = f"{iterator_name}.length"
            value = f"{iterator_name}.data[{index_name}]"
        elif isinstance(iterable_type, ListType):
            iterator_name = self._new_temp("list")
            length_name = self._new_temp("list_length")
            iterator_value = self._list_pointer(statement.iterable)
            self.writer.line(
                f"{c_decl(PointerType(ConstType(iterable_type)), iterator_name)} = "
                f"{iterator_value};"
            )
            self.writer.line(f"size_t {length_name} = {iterator_name}->length;")
            length = length_name
            value = f"{iterator_name}->data[{index_name}]"
        elif isinstance(iterable_type, MapType):
            iterator_name = self._new_temp("map")
            iterator_value = self._container_pointer(statement.iterable)
            self.writer.line(
                f"{c_decl(PointerType(ConstType(iterable_type)), iterator_name)} = "
                f"{iterator_value};"
            )
            helper = c_identifier(map_c_name(iterable_type))
            self.writer.line(f"{helper}_begin_iteration({iterator_name});")
            iterator_cleanup = _Cleanup(iterator_end=(f"{helper}_end_iteration", iterator_name))
            if self.scope_frames:
                self.scope_frames[-1].cleanups.append(iterator_cleanup)
            length = f"{iterator_name}->entries_length"
            skip_condition = f"!{iterator_name}->entries[{index_name}].occupied"
            value = f"{iterator_name}->entries[{index_name}].key"
        elif isinstance(iterable_type, SetType):
            iterator_name = self._new_temp("set")
            iterator_value = self._container_pointer(statement.iterable)
            self.writer.line(
                f"{c_decl(PointerType(ConstType(iterable_type)), iterator_name)} = "
                f"{iterator_value};"
            )
            helper = c_identifier(set_c_name(iterable_type))
            self.writer.line(f"{helper}_begin_iteration({iterator_name});")
            iterator_cleanup = _Cleanup(iterator_end=(f"{helper}_end_iteration", iterator_name))
            if self.scope_frames:
                self.scope_frames[-1].cleanups.append(iterator_cleanup)
            length = f"{iterator_name}->capacity"
            skip_condition = f"{iterator_name}->entries[{index_name}].state != 1"
            value = f"{iterator_name}->entries[{index_name}].value"
        elif isinstance(iterable_type, MapViewType):
            view_name = self._new_temp("map_view")
            self.writer.line(
                f"{c_decl(iterable_type, view_name)} = {self._emit_expr(statement.iterable)};"
            )
            iterator_name = self._new_temp("map")
            map_type = iterable_type.map_type
            self.writer.line(
                f"{c_decl(PointerType(ConstType(map_type)), iterator_name)} = {view_name}.map;"
            )
            helper = c_identifier(map_c_name(map_type))
            self.writer.line(f"{helper}_begin_iteration({iterator_name});")
            iterator_cleanup = _Cleanup(iterator_end=(f"{helper}_end_iteration", iterator_name))
            if self.scope_frames:
                self.scope_frames[-1].cleanups.append(iterator_cleanup)
            length = f"{iterator_name}->entries_length"
            skip_condition = f"!{iterator_name}->entries[{index_name}].occupied"
            if iterable_type.kind == "keys":
                value = f"{iterator_name}->entries[{index_name}].key"
            elif iterable_type.kind == "values":
                value = f"{iterator_name}->entries[{index_name}].value"
            else:
                tuple_type = TupleType((map_type.key, map_type.value))
                value = (
                    f"({c_type_expression(tuple_type)}){{ "
                    f".item_0 = {iterator_name}->entries[{index_name}].key, "
                    f".item_1 = {iterator_name}->entries[{index_name}].value }}"
                )
        elif isinstance(iterable_type, ArrayType):
            iterator = self._emit_expr(statement.iterable)
            length = str(iterable_type.length)
            value = f"({iterator})[{index_name}]"
        else:
            raise AssertionError(f"invalid iterable type: {iterable_type!r}")

        self.writer.line(f"for (size_t {index_name} = 0; {index_name} < {length}; ++{index_name})")
        self.writer.line("{")
        self.writer.indent += 1
        if skip_condition is not None:
            self.writer.line(f"if ({skip_condition})")
            self.writer.line("{")
            self.writer.indent += 1
            self.writer.line("continue;")
            self.writer.indent -= 1
            self.writer.line("}")
        self.writer.line(f"{c_decl(symbol.type, c_identifier(symbol.name))} = {value};")
        self._emit_block_contents(statement.body, loop_body=True)
        self.writer.indent -= 1
        self.writer.line("}")
        if iterator_cleanup is not None:
            if self.scope_frames:
                cleanup = self.scope_frames[-1].cleanups.pop()
                if cleanup is not iterator_cleanup:
                    raise AssertionError("iterator cleanup stack is unbalanced")
            assert iterator_cleanup.iterator_end is not None
            helper_name, pointer = iterator_cleanup.iterator_end
            self.writer.line(f"{helper_name}({pointer});")
        self.writer.indent -= 1
        self.writer.line("}")

    def _emit_comptime_for_each(self, statement: ast.ForEachStmt) -> None:
        symbol = self.semantic.comptime_foreach_symbols[id(statement)]
        if symbol.collection_kind == "fields":
            members: list[object] = list(self._nominal_fields(symbol.owner))
        elif symbol.collection_kind == "methods":
            members = list(self._nominal_methods(symbol.owner))
        else:
            raise AssertionError(f"unknown compile-time collection {symbol.collection_kind!r}")

        if not members:
            self.writer.line(
                f"/* comptime {symbol.collection_kind} loop for {symbol.owner.name}: empty */"
            )
            return

        for index, member in enumerate(members):
            self.comptime_members[symbol.statement_id] = member
            self.writer.line(
                f"/* comptime {symbol.collection_kind} iteration {index} for {symbol.owner.name} */"
            )
            self.writer.line("{")
            self.writer.indent += 1
            self._emit_block_contents(statement.body, loop_body=False)
            self.writer.indent -= 1
            self.writer.line("}")
        self.comptime_members.pop(symbol.statement_id, None)

    def _emit_range_loop(self, statement: ast.ForEachStmt, symbol: VariableSymbol) -> None:
        assert isinstance(statement.iterable, ast.CallExpr)
        resolution = self.semantic.range_resolutions[id(statement.iterable)]
        call = statement.iterable
        start_name = self._new_temp("range_start")
        stop_name = self._new_temp("range_stop")
        step_name = self._new_temp("range_step")
        loop_name = c_identifier(symbol.name)
        element_type = resolution.element_type

        if resolution.start_index < 0:
            start = "0"
        else:
            start = self._emit_with_expected(
                call.arguments[resolution.start_index].value,
                element_type,
            )
        stop = self._emit_with_expected(
            call.arguments[resolution.stop_index].value,
            element_type,
        )
        step = (
            "1"
            if resolution.step_index is None
            else self._emit_with_expected(
                call.arguments[resolution.step_index].value,
                element_type,
            )
        )

        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"{c_decl(element_type, start_name)} = {start};")
        self.writer.line(f"{c_decl(element_type, stop_name)} = {stop};")
        self.writer.line(f"{c_decl(element_type, step_name)} = {step};")
        self.writer.line(f"if ({step_name} == 0)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line('cinder_panic("range step cannot be zero");')
        self.writer.indent -= 1
        self.writer.line("}")
        condition = f"({step_name} > 0 ? {loop_name} < {stop_name} : {loop_name} > {stop_name})"
        self.writer.line(
            f"for ({c_decl(symbol.type, loop_name)} = {start_name}; "
            f"{condition}; {loop_name} += {step_name})"
        )
        self.writer.line("{")
        self.writer.indent += 1
        self._emit_block_contents(statement.body, loop_body=True)
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.indent -= 1
        self.writer.line("}")

    def _emit_for_c(self, statement: ast.ForCStmt) -> None:
        initializer = (
            "" if statement.initializer is None else self._emit_for_clause(statement.initializer)
        )
        condition = "" if statement.condition is None else self._emit_expr(statement.condition)
        update = "" if statement.update is None else self._emit_for_clause(statement.update)
        self.writer.line(f"for ({initializer}; {condition}; {update})")
        self.writer.line("{")
        self.writer.indent += 1
        self._emit_block_contents(statement.body, loop_body=True)
        self.writer.indent -= 1
        self.writer.line("}")

    def _emit_for_clause(self, statement: ast.Statement) -> str:
        if isinstance(statement, ast.VarDeclStmt):
            symbol = self.semantic.declaration_symbols[id(statement)]
            declaration_type = ConstType(symbol.type) if symbol.is_const else symbol.type
            declaration = c_decl(declaration_type, c_identifier(symbol.name))
            if statement.initializer is None:
                return declaration
            return f"{declaration} = {self._emit_initializer(statement.initializer, symbol.type)}"
        if isinstance(statement, ast.AssignStmt):
            implicit = self.semantic.implicit_declarations.get(id(statement))
            if implicit is not None:
                declaration = c_decl(implicit.type, c_identifier(implicit.name))
                return f"{declaration} = {self._emit_initializer(statement.value, implicit.type)}"
            target = self._emit_lvalue(statement.target)
            expected = strip_reference(self.semantic.expression_type(statement.target))
            return f"{target} {statement.operator} {self._emit_with_expected(statement.value, expected)}"
        if isinstance(statement, ast.ExpressionStmt):
            return self._emit_expr(statement.expression)
        raise AssertionError(f"invalid for clause: {statement!r}")

    def _emit_loop_exit(self, keyword: str) -> None:
        for frame in reversed(self.scope_frames):
            self._emit_deferred(frame)
            if frame.loop_body:
                break
        self.writer.line(f"{keyword};")

    def _emit_all_deferred(
        self,
        *,
        exclude_variable: VariableSymbol | None = None,
    ) -> None:
        for frame in reversed(self.scope_frames):
            self._emit_deferred(frame, exclude_variable=exclude_variable)

    def _emit_deferred(
        self,
        frame: _ScopeFrame,
        *,
        exclude_variable: VariableSymbol | None = None,
    ) -> None:
        for cleanup in reversed(frame.cleanups):
            if cleanup.drop_statement is not None:
                self.writer.line(cleanup.drop_statement)
                continue
            if cleanup.iterator_end is not None:
                helper, pointer = cleanup.iterator_end
                self.writer.line(f"{helper}({pointer});")
                continue
            if cleanup.expression is not None:
                self.writer.line(self._emit_expr(cleanup.expression) + ";")
                continue
            if cleanup.variable is None:
                raise AssertionError("invalid cleanup entry")
            if cleanup.variable is exclude_variable:
                continue
            name = c_identifier(cleanup.variable.c_name or cleanup.variable.name)
            if cleanup.drop_type is not None:
                self._emit_drop_glue(cleanup.drop_type, f"&{name}")
            elif cleanup.class_ is not None:
                self.writer.line(f"{self._class_drop_name(cleanup.class_)}(&{name});")
            elif cleanup.container is not None:
                self.writer.line(f"{self._container_drop_name(cleanup.container)}(&{name});")
            else:
                raise AssertionError("invalid cleanup entry")

    def _register_owned_cleanup(self, symbol: VariableSymbol) -> None:
        if not self.scope_frames:
            return
        if not self._type_needs_drop(symbol.type):
            return
        self.scope_frames[-1].cleanups.append(
            _Cleanup(variable=symbol, drop_type=strip_const(symbol.type))
        )

    def _exclude_moved_variables(
        self,
        moved_variables: tuple[VariableSymbol, ...],
    ) -> None:
        if not moved_variables:
            return
        moved_ids = {id(symbol) for symbol in moved_variables}
        moved_param_names = {symbol.name for symbol in moved_variables if symbol.is_parameter}

        def keep(cleanup: _Cleanup) -> bool:
            if cleanup.variable is None:
                return True
            if id(cleanup.variable) in moved_ids:
                return False
            return not (
                cleanup.variable.is_parameter and cleanup.variable.name in moved_param_names
            )

        for frame in self.scope_frames:
            frame.cleanups = [cleanup for cleanup in frame.cleanups if keep(cleanup)]

    def _exclude_moved_from_expression(self, expression: ast.Expression) -> None:
        if not isinstance(expression, ast.NameExpr):
            return
        symbol = self.semantic.name_symbols.get(id(expression))
        if isinstance(symbol, VariableSymbol) and self._type_needs_drop(symbol.type):
            self._exclude_moved_variables((symbol,))

    def _returned_local_symbol(
        self,
        expression: ast.Expression,
    ) -> VariableSymbol | None:
        if not isinstance(expression, ast.NameExpr):
            return None
        symbol = self.semantic.name_symbols.get(id(expression))
        if not isinstance(symbol, VariableSymbol):
            return None
        if self._type_needs_drop(symbol.type):
            return symbol
        return None

    def _emit_initializer(self, expression: ast.Expression, expected: Type) -> str:
        expected_value = strip_const(expected)
        if isinstance(expression, ast.NoneExpr) and isinstance(
            expected_value,
            OptionType,
        ):
            return "{ 0 }"
        if isinstance(expression, ast.ListLiteralExpr) and isinstance(expected_value, ArrayType):
            values = [
                self._emit_initializer(element, expected_value.inner)
                for element in expression.elements
            ]
            return "{ " + ", ".join(values) + " }"
        if isinstance(expression, ast.TupleLiteralExpr) and isinstance(
            expected_value,
            TupleType,
        ):
            values = [
                f".item_{index} = {self._emit_initializer(element, expected_value.elements[index])}"
                for index, element in enumerate(expression.elements)
                if index < len(expected_value.elements)
            ]
            return "{ 0 }" if not values else "{ " + ", ".join(values) + " }"

        if isinstance(expression, ast.CallExpr):
            resolution = self.semantic.call_resolutions.get(id(expression))
            if resolution is not None and resolution.kind in {
                "constructor",
                "union_constructor",
                "variant_constructor",
                "result_constructor",
                "option_some",
            }:
                self._exclude_moved_variables(resolution.moved_variables)
                return self._constructor_initializer(expression, resolution)

        return self._emit_with_expected(expression, expected)

    def _constructor_initializer(
        self,
        expression: ast.CallExpr,
        resolution: CallResolution,
    ) -> str:
        fields: list[str] = []
        if resolution.kind == "option_some":
            option_type = resolution.compile_value
            if not isinstance(option_type, OptionType):
                raise AssertionError("Some constructor has no Option type")
            name = c_identifier(option_c_name(option_type))
            fields.append(f".tag = {name}_Tag_Some")
            if expression.arguments:
                value = self._emit_initializer(
                    expression.arguments[0].value,
                    option_type.inner,
                )
                fields.append(f".data.value = {value}")

        elif resolution.kind == "variant_constructor":
            assert resolution.variant_case is not None
            fields.append(f".tag = {c_identifier(resolution.variant_case.c_name)}")
            case_name = c_identifier(resolution.variant_case.name)
            payload: list[str] = []
            for output_index, argument_index in enumerate(resolution.argument_order):
                field_name = c_identifier(resolution.field_order[output_index])
                field_type = resolution.expected_types[output_index]
                assert field_type is not None
                value = self._emit_initializer(
                    expression.arguments[argument_index].value,
                    field_type,
                )
                payload.append(f".{field_name} = {value}")
            if payload:
                fields.append(f".data.{case_name} = {{ {', '.join(payload)} }}")

        elif resolution.kind == "result_constructor":
            assert resolution.result_type is not None
            suffix = "Ok" if resolution.result_is_ok else "Err"
            fields.append(f".tag = {self._result_tag(resolution.result_type, suffix)}")
            if resolution.argument_order:
                argument_index = resolution.argument_order[0]
                payload_type = (
                    resolution.result_type.ok
                    if resolution.result_is_ok
                    else resolution.result_type.error
                )
                value = self._emit_initializer(
                    expression.arguments[argument_index].value,
                    payload_type,
                )
                payload_name = "ok" if resolution.result_is_ok else "err"
                fields.append(f".data.{payload_name} = {value}")

        else:
            for output_index, argument_index in enumerate(resolution.argument_order):
                field_name = c_identifier(resolution.field_order[output_index])
                field_type = resolution.expected_types[output_index]
                assert field_type is not None
                value = self._emit_initializer(
                    expression.arguments[argument_index].value,
                    field_type,
                )
                fields.append(f".{field_name} = {value}")

        return "{ 0 }" if not fields else "{ " + ", ".join(fields) + " }"

    def _emit_with_expected(self, expression: ast.Expression, expected: Type) -> str:
        actual = self.semantic.expression_type(expression)
        expected_raw = strip_const(expected)
        actual_raw = strip_const(actual)

        if isinstance(expected_raw, DynType):
            if isinstance(actual_raw, DynType):
                return self._emit_expr(expression)
            return self._emit_dyn_conversion(expression, expected_raw)

        if isinstance(expected_raw, ReferenceType):
            target_inner = strip_const(expected_raw.inner)
            if isinstance(target_inner, ClassType):
                target = self.semantic.nominal_symbols.get(target_inner)
                if isinstance(target, ClassSymbol):
                    return self._class_pointer_from_expression(expression, target)
            if isinstance(actual_raw, ReferenceType):
                return self._emit_expr(expression, mode="raw")
            if isinstance(actual_raw, PointerType):
                return self._emit_expr(expression)
            return self._emit_address(expression)

        if isinstance(expected_raw, PointerType):
            target_inner = strip_const(expected_raw.inner)
            if isinstance(target_inner, ClassType):
                target = self.semantic.nominal_symbols.get(target_inner)
                if isinstance(target, ClassSymbol):
                    return self._class_pointer_from_expression(expression, target)
            if isinstance(actual_raw, ReferenceType):
                return self._emit_expr(expression, mode="raw")

        if isinstance(expected_raw, SliceType):
            actual_value = value_type(actual)
            if isinstance(actual_value, ArrayType):
                return self._array_as_slice(expression, expected_raw)
            if isinstance(actual_value, ListType):
                return self._list_as_slice(expression, expected_raw)
            if (
                isinstance(actual_value, SliceType)
                and actual_value != expected_raw
                and isinstance(expected_raw.inner, ConstType)
                and expected_raw.inner.inner == actual_value.inner
            ):
                return (
                    f"{self._slice_name(expected_raw)}_from_mutable({self._emit_expr(expression)})"
                )

        return self._emit_expr(expression)

    def _emit_condition(self, expression: ast.Expression) -> str:
        text = self._emit_expr(expression)
        condition_type = value_type(self.semantic.expression_type(expression))
        if isinstance(condition_type, (SliceType, ListType)):
            return f"(({text}).length != 0)"
        if text.startswith("(") and text.endswith(")"):
            return text
        return f"({text})"

    def _emit_expr(self, expression: ast.Expression, *, mode: str = "value") -> str:
        match expression:
            case ast.LiteralExpr():
                return self._emit_literal(expression)
            case ast.NoneExpr():
                option_type = value_type(self.semantic.expression_type(expression))
                assert isinstance(option_type, OptionType)
                return f"(({c_type_expression(option_type)}){{ 0 }})"
            case ast.FStringExpr():
                raise AssertionError("f-strings may only be emitted as print arguments")
            case ast.NameExpr():
                return self._emit_name(expression, mode)
            case ast.UnaryExpr(operator=operator, operand=operand):
                if operator == "&":
                    return self._emit_address(operand)
                if operator == "not":
                    return f"(!{self._emit_condition(operand)})"
                if operator == "*":
                    operand_type = strip_const(self.semantic.expression_type(operand))
                    if isinstance(operand_type, OwnedType):
                        return f"(*({self._emit_expr(operand)}).ptr)"
                c_operator = "!" if operator == "not" else operator
                return f"({c_operator}{self._emit_expr(operand)})"
            case ast.BinaryExpr(left=left, operator=operator, right=right):
                resolution = self.semantic.binary_resolutions.get(id(expression))
                if resolution is not None:
                    return self._emit_resolved_binary(
                        expression,
                        resolution.kind,
                        resolution.owner_type,
                    )
                c_operator = {"and": "&&", "or": "||"}.get(operator, operator)
                if operator in {"and", "or"}:
                    return (
                        f"({self._emit_condition(left)} {c_operator} {self._emit_condition(right)})"
                    )
                return f"({self._emit_expr(left)} {c_operator} {self._emit_expr(right)})"
            case ast.AttributeExpr():
                return self._emit_attribute(expression)
            case ast.IndexExpr():
                return self._emit_index(expression)
            case ast.SliceExpr():
                return self._emit_slice(expression)
            case ast.CallExpr():
                return self._emit_call(expression)
            case ast.PropagateExpr():
                return self._emit_propagate(expression)
            case ast.ListLiteralExpr():
                literal_type = value_type(self.semantic.expression_type(expression))
                if isinstance(literal_type, ListType):
                    if not expression.elements:
                        return f"{c_identifier(list_c_name(literal_type))}_from_values(NULL, 0)"
                    array_type = ArrayType(
                        literal_type.inner,
                        len(expression.elements),
                    )
                    values = ", ".join(
                        self._emit_with_expected(element, literal_type.inner)
                        for element in expression.elements
                    )
                    return (
                        f"{c_identifier(list_c_name(literal_type))}_from_values("
                        f"({c_type_expression(array_type)}){{ {values} }}, "
                        f"{len(expression.elements)})"
                    )
                assert isinstance(literal_type, ArrayType)
                values = ", ".join(
                    self._emit_with_expected(element, literal_type.inner)
                    for element in expression.elements
                )
                return f"({c_type_expression(literal_type)}){{ {values} }}"
            case ast.MapLiteralExpr(entries=entries):
                map_type = value_type(self.semantic.expression_type(expression))
                assert isinstance(map_type, MapType)
                return self._emit_map_literal(entries, map_type)
            case ast.SetLiteralExpr(elements=elements):
                set_type = value_type(self.semantic.expression_type(expression))
                assert isinstance(set_type, SetType)
                return self._emit_set_literal(elements, set_type)
            case ast.TupleLiteralExpr():
                tuple_type = value_type(self.semantic.expression_type(expression))
                assert isinstance(tuple_type, TupleType)
                fields = ", ".join(
                    f".item_{index} = "
                    f"{self._emit_with_expected(element, tuple_type.elements[index])}"
                    for index, element in enumerate(expression.elements)
                )
                initializer = "{ 0 }" if not fields else f"{{ {fields} }}"
                return f"({c_type_expression(tuple_type)}){initializer}"
            case ast.CastExpr(target_type=target_node, value=value):
                target = self.semantic.type_nodes[id(target_node)]
                return f"(({c_type_expression(target)})({self._emit_expr(value)}))"
            case ast.AllocExpr(element_type=element_node, count=count):
                element = self.semantic.type_nodes[id(element_node)]
                count_text = "1" if count is None else self._emit_expr(count)
                pointer = PointerType(element)
                return (
                    f"(({c_type_expression(pointer)})cinder_alloc("
                    f"{count_text}, sizeof({c_type_expression(element)})))"
                )
            case _:
                raise AssertionError(f"unhandled expression: {expression!r}")

    def _emit_map_literal(
        self,
        entries: list[ast.MapEntry],
        map_type: MapType,
    ) -> str:
        name = c_identifier(map_c_name(map_type))
        temporary = self._new_temp("map_literal")
        self.writer.line(f"{c_decl(map_type, temporary)} = {{ 0 }};")
        cleanup = _Cleanup(iterator_end=(f"{name}_drop", f"&{temporary}"))
        if self.scope_frames:
            self.scope_frames[-1].cleanups.append(cleanup)
        for entry in entries:
            key_name = self._new_temp("map_key")
            value_name = self._new_temp("map_value")
            self.writer.line(
                f"{c_decl(map_type.key, key_name)} = "
                f"{self._emit_borrowed_value(entry.key, map_type.key, 'map_key')};"
            )
            self.writer.line(
                f"{c_decl(map_type.value, value_name)} = "
                f"{self._emit_with_expected(entry.value, map_type.value)};"
            )
            self.writer.line(f"{name}_set(&{temporary}, {key_name}, {value_name});")
        if self.scope_frames:
            frame = self.scope_frames[-1]
            if cleanup not in frame.cleanups:
                raise AssertionError("Map literal cleanup stack is unbalanced")
            frame.cleanups.remove(cleanup)
        return temporary

    def _emit_set_literal(
        self,
        elements: list[ast.Expression],
        set_type: SetType,
    ) -> str:
        name = c_identifier(set_c_name(set_type))
        temporary = self._new_temp("set_literal")
        self.writer.line(f"{c_decl(set_type, temporary)} = {{ 0 }};")
        cleanup = _Cleanup(iterator_end=(f"{name}_drop", f"&{temporary}"))
        if self.scope_frames:
            self.scope_frames[-1].cleanups.append(cleanup)
        for element in elements:
            item_name = self._new_temp("set_item")
            self.writer.line(
                f"{c_decl(set_type.inner, item_name)} = "
                f"{self._emit_borrowed_value(element, set_type.inner, 'set_item')};"
            )
            self.writer.line(f"{name}_add(&{temporary}, {item_name});")
        if self.scope_frames:
            frame = self.scope_frames[-1]
            if cleanup not in frame.cleanups:
                raise AssertionError("Set literal cleanup stack is unbalanced")
            frame.cleanups.remove(cleanup)
        return temporary

    def _emit_resolved_binary(
        self,
        expression: ast.BinaryExpr,
        kind: str,
        owner_type: Type | None,
    ) -> str:
        if kind == "string_equal" and owner_type is not None and is_c_string(owner_type):
            value = (
                f"cinder_string_equal({self._emit_expr(expression.left)}, "
                f"{self._emit_expr(expression.right)})"
            )
            return f"(!{value})" if expression.operator == "!=" else value

        if kind in {
            "string_concat",
            "string_equal",
            "string_order",
            "string_compare",
        }:
            left = self._borrow_string_pointer(expression.left, "string_left")
            right = self._borrow_string_pointer(expression.right, "string_right")
            if kind == "string_concat":
                return f"cinder_string_concat({left}, {right})"
            if kind == "string_equal":
                value = f"cinder_string_equal_value({left}, {right})"
                return f"(!{value})" if expression.operator == "!=" else value
            comparison = f"cinder_string_compare_value({left}, {right})"
            operator = expression.operator
            if operator not in {"<", "<=", ">", ">="}:
                raise AssertionError(f"invalid String ordering operator {operator!r}")
            return f"({comparison} {operator} 0)"

        if kind == "map_contains":
            assert isinstance(owner_type, MapType)
            name = c_identifier(map_c_name(owner_type))
            key = self._emit_borrowed_value(
                expression.left,
                owner_type.key,
                "map_contains_key",
            )
            if isinstance(expression.right, ast.MapLiteralExpr):
                owned = self._emit_inline_map_literal(
                    expression.right.entries,
                    owner_type,
                )
                value = f"{name}_contains_owned({owned}, {key})"
                return f"(!{value})" if expression.operator == "not in" else value
            if isinstance(expression.right, ast.CallExpr):
                owned = self._emit_expr(expression.right)
                value = f"{name}_contains_owned({owned}, {key})"
                return f"(!{value})" if expression.operator == "not in" else value
            pointer, temporary = self._materialize_container_operand(
                expression.right,
                owner_type,
            )
            value = f"{name}_contains({pointer}, {key})"
            if expression.operator == "not in":
                value = f"(!{value})"
            if temporary is None:
                return value
            result = self._new_temp("contains")
            self.writer.line(f"bool {result} = {value};")
            self.writer.line(f"{name}_drop(&{temporary});")
            return result

        if kind == "set_contains":
            assert isinstance(owner_type, SetType)
            name = c_identifier(set_c_name(owner_type))
            item = self._emit_borrowed_value(
                expression.left,
                owner_type.inner,
                "set_contains_item",
            )
            if isinstance(expression.right, ast.SetLiteralExpr):
                owned = self._emit_inline_set_literal(
                    expression.right.elements,
                    owner_type,
                )
                value = f"{name}_contains_owned({owned}, {item})"
                return f"(!{value})" if expression.operator == "not in" else value
            if isinstance(expression.right, ast.CallExpr):
                owned = self._emit_expr(expression.right)
                value = f"{name}_contains_owned({owned}, {item})"
                return f"(!{value})" if expression.operator == "not in" else value
            pointer, temporary = self._materialize_container_operand(
                expression.right,
                owner_type,
            )
            value = f"{name}_contains({pointer}, {item})"
            if expression.operator == "not in":
                value = f"(!{value})"
            if temporary is None:
                return value
            result = self._new_temp("contains")
            self.writer.line(f"bool {result} = {value};")
            self.writer.line(f"{name}_drop(&{temporary});")
            return result

        if kind == "map_view_contains":
            assert isinstance(owner_type, MapViewType)
            name = c_identifier(map_c_name(owner_type.map_type))
            view = self._emit_expr(expression.right)
            if owner_type.kind == "keys":
                item = self._emit_borrowed_value(
                    expression.left,
                    owner_type.map_type.key,
                    "map_view_key",
                )
                value = f"{name}_contains(({view}).map, {item})"
            elif owner_type.kind == "values":
                item = self._emit_borrowed_value(
                    expression.left,
                    owner_type.map_type.value,
                    "map_view_value",
                )
                value = f"{name}_values_contains(({view}).map, {item})"
            else:
                item_type = TupleType((owner_type.map_type.key, owner_type.map_type.value))
                item = self._emit_with_expected(expression.left, item_type)
                value = f"{name}_items_contains(({view}).map, {item})"
            return f"(!{value})" if expression.operator == "not in" else value

        if kind.startswith("set_") and kind != "set_compare":
            assert isinstance(owner_type, SetType)
            name = c_identifier(set_c_name(owner_type))
            method = kind.removeprefix("set_")
            left, left_temp = self._materialize_container_operand(
                expression.left,
                owner_type,
            )
            right, right_temp = self._materialize_container_operand(
                expression.right,
                owner_type,
            )
            result = self._new_temp("set_expression")
            self.writer.line(f"{c_decl(owner_type, result)} = {name}_{method}({left}, {right});")
            for temporary in (left_temp, right_temp):
                if temporary is not None:
                    self.writer.line(f"{name}_drop(&{temporary});")
            return result

        if kind == "set_compare":
            assert isinstance(owner_type, SetType)
            name = c_identifier(set_c_name(owner_type))
            left, left_temp = self._materialize_container_operand(
                expression.left,
                owner_type,
            )
            right, right_temp = self._materialize_container_operand(
                expression.right,
                owner_type,
            )
            operator = expression.operator
            if operator == "==":
                value = f"{name}_equal({left}, {right})"
            elif operator == "!=":
                value = f"(!{name}_equal({left}, {right}))"
            elif operator == "<=":
                value = f"{name}_is_subset({left}, {right})"
            elif operator == ">=":
                value = f"{name}_is_subset({right}, {left})"
            elif operator == "<":
                value = (
                    f"(({left})->length < ({right})->length && {name}_is_subset({left}, {right}))"
                )
            elif operator == ">":
                value = (
                    f"(({left})->length > ({right})->length && {name}_is_subset({right}, {left}))"
                )
            else:
                raise AssertionError(f"invalid Set comparison {operator!r}")
            if left_temp is None and right_temp is None:
                return value
            result = self._new_temp("set_compare")
            self.writer.line(f"bool {result} = {value};")
            for temporary in (left_temp, right_temp):
                if temporary is not None:
                    self.writer.line(f"{name}_drop(&{temporary});")
            return result

        raise AssertionError(f"unhandled binary resolution {kind!r}")

    def _materialize_container_operand(
        self,
        expression: ast.Expression,
        type_: MapType | SetType,
    ) -> tuple[str, str | None]:
        if isinstance(
            expression,
            (ast.NameExpr, ast.AttributeExpr),
        ) or (isinstance(expression, ast.UnaryExpr) and expression.operator == "*"):
            return self._container_pointer(expression), None
        temporary = self._new_temp("collection_operand")
        self.writer.line(f"{c_decl(type_, temporary)} = {self._emit_expr(expression)};")
        return f"&{temporary}", temporary

    def _emit_inline_map_literal(
        self,
        entries: list[ast.MapEntry],
        map_type: MapType,
    ) -> str:
        name = c_identifier(map_c_name(map_type))
        if not entries:
            return f"{name}_from_values(NULL, NULL, 0)"
        keys = ", ".join(
            self._emit_borrowed_value(entry.key, map_type.key, "map_key") for entry in entries
        )
        values = ", ".join(
            self._emit_with_expected(entry.value, map_type.value) for entry in entries
        )
        key_array = c_type_expression(ArrayType(map_type.key, len(entries)))
        value_array = c_type_expression(ArrayType(map_type.value, len(entries)))
        return (
            f"{name}_from_values(({key_array}){{ {keys} }}, "
            f"({value_array}){{ {values} }}, {len(entries)})"
        )

    def _emit_inline_set_literal(
        self,
        elements: list[ast.Expression],
        set_type: SetType,
    ) -> str:
        name = c_identifier(set_c_name(set_type))
        values = ", ".join(
            self._emit_borrowed_value(element, set_type.inner, "set_item") for element in elements
        )
        array = c_type_expression(ArrayType(set_type.inner, len(elements)))
        return f"{name}_from_values(({array}){{ {values} }}, {len(elements)})"

    def _emit_literal(self, expression: ast.LiteralExpr) -> str:
        if expression.literal_kind == "bool":
            return "true" if expression.value else "false"
        if expression.literal_kind == "null":
            return "NULL"
        if expression.literal_kind == "string":
            assert isinstance(expression.value, str)
            literal_type = value_type(self.semantic.expression_type(expression))
            if isinstance(literal_type, StringType):
                return c_static_string(expression.value)
            return c_string(expression.value)
        if expression.literal_kind == "char":
            assert isinstance(expression.value, str)
            return c_char(expression.value)
        if expression.literal_kind == "integer":
            type_ = value_type(self.semantic.expression_type(expression))
            assert isinstance(expression.value, int)
            if type_ == U64:
                return f"UINT64_C({expression.value})"
            if type_ == I64 and not (-(2**31) <= expression.value <= 2**31 - 1):
                if expression.value < 0:
                    return f"(-INT64_C({abs(expression.value)}))"
                return f"INT64_C({expression.value})"
            return expression.raw.replace("_", "")
        if expression.literal_kind == "float":
            raw = expression.raw.replace("_", "")
            type_ = value_type(self.semantic.expression_type(expression))
            if type_ == F32 and not raw.lower().endswith("f"):
                raw += "f"
            return raw
        raise AssertionError(f"unknown literal kind {expression.literal_kind!r}")

    def _emit_name(self, expression: ast.NameExpr, mode: str) -> str:
        symbol = self.semantic.name_symbols.get(id(expression))
        if symbol is None:
            return c_identifier(expression.name)
        if isinstance(symbol, VariableSymbol):
            name = c_identifier(symbol.c_name or symbol.name)
            if isinstance(strip_const(symbol.type), ReferenceType) and mode != "raw":
                return f"(*{name})"
            return name
        if isinstance(symbol, FunctionSymbol):
            return c_identifier(symbol.c_name)
        if isinstance(symbol, ConstantSymbol):
            return c_identifier(symbol.c_name)
        if isinstance(symbol, (StructSymbol, ClassSymbol, EnumSymbol, UnionSymbol, VariantSymbol)):
            return c_identifier(symbol.c_name)
        if isinstance(symbol, ComptimeVariableSymbol):
            raise AssertionError("compile-time iterator values have no runtime representation")
        if isinstance(symbol, ModuleSymbol):
            return c_identifier(symbol.name)
        return c_identifier(expression.name)

    def _emit_attribute(self, expression: ast.AttributeExpr) -> str:
        resolution = self.semantic.attribute_resolutions[id(expression)]
        if resolution.kind == "module_constant":
            assert resolution.constant is not None
            return c_identifier(resolution.constant.c_name)
        if resolution.kind == "module_global":
            assert resolution.global_ is not None
            return c_identifier(resolution.global_.c_name or resolution.global_.name)
        if resolution.kind == "module_function":
            assert resolution.function is not None
            return c_identifier(resolution.function.c_name)
        if resolution.kind == "module_type":
            if resolution.nominal is not None:
                return c_identifier(resolution.nominal.c_name)
            owner_type = resolution.owner_type
            if isinstance(owner_type, OpaqueType):
                return owner_type.c_name
            if owner_type is not None and owner_type is not ERROR:
                return c_type_expression(owner_type)
            raise AssertionError("module_type attribute has neither nominal nor owner_type")
        if resolution.kind == "enum_member":
            assert resolution.enum_member is not None
            return c_identifier(resolution.enum_member.c_name)
        if resolution.kind in ("field", "union_field"):
            base_type = strip_const(self.semantic.expression_type(expression.value))
            pointer = isinstance(base_type, (PointerType, ReferenceType))
            base = self._emit_expr(
                expression.value,
                mode="raw" if isinstance(base_type, ReferenceType) else "value",
            )
            operator = "->" if pointer else "."
            return f"({base}){operator}{c_identifier(expression.name)}"
        if resolution.kind == "atomic_result_field":
            base_type = strip_const(self.semantic.expression_type(expression.value))
            pointer = isinstance(base_type, (PointerType, ReferenceType))
            base = self._emit_expr(
                expression.value,
                mode="raw" if isinstance(base_type, ReferenceType) else "value",
            )
            operator = "->" if pointer else "."
            return f"({base}){operator}{c_identifier(expression.name)}"
        if resolution.kind == "atomic_method":
            raise AssertionError("atomic method attributes must be emitted through typed atomic IR")
        if resolution.kind == "class_field":
            assert resolution.field is not None
            return self._emit_class_member_access(
                expression.value,
                resolution.access_path,
                resolution.field.name,
            )
        if resolution.kind == "dyn_field":
            assert resolution.field is not None
            owner_type = strip_const(resolution.owner_type or ERROR)
            if not isinstance(owner_type, DynType):
                raise AssertionError("dynamic field has no dynamic owner type")
            interface = self.semantic.nominal_symbols.get(owner_type.interface)
            if not isinstance(interface, ClassSymbol):
                raise AssertionError("dynamic field interface is not a class")
            dynamic = self._materialize_dynamic(expression.value, owner_type, "dyn_field")
            pointer = f"(({c_identifier(interface.c_name)} *){dynamic}.object)"
            return self._emit_pointer_path_access(
                pointer,
                resolution.access_path,
                resolution.field.name,
            )
        if resolution.kind in ("result_is_ok", "result_value", "result_error"):
            base_type = strip_const(self.semantic.expression_type(expression.value))
            pointer = isinstance(base_type, ReferenceType)
            base = self._emit_expr(expression.value, mode="raw" if pointer else "value")
            operator = "->" if pointer else "."
            raw = value_type(base_type)
            assert isinstance(raw, ResultType)
            if resolution.kind == "result_is_ok":
                return f"(({base}){operator}tag == {self._result_tag(raw, 'Ok')})"
            payload = "ok" if resolution.kind == "result_value" else "err"
            return f"({base}){operator}data.{payload}"
        if resolution.kind in {
            "option_is_some",
            "option_is_none",
            "option_value",
        }:
            base_type = strip_const(self.semantic.expression_type(expression.value))
            pointer = isinstance(base_type, (PointerType, ReferenceType))
            base = self._emit_expr(
                expression.value,
                mode="raw" if isinstance(base_type, ReferenceType) else "value",
            )
            raw = strip_const(base_type.inner) if pointer else value_type(base_type)
            assert isinstance(raw, OptionType)
            name = c_identifier(option_c_name(raw))
            if resolution.kind == "option_is_some":
                operator = "->" if pointer else "."
                return f"(({base}){operator}tag == {name}_Tag_Some)"
            if resolution.kind == "option_is_none":
                operator = "->" if pointer else "."
                return f"(({base}){operator}tag == {name}_Tag_None)"
            address = base if pointer else f"&({base})"
            return f"{name}_value_or_panic({address})"
        if resolution.kind in ("slice_data", "slice_length"):
            base_type = strip_const(self.semantic.expression_type(expression.value))
            pointer = isinstance(base_type, ReferenceType)
            base = self._emit_expr(expression.value, mode="raw" if pointer else "value")
            operator = "->" if pointer else "."
            member = "data" if resolution.kind == "slice_data" else "length"
            return f"({base}){operator}{member}"
        if resolution.kind == "string_method":
            method = str(resolution.compile_value)
            return f"cinder_string_{c_identifier(method)}"
        if resolution.kind == "string_builder_method":
            method = str(resolution.compile_value)
            return f"cinder_string_builder_{c_identifier(method)}"
        if resolution.kind == "list_method":
            list_type = value_type(self.semantic.expression_type(expression.value))
            assert isinstance(list_type, ListType)
            method = str(resolution.compile_value)
            return f"{c_identifier(list_c_name(list_type))}_{c_identifier(method)}"
        if resolution.kind == "map_method":
            map_type = value_type(self.semantic.expression_type(expression.value))
            assert isinstance(map_type, MapType)
            method = str(resolution.compile_value)
            return f"{c_identifier(map_c_name(map_type))}_{c_identifier(method)}"
        if resolution.kind == "set_method":
            set_type = value_type(self.semantic.expression_type(expression.value))
            assert isinstance(set_type, SetType)
            method = str(resolution.compile_value)
            return f"{c_identifier(set_c_name(set_type))}_{c_identifier(method)}"
        if resolution.kind == "array_data":
            return self._emit_expr(expression.value)
        if resolution.kind == "array_length":
            return f"CINDER_ARRAY_LEN({self._emit_expr(expression.value)})"
        if resolution.kind == "method":
            assert resolution.method is not None
            return c_identifier(resolution.method.c_name)
        if resolution.kind == "dynamic_method":
            assert resolution.method is not None
            return c_identifier(resolution.method.name)
        if resolution.kind == "comptime_member_attribute":
            return self._emit_comptime_member_attribute(expression)
        if resolution.kind == "variant_case":
            assert resolution.variant_case is not None
            return c_identifier(resolution.variant_case.c_name)
        raise AssertionError(f"unhandled attribute resolution {resolution.kind!r}")

    def _emit_member_access(self, expression: ast.Expression, member: str) -> str:
        base_type = strip_const(self.semantic.expression_type(expression))
        pointer = isinstance(base_type, (PointerType, ReferenceType))
        base = self._emit_expr(
            expression,
            mode="raw" if isinstance(base_type, ReferenceType) else "value",
        )
        operator = "->" if pointer else "."
        return f"({base}){operator}{member}"

    def _emit_class_member_access(
        self,
        expression: ast.Expression,
        path: tuple[str, ...],
        member: str,
    ) -> str:
        base_type = strip_const(self.semantic.expression_type(expression))
        pointer = isinstance(base_type, (PointerType, ReferenceType))
        base = self._emit_expr(
            expression,
            mode="raw" if isinstance(base_type, ReferenceType) else "value",
        )
        parts = [*path, member]
        if not parts:
            return f"({base})"
        result = f"({base}){'->' if pointer else '.'}{c_identifier(parts[0])}"
        for part in parts[1:]:
            result += f".{c_identifier(part)}"
        return result

    @staticmethod
    def _emit_pointer_path_access(
        pointer: str,
        path: tuple[str, ...],
        member: str,
    ) -> str:
        parts = [*path, member]
        if not parts:
            return f"(*({pointer}))"
        result = f"({pointer})->{c_identifier(parts[0])}"
        for part in parts[1:]:
            result += f".{c_identifier(part)}"
        return result

    def _emit_comptime_member_attribute(self, expression: ast.AttributeExpr) -> str:
        if not isinstance(expression.value, ast.NameExpr):
            raise AssertionError("compile-time member attribute has an invalid base")
        symbol = self.semantic.name_symbols.get(id(expression.value))
        if not isinstance(symbol, ComptimeVariableSymbol):
            raise AssertionError("compile-time member attribute has no iterator symbol")
        binding = self.comptime_members.get(symbol.statement_id)
        if binding is None:
            raise AssertionError("compile-time member attribute emitted outside its loop")

        if symbol.collection_kind == "fields":
            field, owner, path = binding
            if not isinstance(field, FieldSymbol):
                raise AssertionError("invalid compile-time field binding")
            if not isinstance(owner, (StructSymbol, ClassSymbol, UnionSymbol)):
                raise AssertionError("invalid compile-time field owner")
            attribute = expression.name
            if attribute == "name":
                return self._emit_compile_text(expression, field.name)
            if attribute == "type_name":
                return self._emit_compile_text(expression, type_name(field.type))
            if attribute == "offset":
                return self._field_offset_expression(symbol.owner, owner, path, field.name)
            field_type = c_type_expression(field.type)
            if attribute == "size":
                return f"sizeof({field_type})"
            if attribute == "alignment":
                return f"CINDER_ALIGNOF({field_type})"
            if attribute == "is_private":
                return "true" if field.is_private else "false"
            raise AssertionError(f"unknown compile-time field attribute {attribute!r}")

        if symbol.collection_kind == "methods":
            method = binding
            if not isinstance(method, FunctionSymbol):
                raise AssertionError("invalid compile-time method binding")
            attribute = expression.name
            if attribute == "name":
                return self._emit_compile_text(expression, method.name)
            if attribute == "signature":
                return self._emit_compile_text(
                    expression,
                    self._method_signature_text(method),
                )
            if attribute == "return_type_name":
                return self._emit_compile_text(
                    expression,
                    type_name(method.return_type),
                )
            if attribute == "parameter_count":
                return str(max(0, len(method.parameters) - (1 if method.owner else 0)))
            if attribute == "is_abstract":
                return "true" if method.is_abstract else "false"
            if attribute == "is_override":
                return "true" if method.is_override else "false"
            raise AssertionError(f"unknown compile-time method attribute {attribute!r}")

        raise AssertionError(f"unknown compile-time collection {symbol.collection_kind!r}")

    def _emit_compile_text(
        self,
        expression: ast.Expression,
        value: str,
    ) -> str:
        result_type = value_type(self.semantic.expression_type(expression))
        return c_static_string(value) if isinstance(result_type, StringType) else c_string(value)

    def _underlying_result_type(self, expression: ast.Expression) -> ResultType:
        type_ = strip_const(self.semantic.expression_type(expression))
        if isinstance(type_, (PointerType, ReferenceType)):
            type_ = strip_const(type_.inner)
        assert isinstance(type_, ResultType)
        return type_

    def _emit_map_index_assignment(
        self,
        statement: ast.AssignStmt,
        map_type: MapType,
    ) -> None:
        assert isinstance(statement.target, ast.IndexExpr)
        name = c_identifier(map_c_name(map_type))
        map_pointer = self._new_temp("map")
        key_name = self._new_temp("map_key")
        value_name = self._new_temp("map_value")
        self.writer.line(
            f"{c_decl(PointerType(map_type), map_pointer)} = "
            f"{self._container_pointer(statement.target.value)};"
        )
        self.writer.line(
            f"{c_decl(map_type.key, key_name)} = "
            f"{self._emit_borrowed_value(statement.target.index, map_type.key, 'map_key')};"
        )
        self.writer.line(
            f"{c_decl(map_type.value, value_name)} = "
            f"{self._emit_with_expected(statement.value, map_type.value)};"
        )
        if statement.operator == "=":
            self.writer.line(f"{name}_set({map_pointer}, {key_name}, {value_name});")
            if self._type_needs_drop(map_type.value):
                self._exclude_moved_from_expression(statement.value)
            return
        target_pointer = self._new_temp("map_slot")
        self.writer.line(
            f"{c_decl(PointerType(map_type.value), target_pointer)} = "
            f"{name}_lookup_mut_or_panic({map_pointer}, {key_name});"
        )
        self.writer.line(f"(*{target_pointer}) {statement.operator} {value_name};")

    def _emit_index(self, expression: ast.IndexExpr) -> str:
        base_type = value_type(self.semantic.expression_type(expression.value))
        if isinstance(base_type, StringType):
            base = self._borrow_string_pointer(
                expression.value,
                "string_index",
            )
            index = self._emit_expr(expression.index)
            return f"cinder_string_byte_at({base}, {index})"
        if isinstance(base_type, TupleType):
            assert isinstance(expression.index, ast.LiteralExpr)
            assert isinstance(expression.index.value, int)
            base = self._emit_expr(expression.value)
            return f"({base}).item_{expression.index.value}"
        index = self._emit_expr(expression.index)
        if isinstance(base_type, MapType):
            name = c_identifier(map_c_name(base_type))
            base = self._container_pointer(expression.value)
            index = self._emit_borrowed_value(
                expression.index,
                base_type.key,
                "map_key",
            )
            return f"{name}_lookup_or_panic({base}, {index})"
        if isinstance(base_type, (SliceType, ListType)):
            base = self._emit_expr(expression.value)
            return f"({base}).data[{index}]"
        base = self._emit_expr(expression.value)
        return f"({base})[{index}]"

    def _emit_slice(self, expression: ast.SliceExpr) -> str:
        result_type = value_type(self.semantic.expression_type(expression))
        base_type = value_type(self.semantic.expression_type(expression.value))
        if isinstance(base_type, StringType):
            if not isinstance(result_type, StringType):
                raise AssertionError("String slicing did not resolve to String")
            base = self._borrow_string_pointer(
                expression.value,
                "string_slice",
            )
            start = "0" if expression.start is None else self._emit_expr(expression.start)
            stop = (
                f"({base})->length" if expression.stop is None else self._emit_expr(expression.stop)
            )
            return f"cinder_string_slice({base}, {start}, {stop})"
        assert isinstance(result_type, SliceType)
        if isinstance(base_type, ArrayType):
            base = self._array_as_slice(expression.value, result_type)
        else:
            base = self._emit_with_expected(expression.value, result_type)
        start = "0" if expression.start is None else self._emit_expr(expression.start)
        slice_name = self._slice_name(result_type)
        if expression.stop is None:
            return f"{slice_name}_from({base}, {start})"
        stop = self._emit_expr(expression.stop)
        return f"{slice_name}_sub({base}, {start}, {stop})"

    def _emit_atomic_receiver_address(
        self,
        receiver: ast.Expression,
    ) -> str:
        receiver_type = strip_const(self.semantic.expression_type(receiver))
        if isinstance(receiver_type, ReferenceType):
            return self._emit_expr(receiver, mode="raw")
        if isinstance(receiver_type, PointerType):
            return self._emit_expr(receiver)
        return self._emit_address(receiver)

    def _emit_atomic_call(self, operation: IRAtomicOperation) -> str:
        if isinstance(operation, IRAtomicInit):
            raise AssertionError("atomic initialization cannot be emitted as a call")
        index = self.atomic_temp_indices.get(id(operation.call))
        if index is None:
            raise AssertionError("atomic call has no deterministic temporary index")

        receiver_name = f"__cinder_atomic_receiver_{index}"
        sequence = [f"({receiver_name} = {self._emit_atomic_receiver_address(operation.receiver)})"]

        if isinstance(operation, IRAtomicLoad):
            sequence.append(f"atomic_load_explicit(&{receiver_name}->value, memory_order_seq_cst)")
            return "(" + ", ".join(sequence) + ")"

        if isinstance(
            operation,
            (IRAtomicStore, IRAtomicExchange, IRAtomicFetch),
        ):
            value_name = f"__cinder_atomic_value_{index}"
            for source_index, operand_index in enumerate(operation.source_order):
                if operand_index != 0:
                    raise AssertionError("malformed atomic operand order")
                source = operation.call.arguments[source_index].value
                sequence.append(
                    f"({value_name} = "
                    f"{self._emit_with_expected(source, operation.atomic_type.inner)})"
                )
            if isinstance(operation, IRAtomicStore):
                sequence.append(
                    f"atomic_store_explicit(&{receiver_name}->value, "
                    f"{value_name}, memory_order_seq_cst)"
                )
            elif isinstance(operation, IRAtomicExchange):
                sequence.append(
                    f"atomic_exchange_explicit(&{receiver_name}->value, "
                    f"{value_name}, memory_order_seq_cst)"
                )
            else:
                fetch_function = {
                    AtomicFetchKind.ADD: "atomic_fetch_add_explicit",
                    AtomicFetchKind.SUB: "atomic_fetch_sub_explicit",
                    AtomicFetchKind.AND: "atomic_fetch_and_explicit",
                    AtomicFetchKind.OR: "atomic_fetch_or_explicit",
                    AtomicFetchKind.XOR: "atomic_fetch_xor_explicit",
                }[operation.fetch_kind]
                sequence.append(
                    f"{fetch_function}(&{receiver_name}->value, {value_name}, memory_order_seq_cst)"
                )
            return "(" + ", ".join(sequence) + ")"

        if isinstance(operation, IRAtomicCompareExchange):
            operand_names = (
                f"__cinder_atomic_expected_{index}",
                f"__cinder_atomic_desired_{index}",
            )
            for source_index, operand_index in enumerate(operation.source_order):
                source = operation.call.arguments[source_index].value
                sequence.append(
                    f"({operand_names[operand_index]} = "
                    f"{self._emit_with_expected(source, operation.atomic_type.inner)})"
                )
            result_name = f"__cinder_atomic_result_{index}"
            expected_name, desired_name = operand_names
            sequence.append(
                f"({result_name}.exchanged = "
                "atomic_compare_exchange_strong_explicit("
                f"&{receiver_name}->value, &{expected_name}, {desired_name}, "
                "memory_order_seq_cst, memory_order_seq_cst))"
            )
            sequence.append(f"({result_name}.observed = {expected_name})")
            sequence.append(result_name)
            return "(" + ", ".join(sequence) + ")"

        raise AssertionError(f"unhandled atomic operation {operation!r}")

    def _emit_call(self, expression: ast.CallExpr) -> str:
        atomic_operation = self.atomic_calls.get(id(expression))
        if atomic_operation is not None:
            return self._emit_atomic_call(atomic_operation)
        resolution = self.semantic.call_resolutions[id(expression)]
        self._exclude_moved_variables(resolution.moved_variables)
        if resolution.kind == "closure_new":
            return self._emit_closure_constructor(expression, resolution)
        if resolution.kind == "print":
            return self._emit_print_call(expression)
        if resolution.kind in {
            "string_constructor",
            "string_new",
            "string_clone",
            "string_append",
            "string_append_char",
            "string_reserve",
            "string_clear",
            "string_byte_at",
            "string_builder_constructor",
            "string_builder_new",
            "string_builder_append",
            "string_builder_append_char",
            "string_builder_reserve",
            "string_builder_clear",
            "string_builder_finish",
            "builder_finish",
        }:
            return self._emit_string_call(expression, resolution)
        if resolution.kind == "input":
            return self._emit_input_call(expression)
        if resolution.kind == "open":
            return self._emit_open_call(expression)
        if resolution.kind == "process_run":
            return self._emit_process_run_call(expression, resolution)
        if resolution.kind == "to_string":
            return self._emit_to_string_call(expression, resolution)
        if resolution.kind in _PARSE_RUNTIME:
            return self._emit_parse_call(expression, resolution)
        if resolution.kind.startswith("file_"):
            return self._emit_file_method_call(expression, resolution)
        if resolution.kind in {
            "constructor",
            "union_constructor",
            "variant_constructor",
            "result_constructor",
            "option_some",
        }:
            if resolution.kind == "constructor":
                assert resolution.struct is not None
                constructor_type = resolution.struct.type
            elif resolution.kind == "union_constructor":
                assert resolution.union is not None
                constructor_type = resolution.union.type
            elif resolution.kind == "variant_constructor":
                assert resolution.variant is not None
                constructor_type = resolution.variant.type
            elif resolution.kind == "option_some":
                if not isinstance(resolution.compile_value, OptionType):
                    raise AssertionError("Some constructor has no Option type")
                constructor_type = resolution.compile_value
            else:
                assert resolution.result_type is not None
                constructor_type = resolution.result_type
            initializer = self._emit_initializer(expression, constructor_type)
            return f"(({c_type_expression(constructor_type)}){initializer})"
        if resolution.kind == "set_empty":
            if not isinstance(resolution.compile_value, SetType):
                raise AssertionError("set() has no Set type")
            return f"(({c_type_expression(resolution.compile_value)}){{ 0 }})"
        if resolution.kind == "owned_new":
            owned_type = resolution.compile_value
            if not isinstance(owned_type, OwnedType):
                raise AssertionError("Owned constructor has no Owned type")
            name = c_identifier(owned_c_name(owned_type))
            if not expression.arguments:
                raise AssertionError("Owned constructor missing value argument")
            value = self._emit_with_expected(
                expression.arguments[0].value,
                owned_type.inner,
            )
            return f"{name}_new({value})"
        if resolution.kind == "class_constructor":
            if resolution.class_ is None:
                raise AssertionError("class constructor has no class symbol")
            arguments = self._emit_ordered_call_arguments(expression, resolution)
            return f"{self._class_new_name(resolution.class_)}({', '.join(arguments)})"
        if resolution.kind in {"list_append", "list_pop", "list_clear"}:
            if not isinstance(expression.callee, ast.AttributeExpr):
                raise AssertionError("List method callee is not an attribute")
            list_type = resolution.compile_value
            if not isinstance(list_type, ListType):
                raise AssertionError("List method has no List type")
            name = c_identifier(list_c_name(list_type))
            receiver = self._list_pointer(expression.callee.value)
            if resolution.kind == "list_append":
                arguments = self._emit_ordered_call_arguments(
                    expression,
                    resolution,
                )
                return f"{name}_append({receiver}, {', '.join(arguments)})"
            method = resolution.kind.removeprefix("list_")
            return f"{name}_{method}({receiver})"
        if resolution.kind.startswith("map_"):
            if not isinstance(expression.callee, ast.AttributeExpr):
                raise AssertionError("Map method callee is not an attribute")
            map_type = resolution.compile_value
            if not isinstance(map_type, MapType):
                raise AssertionError("Map method has no Map type")
            name = c_identifier(map_c_name(map_type))
            receiver = self._container_pointer(expression.callee.value)
            method = resolution.kind.removeprefix("map_")
            if method in {"get", "pop"}:
                key = self._emit_borrowed_value(
                    expression.arguments[0].value,
                    map_type.key,
                    "map_key",
                )
                return f"{name}_{method}({receiver}, {key})"
            if method == "update":
                other, temporary = self._materialize_container_operand(
                    expression.arguments[0].value,
                    map_type,
                )
                value = f"{name}_update({receiver}, {other})"
                if temporary is None:
                    return value
                self.writer.line(value + ";")
                self.writer.line(f"{name}_drop(&{temporary});")
                return "((void)0)"
            return f"{name}_{method}({receiver})"
        if resolution.kind.startswith("set_"):
            if not isinstance(expression.callee, ast.AttributeExpr):
                raise AssertionError("Set method callee is not an attribute")
            set_type = resolution.compile_value
            if not isinstance(set_type, SetType):
                raise AssertionError("Set method has no Set type")
            name = c_identifier(set_c_name(set_type))
            receiver = self._container_pointer(expression.callee.value)
            method = resolution.kind.removeprefix("set_")
            if method in {"add", "discard", "remove"}:
                item = self._emit_borrowed_value(
                    expression.arguments[0].value,
                    set_type.inner,
                    "set_item",
                )
                return f"{name}_{method}({receiver}, {item})"
            if method == "update" or method in {
                "union",
                "intersection",
                "difference",
                "symmetric_difference",
            }:
                other, temporary = self._materialize_container_operand(
                    expression.arguments[0].value,
                    set_type,
                )
                value = f"{name}_{method}({receiver}, {other})"
                if temporary is None:
                    return value
                if method == "update":
                    self.writer.line(value + ";")
                    self.writer.line(f"{name}_drop(&{temporary});")
                    return "((void)0)"
                result = self._new_temp("set_method")
                self.writer.line(f"{c_decl(set_type, result)} = {value};")
                self.writer.line(f"{name}_drop(&{temporary});")
                return result
            return f"{name}_{method}({receiver})"
        if resolution.kind == "len":
            argument = expression.arguments[0].value
            argument_type = value_type(self.semantic.expression_type(argument))
            if isinstance(argument_type, ArrayType):
                return f"CINDER_ARRAY_LEN({self._emit_expr(argument)})"
            if isinstance(argument_type, (SliceType, ListType)):
                return f"({self._emit_expr(argument)}).length"
            if isinstance(argument_type, (MapType, SetType)):
                return f"({self._container_pointer(argument)})->length"
            if isinstance(argument_type, MapViewType):
                return f"({self._emit_expr(argument)}).map->length"
            if isinstance(argument_type, TupleType):
                return f"((void)({self._emit_expr(argument)}), {len(argument_type.elements)})"
            if isinstance(argument_type, StringType):
                pointer = self._borrow_string_pointer(argument, "len_string")
                return f"({pointer})->length"
            return f"strlen({self._emit_expr(argument)})"
        if resolution.kind == "sort":
            expected = resolution.expected_types[0]
            if not isinstance(expected, SliceType):
                raise AssertionError("sort has no slice element type")
            sort_argument = self._emit_with_expected(expression.arguments[0].value, expected)
            return f"{self._sort_helper_name(expected.inner)}({sort_argument})"
        if resolution.kind == "range":
            raise AssertionError("range may only be emitted as a for-loop iterable")

        if resolution.kind in {
            "compile_bool",
            "compile_integer",
            "compile_string",
            "size_of",
            "align_of",
            "type_of",
            "type_info",
            "dynamic_type_info",
            "type_name",
            "dynamic_type_name",
            "fields",
            "methods",
            "dynamic_fields",
            "dynamic_methods",
            "fields_of",
            "methods_of",
        }:
            return self._emit_reflection_call(expression, resolution)

        if resolution.kind == "dynamic_method":
            if resolution.function is None or resolution.interface is None:
                raise AssertionError("dynamic method has incomplete resolution")
            if not isinstance(expression.callee, ast.AttributeExpr):
                raise AssertionError("dynamic method callee is not an attribute")
            receiver_type = strip_const(self.semantic.expression_type(expression.callee.value))
            if not isinstance(receiver_type, DynType):
                raise AssertionError("dynamic method receiver is not dyn")
            receiver = self._materialize_dynamic(
                expression.callee.value,
                receiver_type,
                "dyn_call",
                force=True,
            )
            arguments = [f"{receiver}.object", f"{receiver}.vtable"]
            arguments.extend(self._emit_ordered_call_arguments(expression, resolution))
            method_name = c_identifier(resolution.function.name)
            return f"{receiver}.vtable->{method_name}({', '.join(arguments)})"

        if resolution.kind in {"super_init", "super_method"}:
            return self._emit_super_call(expression, resolution)

        if resolution.kind == "function_pointer":
            callee = self._emit_expr(expression.callee)
            arguments = self._emit_ordered_call_arguments(expression, resolution)
            return f"({callee})({', '.join(arguments)})"

        if resolution.kind == "closure":
            closure_type = value_type(self.semantic.expression_type(expression.callee))
            if not isinstance(closure_type, ClosureType):
                raise AssertionError("closure call has no closure type")
            callee_pointer = self._new_temp("closure")
            self.writer.line(
                f"{c_decl(PointerType(closure_type), callee_pointer)} = "
                f"{self._emit_address(expression.callee)};"
            )
            arguments = [f"&{callee_pointer}->env"]
            arguments.extend(self._emit_ordered_call_arguments(expression, resolution))
            return f"{callee_pointer}->call({', '.join(arguments)})"

        assert resolution.function is not None
        function = resolution.function
        arguments: list[str] = []
        if resolution.kind == "method":
            assert isinstance(expression.callee, ast.AttributeExpr)
            receiver = expression.callee.value
            self_type = function.parameters[0].type
            arguments.append(self._emit_method_receiver(receiver, self_type))

        arguments.extend(self._emit_ordered_call_arguments(expression, resolution))

        return f"{c_identifier(function.c_name)}({', '.join(arguments)})"

    def _emit_closure_constructor(
        self,
        expression: ast.CallExpr,
        resolution: CallResolution,
    ) -> str:
        closure_type = value_type(self.semantic.expression_type(expression))
        if not isinstance(closure_type, ClosureType):
            raise AssertionError("closure constructor has no closure type")
        if resolution.function is None:
            raise AssertionError("closure constructor has no adapter function")
        env_value = self._emit_initializer(
            expression.arguments[0].value,
            closure_type.env_type,
        )
        return (
            f"(({c_type_expression(closure_type)})"
            f"{{ .env = {env_value}, "
            f".call = {c_identifier(resolution.function.c_name)} }})"
        )

    def _emit_string_call(
        self,
        expression: ast.CallExpr,
        resolution: CallResolution,
    ) -> str:
        kind = resolution.kind
        if kind in {"string_constructor", "string_new"}:
            if not expression.arguments:
                return f"(({string_c_name()}){{ 0 }})"
            argument = expression.arguments[0].value
            argument_type = value_type(self.semantic.expression_type(argument))
            if isinstance(argument_type, StringType):
                pointer = self._borrow_string_pointer(argument, "string_constructor")
                return f"cinder_string_clone({pointer})"
            return f"cinder_string_from_cstr({self._emit_expr(argument)})"

        if kind in {"string_builder_constructor", "string_builder_new"}:
            temporary = self._new_temp("string_builder")
            self.writer.line(f"{string_builder_c_name()} {temporary} = {{ 0 }};")
            self.writer.line(f"cinder_string_builder_init(&{temporary});")
            return temporary

        if not isinstance(expression.callee, ast.AttributeExpr):
            raise AssertionError(f"{kind} call has no String receiver")
        receiver_expression = expression.callee.value

        if kind == "string_clone":
            receiver = self._borrow_string_pointer(
                receiver_expression,
                "string_clone",
            )
            return f"cinder_string_clone({receiver})"
        if kind == "string_byte_at":
            if not expression.arguments:
                raise AssertionError("String.byte_at requires an index")
            receiver = self._borrow_string_pointer(
                receiver_expression,
                "string_byte_at",
            )
            index = self._emit_expr(expression.arguments[0].value)
            return f"((uint8_t)(unsigned char)cinder_string_byte_at({receiver}, {index}))"

        builder = kind.startswith("string_builder_") or kind == "builder_finish"
        pointer_type: Type = (
            PointerType(StringBuilderType()) if builder else PointerType(StringType())
        )
        raw_receiver = (
            self._container_pointer(receiver_expression)
            if builder
            else self._mutable_string_pointer(receiver_expression)
        )
        receiver = self._new_temp("string_receiver")
        self.writer.line(f"{c_decl(pointer_type, receiver)} = {raw_receiver};")

        if kind in {"string_builder_finish", "builder_finish"}:
            return f"cinder_string_builder_finish({receiver})"
        if kind in {"string_clear", "string_builder_clear"}:
            if builder:
                return (
                    f"(cinder_string_builder_drop({receiver}), "
                    f"cinder_string_builder_init({receiver}))"
                )
            return f"cinder_string_clear({receiver})"
        if kind in {"string_append", "string_builder_append"}:
            if not expression.arguments:
                raise AssertionError("append requires a String argument")
            suffix = self._borrow_string_pointer(
                expression.arguments[0].value,
                "string_suffix",
            )
            runtime = "cinder_string_builder_append" if builder else "cinder_string_append"
            return f"{runtime}({receiver}, {suffix})"
        if kind in {"string_append_char", "string_builder_append_char"}:
            if not expression.arguments:
                raise AssertionError("append_char requires a char argument")
            value = self._emit_expr(expression.arguments[0].value)
            runtime = (
                "cinder_string_builder_append_char" if builder else "cinder_string_append_char"
            )
            return f"{runtime}({receiver}, {value})"
        if kind in {"string_reserve", "string_builder_reserve"}:
            if not expression.arguments:
                raise AssertionError("reserve requires a capacity argument")
            capacity = self._emit_expr(expression.arguments[0].value)
            runtime = "cinder_string_builder_reserve" if builder else "cinder_string_reserve"
            return f"{runtime}({receiver}, {capacity})"
        raise AssertionError(f"unhandled String call resolution {kind!r}")

    def _emit_print_call(self, expression: ast.CallExpr) -> str:
        if not any(
            self._print_argument_needs_helpers(argument.value) for argument in expression.arguments
        ):
            format_parts: list[str] = []
            arguments: list[str] = []
            for index, argument in enumerate(expression.arguments):
                if index:
                    format_parts.append(" ")
                self._collect_print_argument(argument.value, format_parts, arguments)
            format_parts.append("\n")
            format_string = "".join(format_parts)
            if not arguments:
                return f"printf({c_string(format_string)})"
            return f"printf({c_string(format_string)}, {', '.join(arguments)})"

        for index, argument in enumerate(expression.arguments):
            if index:
                self.writer.line('printf(" ");')
            self._emit_print_argument_statements(argument.value)
        self.writer.line('printf("\\n");')
        return "(void)0"

    def _print_argument_needs_helpers(self, expression: ast.Expression) -> bool:
        if isinstance(expression, ast.FStringExpr):
            for part in expression.parts:
                if isinstance(part, ast.FStringText):
                    continue
                if self._print_argument_needs_helpers(part.expression):
                    return True
            return False
        type_ = value_type(self.semantic.expression_type(expression))
        return isinstance(type_, (ListType, MapType, SetType, TupleType))

    def _emit_print_argument_statements(self, expression: ast.Expression) -> None:
        if isinstance(expression, ast.FStringExpr):
            self._emit_print_fstring_statements(expression)
            return
        type_ = value_type(self.semantic.expression_type(expression))
        if isinstance(type_, (ListType, MapType, SetType, TupleType)):
            self._emit_collection_print_call(expression, type_)
            return
        specifier, value_arguments = self._printf_value(expression, None)
        self._emit_printf_segment([specifier], list(value_arguments))

    def _emit_print_fstring_statements(self, expression: ast.FStringExpr) -> None:
        format_parts: list[str] = []
        arguments: list[str] = []

        def flush() -> None:
            nonlocal format_parts, arguments
            if not format_parts and not arguments:
                return
            self._emit_printf_segment(format_parts, arguments)
            format_parts = []
            arguments = []

        for part in expression.parts:
            if isinstance(part, ast.FStringText):
                format_parts.append(_printf_literal(part.value))
                continue
            if isinstance(part.expression, ast.FStringExpr):
                flush()
                self._emit_print_fstring_statements(part.expression)
                continue
            part_type = value_type(self.semantic.expression_type(part.expression))
            if isinstance(part_type, (ListType, MapType, SetType, TupleType)):
                flush()
                self._emit_collection_print_call(part.expression, part_type)
                continue
            specifier, value_arguments = self._printf_value(
                part.expression,
                part.format_spec,
            )
            format_parts.append(specifier)
            arguments.extend(value_arguments)
        flush()

    def _emit_printf_segment(
        self,
        format_parts: list[str],
        arguments: list[str],
    ) -> None:
        if not format_parts and not arguments:
            return
        format_string = "".join(format_parts)
        if not arguments:
            self.writer.line(f"printf({c_string(format_string)});")
            return
        self.writer.line(f"printf({c_string(format_string)}, {', '.join(arguments)});")

    def _emit_collection_print_call(
        self,
        expression: ast.Expression,
        type_: ListType | MapType | SetType | TupleType,
    ) -> None:
        if isinstance(type_, TupleType):
            pointer = self._tuple_print_pointer(expression, type_)
            name = c_identifier(tuple_c_name(type_))
        else:
            pointer = self._container_pointer(expression)
            if isinstance(type_, ListType):
                name = c_identifier(list_c_name(type_))
            elif isinstance(type_, MapType):
                name = c_identifier(map_c_name(type_))
            else:
                name = c_identifier(set_c_name(type_))
        self.writer.line(f"{name}_print({pointer});")

    def _tuple_print_pointer(
        self,
        expression: ast.Expression,
        tuple_type: TupleType,
    ) -> str:
        if isinstance(
            expression,
            (ast.NameExpr, ast.AttributeExpr),
        ) or (isinstance(expression, ast.UnaryExpr) and expression.operator == "*"):
            return self._emit_address(expression)
        temporary = self._new_temp("print_tuple")
        self.writer.line(f"{c_decl(tuple_type, temporary)} = {self._emit_expr(expression)};")
        return f"&{temporary}"

    def _emit_input_call(self, expression: ast.CallExpr) -> str:
        prompt = (
            "NULL"
            if not expression.arguments
            else self._borrow_string_cstr(
                expression.arguments[0].value,
                "input_prompt",
            )
        )
        return f"cinder_input({prompt})"

    def _emit_parse_call(
        self,
        expression: ast.CallExpr,
        resolution: CallResolution,
    ) -> str:
        if resolution.result_type is None:
            raise AssertionError("parse builtin has no Result type")
        runtime = _PARSE_RUNTIME[resolution.kind]
        if len(expression.arguments) != 1:
            raise AssertionError(f"{resolution.kind} requires one argument")
        argument = self._borrow_string_cstr(
            expression.arguments[0].value,
            "parse_text",
        )
        result_type = resolution.result_type
        result_name = c_identifier(result_c_name(result_type))
        out_temp = self._new_temp("parse_out")
        err_temp = self._new_temp("parse_err")
        result_temp = self._new_temp("parse_result")
        self.writer.line(f"{c_decl(result_type.ok, out_temp)} = {{ 0 }};")
        self.writer.line(f"CinderParseError {err_temp} = CinderParseError_invalid;")
        self.writer.line(
            f"{c_decl(result_type, result_temp)} = {{ {result_name}_Tag_Err, {{ 0 }} }};"
        )
        self.writer.line(f"if ({runtime}({argument}, &{out_temp}, &{err_temp}))")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"{result_temp}.tag = {result_name}_Tag_Ok;")
        self.writer.line(f"{result_temp}.data.ok = {out_temp};")
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line("else")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(f"{result_temp}.data.err = {err_temp};")
        self.writer.indent -= 1
        self.writer.line("}")
        return result_temp

    def _emit_to_string_call(
        self,
        expression: ast.CallExpr,
        resolution: CallResolution,
    ) -> str:
        if not isinstance(resolution.compile_value, Type):
            raise AssertionError("to_string has no value type")
        runtime = _TO_STRING_RUNTIME.get(resolution.compile_value)
        if runtime is None:
            raise AssertionError(
                f"unsupported to_string type {type_name(resolution.compile_value)}"
            )
        arguments = self._emit_ordered_call_arguments(expression, resolution)
        if len(arguments) != 1:
            raise AssertionError("to_string requires one argument")
        return f"{runtime}({arguments[0]})"

    def _emit_open_call(self, expression: ast.CallExpr) -> str:
        if len(expression.arguments) != 2:
            raise AssertionError("open requires path and mode arguments")
        path = self._borrow_string_cstr(expression.arguments[0].value, "open_path")
        mode = self._borrow_string_cstr(expression.arguments[1].value, "open_mode")
        return f"{file_c_name()}_open({path}, {mode})"

    def _emit_process_run_call(
        self,
        expression: ast.CallExpr,
        resolution: CallResolution,
    ) -> str:
        if len(expression.arguments) != 1:
            raise AssertionError("process.run requires a command argument")
        expected = resolution.expected_types[0]
        if not isinstance(expected, SliceType):
            raise AssertionError("process.run command is not a slice")
        command_name = self._new_temp("process_command")
        command = self._emit_with_expected(expression.arguments[0].value, expected)
        argv_name = self._new_temp("process_argv")
        index_name = self._new_temp("process_index")
        result_name = self._new_temp("process_result")
        result_type = self.semantic.expression_type(expression)
        if not isinstance(result_type, StructType):
            raise AssertionError("process.run result is not a struct")

        self.writer.line(f"{c_decl(expected, command_name)} = {command};")
        self.writer.line(f"const char **{argv_name} = NULL;")
        self.writer.line(f"if ({command_name}.length > 0)")
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(
            f"{argv_name} = (const char **)cinder_alloc("
            f"{command_name}.length, sizeof(*{argv_name}));"
        )
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line(
            f"for (size_t {index_name} = 0; {index_name} < {command_name}.length; ++{index_name})"
        )
        self.writer.line("{")
        self.writer.indent += 1
        self.writer.line(
            f"{argv_name}[{index_name}] = cinder_string_cstr(&({command_name}.data[{index_name}]));"
        )
        self.writer.indent -= 1
        self.writer.line("}")
        self.writer.line(
            f"{c_decl(result_type, result_name)} = "
            f"cinder_process_run_argv({command_name}.length, {argv_name});"
        )
        self.writer.line(f"free((void *){argv_name});")
        return result_name

    def _emit_file_method_call(
        self,
        expression: ast.CallExpr,
        resolution: CallResolution,
    ) -> str:
        if not isinstance(expression.callee, ast.AttributeExpr):
            raise AssertionError("File method callee is not an attribute")
        receiver = self._container_pointer(expression.callee.value)
        name = file_c_name()
        if resolution.kind in {"file_write", "file_write_string"}:
            if expression.arguments and isinstance(
                value_type(self.semantic.expression_type(expression.arguments[0].value)),
                StringType,
            ):
                data = self._borrow_string_pointer(
                    expression.arguments[0].value,
                    "file_write_string",
                )
                return f"{name}_write_string({receiver}, {data})"
            arguments = self._emit_ordered_call_arguments(expression, resolution)
            return f"{name}_write({receiver}, {', '.join(arguments)})"
        if resolution.kind == "file_read":
            arguments = self._emit_ordered_call_arguments(expression, resolution)
            return f"{name}_read({receiver}, {', '.join(arguments)})"
        method = resolution.kind.removeprefix("file_")
        return f"{name}_{method}({receiver})"

    def _collect_print_argument(
        self,
        expression: ast.Expression,
        format_parts: list[str],
        arguments: list[str],
    ) -> None:
        if isinstance(expression, ast.FStringExpr):
            for part in expression.parts:
                if isinstance(part, ast.FStringText):
                    format_parts.append(_printf_literal(part.value))
                    continue
                if isinstance(part.expression, ast.FStringExpr):
                    self._collect_print_argument(part.expression, format_parts, arguments)
                    continue
                specifier, value_arguments = self._printf_value(
                    part.expression,
                    part.format_spec,
                )
                format_parts.append(specifier)
                arguments.extend(value_arguments)
            return
        specifier, value_arguments = self._printf_value(expression, None)
        format_parts.append(specifier)
        arguments.extend(value_arguments)

    def _printf_value(
        self,
        expression: ast.Expression,
        format_spec: str | None,
    ) -> tuple[str, tuple[str, ...]]:
        type_ = value_type(self.semantic.expression_type(expression))
        conversion = _print_conversion(format_spec)

        if isinstance(type_, StringType):
            return "%s", (self._borrow_string_cstr(expression, "print_string"),)

        value = self._emit_expr(expression)
        if type_ == BOOL:
            return "%s", (f'(({value}) ? "true" : "false")',)
        if type_ == CHAR:
            return "%c", (f"((int)({value}))",)
        if _is_printf_string_type(type_):
            return "%s", (value,)
        if isinstance(type_, PrimitiveType) and type_.category == "float":
            specifier = _printf_float_specifier(format_spec, conversion)
            if type_ == F32:
                value = f"((double)({value}))"
            return specifier, (value,)
        if isinstance(type_, PrimitiveType) and type_.category == "integer":
            if type_.signed is True and conversion is not None and conversion in "oxX":
                temporary = self._new_temp("print_integer")
                self.writer.line(f"{c_decl(type_, temporary)} = {value};")
                value = temporary
            return _printf_integer_value(type_, conversion, value)

        raise AssertionError(f"type {type_name(type_)} cannot be printed")

    def _emit_ordered_call_arguments(
        self,
        expression: ast.CallExpr,
        resolution: CallResolution,
    ) -> list[str]:
        arguments: list[str] = []
        for output_index, argument_index in enumerate(resolution.argument_order):
            argument = expression.arguments[argument_index].value
            expected = resolution.expected_types[output_index]
            if argument_index in resolution.ffi_borrow_indices:
                arguments.append(self._borrow_string_cstr(argument, "ffi_string"))
            elif expected is None:
                arguments.append(self._emit_vararg(argument))
            else:
                arguments.append(self._emit_with_expected(argument, expected))
        return arguments

    def _emit_reflection_call(
        self,
        expression: ast.CallExpr,
        resolution: CallResolution,
    ) -> str:
        kind = resolution.kind
        if kind == "compile_bool":
            return "true" if bool(resolution.compile_value) else "false"
        if kind == "compile_integer":
            return str(int(resolution.compile_value or 0))
        if kind == "compile_string":
            value = c_static_string(str(resolution.compile_value or ""))
            return self._preserve_reflection_subject(expression, value)
        if kind in {"size_of", "align_of"}:
            reflected_type = resolution.compile_value
            if not isinstance(reflected_type, Type):
                raise AssertionError(f"{kind} has no type")
            type_expression = c_type_expression(reflected_type)
            if kind == "size_of":
                return f"sizeof({type_expression})"
            return f"CINDER_ALIGNOF({type_expression})"
        if kind == "type_of":
            raise AssertionError("type_of is compile-time-only and has no C value")
        if kind in {"fields_of", "methods_of"}:
            raise AssertionError(f"{kind} may only be used by a comptime loop")

        if kind in {"type_info", "fields", "methods"}:
            nominal = resolution.compile_value
            if not isinstance(
                nominal,
                (StructSymbol, ClassSymbol, EnumSymbol, UnionSymbol, VariantSymbol),
            ):
                raise AssertionError(f"{kind} has no reflected nominal type")
            if kind == "type_info":
                value = f"(&{self._type_info_name(nominal)})"
            else:
                value = self._emit_reflection_slice(kind, nominal)
            return self._preserve_reflection_subject(expression, value)

        if kind in {
            "dynamic_type_info",
            "dynamic_type_name",
            "dynamic_fields",
            "dynamic_methods",
        }:
            if not expression.arguments:
                raise AssertionError(f"{kind} has no argument")
            argument = expression.arguments[0].value
            dyn_type = strip_const(self.semantic.expression_type(argument))
            if not isinstance(dyn_type, DynType):
                raise AssertionError(f"{kind} argument is not dyn")
            dynamic = self._materialize_dynamic(
                argument,
                dyn_type,
                "reflect",
                force=kind in {"dynamic_fields", "dynamic_methods"},
            )
            info = f"{dynamic}.vtable->type_info"
            if kind == "dynamic_type_info":
                return info
            if kind == "dynamic_type_name":
                return f"cinder_string_from_cstr({info}->name)"
            item_name = "fields" if kind == "dynamic_fields" else "methods"
            item_type = self.semantic.types[
                "CinderFieldInfo" if item_name == "fields" else "CinderMethodInfo"
            ]
            slice_type = SliceType(ConstType(item_type))
            return (
                f"(({self._slice_name(slice_type)}){{ "
                f".data = {info}->{item_name}, "
                f".length = {info}->{item_name[:-1]}_count }})"
            )

        raise AssertionError(f"unhandled reflection call {kind!r}")

    def _preserve_reflection_subject(
        self,
        expression: ast.CallExpr,
        value: str,
    ) -> str:
        if not expression.arguments:
            return value
        subject = expression.arguments[0].value
        subject_type = self.semantic.expression_type(subject)
        if isinstance(subject_type, TypeValueType):
            return value
        subject_value = value_type(subject_type)
        if isinstance(subject_value, StringType):
            pointer = self._borrow_string_pointer(
                subject,
                "reflect_string",
            )
            return f"((void)({pointer}), {value})"
        if isinstance(
            subject_value, StringBuilderType
        ) and not self._is_addressable_string_expression(subject):
            if not self.scope_frames:
                raise AssertionError("temporary StringBuilder reflection outside a scope")
            temporary = self._new_temp("reflect_string_builder")
            self.writer.line(
                f"{c_decl(StringBuilderType(), temporary)} = {self._emit_expr(subject)};"
            )
            self.scope_frames[-1].cleanups.append(
                _Cleanup(
                    iterator_end=(
                        "cinder_string_builder_drop",
                        f"&{temporary}",
                    )
                )
            )
            return f"((void)(&{temporary}), {value})"
        return f"((void)({self._emit_expr(subject)}), {value})"

    def _emit_reflection_slice(self, kind: str, nominal: NominalSymbol) -> str:
        if kind == "fields":
            item_type = self.semantic.types["CinderFieldInfo"]
            member = "fields"
            count = "field_count"
        elif kind == "methods":
            item_type = self.semantic.types["CinderMethodInfo"]
            member = "methods"
            count = "method_count"
        else:
            raise AssertionError(f"unknown reflection slice kind {kind!r}")
        slice_type = SliceType(ConstType(item_type))
        info = self._type_info_name(nominal)
        return (
            f"(({self._slice_name(slice_type)}){{ "
            f".data = {info}.{member}, .length = {info}.{count} }})"
        )

    def _emit_super_call(
        self,
        expression: ast.CallExpr,
        resolution: CallResolution,
    ) -> str:
        if self.current_function is None or self.current_function.owner_class is None:
            raise AssertionError("super call emitted outside a class method")
        if resolution.super_class is None:
            raise AssertionError("super call has no base class")
        owner = self.current_function.owner_class
        base = resolution.super_class
        self_name = c_identifier(self.current_function.parameters[0].name)
        pointer = self._class_pointer_from_typed_pointer(self_name, owner, base)
        arguments = self._emit_ordered_call_arguments(expression, resolution)

        if resolution.kind == "super_init" and resolution.function is None:
            constructor = f"{self._class_new_name(base)}()"
            return f"(*({pointer}) = {constructor})"

        if resolution.function is None:
            raise AssertionError("resolved super method has no function")
        function = resolution.function
        self_argument = self._adapt_class_pointer_to_self(
            pointer,
            base,
            function.parameters[0].type,
            concrete_owner=owner,
            concrete_pointer=self_name,
        )
        return f"{c_identifier(function.c_name)}({', '.join([self_argument, *arguments])})"

    def _emit_propagate(self, expression: ast.PropagateExpr) -> str:
        resolution = self.semantic.propagate_resolutions[id(expression)]
        source_name = self._new_temp("result")
        source_value = self._emit_with_expected(expression.value, resolution.source)
        self.writer.line(f"{c_decl(resolution.source, source_name)} = {source_value};")
        self.writer.line(f"if ({source_name}.tag == {self._result_tag(resolution.source, 'Err')})")
        self.writer.line("{")
        self.writer.indent += 1
        fields = [f".tag = {self._result_tag(resolution.enclosing, 'Err')}"]
        if not is_void(resolution.source.error):
            fields.append(f".data.err = {source_name}.data.err")
        error_value = f"(({c_type_expression(resolution.enclosing)}){{ {', '.join(fields)} }})"
        if any(frame.cleanups for frame in self.scope_frames):
            return_name = self._new_temp("propagate")
            self.writer.line(f"{c_decl(resolution.enclosing, return_name)} = {error_value};")
            self._emit_all_deferred()
            self.writer.line(f"return {return_name};")
        else:
            self.writer.line(f"return {error_value};")
        self.writer.indent -= 1
        self.writer.line("}")
        if is_void(resolution.source.ok):
            return "((void)0)"
        return f"{source_name}.data.ok"

    def _emit_method_receiver(self, expression: ast.Expression, expected: Type) -> str:
        expected_raw = strip_const(expected)
        actual = strip_const(self.semantic.expression_type(expression))
        if isinstance(expected_raw, DynType):
            return self._emit_with_expected(expression, expected_raw)
        if isinstance(expected_raw, (ReferenceType, PointerType)):
            target_inner = strip_const(expected_raw.inner)
            if isinstance(target_inner, ClassType):
                target = self.semantic.nominal_symbols.get(target_inner)
                if isinstance(target, ClassSymbol):
                    return self._class_pointer_from_expression(expression, target)
            if isinstance(actual, ReferenceType):
                return self._emit_expr(expression, mode="raw")
            if isinstance(actual, PointerType):
                return self._emit_expr(expression)
            return self._emit_address(expression)
        return self._emit_expr(expression)

    def _borrow_string_pointer(
        self,
        expression: ast.Expression,
        purpose: str,
    ) -> str:
        if isinstance(expression, ast.IndexExpr):
            indexed = self._borrow_indexed_string_pointer(expression, purpose)
            if indexed is not None:
                return indexed
        if isinstance(expression, ast.AttributeExpr):
            resolution = self.semantic.attribute_resolutions.get(id(expression))
            if resolution is not None and resolution.kind == "option_value":
                return self._borrow_option_string_value_pointer(
                    expression.value,
                    purpose,
                )
            attribute = self._borrow_attribute_string_pointer(
                expression,
                purpose,
            )
            if attribute is not None:
                return attribute
        actual = strip_const(self.semantic.expression_type(expression))
        if isinstance(actual, ReferenceType):
            return self._emit_expr(expression, mode="raw")
        if isinstance(actual, PointerType):
            return self._emit_expr(expression)
        if not isinstance(value_type(actual), StringType):
            raise AssertionError(f"cannot borrow non-String value as String: {type_name(actual)}")
        if self._is_addressable_string_expression(expression):
            return self._emit_address(expression)
        if not self.scope_frames:
            raise AssertionError("temporary String borrow emitted outside a scope")
        temporary = self._new_temp(purpose)
        self.writer.line(f"{c_decl(StringType(), temporary)} = {self._emit_expr(expression)};")
        self.scope_frames[-1].cleanups.append(
            _Cleanup(iterator_end=("cinder_string_drop", f"&{temporary}"))
        )
        return f"&{temporary}"

    def _borrow_indexed_string_pointer(
        self,
        expression: ast.IndexExpr,
        purpose: str,
    ) -> str | None:
        base_type = value_type(self.semantic.expression_type(expression.value))
        if isinstance(base_type, MapType):
            if not isinstance(value_type(base_type.value), StringType):
                return None
            name = c_identifier(map_c_name(base_type))
            base = self._container_pointer(expression.value)
            key = self._emit_borrowed_value(
                expression.index,
                base_type.key,
                "map_key",
            )
            return f"{name}_lookup_ptr_or_panic({base}, {key})"

        if not isinstance(
            base_type,
            (ArrayType, SliceType, ListType, TupleType, PointerType),
        ):
            return None
        if self._is_addressable_string_expression(expression):
            return self._emit_address(expression)

        owner = self._materialize_borrow_owner(
            expression.value,
            base_type,
            f"{purpose}_owner",
        )
        if isinstance(base_type, TupleType):
            if not (
                isinstance(expression.index, ast.LiteralExpr)
                and isinstance(expression.index.value, int)
            ):
                raise AssertionError("Tuple String index is not an integer literal")
            return f"&({owner}.item_{expression.index.value})"

        index = self._emit_expr(expression.index)
        if isinstance(base_type, (SliceType, ListType)):
            return f"&({owner}.data[{index}])"
        return f"&(({owner})[{index}])"

    def _borrow_attribute_string_pointer(
        self,
        expression: ast.AttributeExpr,
        purpose: str,
    ) -> str | None:
        resolution = self.semantic.attribute_resolutions.get(id(expression))
        if resolution is None or self._is_addressable_string_expression(expression):
            return None
        if resolution.kind not in {
            "field",
            "class_field",
            "result_value",
            "result_error",
        }:
            return None

        owner_type = value_type(self.semantic.expression_type(expression.value))
        owner = self._materialize_borrow_owner(
            expression.value,
            owner_type,
            f"{purpose}_owner",
        )
        if resolution.kind in {"result_value", "result_error"}:
            payload = "ok" if resolution.kind == "result_value" else "err"
            return f"&({owner}.data.{payload})"

        if resolution.field is None:
            raise AssertionError("String field borrow has no field")
        member = self._emit_pointer_path_access(
            f"&{owner}",
            resolution.access_path,
            resolution.field.name,
        )
        return f"&({member})"

    def _materialize_borrow_owner(
        self,
        expression: ast.Expression,
        owner_type: Type,
        purpose: str,
    ) -> str:
        if not self.scope_frames:
            raise AssertionError("temporary String owner emitted outside a scope")
        temporary = self._new_temp(purpose)
        self.writer.line(
            f"{c_decl(owner_type, temporary)} = {self._emit_with_expected(expression, owner_type)};"
        )
        if self._type_needs_drop(owner_type):
            self.scope_frames[-1].cleanups.append(
                _Cleanup(
                    drop_statement=self._drop_glue_call(
                        owner_type,
                        f"&{temporary}",
                    )
                )
            )
        return temporary

    def _borrow_option_string_value_pointer(
        self,
        expression: ast.Expression,
        purpose: str,
    ) -> str:
        storage = strip_const(self.semantic.expression_type(expression))
        option_type = (
            strip_const(storage.inner)
            if isinstance(storage, (PointerType, ReferenceType))
            else value_type(storage)
        )
        if not (
            isinstance(option_type, OptionType)
            and isinstance(value_type(option_type.inner), StringType)
        ):
            raise AssertionError("Option.value String borrow has a non-String payload")
        name = c_identifier(option_c_name(option_type))
        if isinstance(storage, ReferenceType):
            pointer = self._emit_expr(expression, mode="raw")
        elif isinstance(storage, PointerType):
            pointer = self._emit_expr(expression)
        elif self._is_addressable_string_expression(expression):
            pointer = self._emit_address(expression)
        else:
            if not self.scope_frames:
                raise AssertionError("temporary Option[String] borrow outside a scope")
            temporary = self._new_temp(f"{purpose}_option")
            self.writer.line(f"{c_decl(option_type, temporary)} = {self._emit_expr(expression)};")
            self.scope_frames[-1].cleanups.append(
                _Cleanup(iterator_end=(f"{name}_drop", f"&{temporary}"))
            )
            pointer = f"&{temporary}"
        return f"{name}_value_ptr_or_panic({pointer})"

    def _borrow_string_cstr(
        self,
        expression: ast.Expression,
        purpose: str,
    ) -> str:
        pointer = self._borrow_string_pointer(expression, purpose)
        return f"cinder_string_cstr({pointer})"

    def _emit_borrowed_value(
        self,
        expression: ast.Expression,
        expected: Type,
        purpose: str,
    ) -> str:
        if isinstance(value_type(expected), StringType):
            pointer = self._borrow_string_pointer(expression, purpose)
            return f"(*{pointer})"
        return self._emit_with_expected(expression, expected)

    def _mutable_string_pointer(self, expression: ast.Expression) -> str:
        if isinstance(expression, ast.AttributeExpr):
            resolution = self.semantic.attribute_resolutions.get(id(expression))
            if resolution is not None and resolution.kind == "option_value":
                return self._mutable_option_string_value_pointer(expression.value)
        if isinstance(expression, ast.IndexExpr):
            base_type = value_type(self.semantic.expression_type(expression.value))
            if isinstance(base_type, MapType) and isinstance(
                value_type(base_type.value), StringType
            ):
                name = c_identifier(map_c_name(base_type))
                base = self._container_pointer(expression.value)
                key = self._emit_borrowed_value(
                    expression.index,
                    base_type.key,
                    "map_key",
                )
                return f"{name}_lookup_mut_or_panic({base}, {key})"
        actual = strip_const(self.semantic.expression_type(expression))
        if isinstance(actual, ReferenceType):
            return self._emit_expr(expression, mode="raw")
        if isinstance(actual, PointerType):
            return self._emit_expr(expression)
        return self._emit_address(expression)

    def _mutable_option_string_value_pointer(
        self,
        expression: ast.Expression,
    ) -> str:
        storage = strip_const(self.semantic.expression_type(expression))
        option_type = (
            strip_const(storage.inner)
            if isinstance(storage, (PointerType, ReferenceType))
            else value_type(storage)
        )
        if not (
            isinstance(option_type, OptionType)
            and isinstance(value_type(option_type.inner), StringType)
        ):
            raise AssertionError("mutable Option.value String access has a non-String payload")
        name = c_identifier(option_c_name(option_type))
        if isinstance(storage, ReferenceType):
            pointer = self._emit_expr(expression, mode="raw")
        elif isinstance(storage, PointerType):
            pointer = self._emit_expr(expression)
        else:
            pointer = self._emit_address(expression)
        return f"{name}_value_mut_ptr_or_panic({pointer})"

    def _is_addressable_string_expression(self, expression: ast.Expression) -> bool:
        if isinstance(expression, ast.NameExpr):
            return True
        if isinstance(expression, ast.UnaryExpr) and expression.operator == "*":
            return True
        if isinstance(expression, ast.AttributeExpr):
            resolution = self.semantic.attribute_resolutions.get(id(expression))
            if resolution is None:
                return False
            if resolution.kind == "module_global":
                return True
            if resolution.kind not in {
                "field",
                "union_field",
                "class_field",
                "dyn_field",
                "result_value",
                "result_error",
            }:
                return False
            base_type = strip_const(self.semantic.expression_type(expression.value))
            return isinstance(base_type, (PointerType, ReferenceType)) or (
                self._is_addressable_string_expression(expression.value)
            )
        if isinstance(expression, ast.IndexExpr):
            base = value_type(self.semantic.expression_type(expression.value))
            return isinstance(
                base,
                (ArrayType, SliceType, ListType, TupleType, PointerType),
            ) and self._is_addressable_string_expression(expression.value)
        return False

    def _emit_vararg(self, expression: ast.Expression) -> str:
        type_ = value_type(self.semantic.expression_type(expression))
        value = self._emit_expr(expression)
        if type_ == F32:
            return f"((double)({value}))"
        if type_ in (BOOL, CHAR) or (
            isinstance(type_, PrimitiveType)
            and type_.category == "integer"
            and type_.bits is not None
            and type_.bits < 32
        ):
            return f"((int)({value}))"
        if isinstance(type_, PrimitiveType) and type_.category == "integer":
            return f"(({c_type_expression(type_)})({value}))"
        return value

    def _emit_lvalue(self, expression: ast.Expression) -> str:
        if isinstance(expression, ast.NameExpr):
            symbol = self.semantic.name_symbols.get(id(expression))
            if isinstance(symbol, VariableSymbol) and isinstance(
                strip_const(symbol.type), ReferenceType
            ):
                return f"(*{c_identifier(symbol.c_name or symbol.name)})"
        return self._emit_expr(expression)

    def _emit_address(self, expression: ast.Expression) -> str:
        actual = strip_const(self.semantic.expression_type(expression))
        if isinstance(actual, ReferenceType):
            return self._emit_expr(expression, mode="raw")
        if isinstance(expression, ast.UnaryExpr) and expression.operator == "*":
            operand_type = strip_const(self.semantic.expression_type(expression.operand))
            if isinstance(operand_type, OwnedType):
                return f"(({self._emit_expr(expression.operand)}).ptr)"
            return self._emit_expr(expression.operand)
        return f"(&({self._emit_lvalue(expression)}))"

    def _array_as_slice(self, expression: ast.Expression, slice_type: SliceType) -> str:
        array_type = value_type(self.semantic.expression_type(expression))
        assert isinstance(array_type, ArrayType)
        name = self._slice_name(slice_type)
        value = self._emit_expr(expression)
        return f"(({name}){{ .data = {value}, .length = {array_type.length} }})"

    def _list_as_slice(
        self,
        expression: ast.Expression,
        slice_type: SliceType,
    ) -> str:
        list_type = value_type(self.semantic.expression_type(expression))
        assert isinstance(list_type, ListType)
        name = self._slice_name(slice_type)
        value = self._emit_expr(expression)
        return f"(({name}){{ .data = ({value}).data, .length = ({value}).length }})"

    def _list_pointer(self, expression: ast.Expression) -> str:
        return self._container_pointer(expression)

    def _container_pointer(self, expression: ast.Expression) -> str:
        actual = strip_const(self.semantic.expression_type(expression))
        if isinstance(actual, ReferenceType):
            return self._emit_expr(expression, mode="raw")
        if isinstance(actual, PointerType):
            return self._emit_expr(expression)
        return self._emit_address(expression)

    @staticmethod
    def _container_drop_name(
        type_: ListType | MapType | SetType | FileType | OwnedType,
    ) -> str:
        if isinstance(type_, ListType):
            return f"{c_identifier(list_c_name(type_))}_drop"
        if isinstance(type_, MapType):
            return f"{c_identifier(map_c_name(type_))}_drop"
        if isinstance(type_, SetType):
            return f"{c_identifier(set_c_name(type_))}_drop"
        if isinstance(type_, OwnedType):
            return f"{c_identifier(owned_c_name(type_))}_drop"
        return f"{file_c_name()}_drop"

    def _slice_name(self, slice_type: SliceType) -> str:
        return "CinderSlice_" + c_identifier(type_key(slice_type.inner))

    @staticmethod
    def _sort_compare_name(element_type: Type) -> str:
        return "CinderSortCompare_" + c_identifier(type_key(element_type))

    @staticmethod
    def _sort_helper_name(element_type: Type) -> str:
        return "CinderSort_" + c_identifier(type_key(element_type))

    def _result_tag(self, result_type: ResultType, suffix: str) -> str:
        return f"{c_identifier(result_c_name(result_type))}_Tag_{suffix}"

    def _local_nominals(self) -> list[NominalSymbol]:
        return [
            *(item.symbol for item in self.ir.structs),
            *(item.symbol for item in self.ir.classes),
            *(item.symbol for item in self.ir.enums),
            *(item.symbol for item in self.ir.unions),
            *(item.symbol for item in self.ir.variants),
        ]

    @staticmethod
    def _type_info_name(nominal: NominalSymbol) -> str:
        return c_identifier(f"{nominal.c_name}__type_info")

    @staticmethod
    def _field_info_array_name(nominal: NominalSymbol) -> str:
        return c_identifier(f"{nominal.c_name}__field_info")

    @staticmethod
    def _method_info_array_name(nominal: NominalSymbol) -> str:
        return c_identifier(f"{nominal.c_name}__method_info")

    @staticmethod
    def _reflection_kind(nominal: NominalSymbol) -> str:
        if isinstance(nominal, StructSymbol):
            return "CINDER_TYPE_STRUCT"
        if isinstance(nominal, ClassSymbol):
            return "CINDER_TYPE_CLASS"
        if isinstance(nominal, EnumSymbol):
            return "CINDER_TYPE_ENUM"
        if isinstance(nominal, UnionSymbol):
            return "CINDER_TYPE_UNION"
        if isinstance(nominal, VariantSymbol):
            return "CINDER_TYPE_VARIANT"
        raise AssertionError(f"unsupported reflected nominal {nominal!r}")

    def _nominal_fields(
        self,
        nominal: NominalSymbol,
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
    def _nominal_methods(nominal: NominalSymbol) -> list[FunctionSymbol]:
        if isinstance(nominal, ClassSymbol):
            return list(nominal.interface_methods.values())
        if isinstance(nominal, StructSymbol):
            return list(nominal.methods.values())
        return []

    @staticmethod
    def _method_signature_text(method: FunctionSymbol) -> str:
        parameters = ", ".join(type_name(parameter.type) for parameter in method.parameters[1:])
        return f"{method.name}({parameters}) -> {type_name(method.return_type)}"

    def _field_offset_expression(
        self,
        root: NominalSymbol,
        owner: NominalSymbol,
        path: tuple[str, ...],
        field_name: str,
    ) -> str:
        terms: list[str] = []
        current = root
        for component in path:
            terms.append(f"offsetof({c_identifier(current.c_name)}, {c_identifier(component)})")
            if component == "_base" and isinstance(current, ClassSymbol):
                if current.primary_base is None:
                    raise AssertionError("invalid reflected base path")
                current = current.primary_base
        terms.append(f"offsetof({c_identifier(owner.c_name)}, {c_identifier(field_name)})")
        return " + ".join(terms)

    @staticmethod
    def _class_has_destructor(class_: ClassSymbol) -> bool:
        current: ClassSymbol | None = class_
        while current is not None:
            if current.destructor is not None:
                return True
            current = current.primary_base
        return False

    @staticmethod
    def _implemented_interfaces(class_: ClassSymbol) -> list[ClassSymbol]:
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
        return result

    @staticmethod
    def _class_new_name(class_: ClassSymbol) -> str:
        return c_identifier(f"{class_.c_name}__new")

    @staticmethod
    def _class_drop_name(class_: ClassSymbol) -> str:
        return c_identifier(f"{class_.c_name}__drop")

    def _class_support_linkage(
        self,
        nominal: StructSymbol | ClassSymbol | None = None,
    ) -> str:
        if nominal is not None and (nominal.type_args or nominal.template_name):
            return "static CINDER_MAYBE_UNUSED "
        return "" if self.semantic.module_mode else "static CINDER_MAYBE_UNUSED "

    def _class_new_signature(self, class_: ClassSymbol, *, definition: bool) -> str:
        del definition
        parameters = []
        if class_.constructor is not None:
            parameters.extend(
                c_decl(parameter.type, c_identifier(parameter.name))
                for parameter in class_.constructor.parameters[1:]
            )
        if not parameters:
            parameters.append("void")
        return (
            f"{self._class_support_linkage(class_)}"
            f"{c_decl(class_.type, self._class_new_name(class_))}"
            f"({', '.join(parameters)})"
        )

    def _class_drop_signature(self, class_: ClassSymbol, *, definition: bool) -> str:
        del definition
        return (
            f"{self._class_support_linkage(class_)}void {self._class_drop_name(class_)}"
            f"({c_identifier(class_.c_name)} *self)"
        )

    @staticmethod
    def _vtable_instance_name(class_: ClassSymbol, interface: ClassSymbol) -> str:
        return c_identifier(f"{class_.c_name}__as__{interface.c_name}__vtable")

    @staticmethod
    def _vtable_thunk_name(
        class_: ClassSymbol,
        interface: ClassSymbol,
        method_name: str,
    ) -> str:
        return c_identifier(f"{class_.c_name}__as__{interface.c_name}__{method_name}__thunk")

    def _thunk_self_argument(
        self,
        class_: ClassSymbol,
        implementation: FunctionSymbol,
    ) -> str:
        if not implementation.parameters:
            raise AssertionError("method implementation has no self parameter")
        self_type = strip_const(implementation.parameters[0].type)
        if isinstance(self_type, DynType):
            target = self.semantic.nominal_symbols.get(self_type.interface)
            if not isinstance(target, ClassSymbol):
                raise AssertionError("dynamic self has no interface symbol")
            dyn_name = c_identifier(dyn_c_name(self_type))
            vtable = self._vtable_instance_name(class_, target)
            return f"(({dyn_name}){{ .object = object, .vtable = &{vtable} }})"

        if isinstance(self_type, (ReferenceType, PointerType)):
            inner = strip_const(self_type.inner)
            if not isinstance(inner, ClassType):
                return f"(({c_type_expression(self_type)})object)"
            target = self.semantic.nominal_symbols.get(inner)
            if not isinstance(target, ClassSymbol):
                raise AssertionError("class self has no class symbol")
            return self._class_pointer_from_void("object", class_, target)

        if isinstance(self_type, ClassType):
            target = self.semantic.nominal_symbols.get(self_type)
            if not isinstance(target, ClassSymbol):
                raise AssertionError("class self has no class symbol")
            return f"(*{self._class_pointer_from_void('object', class_, target)})"
        return f"(({c_type_expression(self_type)})object)"

    def _class_symbol_from_storage_type(self, type_: Type) -> ClassSymbol | None:
        raw = strip_const(type_)
        if isinstance(raw, (ReferenceType, PointerType)):
            raw = strip_const(raw.inner)
        if not isinstance(raw, ClassType):
            return None
        nominal = self.semantic.nominal_symbols.get(raw)
        return nominal if isinstance(nominal, ClassSymbol) else None

    def _class_pointer_from_expression(
        self,
        expression: ast.Expression,
        target: ClassSymbol,
    ) -> str:
        actual = strip_const(self.semantic.expression_type(expression))
        if isinstance(actual, ReferenceType):
            source_type = strip_const(actual.inner)
            pointer = self._emit_expr(expression, mode="raw")
        elif isinstance(actual, PointerType):
            source_type = strip_const(actual.inner)
            pointer = self._emit_expr(expression)
        else:
            source_type = actual
            pointer = self._emit_address(expression)
        if not isinstance(source_type, ClassType):
            raise AssertionError(f"cannot derive a class pointer from {type_name(actual)}")
        source = self.semantic.nominal_symbols.get(source_type)
        if not isinstance(source, ClassSymbol):
            raise AssertionError("class expression has no class symbol")
        return self._class_pointer_from_typed_pointer(pointer, source, target)

    @staticmethod
    def _class_pointer_from_typed_pointer(
        pointer: str,
        source: ClassSymbol,
        target: ClassSymbol,
    ) -> str:
        expression = f"({pointer})"
        current: ClassSymbol | None = source
        while current is not None and current.type != target.type:
            if current.primary_base is None:
                raise AssertionError(f"{source.name} is not layout-derived from {target.name}")
            expression = f"(&(({expression})->_base))"
            current = current.primary_base
        if current is None:
            raise AssertionError(f"missing base path from {source.name} to {target.name}")
        return expression

    def _emit_dyn_conversion(
        self,
        expression: ast.Expression,
        target: DynType,
    ) -> str:
        source = self._class_symbol_from_storage_type(self.semantic.expression_type(expression))
        interface = self.semantic.nominal_symbols.get(target.interface)
        if source is None or not isinstance(interface, ClassSymbol):
            raise AssertionError("invalid concrete-to-dyn conversion")
        if source.is_abstract:
            raise AssertionError(
                "abstract class references cannot be converted to dyn without an existing vtable"
            )

        actual = strip_const(self.semantic.expression_type(expression))
        if isinstance(actual, ReferenceType):
            pointer = self._emit_expr(expression, mode="raw")
        elif isinstance(actual, PointerType):
            pointer = self._emit_expr(expression)
        else:
            pointer = self._emit_address(expression)
        dyn_name = c_identifier(dyn_c_name(target))
        vtable = self._vtable_instance_name(source, interface)
        return f"(({dyn_name}){{ .object = (void *)({pointer}), .vtable = &{vtable} }})"

    def _materialize_dynamic(
        self,
        expression: ast.Expression,
        expected: DynType,
        purpose: str,
        *,
        force: bool = False,
    ) -> str:
        value = self._emit_with_expected(expression, expected)
        if not force and isinstance(expression, ast.NameExpr):
            return value
        temporary = self._new_temp(purpose)
        self.writer.line(f"{c_decl(expected, temporary)} = {value};")
        return temporary

    def _adapt_class_pointer_to_self(
        self,
        pointer: str,
        source: ClassSymbol,
        expected: Type,
        *,
        concrete_owner: ClassSymbol,
        concrete_pointer: str,
    ) -> str:
        expected_raw = strip_const(expected)
        if isinstance(expected_raw, DynType):
            interface = self.semantic.nominal_symbols.get(expected_raw.interface)
            if not isinstance(interface, ClassSymbol):
                raise AssertionError("dynamic self interface is not a class")
            dyn_name = c_identifier(dyn_c_name(expected_raw))
            vtable = self._vtable_instance_name(concrete_owner, interface)
            return (
                f"(({dyn_name}){{ .object = (void *)({concrete_pointer}), .vtable = &{vtable} }})"
            )
        if isinstance(expected_raw, (ReferenceType, PointerType)):
            target_type = strip_const(expected_raw.inner)
            if isinstance(target_type, ClassType):
                target = self.semantic.nominal_symbols.get(target_type)
                if not isinstance(target, ClassSymbol):
                    raise AssertionError("self target has no class symbol")
                return self._class_pointer_from_typed_pointer(pointer, source, target)
            return pointer
        if isinstance(expected_raw, ClassType):
            target = self.semantic.nominal_symbols.get(expected_raw)
            if not isinstance(target, ClassSymbol):
                raise AssertionError("self target has no class symbol")
            return f"(*{self._class_pointer_from_typed_pointer(pointer, source, target)})"
        return pointer

    @staticmethod
    def _class_pointer_from_void(
        object_expression: str,
        class_: ClassSymbol,
        target: ClassSymbol,
    ) -> str:
        expression = f"(({c_identifier(class_.c_name)} *){object_expression})"
        current: ClassSymbol | None = class_
        while current is not None and current.type != target.type:
            if current.primary_base is None:
                raise AssertionError(f"{class_.name} is not layout-derived from {target.name}")
            expression = f"(&({expression}->_base))"
            current = current.primary_base
        if current is None:
            raise AssertionError(f"missing base path from {class_.name} to {target.name}")
        return expression

    def _new_temp(self, purpose: str) -> str:
        self.temp_counter += 1
        return f"__cinder_{purpose}_{self.temp_counter}"


def _printf_literal(value: str) -> str:
    return value.replace("%", "%%")


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


def _printf_float_specifier(format_spec: str | None, conversion: str | None) -> str:
    if format_spec in (None, ""):
        return "%g"
    if conversion is None or conversion not in "fFeEgG":
        raise AssertionError(f"invalid float print format {format_spec!r}")
    return f"%{format_spec}"


def _printf_integer_value(
    type_: PrimitiveType,
    conversion: str | None,
    value: str,
) -> tuple[str, tuple[str, ...]]:
    if conversion is None:
        conversion = "u" if type_.signed is False else "d"
    if conversion not in "diuoxX":
        raise AssertionError(f"invalid integer print conversion {conversion!r}")
    if type_.signed is False and conversion in "di":
        conversion = "u"
    if type_.signed is True and conversion in "oxX":
        sign = f'(({value}) < 0 ? "-" : "")'
        magnitude = (
            f"((({value}) < 0) "
            f"? (0ULL - ((unsigned long long)({value}))) "
            f": ((unsigned long long)({value})))"
        )
        return f"%s%ll{conversion}", (sign, magnitude)
    if conversion in "uoxX":
        return f"%ll{conversion}", (f"((unsigned long long)({value}))",)
    return f"%ll{conversion}", (f"((long long)({value}))",)


def _is_printf_string_type(type_: Type) -> bool:
    return isinstance(type_, PointerType) and strip_const(type_.inner) == CHAR


def c_identifier(name: str) -> str:
    cleaned = "".join(
        character if character.isascii() and (character.isalnum() or character == "_") else "_"
        for character in name
    )
    if not cleaned:
        cleaned = "cinder_name"
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    if cleaned in _C_KEYWORDS or cleaned.startswith("__"):
        cleaned = "cinder_" + cleaned.lstrip("_")
    return cleaned


def c_decl(type_: Type, name: str) -> str:
    if type_ == ERROR:
        return f"int {name}".strip()

    if isinstance(type_, ConstType):
        inner = type_.inner
        if isinstance(inner, PointerType):
            decorated = f"* const {name}".strip()
            if isinstance(strip_const(inner.inner), ArrayType):
                decorated = f"(* const {name})"
            return c_decl(inner.inner, decorated)
        if isinstance(inner, ReferenceType):
            return c_decl(inner.inner, f"* const {name}".strip())
        if isinstance(inner, FunctionPointerType):
            parameters = [c_type_expression(parameter) for parameter in inner.param_types]
            if not parameters:
                parameters.append("void")
            return f"{c_decl(inner.return_type, f'(* const {name})')}({', '.join(parameters)})"
        if isinstance(inner, ArrayType):
            return c_decl(ConstType(inner.inner), f"{name}[{inner.length}]")
        if isinstance(inner, SliceType):
            return f"const {slice_c_name(inner)} {name}".strip()
        return f"const {c_decl(inner, name)}"

    if isinstance(type_, PointerType):
        decorated = f"*{name}".strip()
        if isinstance(strip_const(type_.inner), ArrayType):
            decorated = f"(*{name})"
        return c_decl(type_.inner, decorated)

    if isinstance(type_, ReferenceType):
        decorated = f"*{name}".strip()
        if isinstance(strip_const(type_.inner), ArrayType):
            decorated = f"(*{name})"
        return c_decl(type_.inner, decorated)

    if isinstance(type_, ArrayType):
        return c_decl(type_.inner, f"{name}[{type_.length}]")

    if isinstance(type_, SliceType):
        return f"{slice_c_name(type_)} {name}".strip()

    if isinstance(type_, StringType):
        return f"{string_c_name()} {name}".strip()
    if isinstance(type_, StringBuilderType):
        return f"{string_builder_c_name()} {name}".strip()
    if isinstance(type_, PrimitiveType):
        return f"{type_.c_name} {name}".strip()
    if isinstance(type_, (StructType, ClassType, EnumType, UnionType, VariantType)):
        return f"{c_identifier(nominal_c_name(type_))} {name}".strip()
    if isinstance(type_, DynType):
        return f"{c_identifier(dyn_c_name(type_))} {name}".strip()
    if isinstance(type_, TupleType):
        return f"{c_identifier(tuple_c_name(type_))} {name}".strip()
    if isinstance(type_, ListType):
        return f"{c_identifier(list_c_name(type_))} {name}".strip()
    if isinstance(type_, MapType):
        return f"{c_identifier(map_c_name(type_))} {name}".strip()
    if isinstance(type_, SetType):
        return f"{c_identifier(set_c_name(type_))} {name}".strip()
    if isinstance(type_, FileType):
        return f"{file_c_name()} {name}".strip()
    if isinstance(type_, MapViewType):
        return f"{c_identifier(map_view_c_name(type_))} {name}".strip()
    if isinstance(type_, ResultType):
        return f"{c_identifier(result_c_name(type_))} {name}".strip()
    if isinstance(type_, OptionType):
        return f"{c_identifier(option_c_name(type_))} {name}".strip()
    if isinstance(type_, OwnedType):
        return f"{c_identifier(owned_c_name(type_))} {name}".strip()
    if isinstance(type_, AtomicType):
        return f"{c_identifier(atomic_c_name(type_))} {name}".strip()
    if isinstance(type_, AtomicCompareExchangeResultType):
        return (f"{c_identifier(atomic_compare_exchange_result_c_name(type_))} {name}").strip()
    if isinstance(type_, OpaqueType):
        return f"{type_.c_name} {name}".strip()
    if isinstance(type_, FunctionPointerType):
        parameters = [c_type_expression(parameter) for parameter in type_.param_types]
        if not parameters:
            parameters.append("void")
        declarator = f"(*{name})" if name else "(*)"
        return f"{c_decl(type_.return_type, declarator)}({', '.join(parameters)})"
    if isinstance(type_, ClosureType):
        return f"{c_identifier(closure_c_name(type_))} {name}".strip()
    if isinstance(type_, NullType):
        return f"void *{name}".strip()
    if isinstance(
        type_,
        (
            TypeValueType,
            ComptimeCollectionType,
            ComptimeItemType,
            FunctionValueType,
            ModuleType,
            RangeType,
        ),
    ):
        return f"void *{name}".strip()
    raise AssertionError(f"unhandled C declaration type: {type_!r}")


def c_type_expression(type_: Type) -> str:
    marker = "__cinder_type_marker"
    declaration = c_decl(type_, marker)
    return declaration.replace(marker, "").strip()


def slice_c_name(slice_type: SliceType) -> str:
    return "CinderSlice_" + c_identifier(type_key(slice_type.inner))


def c_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace("\0", "\\000")
    )
    return f'"{escaped}"'


def c_static_string(value: str) -> str:
    return (
        f"({string_c_name()}){{ .data = (char *){c_string(value)}, "
        f".length = {len(value.encode('utf-8'))}, .capacity = 0 }}"
    )


def c_char(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace("\0", "\\0")
    )
    return f"'{escaped}'"


def generate_c(module: IRModule) -> str:
    return CGenerator(module).generate()


def generate_module_header(
    module: IRModule,
    header_name: str,
    dependency_headers: tuple[str, ...] = (),
) -> str:
    return CGenerator(module).generate_header(header_name, dependency_headers)


def generate_module_source(module: IRModule, header_name: str) -> str:
    return CGenerator(module).generate_source(header_name)
