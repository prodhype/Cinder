from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from cinder import __version__
from cinder.compiler import Compiler, CompilerOptions
from cinder.diagnostics import CompilationFailed
from cinder.project import ProjectError
from cinder.toolchain import ToolchainError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cinder",
        description="Compile the Cinder systems language to readable portable C11.",
    )
    parser.add_argument("--version", action="version", version=f"Cinder {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser(
        "check",
        help="parse and type-check a source file or project",
    )
    check_parser.add_argument("source", type=Path)

    emit_parser = subparsers.add_parser(
        "emit-c",
        help="write one amalgamated C11 translation unit",
    )
    emit_parser.add_argument("source", type=Path)
    emit_parser.add_argument("-o", "--output", type=Path)

    emit_project_parser = subparsers.add_parser(
        "emit-project",
        help="write generated C11 translation units and headers",
    )
    emit_project_parser.add_argument("source", type=Path)
    emit_project_parser.add_argument("-o", "--output", type=Path, required=True)

    build_command = subparsers.add_parser(
        "build",
        help="compile a source file or project to a native executable",
    )
    _add_build_options(build_command)
    build_command.add_argument("source", type=Path)
    build_command.add_argument("-o", "--output", type=Path)
    build_command.add_argument("--build-dir", type=Path)

    run_parser = subparsers.add_parser(
        "run",
        help="compile and run a source file or project",
    )
    _add_build_options(run_parser)
    run_parser.add_argument("source", type=Path)
    run_parser.add_argument("program_args", nargs=argparse.REMAINDER)

    return parser


def _add_build_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cc", dest="compiler", help="C compiler command")
    parser.add_argument("--cflag", action="append", default=[], help="extra C compiler flag")
    parser.add_argument("--ldflag", action="append", default=[], help="extra linker flag")
    parser.add_argument("-I", dest="include_dirs", action="append", default=[], type=Path)
    parser.add_argument("--debug", action="store_true")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    options = CompilerOptions(
        compiler=getattr(arguments, "compiler", None),
        c_flags=tuple(getattr(arguments, "cflag", [])),
        linker_flags=tuple(getattr(arguments, "ldflag", [])),
        include_dirs=tuple(getattr(arguments, "include_dirs", [])),
        debug=getattr(arguments, "debug", False),
    )
    compiler = Compiler(options)

    try:
        if arguments.command == "check":
            compiler.check_file(arguments.source)
            print(f"ok: {arguments.source}")
            return 0

        if arguments.command == "emit-c":
            c_source = compiler.emit_c(arguments.source)
            if arguments.output is None:
                sys.stdout.write(c_source)
            else:
                arguments.output.parent.mkdir(parents=True, exist_ok=True)
                arguments.output.write_text(c_source, encoding="utf-8", newline="\n")
                print(arguments.output.resolve())
            return 0

        if arguments.command == "emit-project":
            compiler.emit_project(arguments.source, arguments.output)
            print(Path(arguments.output).expanduser().resolve())
            return 0

        if arguments.command == "build":
            artifact = compiler.build(
                arguments.source,
                output=arguments.output,
                build_dir=arguments.build_dir,
            )
            print(artifact.executable)
            return 0

        if arguments.command == "run":
            program_args = list(arguments.program_args)
            if program_args and program_args[0] == "--":
                program_args.pop(0)
            result = compiler.run(arguments.source, program_args)
            return result.returncode

        parser.error(f"unknown command {arguments.command!r}")
    except CompilationFailed as error:
        print(str(error), file=sys.stderr)
        return 1
    except ProjectError as error:
        print(f"project error: {error}", file=sys.stderr)
        return 2
    except ToolchainError as error:
        print(f"toolchain error: {error}", file=sys.stderr)
        return 2
    except FileNotFoundError as error:
        print(f"file error: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"system error: {error}", file=sys.stderr)
        return 2

    return 2
