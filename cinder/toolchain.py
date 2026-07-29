from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True, slots=True)
class ToolchainResult:
    command: tuple[str, ...]
    output: Path
    stdout: str
    stderr: str


class ToolchainError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        command: Sequence[str] = (),
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.command = tuple(command)
        self.stdout = stdout
        self.stderr = stderr
        details = [message]
        if command:
            details.append("command: " + " ".join(command))
        if stdout.strip():
            details.append(stdout.rstrip())
        if stderr.strip():
            details.append(stderr.rstrip())
        super().__init__("\n".join(details))


def discover_compiler(requested: str | None = None) -> str:
    candidates: list[str] = []
    if requested:
        candidates.append(requested)
    if os.environ.get("CC"):
        candidates.append(os.environ["CC"])
    if os.name == "nt":
        candidates.extend(("cl", "clang-cl", "clang", "gcc"))
    else:
        candidates.extend(("cc", "clang", "gcc"))

    for candidate in candidates:
        executable = candidate.split()[0]
        resolved = shutil.which(executable)
        if resolved is not None:
            return candidate
    raise ToolchainError(
        "no C compiler found; install GCC, Clang, or MSVC, or pass --cc"
    )


def compile_c11(
    *,
    compiler: str,
    generated_c: Path | Sequence[Path],
    runtime_c: Path,
    runtime_include: Path,
    output: Path,
    libraries: Sequence[str],
    c_flags: Sequence[str],
    linker_flags: Sequence[str],
    include_dirs: Sequence[Path],
    debug: bool,
    library_dirs: Sequence[Path] = (),
    link_files: Sequence[Path] = (),
) -> ToolchainResult:
    output.parent.mkdir(parents=True, exist_ok=True)
    sources = _source_paths(generated_c)
    compiler_name = Path(compiler.split()[0]).name.lower()
    is_msvc = compiler_name in {"cl", "cl.exe", "clang-cl", "clang-cl.exe"}

    if is_msvc:
        command = _msvc_command(
            compiler,
            sources,
            runtime_c,
            runtime_include,
            output,
            libraries,
            c_flags,
            linker_flags,
            include_dirs,
            debug,
            library_dirs,
            link_files,
        )
    else:
        command = _unix_command(
            compiler,
            sources,
            runtime_c,
            runtime_include,
            output,
            libraries,
            c_flags,
            linker_flags,
            include_dirs,
            debug,
            library_dirs,
            link_files,
        )

    process = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.returncode != 0:
        raise ToolchainError(
            f"C compiler exited with status {process.returncode}",
            command=command,
            stdout=process.stdout,
            stderr=process.stderr,
        )
    return ToolchainResult(tuple(command), output, process.stdout, process.stderr)


def _source_paths(value: Path | Sequence[Path]) -> tuple[Path, ...]:
    if isinstance(value, Path):
        return (value,)
    sources = tuple(value)
    if not sources:
        raise ToolchainError("no generated C translation units were provided")
    return sources


def _unix_command(
    compiler: str,
    generated_c: Sequence[Path],
    runtime_c: Path,
    runtime_include: Path,
    output: Path,
    libraries: Sequence[str],
    c_flags: Sequence[str],
    linker_flags: Sequence[str],
    include_dirs: Sequence[Path],
    debug: bool,
    library_dirs: Sequence[Path],
    link_files: Sequence[Path],
) -> list[str]:
    command = compiler.split()
    command.extend(
        [
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-g" if debug else "-O2",
            f"-I{runtime_include}",
        ]
    )
    command.extend(f"-I{path}" for path in _unique_paths(include_dirs))
    command.extend(c_flags)
    command.extend(str(path) for path in generated_c)
    command.extend((str(runtime_c), "-o", str(output)))
    command.extend(str(path) for path in _unique_paths(link_files))
    command.extend(f"-L{path}" for path in _unique_paths(library_dirs))
    command.extend(f"-l{library}" for library in dict.fromkeys(libraries))
    command.extend(linker_flags)
    return command


def _msvc_command(
    compiler: str,
    generated_c: Sequence[Path],
    runtime_c: Path,
    runtime_include: Path,
    output: Path,
    libraries: Sequence[str],
    c_flags: Sequence[str],
    linker_flags: Sequence[str],
    include_dirs: Sequence[Path],
    debug: bool,
    library_dirs: Sequence[Path],
    link_files: Sequence[Path],
) -> list[str]:
    command = compiler.split()
    command.extend(
        [
            "/nologo",
            "/std:c11",
            "/W4",
            "/Zi" if debug else "/O2",
            f"/I{runtime_include}",
        ]
    )
    command.extend(f"/I{path}" for path in _unique_paths(include_dirs))
    command.extend(c_flags)
    command.extend(str(path) for path in generated_c)
    command.extend((str(runtime_c), f"/Fe:{output}"))

    link_args: list[str] = []
    link_args.extend(str(path) for path in _unique_paths(link_files))
    link_args.extend(f"/LIBPATH:{path}" for path in _unique_paths(library_dirs))
    for library in dict.fromkeys(libraries):
        link_args.append(library if library.lower().endswith(".lib") else f"{library}.lib")
    link_args.extend(linker_flags)
    if link_args:
        command.append("/link")
        command.extend(link_args)
    return command


def _unique_paths(paths: Sequence[Path]) -> tuple[Path, ...]:
    return tuple(dict.fromkeys(path.resolve() for path in paths))
