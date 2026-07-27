from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("generics_test.ci")).c_source


def test_generic_struct_method_and_function_codegen() -> None:
    generated = compile_source(
        "struct Box[T]:\n"
        "    value: T\n"
        "    def get(self: &const Box[T]) -> T:\n"
        "        return self.value\n"
        "\n"
        "def identity[T](value: T) -> T:\n"
        "    return value\n"
        "\n"
        "def main() -> i32:\n"
        "    boxed: Box[i32] = Box(value=40)\n"
        "    return identity(boxed.get()) + 2\n"
    )

    assert "typedef struct Box_i32 Box_i32;" in generated
    assert "Box_i32_get" in generated
    assert "identity_i32" in generated
    assert "identity_i32(Box_i32_get((&(boxed))))" in generated


def test_generic_struct_explicit_type_args_at_construction() -> None:
    generated = compile_source(
        "struct Box[T]:\n"
        "    value: T\n"
        "\n"
        "def main() -> i32:\n"
        "    boxed = Box[i32](value=7)\n"
        "    return boxed.value\n"
    )
    assert "Box_i32 boxed" in generated


def test_generic_function_explicit_type_args() -> None:
    generated = compile_source(
        "def identity[T](value: T) -> T:\n"
        "    return value\n"
        "\n"
        "def main() -> i32:\n"
        "    return identity[i32](11)\n"
    )
    assert "identity_i32(11)" in generated


def test_generic_pair_two_params() -> None:
    generated = compile_source(
        "struct Pair[T, U]:\n"
        "    first: T\n"
        "    second: U\n"
        "\n"
        "def main() -> i32:\n"
        "    pair: Pair[i32, f64] = Pair(first=1, second=2.5)\n"
        "    return pair.first\n"
    )
    assert "Pair_i32_f64" in generated


def test_generic_union() -> None:
    generated = compile_source(
        "union Either[T]:\n"
        "    as_int: i32\n"
        "    as_t: T\n"
        "\n"
        "def main() -> i32:\n"
        "    value: Either[i32] = Either(as_t=7)\n"
        "    return value.as_t\n"
    )
    assert "Either_i32" in generated


def test_generic_enum_match() -> None:
    generated = compile_source(
        "enum Color[T]:\n"
        "    Red\n"
        "    Blue\n"
        "\n"
        "def main() -> i32:\n"
        "    c: Color[i32] = Color.Red\n"
        "    match c:\n"
        "        case Color.Red:\n"
        "            return 1\n"
        "        case Color.Blue:\n"
        "            return 2\n"
    )
    assert "Color_i32" in generated
    assert "Color_i32_Red" in generated


def test_generic_variant_match() -> None:
    generated = compile_source(
        "variant Tagged[T]:\n"
        "    None_\n"
        "    Some(value: T)\n"
        "\n"
        "def main() -> i32:\n"
        "    value: Tagged[i32] = Tagged.Some(value=9)\n"
        "    match value:\n"
        "        case Tagged.None_:\n"
        "            return 0\n"
        "        case Tagged.Some(x):\n"
        "            return x\n"
    )
    assert "Tagged_i32" in generated
    assert "Tagged_i32_Tag_Some" in generated


def test_generic_class_implements_generic_interface() -> None:
    generated = compile_source(
        "abstract class Writer[T]:\n"
        "    @abstractmethod\n"
        "    def write(self, item: T) -> void:\n"
        "        pass\n"
        "\n"
        "class IntWriter(Writer[i32]):\n"
        "    def write(self, item: i32) -> void:\n"
        "        print(item)\n"
        "\n"
        "def main() -> i32:\n"
        "    w = IntWriter()\n"
        "    w.write(3)\n"
        "    return 0\n"
    )
    assert "Writer_i32" in generated
    assert "IntWriter" in generated


def test_nested_generic_with_option() -> None:
    generated = compile_source(
        "struct Box[T]:\n"
        "    value: T\n"
        "\n"
        "def main() -> i32:\n"
        "    boxed: Option[Box[i32]] = Some(Box(value=4))\n"
        "    match boxed:\n"
        "        case None:\n"
        "            return 0\n"
        "        case Some(inner):\n"
        "            return inner.value\n"
    )
    assert "Box_i32" in generated
    assert "CinderOption_Box_i32" in generated


def test_multiple_specializations_and_list_nesting() -> None:
    generated = compile_source(
        "struct Box[T]:\n"
        "    value: T\n"
        "\n"
        "def main() -> i32:\n"
        "    numbers: List[Box[i32]] = [Box(value=1), Box(value=2)]\n"
        "    floats: Box[f64] = Box(value=1.5)\n"
        "    return numbers[0].value + cast[i32](floats.value)\n"
    )
    assert "Box_i32" in generated
    assert "Box_f64" in generated
    assert "CinderList_Box_i32" in generated


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "struct Box[T]:\n"
            "    value: T\n"
            "\n"
            "def main() -> void:\n"
            "    value: Box = Box(value=1)\n",
            "generic type 'Box' requires type arguments",
        ),
        (
            "struct Box[T]:\n"
            "    value: T\n"
            "\n"
            "def main() -> void:\n"
            "    value: Box[i32, i32] = Box(value=1)\n",
            "expects 1 type argument",
        ),
        (
            "def identity[T](value: T) -> T:\n"
            "    return value\n"
            "\n"
            "def main() -> void:\n"
            "    print(identity())\n",
            "cannot infer type arguments",
        ),
    ],
)
def test_generic_diagnostics(source: str, message: str) -> None:
    with pytest.raises(CompilationFailed) as raised:
        compile_source(source)
    assert any(message in diagnostic.message for diagnostic in raised.value.diagnostics)


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_generics_end_to_end(tmp_path: Path) -> None:
    source = (
        "struct Box[T]:\n"
        "    value: T\n"
        "    def get(self: &const Box[T]) -> T:\n"
        "        return self.value\n"
        "\n"
        "def identity[T](value: T) -> T:\n"
        "    return value\n"
        "\n"
        "def main() -> i32:\n"
        "    boxed: Box[i32] = Box(value=40)\n"
        "    return identity(boxed.get()) + 2\n"
    )
    source_path = tmp_path / "generics.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "generics.exe" if shutil.which("cl") and not shutil.which("cc") else "generics"
    )
    artifact = Compiler().build(
        source_path,
        output=executable,
        build_dir=tmp_path / "build",
    )
    result = subprocess.run(
        [str(artifact.executable)],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 42, result.stderr
