from __future__ import annotations

from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("reflection.ci")).c_source


def test_reflect_emits_explicit_field_method_and_type_metadata() -> None:
    generated = compile_source(
        "@reflect\n"
        "struct User:\n"
        "    id: u64\n"
        "    private active: bool\n"
        "\n"
        "    def enabled(self: &const User) -> bool:\n"
        "        return self.active\n"
        "\n"
        "def inspect(user: &const User) -> usize:\n"
        "    info = type_info(user)\n"
        "    return info.field_count + info.method_count\n"
    )
    assert "static const CinderFieldInfo User__field_info[]" in generated
    assert '.name = "id"' in generated
    assert '.name = "active"' in generated
    assert ".is_private = true" in generated
    assert "static const CinderMethodInfo User__method_info[]" in generated
    assert '.signature = "enabled() -> bool"' in generated
    assert "const CinderTypeInfo User__type_info" in generated
    assert ".kind = CINDER_TYPE_STRUCT" in generated
    assert ".fields = User__field_info" in generated
    assert ".methods = User__method_info" in generated


def test_compile_time_reflection_becomes_constants_and_unrolled_c() -> None:
    generated = compile_source(
        "struct Pair:\n"
        "    left: i32\n"
        "    right: i32\n"
        "\n"
        "    def sum(self: &const Pair) -> i32:\n"
        "        return self.left + self.right\n"
        "\n"
        "static_assert(type_of(Pair(left=1, right=2)) == type_of(Pair(left=3, right=4)))\n"
        "static_assert(field_count(Pair) == 2)\n"
        "static_assert(method_count(Pair) == 1)\n"
        "static_assert(has_field(Pair, \"left\"))\n"
        "static_assert(has_method(Pair, \"sum\"))\n"
        "static_assert(size_of(Pair) >= 8)\n"
        "static_assert(align_of(Pair) >= 1)\n"
        "\n"
        "def offsets() -> usize:\n"
        "    total: usize = 0\n"
        "    for field in comptime fields_of(Pair):\n"
        "        total += field.offset\n"
        "    for method in comptime methods_of(Pair):\n"
        "        total += method.parameter_count\n"
        "    return total\n"
    )
    assert generated.count('CINDER_STATIC_ASSERT(true, "static assertion failed");') == 5
    assert 'CINDER_STATIC_ASSERT((sizeof(Pair) >= 8), "static assertion failed");' in generated
    assert 'CINDER_STATIC_ASSERT((CINDER_ALIGNOF(Pair) >= 1), "static assertion failed");' in generated
    assert "Pair__type_info" not in generated
    assert "/* comptime fields iteration 0 for Pair */" in generated
    assert "/* comptime fields iteration 1 for Pair */" in generated
    assert "/* comptime methods iteration 0 for Pair */" in generated
    assert "offsetof(Pair, left)" in generated
    assert "offsetof(Pair, right)" in generated
    assert "for (" not in generated.split("size_t offsets(void)", 1)[1]


def test_implements_is_a_compile_time_query() -> None:
    generated = compile_source(
        "abstract class Runnable:\n"
        "    @abstractmethod\n"
        "    def run(self) -> i32:\n"
        "        pass\n"
        "\n"
        "class Task(Runnable):\n"
        "    @override\n"
        "    def run(self) -> i32:\n"
        "        return 0\n"
        "\n"
        "static_assert(implements(Task, Runnable))\n"
        "static_assert(not implements(Runnable, Task))\n"
    )
    assert generated.count('CINDER_STATIC_ASSERT(true, "static assertion failed");') == 2


def test_type_of_comparison_is_actually_evaluated() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "struct Left:\n"
            "    value: i32\n"
            "\n"
            "struct Right:\n"
            "    value: i32\n"
            "\n"
            "static_assert(\n"
            "    type_of(Left(value=1)) == type_of(Right(value=1)),\n"
            "    \"types must match\"\n"
            ")\n"
        )
    assert "error[C214]: types must match" in str(captured.value)


def test_reflection_is_opt_in_at_runtime() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "struct User:\n"
            "    id: i32\n"
            "\n"
            "def inspect(user: &const User) -> usize:\n"
            "    return type_info(user).field_count\n"
        )
    assert "type_info requires a value whose type uses @reflect" in str(captured.value)


def test_runtime_dyn_reflection_requires_reflected_interface() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "abstract class Shape:\n"
            "    @abstractmethod\n"
            "    def area(self) -> f64:\n"
            "        pass\n"
            "\n"
            "def name(shape: &dyn Shape) -> String:\n"
            "    return type_name(shape)\n"
        )
    assert "runtime type_name on dyn requires a @reflect interface" in str(captured.value)


def test_reflected_interface_requires_reflected_implementations() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "@reflect\n"
            "abstract class Shape:\n"
            "    @abstractmethod\n"
            "    def area(self) -> f64:\n"
            "        pass\n"
            "\n"
            "class Circle(Shape):\n"
            "    @override\n"
            "    def area(self) -> f64:\n"
            "        return 1.0\n"
        )
    assert "class Circle must use @reflect" in str(captured.value)


def test_failed_static_assert_is_a_source_diagnostic() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "struct Empty:\n"
            "    value: i32\n"
            "\n"
            "static_assert(field_count(Empty) == 2, \"layout contract\")\n"
        )
    rendered = str(captured.value)
    assert "error[C214]: layout contract" in rendered
    assert "reflection.ci:4:1" in rendered
