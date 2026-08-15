from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from cinder.diagnostics import CompilationFailed, DiagnosticBag, Span


class TokenKind(StrEnum):
    EOF = "EOF"
    NEWLINE = "NEWLINE"
    INDENT = "INDENT"
    DEDENT = "DEDENT"

    NAME = "NAME"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    STRING = "STRING"
    FSTRING = "FSTRING"
    CHAR = "CHAR"

    IMPORT = "import"
    FROM = "from"
    AS = "as"
    EXTERN = "extern"
    DEF = "def"
    STRUCT = "struct"
    ENUM = "enum"
    UNION = "union"
    VARIANT = "variant"
    CLASS = "class"
    ABSTRACT = "abstract"
    DYN = "dyn"
    COMPTIME = "comptime"
    IF = "if"
    ELIF = "elif"
    ELSE = "else"
    WHILE = "while"
    FOR = "for"
    MATCH = "match"
    CASE = "case"
    IN = "in"
    RETURN = "return"
    BREAK = "break"
    CONTINUE = "continue"
    PASS = "pass"
    CONST = "const"
    TRUE = "true"
    FALSE = "false"
    NULL = "null"
    NONE = "None"
    AND = "and"
    OR = "or"
    NOT = "not"
    UNSAFE = "unsafe"
    DEFER = "defer"
    WITH = "with"
    PRIVATE = "private"
    LOCK = "lock"

    LEFT_PAREN = "("
    RIGHT_PAREN = ")"
    LEFT_BRACKET = "["
    RIGHT_BRACKET = "]"
    LEFT_BRACE = "{"
    RIGHT_BRACE = "}"
    COLON = ":"
    COMMA = ","
    DOT = "."
    SEMICOLON = ";"
    AT = "@"
    ARROW = "->"
    ELLIPSIS = "..."
    QUESTION = "?"

    ASSIGN = "="
    PLUS = "+"
    MINUS = "-"
    STAR = "*"
    SLASH = "/"
    PERCENT = "%"
    AMPERSAND = "&"
    PIPE = "|"
    CARET = "^"
    TILDE = "~"
    BANG = "!"
    EQUAL = "=="
    NOT_EQUAL = "!="
    LESS = "<"
    LESS_EQUAL = "<="
    GREATER = ">"
    GREATER_EQUAL = ">="
    SHIFT_LEFT = "<<"
    SHIFT_RIGHT = ">>"
    PLUS_ASSIGN = "+="
    MINUS_ASSIGN = "-="
    STAR_ASSIGN = "*="
    SLASH_ASSIGN = "/="
    PERCENT_ASSIGN = "%="
    AMPERSAND_ASSIGN = "&="
    PIPE_ASSIGN = "|="
    CARET_ASSIGN = "^="
    SHIFT_LEFT_ASSIGN = "<<="
    SHIFT_RIGHT_ASSIGN = ">>="


_KEYWORDS: dict[str, TokenKind] = {
    kind.value: kind
    for kind in (
        TokenKind.IMPORT,
        TokenKind.FROM,
        TokenKind.AS,
        TokenKind.EXTERN,
        TokenKind.DEF,
        TokenKind.STRUCT,
        TokenKind.ENUM,
        TokenKind.UNION,
        TokenKind.VARIANT,
        TokenKind.CLASS,
        TokenKind.ABSTRACT,
        TokenKind.DYN,
        TokenKind.COMPTIME,
        TokenKind.IF,
        TokenKind.ELIF,
        TokenKind.ELSE,
        TokenKind.WHILE,
        TokenKind.FOR,
        TokenKind.MATCH,
        TokenKind.CASE,
        TokenKind.IN,
        TokenKind.RETURN,
        TokenKind.BREAK,
        TokenKind.CONTINUE,
        TokenKind.PASS,
        TokenKind.CONST,
        TokenKind.TRUE,
        TokenKind.FALSE,
        TokenKind.NULL,
        TokenKind.NONE,
        TokenKind.AND,
        TokenKind.OR,
        TokenKind.NOT,
        TokenKind.UNSAFE,
        TokenKind.DEFER,
        TokenKind.WITH,
        TokenKind.PRIVATE,
        TokenKind.LOCK,
    )
}


