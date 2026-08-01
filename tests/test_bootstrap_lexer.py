from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed, Diagnostic, Span
from cinder.lexer import Token, TokenKind, lex


ROOT = Path(__file__).resolve().parents[1]
INPUT_NAME = "bootstrap_lexer_input.ci"
TOKEN_IDS = {kind: index for index, kind in enumerate(TokenKind)}


pytestmark = pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)


@pytest.fixture(scope="module")
def bootstrap_lexer_executable(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build_root = tmp_path_factory.mktemp("bootstrap_lexer_build")
    executable = build_root / (
        "bootstrap_lexer.exe" if shutil.which("cl") and not shutil.which("cc") else "bootstrap_lexer"
    )
    artifact = Compiler().build(
        ROOT / "compiler",
        output=executable,
        build_dir=build_root / "build",
    )
    return artifact.executable


def run_bootstrap_lexer(executable: Path, tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / INPUT_NAME).write_text(source, encoding="utf-8")
    return subprocess.run(
        [str(executable)],
        check=False,
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )


def parse_records(stdout: str) -> list[tuple[str, int, int, int, int, int]]:
    records: list[tuple[str, int, int, int, int, int]] = []
    for line in stdout.splitlines():
        parts = line.split()
        assert len(parts) == 6, line
        tag, kind_or_code, start, length, row, column = parts
        records.append(
            (
                tag,
                int(kind_or_code),
                int(start),
                int(length),
                int(row),
                int(column),
            )
        )
    return records


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


def token_record(
    source: str,
    token: Token,
    *,
    synthetic_eof_span: bool = False,
) -> tuple[str, int, int, int, int, int]:
    if synthetic_eof_span:
        start = len(source.encode("utf-8"))
        end = start
    else:
        start = span_offset(source, token.span.start_line, token.span.start_column)
        end = span_offset(source, token.span.end_line, token.span.end_column)
    return (
        "T",
        TOKEN_IDS[token.kind],
        start,
        end - start,
        token.span.start_line,
        token.span.start_column,
    )


def token_records(source: str, tokens: list[Token]) -> list[tuple[str, int, int, int, int, int]]:
    synthetic_start = len(tokens) - 1
    while synthetic_start > 0 and tokens[synthetic_start - 1].kind is TokenKind.DEDENT:
        synthetic_start -= 1

    records: list[tuple[str, int, int, int, int, int]] = []
    for index, token in enumerate(tokens):
        records.append(
            token_record(
                source,
                token,
                synthetic_eof_span=index >= synthetic_start,
            )
        )
    return records


def diagnostic_record(source: str, diagnostic: Diagnostic) -> tuple[str, int, int, int, int, int]:
    assert diagnostic.code is not None
    start = span_offset(source, diagnostic.span.start_line, diagnostic.span.start_column)
    end = span_offset(source, diagnostic.span.end_line, diagnostic.span.end_column)
    return (
        "E",
        int(diagnostic.code[1:]) - 1,
        start,
        end - start,
        diagnostic.span.start_line,
        diagnostic.span.start_column,
    )


@pytest.mark.parametrize(
    "source",
    [
        "def main() -> i32:\n    if true:\n        return 0\n    return 1\n",
        "def main() -> i32:\n"
        "    value = add(\n"
        "        1,\n"
        "        2,\n"
        "    )\n"
        "    return value\n",
        'def main() -> i32:\n    print(f"hello {name}")\n    return 0\n',
        'def main() -> i32:\n    print(f"{values["key"] in {"key": 1}}")\n',
        "value: Option[i32] = None\n",
        "a <<= 1\nb >>= 2\nc = ...\nd = a != b and c == d\n",
        "a = 0x2a\nb = 0b1010\nc = 0o52\nd = 1_000.5e-2\ne = .5\n",
        "# comment\n\n// c++ style comment\nvalue = 'x'; text = \"héllo\"; next = 1\n",
    ],
)
def test_bootstrap_lexer_matches_stage0_tokens(
    bootstrap_lexer_executable: Path,
    tmp_path: Path,
    source: str,
) -> None:
    result = run_bootstrap_lexer(bootstrap_lexer_executable, tmp_path, source)
    assert result.returncode == 0, result.stderr
    actual = parse_records(result.stdout)
    expected = token_records(source, lex(source, Path(INPUT_NAME)))
    assert actual == expected


@pytest.mark.parametrize(
    "source",
    [
        "def main() -> i32:\n\treturn 0\n",
        ")\n",
        "(]\n",
        "(\n",
        'value = "oops\n',
        "value = 1e\n",
        "value = 0x\n",
        "if true:\n    pass\n  pass\n",
    ],
)
def test_bootstrap_lexer_matches_stage0_diagnostics(
    bootstrap_lexer_executable: Path,
    tmp_path: Path,
    source: str,
) -> None:
    result = run_bootstrap_lexer(bootstrap_lexer_executable, tmp_path, source)
    assert result.returncode != 0
    actual = parse_records(result.stdout)

    with pytest.raises(CompilationFailed) as error:
        lex(source, Path(INPUT_NAME))

    expected = [diagnostic_record(source, diagnostic) for diagnostic in error.value.diagnostics]
    assert actual == expected
