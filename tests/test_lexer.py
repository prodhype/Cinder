from __future__ import annotations

from pathlib import Path

import pytest

from cinder.diagnostics import CompilationFailed
from cinder.lexer import TokenKind, lex


def test_indentation_and_newlines() -> None:
    tokens = lex(
        "def main() -> i32:\n    if true:\n        return 0\n    return 1\n",
        Path("test.ci"),
    )
    kinds = [token.kind for token in tokens]
    assert kinds.count(TokenKind.INDENT) == 2
    assert kinds.count(TokenKind.DEDENT) == 2
    assert kinds[-1] is TokenKind.EOF


def test_multiline_call_suppresses_physical_newlines() -> None:
    tokens = lex(
        "def main() -> i32:\n"
        "    value = add(\n"
        "        1,\n"
        "        2,\n"
        "    )\n"
        "    return value\n",
        Path("test.ci"),
    )
    assert [token.kind for token in tokens].count(TokenKind.NEWLINE) == 3


def test_fstring_token() -> None:
    tokens = lex('def main() -> i32:\n    print(f"hello {name}")\n    return 0\n', Path("test.ci"))
    fstrings = [token for token in tokens if token.kind is TokenKind.FSTRING]
    assert len(fstrings) == 1
    assert fstrings[0].lexeme == 'f"hello {name}"'


def test_tabs_are_rejected() -> None:
    with pytest.raises(CompilationFailed, match="tabs are not allowed"):
        lex("def main() -> i32:\n\treturn 0\n", Path("test.ci"))
