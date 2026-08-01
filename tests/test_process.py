from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("process_test.ci")).c_source


def test_process_run_codegen_and_cleanup() -> None:
    generated = compile_source(
        "import process\n"
        "\n"
        "def main() -> i32:\n"
        '    command: List[String] = ["/bin/sh", "-c", "exit 7"]\n'
        "    result = process.run(command)\n"
        "    return result.exit_code\n"
    )

    assert "const char **" in generated
    assert "cinder_process_run_argv" in generated
    assert "cinder_string_cstr" in generated
    assert "CinderProcessResult__drop" in generated


def test_process_run_imported_function_codegen_and_cleanup() -> None:
    generated = compile_source(
        "from process import run\n"
        "from process import run as spawn\n"
        "\n"
        "def main() -> i32:\n"
        '    command: List[String] = ["/bin/sh", "-c", "exit 7"]\n'
        "    first = run(command)\n"
        "    second = spawn(command)\n"
        "    return first.exit_code + second.exit_code\n"
    )

    assert "const char **" in generated
    assert generated.count("cinder_process_run_argv(") == 2
    assert generated.count(".length, __cinder_process_argv") == 2
    assert "cinder_string_cstr" in generated
    assert "CinderProcessResult__drop" in generated


def test_process_result_name_is_available_without_process_import() -> None:
    generated = compile_source(
        "struct ProcessResult:\n"
        "    code: i32\n"
        "\n"
        "def main() -> i32:\n"
        "    result = ProcessResult(code=7)\n"
        "    return result.code\n"
    )

    assert "struct ProcessResult" in generated
    assert "ProcessResult result = { .code = 7 };" in generated


def test_process_result_is_exposed_through_process_module() -> None:
    generated = compile_source(
        "import process\n"
        "\n"
        "struct ProcessResult:\n"
        "    code: i32\n"
        "\n"
        "def main() -> i32:\n"
        '    command: List[String] = ["/bin/sh", "-c", "exit 0"]\n'
        "    runtime: process.ProcessResult = process.run(command)\n"
        "    local = ProcessResult(code=3)\n"
        "    return runtime.exit_code + local.code\n"
    )

    assert "struct ProcessResult" in generated
    assert "CinderProcessResult runtime =" in generated
    assert "ProcessResult local = { .code = 3 };" in generated


def test_process_run_rejects_invalid_calls() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "import process\n"
            "\n"
            "def main() -> i32:\n"
            "    process.run()\n"
            '    process.run(command=["cc"])\n'
            '    process.run("cc")\n'
            "    return 0\n"
        )

    rendered = str(captured.value)
    assert "process.run expects one positional argument" in rendered
    assert "process.run does not accept named arguments" in rendered
    assert "expected []const String, got String" in rendered


pytestmark_native = pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)


@pytestmark_native
@pytest.mark.skipif(not Path("/bin/sh").is_file(), reason="/bin/sh is required")
def test_process_run_captures_stdout_stderr_and_exit_status(tmp_path: Path) -> None:
    source = tmp_path / "process_capture.ci"
    source.write_text(
        "import process\n"
        "\n"
        "def main() -> i32:\n"
        '    command: List[String] = ["/bin/sh", "-c", "printf out; printf err >&2; exit 7"]\n'
        "    result = process.run(command)\n"
        "    if result.exit_code != 7:\n"
        "        return 1\n"
        '    if result.stdout != "out":\n'
        "        return 2\n"
        '    if result.stderr != "err":\n'
        "        return 3\n"
        "    return 0\n",
        encoding="utf-8",
    )
    executable = tmp_path / (
        "process_capture.exe" if shutil.which("cl") and not shutil.which("cc") else "process_capture"
    )

    artifact = Compiler().build(source, output=executable, build_dir=tmp_path / "build")
    result = subprocess.run([str(artifact.executable)], check=False)

    assert result.returncode == 0


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc")),
    reason="no Unix-style C compiler is available",
)
def test_process_run_observes_host_compiler_exit_status(tmp_path: Path) -> None:
    compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    assert compiler is not None
    source = tmp_path / "process_cc.ci"
    source.write_text(
        "import process\n"
        "\n"
        "def main() -> i32:\n"
        f"    command: List[String] = [{json.dumps(compiler)}, \"--version\"]\n"
        "    result = process.run(command)\n"
        "    if result.exit_code != 0:\n"
        "        return 1\n"
        "    if len(result.stdout) + len(result.stderr) == 0:\n"
        "        return 2\n"
        "    return 0\n",
        encoding="utf-8",
    )
    executable = tmp_path / "process_cc"

    artifact = Compiler().build(source, output=executable, build_dir=tmp_path / "build")
    result = subprocess.run([str(artifact.executable)], check=False)

    assert result.returncode == 0
