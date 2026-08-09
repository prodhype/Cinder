from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed, Diagnostic
from cinder.lexer import lex
from cinder.parser import parse


ROOT = Path(__file__).resolve().parents[1]
INPUT_NAME = "bootstrap_parser_input.ci"


pytestmark = pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)


@pytest.fixture(scope="module")
def bootstrap_parser_executable(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build_root = tmp_path_factory.mktemp("bootstrap_parser_build")
    executable = build_root / (
        "bootstrap_parser.exe" if shutil.which("cl") and not shutil.which("cc") else "bootstrap_parser"
    )
    artifact = Compiler().build(
        ROOT / "compiler_parser",
        output=executable,
        build_dir=build_root / "build",
    )
    return artifact.executable


def run_bootstrap_parser(executable: Path, tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / INPUT_NAME).write_text(source, encoding="utf-8")
    return subprocess.run(
        [str(executable)],
        check=False,
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )


def span_offset(source: str, line: int, column: int) -> int:
    if line < 1:
        return 0

    lines = source.splitlines(keepends=True)
    if line > len(lines):
        return len(source.encode("utf-8"))

    offset = 0
    for previous in lines[: line - 1]:
        offset += len(previous.encode("utf-8"))

    current = lines[line - 1]
    content = current.rstrip("\r\n")
    character_index = max(0, min(column - 1, len(content)))
    return offset + len(content[:character_index].encode("utf-8"))


def diagnostic_record(source: str, diagnostic: Diagnostic) -> tuple[str, int, int, int, int, int]:
    assert diagnostic.code is not None
    code = int(diagnostic.code[1:])
    if (
        code in {27, 46}
        and diagnostic.span.start_column == 1
        and source.endswith(("\n", "\r"))
    ):
        start = len(source.encode("utf-8"))
        end = start
    else:
        start = span_offset(source, diagnostic.span.start_line, diagnostic.span.start_column)
        end = span_offset(source, diagnostic.span.end_line, diagnostic.span.end_column)
    return (
        "E",
        code,
        start,
        end - start,
        diagnostic.span.start_line,
        diagnostic.span.start_column,
    )


def parse_error_records(stdout: str) -> list[tuple[str, int, int, int, int, int]]:
    records: list[tuple[str, int, int, int, int, int]] = []
    for line in stdout.splitlines():
        parts = line.split()
        assert len(parts) == 6, line
        tag, code, start, length, row, column = parts
        assert tag == "E", line
        records.append((tag, int(code), int(start), int(length), int(row), int(column)))
    return records


VALID_SOURCES = [
    "import model\n"
    "from model import Token as ModelToken\n"
    "\n"
    "def main() -> i32:\n"
    "    value: i32 = 41\n"
    "    if value > 0:\n"
    "        return value + 1\n"
    "    return 0\n",
    "struct Pair[T]:\n"
    "    first: T\n"
    "    second: T\n"
    "\n"
    "enum State:\n"
    "    idle\n"
    "    running = 2\n"
    "\n"
    "variant Maybe:\n"
    "    Some(value: i32)\n"
    "    End\n",
    "abstract class Shape:\n"
    "    @abstractmethod\n"
    "    def area(self) -> f64:\n"
    "        pass\n"
    "\n"
    "class Circle(Shape):\n"
    "    radius: f64\n"
    "\n"
    "    def area(self) -> f64:\n"
    "        return self.radius * self.radius\n",
    "def describe(value: Option[i32]) -> i32:\n"
    "    match value:\n"
    "        case Some(score) if score > 0:\n"
    "            return score\n"
    "        case None:\n"
    "            return 0\n",
    "def main() -> i32:\n"
    "    values = [1, 2, 3]\n"
    "    names = {\"Ada\": 10, \"Grace\": 20}\n"
    "    primes = {2, 3, 5}\n"
    "    print(f\"count={len(values)}\")\n"
    "    return cast[i32](len(names)) + alloc[i32](4)?\n",
    "extern import \"stdio.h\"\n"
    "\n"
    "extern \"C\":\n"
    "    type FILE\n"
    "    def printf(format: const char*, ...) -> c_int\n",
    "from std.atomic import Atomic\n"
    "\n"
    "counter: Atomic[u64] = 0\n"
    "\n"
    "def increment() -> u64:\n"
    "    return counter.fetch_add(1)\n",
]


@pytest.mark.parametrize("source", VALID_SOURCES)
def test_bootstrap_parser_accepts_stage0_valid_sources(
    bootstrap_parser_executable: Path,
    tmp_path: Path,
    source: str,
) -> None:
    parse(lex(source, Path(INPUT_NAME)), source, Path(INPUT_NAME))

    result = run_bootstrap_parser(bootstrap_parser_executable, tmp_path, source)
    assert result.returncode == 0, result.stderr
    records = result.stdout.splitlines()
    assert records
    assert records[0].startswith("N 0 ")


@pytest.mark.parametrize(
    "source",
    [
        "import \n",
        "from model import \n",
        "def main() -> i32\n",
        "def main() -> i32:\n",
        "struct Box:\n",
        "enum E:\n    value = \n",
        "def main() -> i32:\n    if true\n        pass\n",
    ],
)
def test_bootstrap_parser_matches_stage0_diagnostics(
    bootstrap_parser_executable: Path,
    tmp_path: Path,
    source: str,
) -> None:
    with pytest.raises(CompilationFailed) as error:
        parse(lex(source, Path(INPUT_NAME)), source, Path(INPUT_NAME))

    result = run_bootstrap_parser(bootstrap_parser_executable, tmp_path, source)
    assert result.returncode != 0
    actual = parse_error_records(result.stdout)
    expected = [diagnostic_record(source, diagnostic) for diagnostic in error.value.diagnostics]
    assert actual == expected
