from __future__ import annotations

from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("classes.ci")).c_source


def assert_compile_error(source: str, message: str) -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(source)
    assert message in str(captured.value)


def test_abstract_interface_uses_explicit_dyn_value_and_table() -> None:
    generated = compile_source(
        "abstract class Shape:\n"
        "    @abstractmethod\n"
        "    def area(self) -> f64:\n"
        "        pass\n"
        "\n"
        "class Circle(Shape):\n"
        "    radius: f64\n"
        "\n"
        "    def __init__(self, radius: f64):\n"
        "        self.radius = radius\n"
        "\n"
        "    @override\n"
        "    def area(self) -> f64:\n"
        "        return self.radius * self.radius\n"
        "\n"
        "def concrete_area(circle: &Circle) -> f64:\n"
        "    return circle.area()\n"
        "\n"
        "def dynamic_area(shape: &dyn Shape) -> f64:\n"
        "    return shape.area()\n"
        "\n"
        "def convert(circle: &Circle) -> f64:\n"
        "    return dynamic_area(circle)\n"
    )
    assert "typedef struct CinderDyn_Shape" in generated
    assert "void *object;" in generated
    assert "const CinderVTable_Shape *vtable;" in generated
    assert "double (*area)(void *object, const CinderVTable_Shape *vtable);" in generated
    assert "return Circle_area((circle));" in generated
    assert "vtable->area(" in generated
    assert ".vtable = &Circle__as__Shape__vtable" in generated


def test_single_implementation_base_is_a_zero_offset_prefix() -> None:
    generated = compile_source(
        "class Base:\n"
        "    first: i32\n"
        "\n"
        "    def __init__(self, first: i32):\n"
        "        self.first = first\n"
        "\n"
        "class Derived(Base):\n"
        "    second: i32\n"
        "\n"
        "    def __init__(self, first: i32, second: i32):\n"
        "        super().__init__(first)\n"
        "        self.second = second\n"
        "\n"
        "    def total(self) -> i32:\n"
        "        return self.first + self.second\n"
    )
    derived = generated.split("struct Derived\n{", 1)[1].split("\n};", 1)[0]
    assert derived.index("Base _base;") < derived.index("int32_t second;")
    assert "Base___init__" in generated
    assert "->_base" in generated
    assert "((self)->_base.first + (self)->second)" in generated


def test_destructor_cleanup_is_reverse_order_and_move_only() -> None:
    generated = compile_source(
        "class Resource:\n"
        "    value: i32\n"
        "\n"
        "    def __init__(self, value: i32):\n"
        "        self.value = value\n"
        "\n"
        "    def __del__(self):\n"
        "        self.value = 0\n"
        "\n"
        "def make(value: i32) -> Resource:\n"
        "    resource = Resource(value)\n"
        "    return resource\n"
        "\n"
        "def consume() -> i32:\n"
        "    first = make(1)\n"
        "    second = make(2)\n"
        "    return first.value + second.value\n"
    )
    return_value = generated.index("int32_t __cinder_return_")
    drop_second = generated.index("Resource__drop(&second);", return_value)
    drop_first = generated.index("Resource__drop(&first);", drop_second)
    final_return = generated.index("return __cinder_return_", drop_first)
    assert return_value < drop_second < drop_first < final_return
    make_body = generated.split("Resource make(int32_t value)\n{", 1)[1].split("\n}", 1)[0]
    assert "Resource__drop(&resource);" not in make_body


def test_concrete_class_must_implement_abstract_methods() -> None:
    assert_compile_error(
        "abstract class Reader:\n"
        "    @abstractmethod\n"
        "    def read(self) -> i32:\n"
        "        pass\n"
        "\n"
        "class Incomplete(Reader):\n"
        "    pass\n",
        "concrete class Incomplete does not implement: read",
    )


def test_override_signature_is_checked() -> None:
    assert_compile_error(
        "abstract class Base:\n"
        "    def value(self, number: i32) -> i32:\n"
        "        return number\n"
        "\n"
        "class Child(Base):\n"
        "    @override\n"
        "    def value(self, number: f64) -> i32:\n"
        "        return 0\n",
        "override Child.value does not match the base signature",
    )


def test_derived_constructor_must_initialize_base_first() -> None:
    assert_compile_error(
        "class Base:\n"
        "    value: i32\n"
        "\n"
        "    def __init__(self, value: i32):\n"
        "        self.value = value\n"
        "\n"
        "class Child(Base):\n"
        "    other: i32\n"
        "\n"
        "    def __init__(self, value: i32):\n"
        "        self.other = value\n",
        "constructor Child.__init__ must call super().__init__ first",
    )


def test_multiple_implementation_inheritance_is_rejected() -> None:
    assert_compile_error(
        "class Left:\n"
        "    left: i32\n"
        "\n"
        "class Right:\n"
        "    right: i32\n"
        "\n"
        "class Invalid(Left, Right):\n"
        "    pass\n",
        "class Invalid has multiple implementation bases",
    )


def test_destructor_bearing_classes_cannot_be_copied() -> None:
    assert_compile_error(
        "class Resource:\n"
        "    def __del__(self):\n"
        "        pass\n"
        "\n"
        "def main() -> i32:\n"
        "    original = Resource()\n"
        "    copy = original\n"
        "    copy = original\n"
        "    return 0\n",
        "use of moved value original",
    )


def test_temporary_cannot_be_borrowed_as_dyn() -> None:
    assert_compile_error(
        "abstract class Shape:\n"
        "    @abstractmethod\n"
        "    def area(self) -> f64:\n"
        "        pass\n"
        "\n"
        "class Circle(Shape):\n"
        "    @override\n"
        "    def area(self) -> f64:\n"
        "        return 1.0\n"
        "\n"
        "def measure(shape: &dyn Shape) -> f64:\n"
        "    return shape.area()\n"
        "\n"
        "def main() -> i32:\n"
        "    result = measure(Circle())\n"
        "    return cast[i32](result)\n",
        "concrete-to-dyn conversion requires an addressable object",
    )


def test_private_class_field_is_enforced() -> None:
    assert_compile_error(
        "class Secret:\n"
        "    private value: i32\n"
        "\n"
        "    def __init__(self):\n"
        "        self.value = 1\n"
        "\n"
        "def reveal(secret: &Secret) -> i32:\n"
        "    return secret.value\n",
        "field Secret.value is private",
    )
