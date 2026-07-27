from __future__ import annotations

from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("test.ci")).c_source


def test_struct_method_and_named_constructor() -> None:
    generated = compile_source(
        "import math\n"
        "\n"
        "struct Vec2:\n"
        "    x: f32\n"
        "    y: f32\n"
        "\n"
        "    def length(self: &const Vec2) -> f32:\n"
        "        return math.sqrtf(self.x * self.x + self.y * self.y)\n"
        "\n"
        "def main() -> i32:\n"
        "    vector = Vec2(y=4.0, x=3.0)\n"
        "    result = vector.length()\n"
        "    return cast[i32](result)\n"
    )
    assert "struct Vec2" in generated
    assert "float Vec2_length(const Vec2 *self)" in generated
    assert "Vec2 vector = { .x = 3.0f, .y = 4.0f };" in generated
    assert "Vec2_length((&(vector)))" in generated


def test_array_to_const_slice_coercion() -> None:
    generated = compile_source(
        "def first(values: []const i32) -> i32:\n"
        "    return values[0]\n"
        "\n"
        "def main() -> i32:\n"
        "    values: i32[2] = [7, 8]\n"
        "    return first(values)\n"
    )
    assert "CinderSlice_const_i32" in generated
    assert ".data = values, .length = 2" in generated


def test_builtin_print_generates_printf_without_import() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        "    print(\"answer\", 42)\n"
        "    return 0\n"
    )
    assert "#include <stdio.h>" in generated
    assert 'printf("%s %lld\\n", "answer", ((long long)(42)));' in generated


def test_builtin_input_generates_runtime_call_without_import() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        "    name = input(\"Name: \")\n"
        "    other = input()\n"
        "    return cast[i32](len(name) + len(other))\n"
    )
    assert 'const char *name = cinder_input("Name: ");' in generated
    assert "const char *other = cinder_input(NULL);" in generated


def test_input_rejects_invalid_arguments() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "def main() -> i32:\n"
            "    input(\"a\", \"b\")\n"
            "    input(prompt=\">\")\n"
            "    input(1)\n"
            "    return 0\n"
        )
    text = str(captured.value)
    assert "input expects zero or one positional argument" in text
    assert "input does not accept named arguments" in text
    assert "expected *const char, got i32" in text


def test_print_fstring_generates_escaped_printf_format() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        "    value: i32 = 42\n"
        "    pi: f64 = 3.14159\n"
        "    print(f\"value={value:x} pi={pi:.2f} {{ok}} 100%\")\n"
        "    return 0\n"
    )
    assert "int32_t __cinder_print_integer_1 = value;" in generated
    assert 'printf("value=%s%llx pi=%.2f {ok} 100%%\\n"' in generated
    assert '((__cinder_print_integer_1) < 0 ? "-" : "")' in generated


def test_nested_fstrings_are_supported_inside_print() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        "    value: i32 = 42\n"
        "    print(f\"outer {f'inner {value}'}\")\n"
        "    return 0\n"
    )
    assert 'printf("outer inner %lld\\n", ((long long)(value)));' in generated


def test_unsigned_integer_decimal_format_preserves_unsigned_codegen() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        "    value: u64 = 18446744073709551615\n"
        "    print(f\"{value:d}\")\n"
        "    return 0\n"
    )
    assert 'printf("%llu\\n", ((unsigned long long)(value)));' in generated


def test_fstrings_are_rejected_outside_print() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "def main() -> i32:\n"
            "    message = f\"value {1}\"\n"
            "    return 0\n"
        )
    assert "f-strings are only supported inside print(...)" in str(captured.value)


def test_print_rejects_incompatible_fstring_format() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "def main() -> i32:\n"
            "    print(f\"{1:s}\")\n"
            "    return 0\n"
        )
    assert "integer print values do not support :s" in str(captured.value)


def test_print_collections_generate_helpers() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        "    values = [1, 2]\n"
        "    print(values)\n"
        "    print((3, 4))\n"
        "    return 0\n"
    )
    assert "CinderList_i32_print((&(values)));" in generated
    assert "CinderTuple_2_i32_i32_print(&" in generated
    assert 'printf("\\n");' in generated


def test_print_rejects_collection_format_spec_and_unaddressable_list() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "def main() -> i32:\n"
            "    values = [1, 2]\n"
            "    print(f\"{values:d}\")\n"
            "    print([3, 4])\n"
            "    return 0\n"
        )
    text = str(captured.value)
    assert "List[i32] print values support only the default format" in text
    assert "print requires an addressable List[i32]" in text


def test_print_rejects_unprintable_list_element_type() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "struct Point:\n"
            "    x: i32\n"
            "\n"
            "def main() -> i32:\n"
            "    points = [Point(x=1)]\n"
            "    print(points)\n"
            "    return 0\n"
        )
    assert "type Point cannot be printed" in str(captured.value)


def test_scoped_defer_runs_before_return_value_is_released() -> None:
    generated = compile_source(
        "def compute() -> i32:\n"
        "    values = alloc[i32](1)\n"
        "    defer free(values)\n"
        "    values[0] = 42\n"
        "    return values[0]\n"
    )
    temporary = generated.index("__cinder_return_")
    cleanup = generated.index("free(values);")
    return_statement = generated.index("return __cinder_return_")
    assert temporary < cleanup < return_statement
    assert generated.count("free(values);") == 1


def test_unknown_name_has_source_diagnostic() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "def main() -> i32:\n"
            "    return missing\n"
        )
    rendered = str(captured.value)
    assert "test.ci:2:12" in rendered
    assert "unknown name 'missing'" in rendered
    assert "return missing" in rendered


def test_classes_generate_explicit_layout_and_static_dispatch() -> None:
    generated = compile_source(
        "class Counter:\n"
        "    value: i32\n"
        "\n"
        "    def __init__(self, value: i32):\n"
        "        self.value = value\n"
        "\n"
        "    def add(self, amount: i32) -> i32:\n"
        "        self.value += amount\n"
        "        return self.value\n"
        "\n"
        "def increment(counter: &Counter) -> i32:\n"
        "    return counter.add(1)\n"
    )
    assert "struct Counter" in generated
    assert "Counter Counter__new(int32_t value)" in generated
    assert "return Counter_add((counter), 1);" in generated
    assert "vtable" not in generated
