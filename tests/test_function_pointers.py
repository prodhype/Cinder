from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("function_pointer_test.ci")).c_source


def test_function_pointer_pass_store_and_call_codegen() -> None:
    generated = compile_source(
        "def double(n: i32) -> i32:\n"
        "    return n * 2\n"
        "\n"
        "def apply(f: def(i32) -> i32, x: i32) -> i32:\n"
        "    return f(x)\n"
        "\n"
        "def main() -> i32:\n"
        "    callback = double\n"
        "    typed: def(i32) -> i32 = double\n"
        "    return apply(callback, 21) + typed(0)\n"
    )

    assert "int32_t (*f)(int32_t)" in generated
    assert "int32_t (*callback)(int32_t) = cinder_double;" in generated
    assert "int32_t (*typed)(int32_t) = cinder_double;" in generated
    assert "(typed)(0)" in generated
    assert "apply(callback, 21)" in generated


def test_function_pointer_void_return_defaults() -> None:
    generated = compile_source(
        "def bump(n: &i32) -> void:\n"
        "    n += 1\n"
        "\n"
        "def main() -> i32:\n"
        "    value: i32 = 0\n"
        "    action: def(&i32) = bump\n"
        "    action(&value)\n"
        "    return value\n"
    )

    assert "void (*action)(int32_t *) = bump;" in generated


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "def add(a: i32, b: i32) -> i32:\n"
            "    return a + b\n"
            "\n"
            "def main() -> i32:\n"
            "    callback: def(i32) -> i32 = add\n"
            "    return callback(1)\n",
            "expected def(i32) -> i32, got def(i32, i32) -> i32",
        ),
        (
            "def identity[T](value: T) -> T:\n"
            "    return value\n"
            "\n"
            "def main() -> i32:\n"
            "    callback: def(i32) -> i32 = identity\n"
            "    return 0\n",
            "expected def(i32) -> i32, got function identity",
        ),
        (
            "def main() -> i32:\n"
            "    callback: def(i32) -> i32 = print\n"
            "    return 0\n",
            "expected def(i32) -> i32, got function print",
        ),
        (
            "struct Point:\n"
            "    x: i32\n"
            "    def bump(self: &Point) -> void:\n"
            "        self.x += 1\n"
            "\n"
            "def main() -> i32:\n"
            "    point = Point(x=0)\n"
            "    callback: def(&Point) = point.bump\n"
            "    return 0\n",
            "expected def(&Point) -> void, got function Point_bump",
        ),
        (
            "def double(n: i32) -> i32:\n"
            "    return n * 2\n"
            "\n"
            "def main() -> i32:\n"
            "    callback = double\n"
            "    return callback(x=21)\n",
            "function pointer calls do not support named arguments",
        ),
    ],
)
def test_function_pointer_diagnostics(source: str, message: str) -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(source)
    assert message in str(captured.value)


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_function_pointers_run_end_to_end(tmp_path: Path) -> None:
    source = (
        "def double(n: i32) -> i32:\n"
        "    return n * 2\n"
        "\n"
        "def apply(f: def(i32) -> i32, x: i32) -> i32:\n"
        "    return f(x)\n"
        "\n"
        "def main() -> i32:\n"
        "    callback = double\n"
        "    if apply(callback, 21) != 42:\n"
        "        return 1\n"
        "    if apply(double, 3) != 6:\n"
        "        return 2\n"
        "    return 0\n"
    )
    source_path = tmp_path / "function_pointers.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "function_pointers.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "function_pointers"
    )
    artifact = Compiler().build(
        source_path,
        output=executable,
        build_dir=tmp_path / "build",
    )
    result = subprocess.run(
        [str(artifact.executable)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
