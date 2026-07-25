from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable, NoReturn


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    NOTE = "note"


@dataclass(frozen=True, slots=True)
class Span:
    path: Path
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    @classmethod
    def point(cls, path: Path, line: int, column: int) -> Span:
        return cls(path, line, column, line, column + 1)

    @classmethod
    def synthetic(cls, path: Path) -> Span:
        return cls(path, 1, 1, 1, 1)

    def merge(self, other: Span) -> Span:
        if self.path != other.path:
            return self
        return Span(
            path=self.path,
            start_line=self.start_line,
            start_column=self.start_column,
            end_line=other.end_line,
            end_column=other.end_column,
        )


@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: Severity
    message: str
    span: Span
    code: str | None = None
    note: str | None = None


class DiagnosticBag:
    def __init__(self) -> None:
        self._items: list[Diagnostic] = []

    @property
    def items(self) -> tuple[Diagnostic, ...]:
        return tuple(self._items)

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self._items)

    def error(
        self,
        message: str,
        span: Span,
        *,
        code: str | None = None,
        note: str | None = None,
    ) -> None:
        self._items.append(Diagnostic(Severity.ERROR, message, span, code, note))

    def warning(
        self,
        message: str,
        span: Span,
        *,
        code: str | None = None,
        note: str | None = None,
    ) -> None:
        self._items.append(Diagnostic(Severity.WARNING, message, span, code, note))

    def extend(self, diagnostics: Iterable[Diagnostic]) -> None:
        self._items.extend(diagnostics)

    def raise_if_errors(self, source: str) -> None:
        if self.has_errors:
            raise CompilationFailed(self.items, source)


class CompilationFailed(Exception):
    def __init__(self, diagnostics: Iterable[Diagnostic], source: str) -> None:
        self.diagnostics = tuple(diagnostics)
        self.source = source
        super().__init__(render_diagnostics(self.diagnostics, source))


class InternalCompilerError(RuntimeError):
    pass


def render_diagnostic(diagnostic: Diagnostic, source: str) -> str:
    span = diagnostic.span
    label = diagnostic.severity.value
    if diagnostic.code:
        label = f"{label}[{diagnostic.code}]"

    header = (
        f"{span.path}:{span.start_line}:{span.start_column}: "
        f"{label}: {diagnostic.message}"
    )

    lines = source.splitlines()
    if not (1 <= span.start_line <= len(lines)):
        return header

    source_line = lines[span.start_line - 1]
    line_number = str(span.start_line)
    gutter = " " * len(line_number)

    start = max(1, span.start_column)
    if span.end_line == span.start_line:
        end = max(start + 1, span.end_column)
    else:
        end = max(start + 1, len(source_line) + 1)
    width = max(1, min(end - start, max(1, len(source_line) - start + 2)))
    caret = " " * (start - 1) + "^" * width

    rendered = [
        header,
        f" {gutter} |",
        f" {line_number} | {source_line}",
        f" {gutter} | {caret}",
    ]
    if diagnostic.note:
        rendered.append(f" {gutter} = note: {diagnostic.note}")
    return "\n".join(rendered)


def render_diagnostics(diagnostics: Iterable[Diagnostic], source: str) -> str:
    return "\n\n".join(render_diagnostic(item, source) for item in diagnostics)


def fail_internal(message: str) -> NoReturn:
    raise InternalCompilerError(message)
