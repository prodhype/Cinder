from __future__ import annotations

from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("file_io_test.ci")).c_source


def test_with_open_writes_and_drops_file() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        '    with open("out.bin", "wb") as file:\n'
        "        data: u8[2] = [0x41, 0x42]\n"
        "        written = file.write(data)\n"
        "        return cast[i32](written)\n"
    )

    assert "CinderFile file = CinderFile_open" in generated
    assert 'CinderFile_open("out.bin", "wb")' in generated
    assert "CinderFile_write((&(file))" in generated
    assert "CinderFile_drop(&file);" in generated
    assert "#include <stdio.h>" in generated


def test_open_outside_with_still_registers_drop() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        '    file = open("out.bin", "wb")\n'
        "    file.close()\n"
        "    return 0\n"
    )

    assert "CinderFile file = CinderFile_open" in generated
    assert "CinderFile_close((&(file)));" in generated
    assert "CinderFile_drop(&file);" in generated


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "def consume(file: File) -> void:\n"
            "    pass\n"
            "\n"
            "def main() -> i32:\n"
            '    file = open("out.bin", "wb")\n'
            "    consume(file)\n"
            "    file.close()\n"
            "    return 0\n",
            "use of moved value file",
        ),
        (
            "def main() -> i32:\n"
            '    file = open("out.bin", "wb")\n'
            "    copied = file\n"
            "    file.close()\n"
            "    return 0\n",
            "use of moved value file",
        ),
        (
            "def main() -> i32:\n"
            '    with 1 as value:\n'
            "        return value\n",
            None,
        ),
    ],
)
def test_file_ownership_and_with_binding(source: str, message: str | None) -> None:
    if message is None:
        generated = compile_source(source)
        assert "int32_t value = 1;" in generated
        return

    with pytest.raises(CompilationFailed) as captured:
        compile_source(source)
    assert message in str(captured.value)
