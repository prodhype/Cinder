from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler


ROOT = Path(__file__).resolve().parents[1]


pytestmark = pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)


@pytest.fixture(scope="module")
def gen1_compiler(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build_root = tmp_path_factory.mktemp("bootstrap_gen1_build")
    executable = build_root / (
        "cinder-gen1.exe" if shutil.which("cl") and not shutil.which("cc") else "cinder-gen1"
    )
    artifact = Compiler().build(
        ROOT / "compiler_selfhost",
        output=executable,
        build_dir=build_root / "build",
    )
    return artifact.executable


def run_gen1(gen1: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(gen1), *arguments],
        check=False,
        text=True,
        capture_output=True,
    )


def run_gen1_without_python_on_path(
    gen1: Path,
    tmp_path: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    empty_path = tmp_path / "empty-bin"
    empty_path.mkdir()
    env = {**os.environ, "PATH": str(empty_path)}
    return subprocess.run(
        [str(gen1), *arguments],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )


def write_single_source(tmp_path: Path) -> Path:
    source = tmp_path / "single.ci"
    source.write_text("def main() -> i32:\n    return 42\n", encoding="utf-8")
    return source


def write_project(tmp_path: Path) -> Path:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"selfhost_cli_demo\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "maths.ci").write_text(
        "def answer() -> i32:\n    return 42\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import maths\n"
        "\n"
        "def main() -> i32:\n"
        "    return maths.answer()\n",
        encoding="utf-8",
    )
    return tmp_path / "cinder.toml"


def test_gen1_check_and_emit_c(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = write_single_source(tmp_path)

    checked = run_gen1(gen1_compiler, "check", str(source))
    assert checked.returncode == 0, checked.stderr
    assert checked.stdout.strip() == f"ok: {source}"

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    assert "int main(void)" in emitted.stdout
    assert "return 42;" in emitted.stdout


def test_gen1_check_is_native_and_does_not_require_python_on_path(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = write_single_source(tmp_path)

    checked = run_gen1_without_python_on_path(
        gen1_compiler,
        tmp_path,
        "check",
        str(source),
    )

    assert checked.returncode == 0, checked.stderr
    assert checked.stdout.strip() == f"ok: {source}"


def test_gen1_emit_project_build_and_run(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    manifest = write_project(tmp_path)
    generated = tmp_path / "generated"
    executable = tmp_path / (
        "selfhost_cli_demo.exe" if shutil.which("cl") and not shutil.which("cc") else "selfhost_cli_demo"
    )

    emitted = run_gen1(gen1_compiler, "emit-project", str(manifest), "-o", str(generated))
    assert emitted.returncode == 0, emitted.stderr
    assert emitted.stdout.strip() == str(generated.resolve())
    assert (generated / "cinder_gen" / "main.c").is_file()
    assert (generated / "cinder_gen" / "main.cinder.h").is_file()
    assert (generated / "cinder_gen" / "maths.c").is_file()
    assert (generated / "cinder_gen" / "maths.cinder.h").is_file()

    built = run_gen1(
        gen1_compiler,
        "build",
        str(manifest),
        "-o",
        str(executable),
        "--build-dir",
        str(tmp_path / "build"),
    )
    assert built.returncode == 0, built.stderr
    assert built.stdout.strip() == str(executable.resolve())
    assert subprocess.run([str(executable)], check=False).returncode == 42

    ran = run_gen1(gen1_compiler, "run", str(manifest))
    assert ran.returncode == 42


def test_gen1_builds_compiler_sources_into_gen2(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    gen2 = tmp_path / ("cinder-gen2.exe" if shutil.which("cl") and not shutil.which("cc") else "cinder-gen2")
    build_dir = tmp_path / "gen2-build"

    built = run_gen1(
        gen1_compiler,
        "build",
        str(ROOT / "compiler_selfhost"),
        "-o",
        str(gen2),
        "--build-dir",
        str(build_dir),
    )

    assert built.returncode == 0, built.stderr
    assert built.stdout.strip() == str(gen2.resolve())
    assert gen2.is_file()
    assert (build_dir / "cinder_gen" / "compiler_main.c").is_file()
    assert (build_dir / "cinder_gen" / "checker.c").is_file()

    source = write_single_source(tmp_path)
    checked = run_gen1_without_python_on_path(gen2, tmp_path, "check", str(source))
    assert checked.returncode == 0, checked.stderr
    assert checked.stdout.strip() == f"ok: {source}"