_MULTI_CHAR_TOKENS: tuple[tuple[str, TokenKind], ...] = (
    ("<<=", TokenKind.SHIFT_LEFT_ASSIGN),
    (">>=", TokenKind.SHIFT_RIGHT_ASSIGN),
    ("...", TokenKind.ELLIPSIS),
    ("->", TokenKind.ARROW),
    ("==", TokenKind.EQUAL),
    ("!=", TokenKind.NOT_EQUAL),
    ("<=", TokenKind.LESS_EQUAL),
    (">=", TokenKind.GREATER_EQUAL),
    ("<<", TokenKind.SHIFT_LEFT),
    (">>", TokenKind.SHIFT_RIGHT),
    ("+=", TokenKind.PLUS_ASSIGN),
    ("-=", TokenKind.MINUS_ASSIGN),
    ("*=", TokenKind.STAR_ASSIGN),
    ("/=", TokenKind.SLASH_ASSIGN),
    ("%=", TokenKind.PERCENT_ASSIGN),
    ("&=", TokenKind.AMPERSAND_ASSIGN),
    ("|=", TokenKind.PIPE_ASSIGN),
    ("^=", TokenKind.CARET_ASSIGN),
)


_SINGLE_CHAR_TOKENS: dict[str, TokenKind] = {
    "(": TokenKind.LEFT_PAREN,
    ")": TokenKind.RIGHT_PAREN,
    "[": TokenKind.LEFT_BRACKET,
    "]": TokenKind.RIGHT_BRACKET,
    "{": TokenKind.LEFT_BRACE,
    "}": TokenKind.RIGHT_BRACE,
    ":": TokenKind.COLON,
    ",": TokenKind.COMMA,
    ".": TokenKind.DOT,
    ";": TokenKind.SEMICOLON,
    "@": TokenKind.AT,
    "?": TokenKind.QUESTION,
    "=": TokenKind.ASSIGN,
    "+": TokenKind.PLUS,
    "-": TokenKind.MINUS,
    "*": TokenKind.STAR,
    "/": TokenKind.SLASH,
    "%": TokenKind.PERCENT,
    "&": TokenKind.AMPERSAND,
    "|": TokenKind.PIPE,
    "^": TokenKind.CARET,
    "~": TokenKind.TILDE,
    "!": TokenKind.BANG,
    "<": TokenKind.LESS,
    ">": TokenKind.GREATER,
}


_OPENING = {
    TokenKind.LEFT_PAREN: TokenKind.RIGHT_PAREN,
    TokenKind.LEFT_BRACKET: TokenKind.RIGHT_BRACKET,
    TokenKind.LEFT_BRACE: TokenKind.RIGHT_BRACE,
}
_CLOSING = {value: key for key, value in _OPENING.items()}


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    lexeme: str
    span: Span
    value: int | float | str | None = None


