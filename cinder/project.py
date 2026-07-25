from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from cinder import ast
from cinder.diagnostics import CompilationFailed, Diagnostic, Severity
from cinder.lexer import lex
from cinder.parser import parse
from cinder.stdlib import builtin_modules


class ProjectError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    name: str
    root: Path
    source_root: Path
    entry: Path
    manifest: Path | None = None

    @property
    def source_roots(self) -> tuple[Path, ...]:
        return (self.source_root,)


@dataclass(frozen=True, slots=True)
class ParsedModule:
    name: str
    path: Path
    source: str
    syntax: ast.Module
    dependencies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProjectGraph:
    config: ProjectConfig
    modules: tuple[ParsedModule, ...]

    @classmethod
    def load(cls, path: Path | str) -> ProjectGraph:
        return load_project(path)

    @property
    def entry_module(self) -> str:
        return module_name_for_path(self.config.entry, self.config.source_root)

    @property
    def entry(self) -> ParsedModule:
        entry_path = self.config.entry.resolve()
        for module in self.modules:
            if module.path == entry_path:
                return module
        raise AssertionError("project graph does not contain its entry module")

    @property
    def by_name(self) -> dict[str, ParsedModule]:
        return {module.name: module for module in self.modules}


class ProjectLoader:
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config
        self._builtins = frozenset(builtin_modules(config.entry).keys())
        self._modules: dict[str, ParsedModule] = {}
        self._path_names: dict[Path, str] = {}
        self._visiting: list[str] = []
        self._ordered: list[ParsedModule] = []

    def load(self) -> ProjectGraph:
        entry_name = module_name_for_path(self.config.entry, self.config.source_root)
        self._visit(entry_name, self.config.entry.resolve(), importer=None)
        return ProjectGraph(self.config, tuple(self._ordered))

    def _visit(
        self,
        module_name: str,
        path: Path,
        *,
        importer: tuple[ParsedModule, ast.ImportDecl | ast.FromImportDecl] | None,
    ) -> None:
        if module_name in self._modules:
            return
        if module_name in self._visiting:
            if importer is None:
                raise ProjectError(f"cyclic module dependency involving {module_name!r}")
            source_module, declaration = importer
            cycle_start = self._visiting.index(module_name)
            cycle = " -> ".join([*self._visiting[cycle_start:], module_name])
            diagnostic = Diagnostic(
                severity=Severity.ERROR,
                message=f"cyclic module dependency: {cycle}",
                span=declaration.span,
                code="B003",
                note="Cinder modules must form an acyclic build graph",
            )
            raise CompilationFailed((diagnostic,), source_module.source)

        path = path.resolve()
        previous_name = self._path_names.get(path)
        if previous_name is not None and previous_name != module_name:
            raise ProjectError(
                f"source file {path} resolves as both {previous_name!r} and {module_name!r}"
            )
        if not path.is_file():
            raise ProjectError(f"source file does not exist: {path}")

        source = path.read_text(encoding="utf-8")
        syntax = parse(lex(source, path), source, path)
        dependencies: list[str] = []
        declarations: list[ast.ImportDecl | ast.FromImportDecl] = [
            *syntax.imports,
            *syntax.from_imports,
        ]
        parsed = ParsedModule(module_name, path, source, syntax, ())

        self._path_names[path] = module_name
        self._visiting.append(module_name)
        try:
            for declaration in declarations:
                dependency_name = declaration.module
                dependency_path = self._resolve_module(dependency_name, declaration, parsed)
                if dependency_path is None:
                    continue
                if dependency_name not in dependencies:
                    dependencies.append(dependency_name)
                self._visit(
                    dependency_name,
                    dependency_path,
                    importer=(parsed, declaration),
                )
        finally:
            self._visiting.pop()

        completed = ParsedModule(
            name=module_name,
            path=path,
            source=source,
            syntax=syntax,
            dependencies=tuple(dependencies),
        )
        self._modules[module_name] = completed
        self._ordered.append(completed)

    def _resolve_module(
        self,
        module_name: str,
        declaration: ast.ImportDecl | ast.FromImportDecl,
        importer: ParsedModule,
    ) -> Path | None:
        parts = module_name.split(".")
        base = self.config.source_root.joinpath(*parts)
        file_candidate = base.with_suffix(".ci")
        package_candidate = base / "__init__.ci"
        candidates = [
            candidate.resolve()
            for candidate in (file_candidate, package_candidate)
            if candidate.is_file()
        ]
        if len(candidates) > 1:
            diagnostic = Diagnostic(
                severity=Severity.ERROR,
                message=f"module {module_name!r} is ambiguous",
                span=declaration.span,
                code="B001",
                note=(
                    f"both {_display_path(file_candidate, self.config.root)} and "
                    f"{_display_path(package_candidate, self.config.root)} exist"
                ),
            )
            raise CompilationFailed((diagnostic,), importer.source)
        if candidates:
            return candidates[0]
        if module_name in self._builtins:
            return None

        diagnostic = Diagnostic(
            severity=Severity.ERROR,
            message=f"cannot resolve local module {module_name!r}",
            span=declaration.span,
            code="B002",
            note=(
                f"expected {_display_path(file_candidate, self.config.root)} or "
                f"{_display_path(package_candidate, self.config.root)}"
            ),
        )
        raise CompilationFailed((diagnostic,), importer.source)


