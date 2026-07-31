from __future__ import annotations

import shutil
import subprocess
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
    # Shared File helper guard must always include read_all, even for write-only modules.
    assert "static inline CINDER_MAYBE_UNUSED CinderList_u8 CinderFile_read_all(" in generated


def test_file_read_all_helper_survives_dependency_without_read_all(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"file_read_all_guard\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "writer.ci").write_text(
        "def write_marker(path: const char*) -> void:\n"
        '    with open(path, "wb") as file:\n'
        "        data: u8[3] = [65, 66, 67]\n"
        "        file.write(data)\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import writer\n"
        "\n"
        "def main() -> i32:\n"
        '    path: const char* = "marker.bin"\n'
        "    writer.write_marker(path)\n"
        '    with open(path, "rb") as file:\n'
        "        data = file.read_all()\n"
        "        if len(data) != 3:\n"
        "            return 1\n"
        "        if data[0] != 65 or data[2] != 67:\n"
        "            return 2\n"
        "    return 0\n",
        encoding="utf-8",
    )

    project = Compiler().compile_project(tmp_path)
    writer_header = project.units_by_name["writer"].c_header
    assert writer_header is not None
    assert "CINDER_HELPERS_CINDERFILE" in writer_header
    assert "CinderFile_read_all(" in writer_header
    assert "CinderList_u8" in writer_header

    main_header = project.units_by_name["main"].c_header
    assert main_header is not None
    assert '#include "cinder_gen/writer.cinder.h"' in main_header

    if not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")):
        return

    executable = tmp_path / (
        "file_read_all_guard.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "file_read_all_guard"
    )
    artifact = Compiler().build(tmp_path, output=executable, build_dir=tmp_path / "build")
    result = subprocess.run(
        [str(artifact.executable)],
        check=False,
        text=True,
        capture_output=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


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


def test_file_read_helpers_codegen() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        '    with open("in.bin", "rb") as file:\n'
        "        buffer: u8[4]\n"
        "        counted = file.read(buffer)\n"
        "        line = file.read_line()\n"
        "        defer free(cast[void*](line))\n"
        "        data = file.read_all()\n"
        "        return cast[i32](counted + len(data))\n"
    )

    assert "CinderFile_read((&(file))" in generated
    assert "CinderFile_read_line((&(file)))" in generated
    assert "CinderFile_read_all((&(file)))" in generated
    assert "static inline CINDER_MAYBE_UNUSED size_t CinderFile_read(" in generated
    assert "static inline CINDER_MAYBE_UNUSED char *CinderFile_read_line(" in generated
    assert "static inline CINDER_MAYBE_UNUSED CinderList_u8 CinderFile_read_all(" in generated
    assert "typedef struct CinderSlice_u8" in generated


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
        (
            "def main() -> i32:\n"
            '    with open("in.bin", "rb") as file:\n'
            "        file.read()\n"
            "    return 0\n",
            "File.read expects one argument",
        ),
        (
            "def main() -> i32:\n"
            '    with open("in.bin", "rb") as file:\n'
            '        file.read("not-a-buffer")\n'
            "    return 0\n",
            "expected []u8",
        ),
        (
            "def main() -> i32:\n"
            '    with open("in.bin", "rb") as file:\n'
            '        file.read_line("extra")\n'
            "    return 0\n",
            "File.read_line expects no arguments",
        ),
        (
            "def main() -> i32:\n"
            '    with open("in.bin", "rb") as file:\n'
            "        file.read_all(1)\n"
            "    return 0\n",
            "File.read_all expects no arguments",
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


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_file_read_write_roundtrip_runs_end_to_end(tmp_path: Path) -> None:
    source = (
        "def main() -> i32:\n"
        '    path: const char* = "cinder_read_roundtrip.bin"\n'
        "\n"
        "    with open(path, \"wb\") as out:\n"
        "        payload: u8[11] = [\n"
        "            104, 101, 108, 108, 111, 10,\n"
        "            119, 111, 114, 108, 100,\n"
        "        ]\n"
        "        if out.write(payload) != 11:\n"
        "            return 1\n"
        "\n"
        "    with open(path, \"rb\") as file:\n"
        "        chunk: u8[5]\n"
        "        counted = file.read(chunk)\n"
        "        if counted != 5:\n"
        "            return 2\n"
        "        if chunk[0] != 104 or chunk[4] != 111:\n"
        "            return 3\n"
        "\n"
        "        line = file.read_line()\n"
        "        defer free(cast[void*](line))\n"
        "        if line == null or line[0] != 0:\n"
        "            return 4\n"
        "\n"
        "        rest = file.read_all()\n"
        "        if len(rest) != 5:\n"
        "            return 5\n"
        "        if rest[0] != 119 or rest[4] != 100:\n"
        "            return 6\n"
        "\n"
        "    with open(path, \"rb\") as file:\n"
        "        first = file.read_line()\n"
        "        defer free(cast[void*](first))\n"
        "        second = file.read_line()\n"
        "        defer free(cast[void*](second))\n"
        "        if first[0] != 104 or first[4] != 111:\n"
        "            return 7\n"
        "        if second[0] != 119 or second[4] != 100:\n"
        "            return 8\n"
        "        empty = file.read_line()\n"
        "        if empty != null:\n"
        "            return 9\n"
        "\n"
        "    return 0\n"
    )
    source_path = tmp_path / "file_read_roundtrip.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "file_read_roundtrip.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "file_read_roundtrip"
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
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_read_line_preserves_lone_trailing_cr(tmp_path: Path) -> None:
    source = (
        "def main() -> i32:\n"
        '    path: const char* = "cr_payload.bin"\n'
        "\n"
        "    with open(path, \"wb\") as out:\n"
        "        # x\\r\\n then abc\\r at EOF\n"
        "        payload: u8[7] = [120, 13, 10, 97, 98, 99, 13]\n"
        "        if out.write(payload) != 7:\n"
        "            return 1\n"
        "\n"
        "    with open(path, \"rb\") as file:\n"
        "        first = file.read_line()\n"
        "        defer free(cast[void*](first))\n"
        "        if first[0] != 120 or first[1] != 0:\n"
        "            return 2\n"
        "\n"
        "        second = file.read_line()\n"
        "        defer free(cast[void*](second))\n"
        "        if second[0] != 97 or second[1] != 98 or second[2] != 99:\n"
        "            return 3\n"
        "        if second[3] != 13 or second[4] != 0:\n"
        "            return 4\n"
        "\n"
        "        if file.read_line() != null:\n"
        "            return 5\n"
        "\n"
        "    return 0\n"
    )
    source_path = tmp_path / "read_line_cr.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "read_line_cr.exe" if shutil.which("cl") and not shutil.which("cc") else "read_line_cr"
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
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