class Lexer:
    def __init__(self, source: str, path: Path) -> None:
        self.source = source
        self.path = path
        self.diagnostics = DiagnosticBag()
        self.tokens: list[Token] = []
        self._indent_stack: list[int] = [0]
        self._brackets: list[tuple[TokenKind, Span]] = []

    def tokenize(self) -> list[Token]:
        lines = self.source.splitlines(keepends=True)
        if not lines and self.source == "":
            lines = []

        explicit_continuation = False
        for line_number, physical_line in enumerate(lines, start=1):
            line = physical_line.rstrip("\r\n")
            logical_start = not self._brackets and not explicit_continuation

            if logical_start:
                indent_end = 0
                while indent_end < len(line) and line[indent_end] in " \t":
                    indent_end += 1
                indentation = line[:indent_end]
                content = line[indent_end:]

                if "\t" in indentation:
                    self.diagnostics.error(
                        "tabs are not allowed for indentation",
                        Span(self.path, line_number, 1, line_number, indent_end + 1),
                        code="L001",
                        note="use spaces consistently",
                    )

                if content.strip() == "" or content.lstrip().startswith(("#", "//")):
                    explicit_continuation = False
                    continue

                self._emit_indentation(len(indentation), line_number)
                start_column = indent_end + 1
            else:
                start_column = 1

            explicit_continuation = self._scan_line(line, line_number, start_column)
            if not self._brackets and not explicit_continuation:
                end_column = max(1, len(line) + 1)
                self.tokens.append(
                    Token(
                        TokenKind.NEWLINE,
                        "\n",
                        Span(self.path, line_number, end_column, line_number, end_column),
                    )
                )

        if explicit_continuation:
            line = max(1, len(lines))
            self.diagnostics.error(
                "line continuation at end of file",
                Span.point(self.path, line, 1),
                code="L002",
            )

        if self._brackets:
            _, opening_span = self._brackets[-1]
            self.diagnostics.error(
                "unclosed bracket",
                opening_span,
                code="L003",
            )

        eof_line = max(1, len(lines) + (0 if self.source.endswith(("\n", "\r")) else 1))
        while len(self._indent_stack) > 1:
            self._indent_stack.pop()
            self.tokens.append(
                Token(
                    TokenKind.DEDENT,
                    "",
                    Span.point(self.path, eof_line, 1),
                )
            )
        self.tokens.append(Token(TokenKind.EOF, "", Span.point(self.path, eof_line, 1)))

        if self.diagnostics.has_errors:
            raise CompilationFailed(self.diagnostics.items, self.source)
        return self.tokens

    def _emit_indentation(self, indentation: int, line_number: int) -> None:
        current = self._indent_stack[-1]
        span = Span(self.path, line_number, 1, line_number, indentation + 1)
        if indentation > current:
            self._indent_stack.append(indentation)
            self.tokens.append(Token(TokenKind.INDENT, "", span))
            return

        if indentation == current:
            return

        while len(self._indent_stack) > 1 and indentation < self._indent_stack[-1]:
            self._indent_stack.pop()
            self.tokens.append(Token(TokenKind.DEDENT, "", span))

        if indentation != self._indent_stack[-1]:
            self.diagnostics.error(
                "indentation does not match any outer block",
                span,
                code="L004",
            )

    def _scan_line(self, line: str, line_number: int, start_column: int) -> bool:
        index = start_column - 1
        explicit_continuation = False

        while index < len(line):
            character = line[index]
            column = index + 1

            if character in " \t":
                index += 1
                continue

            if character == "#" or line.startswith("//", index):
                break

            if character == "\\" and line[index + 1 :].strip() == "":
                explicit_continuation = True
                break

            if character in ('"', "'"):
                index = self._scan_string(line, line_number, index)
                continue

            if (
                character in "fF"
                and index + 1 < len(line)
                and line[index + 1] in ('"', "'")
            ):
                index = self._scan_string(line, line_number, index, prefix_length=1)
                continue

            if _is_identifier_start(character):
                end = index + 1
                while end < len(line) and _is_identifier_continue(line[end]):
                    end += 1
                lexeme = line[index:end]
                kind = _KEYWORDS.get(lexeme, TokenKind.NAME)
                self.tokens.append(
                    Token(
                        kind,
                        lexeme,
                        Span(self.path, line_number, column, line_number, end + 1),
                        lexeme if kind is TokenKind.NAME else None,
                    )
                )
                index = end
                continue

            if character.isdigit() or (
                character == "."
                and index + 1 < len(line)
                and line[index + 1].isdigit()
            ):
                index = self._scan_number(line, line_number, index)
                continue

            matched = False
            for text, kind in _MULTI_CHAR_TOKENS:
                if line.startswith(text, index):
                    span = Span(
                        self.path,
                        line_number,
                        column,
                        line_number,
                        column + len(text),
                    )
                    token = Token(kind, text, span)
                    self.tokens.append(token)
                    self._track_bracket(token)
                    index += len(text)
                    matched = True
                    break
            if matched:
                continue

            kind = _SINGLE_CHAR_TOKENS.get(character)
            if kind is not None:
                span = Span(
                    self.path,
                    line_number,
                    column,
                    line_number,
                    column + 1,
                )
                token = Token(kind, character, span)
                self.tokens.append(token)
                self._track_bracket(token)
                index += 1
                continue

            self.diagnostics.error(
                f"unexpected character {character!r}",
                Span(self.path, line_number, column, line_number, column + 1),
                code="L005",
            )
            index += 1

        return explicit_continuation

    def _scan_string(
        self,
        line: str,
        line_number: int,
        start: int,
        *,
        prefix_length: int = 0,
    ) -> int:
        if prefix_length:
            return self._scan_fstring(line, line_number, start, prefix_length)

        quote = line[start + prefix_length]
        index = start + prefix_length + 1
        escaped = False
        decoded_length = 0
        while index < len(line):
            character = line[index]
            if escaped:
                escaped = False
                decoded_length += 1
                index += 1
                continue
            if character == "\\":
                escaped = True
                index += 1
                continue
            if character == quote:
                end = index + 1
                lexeme = line[start:end]
                kind = TokenKind.CHAR if quote == "'" and decoded_length == 1 else TokenKind.STRING
                self.tokens.append(
                    Token(
                        kind,
                        lexeme,
                        Span(self.path, line_number, start + 1, line_number, end + 1),
                        lexeme,
                    )
                )
                return end
            decoded_length += 1
            index += 1

        self.diagnostics.error(
            "unterminated string literal",
            Span(self.path, line_number, start + 1, line_number, len(line) + 1),
            code="L006",
        )
        return len(line)

    def _scan_fstring(
        self,
        line: str,
        line_number: int,
        start: int,
        prefix_length: int,
    ) -> int:
        quote = line[start + prefix_length]
        index = start + prefix_length + 1
        replacement_depth = 0
        escaped = False

        while index < len(line):
            character = line[index]
            if replacement_depth == 0:
                if escaped:
                    escaped = False
                    index += 1
                    continue
                if character == "\\":
                    escaped = True
                    index += 1
                    continue
                if character == quote:
                    end = index + 1
                    lexeme = line[start:end]
                    self.tokens.append(
                        Token(
                            TokenKind.FSTRING,
                            lexeme,
                            Span(
                                self.path,
                                line_number,
                                start + 1,
                                line_number,
                                end + 1,
                            ),
                            lexeme,
                        )
                    )
                    return end
                if character == "{" and not line.startswith("{{", index):
                    replacement_depth = 1
                    index += 1
                    continue
                if line.startswith(("{{", "}}"), index):
                    index += 2
                    continue
                index += 1
                continue

            if character in ('"', "'"):
                index = _skip_quoted_text(line, index)
                continue
            if character == "{":
                replacement_depth += 1
            elif character == "}":
                replacement_depth -= 1
            index += 1

        self.diagnostics.error(
            "unterminated f-string literal",
            Span(self.path, line_number, start + 1, line_number, len(line) + 1),
            code="L006",
        )
        return len(line)

    def _scan_number(self, line: str, line_number: int, start: int) -> int:
        index = start
        is_float = False

        if line.startswith(("0x", "0X"), index):
            index += 2
            while index < len(line) and (line[index].isdigit() or line[index].lower() in "abcdef_"):
                index += 1
            lexeme = line[start:index]
            self._emit_integer(lexeme, line_number, start, index, 16)
            return index

        if line.startswith(("0b", "0B"), index):
            index += 2
            while index < len(line) and line[index] in "01_":
                index += 1
            lexeme = line[start:index]
            self._emit_integer(lexeme, line_number, start, index, 2)
            return index

        if line.startswith(("0o", "0O"), index):
            index += 2
            while index < len(line) and line[index] in "01234567_":
                index += 1
            lexeme = line[start:index]
            self._emit_integer(lexeme, line_number, start, index, 8)
            return index

        while index < len(line) and (line[index].isdigit() or line[index] == "_"):
            index += 1

        if index < len(line) and line[index] == ".":
            is_float = True
            index += 1
            while index < len(line) and (line[index].isdigit() or line[index] == "_"):
                index += 1

        if index < len(line) and line[index] in "eE":
            is_float = True
            index += 1
            if index < len(line) and line[index] in "+-":
                index += 1
            exponent_start = index
            while index < len(line) and (line[index].isdigit() or line[index] == "_"):
                index += 1
            if exponent_start == index:
                self.diagnostics.error(
                    "expected exponent digits",
                    Span(self.path, line_number, start + 1, line_number, index + 1),
                    code="L007",
                )

        lexeme = line[start:index]
        clean = lexeme.replace("_", "")
        span = Span(self.path, line_number, start + 1, line_number, index + 1)
        try:
            if is_float:
                self.tokens.append(Token(TokenKind.FLOAT, lexeme, span, float(clean)))
            else:
                self.tokens.append(Token(TokenKind.INTEGER, lexeme, span, int(clean, 10)))
        except ValueError:
            self.diagnostics.error("invalid numeric literal", span, code="L008")
        return index

    def _emit_integer(
        self,
        lexeme: str,
        line_number: int,
        start: int,
        end: int,
        base: int,
    ) -> None:
        span = Span(self.path, line_number, start + 1, line_number, end + 1)
        try:
            value = int(lexeme.replace("_", ""), base)
            self.tokens.append(Token(TokenKind.INTEGER, lexeme, span, value))
        except ValueError:
            self.diagnostics.error("invalid integer literal", span, code="L009")

    def _track_bracket(self, token: Token) -> None:
        if token.kind in _OPENING:
            self._brackets.append((token.kind, token.span))
            return
        if token.kind not in _CLOSING:
            return
        if not self._brackets:
            self.diagnostics.error(
                f"unmatched closing bracket {token.lexeme!r}",
                token.span,
                code="L010",
            )
            return
        opening_kind, opening_span = self._brackets[-1]
        if _OPENING[opening_kind] is not token.kind:
            self.diagnostics.error(
                f"mismatched closing bracket {token.lexeme!r}",
                token.span,
                code="L011",
                note=f"opening bracket is at {opening_span.start_line}:{opening_span.start_column}",
            )
            self._brackets.pop()
            return
        self._brackets.pop()


def _skip_quoted_text(text: str, start: int) -> int:
    quote = text[start]
    index = start + 1
    escaped = False
    while index < len(text):
        character = text[index]
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == quote:
            return index + 1
        index += 1
    return index


def _is_identifier_start(character: str) -> bool:
    return character == "_" or "A" <= character <= "Z" or "a" <= character <= "z"


def _is_identifier_continue(character: str) -> bool:
    return _is_identifier_start(character) or character.isdigit()


def lex(source: str, path: Path) -> list[Token]:
    return Lexer(source, path).tokenize()
