from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed, Diagnostic


ROOT = Path(__file__).resolve().parents[1]
INPUT_NAME = "bootstrap_backend_input.ci"


pytestmark = pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)


@pytest.fixture(scope="module")
def bootstrap_backend_executable(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build_root = tmp_path_factory.mktemp("bootstrap_backend_build")
    executable = build_root / (
        "bootstrap_backend.exe" if shutil.which("cl") and not shutil.which("cc") else "bootstrap_backend"
    )
    artifact = Compiler().build(
        ROOT / "compiler_backend",
        output=executable,
        build_dir=build_root / "build",
    )
    return artifact.executable


def run_bootstrap_backend(executable: Path, tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / INPUT_NAME).write_text(source, encoding="utf-8")
    return subprocess.run(
        [str(executable)],
        check=False,
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )


def split_backend_output(stdout: str) -> tuple[str, str]:
    lines = stdout.splitlines()
    assert len(lines) >= 3, stdout
    assert lines[0].startswith("B "), stdout
    assert lines[1].startswith("C "), stdout
    return lines[0], "\n".join(lines[2:])


def parse_summary(summary: str) -> list[int]:
    parts = summary.split()
    assert parts[0] == "B", summary
    return [int(part) for part in parts[1:]]


def compile_and_run_c(tmp_path: Path, c_source: str) -> subprocess.CompletedProcess[str]:
    compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    assert compiler is not None
    source_path = tmp_path / "bootstrap_backend_generated.c"
    executable = tmp_path / "bootstrap_backend_generated"
    source_path.write_text(c_source, encoding="utf-8")
    compiled = subprocess.run(
        [compiler, "-std=c11", str(source_path), "-o", str(executable)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert compiled.returncode == 0, compiled.stderr
    return subprocess.run([str(executable)], check=False, text=True, capture_output=True)


def span_offset(source: str, line: int, column: int) -> int:
    lines = source.splitlines(keepends=True)
    if line > len(lines):
        return len(source.encode("utf-8"))
    offset = 0
    for previous in lines[: line - 1]:
        offset += len(previous.encode("utf-8"))
    content = lines[line - 1].rstrip("\r\n")
    character_index = max(0, min(column - 1, len(content)))
    return offset + len(content[:character_index].encode("utf-8"))


def diagnostic_record(source: str, diagnostic: Diagnostic) -> tuple[str, int, int, int, int, int]:
    assert diagnostic.code is not None
    start = span_offset(source, diagnostic.span.start_line, diagnostic.span.start_column)
    end = span_offset(source, diagnostic.span.end_line, diagnostic.span.end_column)
    return (
        "E",
        int(diagnostic.code[1:]),
        start,
        end - start,
        diagnostic.span.start_line,
        diagnostic.span.start_column,
    )


def parse_error_record(stdout: str) -> tuple[str, int, int, int, int, int]:
    [line] = stdout.splitlines()
    tag, code, start, length, row, column = line.split()
    return (tag, int(code), int(start), int(length), int(row), int(column))


@pytest.mark.parametrize(
    ("source", "backend_snippets", "stage0_snippets"),
    [
        (
            "def main() -> i32:\n"
            "    return 42\n",
            ["int32_t main(void)", "return 42;"],
            ["int main(void)", "return 42;"],
        ),
        (
            "def main() -> i32:\n"
            "    value: i32 = 41\n"
            "    return value + 1\n",
            ["int32_t value = 41;", "return value + 1;"],
            ["int32_t value = 41;", "return (value + 1);"],
        ),
        (
            "struct Point:\n"
            "    x: i32\n"
            "    y: i32\n"
            "\n"
            "def main() -> i32:\n"
            "    return 0\n",
            ["typedef struct Point", "int32_t x;", "int32_t y;", "return 0;"],
            ["return 0;"],
        ),
        (
            "class Point:\n"
            "    x: i32\n"
            "\n"
            "def main() -> i32:\n"
            "    return 0\n",
            ["typedef struct Point", "int32_t x;", "return 0;"],
            ["Point", "return 0;"],
        ),
        (
            "def add(a: i32, b: i32) -> i32:\n"
            "    return a + b\n"
            "\n"
            "def main() -> i32:\n"
            "    return add(41, 1)\n",
            ["int32_t add(int32_t a, int32_t b)", "return add(41, 1);"],
            ["int32_t add(int32_t a, int32_t b)", "return add(41, 1);"],
        ),
        (
            "def widen(value: i64) -> i64:\n"
            "    return value\n"
            "\n"
            "def main() -> i32:\n"
            "    return 0\n",
            ["int64_t widen(int64_t value)", "return value;"],
            ["int64_t widen(int64_t value)", "return value;"],
        ),
        (
            "def main() -> i32:\n"
            "    value: i32 = 1\n"
            "    if value > 0:\n"
            "        return 10\n"
            "    elif value < 0:\n"
            "        return 20\n"
            "    else:\n"
            "        return 30\n",
            ["if (value > 0)", "else if (value < 0)", "else {"],
            ["if (value > 0)", "else if (value < 0)", "else"],
        ),
        (
            "def main() -> i32:\n"
            "    total: i32 = 0\n"
            "    n: i32 = 3\n"
            "    while n > 0:\n"
            "        total = total + n\n"
            "        n = n - 1\n"
            "    return total\n",
            ["while (n > 0)", "total = total + n;", "n = n - 1;"],
            ["while (n > 0)", "total = (total + n);", "n = (n - 1);"],
        ),
        (
            "enum State:\n"
            "    idle\n"
            "    running\n"
            "\n"
            "union Number:\n"
            "    integer: i32\n"
            "\n"
            "def main() -> i32:\n"
            "    return 0\n",
            ["typedef enum State", "State_idle", "State_running", "typedef union Number"],
            ["return 0;"],
        ),
        (
            "def log() -> i32:\n"
            "    return 0\n"
            "\n"
            "def main() -> i32:\n"
            "    defer log()\n"
            "    return 42\n",
            ["log();\n    return 42;"],
            ["log();"],
        ),
    ],
)
def test_bootstrap_backend_emits_stage0_overlapping_c_snippets(
    bootstrap_backend_executable: Path,
    tmp_path: Path,
    source: str,
    backend_snippets: list[str],
    stage0_snippets: list[str],
) -> None:
    stage0_c = Compiler().compile_source(source, Path(INPUT_NAME)).c_source

    result = run_bootstrap_backend(bootstrap_backend_executable, tmp_path, source)
    assert result.returncode == 0, result.stderr
    summary, backend_c = split_backend_output(result.stdout)
    assert summary.startswith("B ")

    for snippet in backend_snippets:
        assert snippet in backend_c
    for snippet in stage0_snippets:
        assert snippet in stage0_c


def test_bootstrap_backend_summary_counts_nominal_declarations(
    bootstrap_backend_executable: Path,
    tmp_path: Path,
) -> None:
    source = (
        "enum State:\n"
        "    idle\n"
        "\n"
        "union Number:\n"
        "    integer: i32\n"
        "\n"
        "variant Maybe:\n"
        "    Some(value: i32)\n"
        "    End\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n"
    )
    Compiler().compile_source(source, Path(INPUT_NAME))
    result = run_bootstrap_backend(bootstrap_backend_executable, tmp_path, source)
    assert result.returncode == 0, result.stderr
    summary, _ = split_backend_output(result.stdout)
    values = parse_summary(summary)
    assert values[0] == 1  # functions
    assert values[3] == 1  # enums
    assert values[4] == 1  # unions
    assert values[5] == 1  # variants


def test_bootstrap_backend_matches_unknown_name_diagnostic(
    bootstrap_backend_executable: Path,
    tmp_path: Path,
) -> None:
    source = "def main() -> i32:\n    return missing\n"
    with pytest.raises(CompilationFailed) as error:
        Compiler().compile_source(source, Path(INPUT_NAME))

    result = run_bootstrap_backend(bootstrap_backend_executable, tmp_path, source)
    assert result.returncode != 0
    assert parse_error_record(result.stdout) == diagnostic_record(source, error.value.diagnostics[0])


def test_bootstrap_backend_uses_block_scoped_locals(
    bootstrap_backend_executable: Path,
    tmp_path: Path,
) -> None:
    source = (
        "def main() -> i32:\n"
        "    if true:\n"
        "        value: i32 = 1\n"
        "    return value\n"
    )
    with pytest.raises(CompilationFailed) as error:
        Compiler().compile_source(source, Path(INPUT_NAME))

    result = run_bootstrap_backend(bootstrap_backend_executable, tmp_path, source)
    assert result.returncode != 0
    assert parse_error_record(result.stdout) == diagnostic_record(source, error.value.diagnostics[0])


@pytest.mark.parametrize(
    ("source", "expected_code"),
    [
        (
            "def f(x: i32) -> i32:\n"
            "    return x\n"
            "\n"
            "def main() -> i32:\n"
            "    return f()\n",
            78,
        ),
        (
            "def f(x: i32) -> i32:\n"
            "    return x\n"
            "\n"
            "def main() -> i32:\n"
            "    return f(1, 2)\n",
            77,
        ),
        (
            "def main() -> i32:\n"
            "    value: i32 = true\n"
            "    return value\n",
            107,
        ),
        (
            "def main() -> i32:\n"
            "    value: i32 = \"x\"\n"
            "    return value\n",
            107,
        ),
        (
            "def main() -> i32:\n"
            "    return true\n",
            107,
        ),
        (
            "def main() -> i32:\n"
            "    xs: List[i32] = [true]\n"
            "    return 0\n",
            107,
        ),
        (
            "enum E:\n"
            "    a\n"
            "    b\n"
            "\n"
            "def main() -> i32:\n"
            "    x: E = E.a\n"
            "    match x:\n"
            "        case _:\n"
            "            return 1\n"
            "        case E.b:\n"
            "            return 2\n",
            121,
        ),
        (
            "static_assert(false, \"no\")\n"
            "\n"
            "def main() -> i32:\n"
            "    return 0\n",
            214,
        ),
        (
            "def main() -> i32:\n"
            "    return\n",
            42,
        ),
        (
            "def main() -> i32:\n"
            "    if \"x\":\n"
            "        return 1\n"
            "    return 0\n",
            24,
        ),
    ],
)
def test_bootstrap_backend_reports_procedural_checker_codes(
    bootstrap_backend_executable: Path,
    tmp_path: Path,
    source: str,
    expected_code: int,
) -> None:
    with pytest.raises(CompilationFailed) as error:
        Compiler().compile_source(source, Path(INPUT_NAME))
    assert int(error.value.diagnostics[0].code[1:]) == expected_code

    result = run_bootstrap_backend(bootstrap_backend_executable, tmp_path, source)
    assert result.returncode != 0
    assert parse_error_record(result.stdout)[1] == expected_code


@pytest.mark.parametrize(
    ("source", "expected_returncode"),
    [
        ("def main() -> i32:\n    return 42\n", 42),
        (
            "def main() -> i32:\n"
            "    total: i32 = 0\n"
            "    n: i32 = 3\n"
            "    while n > 0:\n"
            "        total = total + n\n"
            "        n = n - 1\n"
            "    return total\n",
            6,
        ),
    ],
)
def test_bootstrap_backend_emitted_c_runs(
    bootstrap_backend_executable: Path,
    tmp_path: Path,
    source: str,
    expected_returncode: int,
) -> None:
    result = run_bootstrap_backend(bootstrap_backend_executable, tmp_path, source)
    assert result.returncode == 0, result.stderr
    _, backend_c = split_backend_output(result.stdout)
    native = compile_and_run_c(tmp_path, backend_c)
    assert native.returncode == expected_returncode