def load_project(path: Path | str) -> ProjectGraph:
    return ProjectLoader(resolve_project(path)).load()


def resolve_project(path: Path | str) -> ProjectConfig:
    requested = Path(path).expanduser().resolve()
    if requested.is_dir():
        manifest = requested / "cinder.toml"
        if manifest.is_file():
            return _read_manifest(manifest)
        entry = _default_directory_entry(requested)
        return ProjectConfig(
            name=requested.name,
            root=requested,
            source_root=entry.parent,
            entry=entry,
        )

    if requested.name == "cinder.toml":
        if not requested.is_file():
            raise ProjectError(f"project manifest does not exist: {requested}")
        return _read_manifest(requested)

    if requested.suffix != ".ci":
        raise ProjectError("expected a .ci source file, project directory, or cinder.toml")
    if not requested.is_file():
        raise ProjectError(f"source file does not exist: {requested}")

    manifest = _find_manifest(requested.parent)
    if manifest is not None:
        configured = _read_manifest(manifest)
        try:
            requested.relative_to(configured.source_root)
        except ValueError as error:
            raise ProjectError(
                f"source file {requested} is outside project source root "
                f"{configured.source_root}"
            ) from error
        return ProjectConfig(
            name=configured.name,
            root=configured.root,
            source_root=configured.source_root,
            entry=requested,
            manifest=configured.manifest,
        )

    return ProjectConfig(
        name=requested.stem,
        root=requested.parent,
        source_root=requested.parent,
        entry=requested,
    )


def module_name_for_path(path: Path, source_root: Path) -> str:
    resolved = path.resolve()
    root = source_root.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as error:
        raise ProjectError(f"source file {resolved} is outside source root {root}") from error
    if relative.suffix != ".ci":
        raise ProjectError(f"Cinder source must use the .ci extension: {relative}")

    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if not parts:
        return "root"
    return ".".join(parts)


def generated_module_stem(module_name: str) -> str:
    cleaned = _sanitize_identifier(module_name.replace(".", "_"))
    return f"cinder_{cleaned or 'module'}"


def _read_manifest(manifest: Path) -> ProjectConfig:
    try:
        payload = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ProjectError(f"invalid project manifest {manifest}: {error}") from error

    project = payload.get("project")
    if not isinstance(project, dict):
        raise ProjectError(f"manifest {manifest} must contain a [project] table")
    allowed = {"name", "source-root", "entry"}
    unknown = sorted(set(project) - allowed)
    if unknown:
        raise ProjectError(
            f"unknown [project] key(s) in {manifest}: {', '.join(unknown)}"
        )

    root = manifest.parent.resolve()
    name_value = project.get("name", root.name)
    source_value = project.get("source-root", "src")
    entry_value = project.get("entry", "main.ci")
    if not isinstance(name_value, str) or not name_value.strip():
        raise ProjectError("[project].name must be a non-empty string")
    name = name_value.strip()
    if not _valid_project_name(name):
        raise ProjectError(
            "[project].name must use only ASCII letters, digits, '.', '-', and '_' "
            "and must begin with a letter or digit"
        )
    if not isinstance(source_value, str) or not source_value.strip():
        raise ProjectError("[project].source-root must be a non-empty string")
    if not isinstance(entry_value, str) or not entry_value.strip():
        raise ProjectError("[project].entry must be a non-empty string")

    source_root = (root / source_value).resolve()
    entry = (source_root / entry_value).resolve()
    try:
        source_root.relative_to(root)
        entry.relative_to(source_root)
    except ValueError as error:
        raise ProjectError(
            "project source-root and entry must remain inside the project root"
        ) from error
    if not source_root.is_dir():
        raise ProjectError(f"project source root does not exist: {source_root}")
    if not entry.is_file():
        raise ProjectError(f"project entry source does not exist: {entry}")

    return ProjectConfig(
        name=name,
        root=root,
        source_root=source_root,
        entry=entry,
        manifest=manifest.resolve(),
    )


def _find_manifest(start: Path) -> Path | None:
    current = start.resolve()
    for directory in (current, *current.parents):
        candidate = directory / "cinder.toml"
        if candidate.is_file():
            return candidate
    return None


def _default_directory_entry(root: Path) -> Path:
    candidates = (root / "main.ci", root / "src" / "main.ci")
    found = [candidate.resolve() for candidate in candidates if candidate.is_file()]
    if len(found) == 1:
        return found[0]
    if not found:
        raise ProjectError(
            f"directory {root} has no cinder.toml, main.ci, or src/main.ci"
        )
    raise ProjectError(
        f"directory {root} has both main.ci and src/main.ci; add cinder.toml"
    )


def _sanitize_identifier(value: str) -> str:
    characters = [
        character
        if character.isascii() and (character.isalnum() or character == "_")
        else "_"
        for character in value
    ]
    cleaned = "".join(characters)
    if cleaned and cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned


def _valid_project_name(value: str) -> bool:
    if not value or not value[0].isascii() or not value[0].isalnum():
        return False
    return all(
        character.isascii()
        and (character.isalnum() or character in {".", "-", "_"})
        for character in value
    )


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
