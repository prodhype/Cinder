from __future__ import annotations

from pathlib import Path

from cinder.diagnostics import Span
from cinder.symbols import (
    ConstantSymbol,
    FunctionSymbol,
    ModuleSymbol,
    ParameterSymbol,
    SymbolKind,
)
from cinder.types import (
    C_INT,
    CHAR,
    F32,
    F64,
    I32,
    STRING,
    USIZE,
    VOID,
    ConstType,
    OpaqueType,
    PointerType,
    SliceType,
    StructType,
    Type,
    c_string_type,
)


def builtin_modules(path: Path) -> dict[str, ModuleSymbol]:
    span = Span.synthetic(path)
    file_type = OpaqueType("FILE", "FILE")
    process_result_type = StructType("ProcessResult", "CinderProcessResult")
    void_pointer = PointerType(VOID)
    const_void_pointer = PointerType(ConstType(VOID))
    char_pointer = PointerType(CHAR)
    file_pointer = PointerType(file_type)

    stdio = ModuleSymbol(
        name="stdio",
        span=span,
        kind=SymbolKind.MODULE,
        module_name="stdio",
        includes=("<stdio.h>",),
        types={"FILE": file_type},
    )
    stdio.functions.update(
        {
            "printf": _function(span, "printf", C_INT, [("format", c_string_type())], variadic=True, module="stdio"),
            "fprintf": _function(
                span,
                "fprintf",
                C_INT,
                [("stream", file_pointer), ("format", c_string_type())],
                variadic=True,
                module="stdio",
            ),
            "snprintf": _function(
                span,
                "snprintf",
                C_INT,
                [("buffer", char_pointer), ("size", USIZE), ("format", c_string_type())],
                variadic=True,
                module="stdio",
            ),
            "puts": _function(span, "puts", C_INT, [("text", c_string_type())], module="stdio"),
            "putchar": _function(span, "putchar", C_INT, [("character", C_INT)], module="stdio"),
            "fopen": _function(
                span,
                "fopen",
                file_pointer,
                [("path", c_string_type()), ("mode", c_string_type())],
                module="stdio",
            ),
            "fclose": _function(span, "fclose", C_INT, [("stream", file_pointer)], module="stdio"),
            "fread": _function(
                span,
                "fread",
                USIZE,
                [("buffer", void_pointer), ("size", USIZE), ("count", USIZE), ("stream", file_pointer)],
                module="stdio",
            ),
            "fwrite": _function(
                span,
                "fwrite",
                USIZE,
                [("buffer", const_void_pointer), ("size", USIZE), ("count", USIZE), ("stream", file_pointer)],
                module="stdio",
            ),
            "fflush": _function(span, "fflush", C_INT, [("stream", file_pointer)], module="stdio"),
        }
    )

    math = ModuleSymbol(
        name="math",
        span=span,
        kind=SymbolKind.MODULE,
        module_name="math",
        includes=("<math.h>",),
        libraries=("m",),
    )
    for name in ("sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "exp", "log", "floor", "ceil", "fabs"):
        math.functions[name] = _function(span, name, F64, [("value", F64)], module="math")
    for name in ("sqrtf", "sinf", "cosf", "tanf", "expf", "logf", "floorf", "ceilf", "fabsf"):
        math.functions[name] = _function(span, name, F32, [("value", F32)], module="math")
    math.functions["pow"] = _function(span, "pow", F64, [("base", F64), ("exponent", F64)], module="math")
    math.functions["atan2"] = _function(span, "atan2", F64, [("y", F64), ("x", F64)], module="math")
    math.constants["pi"] = ConstantSymbol("pi", span, SymbolKind.CONSTANT, F64, "CINDER_PI")

    stdlib = ModuleSymbol(
        name="stdlib",
        span=span,
        kind=SymbolKind.MODULE,
        module_name="stdlib",
        includes=("<stdlib.h>",),
    )
    stdlib.functions.update(
        {
            "malloc": _function(span, "malloc", void_pointer, [("size", USIZE)], module="stdlib"),
            "calloc": _function(span, "calloc", void_pointer, [("count", USIZE), ("size", USIZE)], module="stdlib"),
            "realloc": _function(span, "realloc", void_pointer, [("pointer", void_pointer), ("size", USIZE)], module="stdlib"),
            "free": _function(span, "free", VOID, [("pointer", void_pointer)], module="stdlib"),
            "exit": _function(span, "exit", VOID, [("status", I32)], module="stdlib"),
        }
    )

    string = ModuleSymbol(
        name="string",
        span=span,
        kind=SymbolKind.MODULE,
        module_name="string",
        includes=("<string.h>",),
    )
    string.functions.update(
        {
            "strlen": _function(span, "strlen", USIZE, [("text", c_string_type())], module="string"),
            "strcmp": _function(span, "strcmp", C_INT, [("left", c_string_type()), ("right", c_string_type())], module="string"),
            "strncmp": _function(
                span,
                "strncmp",
                C_INT,
                [("left", c_string_type()), ("right", c_string_type()), ("count", USIZE)],
                module="string",
            ),
            "memcpy": _function(
                span,
                "memcpy",
                void_pointer,
                [("destination", void_pointer), ("source", const_void_pointer), ("count", USIZE)],
                module="string",
            ),
            "memset": _function(
                span,
                "memset",
                void_pointer,
                [("destination", void_pointer), ("value", C_INT), ("count", USIZE)],
                module="string",
            ),
        }
    )

    cinder = ModuleSymbol(
        name="cinder",
        span=span,
        kind=SymbolKind.MODULE,
        module_name="cinder",
        includes=(),
    )
    cinder.functions["panic"] = _function(
        span,
        "cinder_panic",
        VOID,
        [("message", c_string_type())],
        module="cinder",
        public_name="panic",
    )

    process = ModuleSymbol(
        name="process",
        span=span,
        kind=SymbolKind.MODULE,
        module_name="process",
        includes=(),
        types={"ProcessResult": process_result_type},
    )
    process.functions["run"] = _function(
        span,
        "cinder_process_run_argv",
        process_result_type,
        [("command", SliceType(ConstType(STRING)))],
        module="process",
        public_name="run",
    )

    return {
        "stdio": stdio,
        "math": math,
        "stdlib": stdlib,
        "string": string,
        "cinder": cinder,
        "process": process,
    }


def builtin_global_functions(path: Path) -> dict[str, FunctionSymbol]:
    span = Span.synthetic(path)
    void_pointer = PointerType(VOID)
    return {
        "free": _function(span, "free", VOID, [("pointer", void_pointer)]),
        "panic": _function(span, "cinder_panic", VOID, [("message", c_string_type())], public_name="panic"),
    }


def _function(
    span: Span,
    c_name: str,
    return_type: Type,
    parameters: list[tuple[str, Type]],
    *,
    variadic: bool = False,
    module: str | None = None,
    public_name: str | None = None,
) -> FunctionSymbol:
    name = public_name or c_name
    return FunctionSymbol(
        name=name,
        span=span,
        kind=SymbolKind.FUNCTION,
        parameters=[ParameterSymbol(param_name, param_type, span) for param_name, param_type in parameters],
        return_type=return_type,
        c_name=c_name,
        declaration=None,
        owner=None,
        is_extern=True,
        is_exported=True,
        is_variadic=variadic,
        module=module,
    )
