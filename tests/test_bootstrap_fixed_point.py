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


@pytest.fixture(scope="module")
def gen2_compiler(gen1_compiler: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    build_root = tmp_path_factory.mktemp("bootstrap_gen2_build")
    gen2 = build_root / (
        "cinder-gen2.exe" if shutil.which("cl") and not shutil.which("cc") else "cinder-gen2"
    )
    build_dir = build_root / "build"
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
    return gen2, build_dir


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


def compile_generated_project(
    generated_root: Path,
    output: Path,
) -> subprocess.CompletedProcess[str]:
    compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    assert compiler is not None
    generated_sources = sorted((generated_root / "cinder_gen").rglob("*.c"))
    assert generated_sources
    return subprocess.run(
        [
            compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-O2",
            "-I",
            str(ROOT / "cinder" / "runtime"),
            "-I",
            str(generated_root),
            "-I",
            str(ROOT / "compiler_selfhost" / "src"),
            *(str(path) for path in generated_sources),
            str(ROOT / "cinder" / "runtime" / "cinder_runtime.c"),
            "-o",
            str(output),
        ],
        check=False,
        text=True,
        capture_output=True,
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


def collect_normalized_tree(root: Path) -> dict[str, str]:
    generated_root = root / "cinder_gen"
    assert generated_root.is_dir()
    result: dict[str, str] = {}
    for path in sorted(generated_root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(generated_root).as_posix()
            result[relative] = normalize_generated_text(path.read_text(encoding="utf-8"))
    return result


def normalize_generated_text(text: str) -> str:
    return text.replace("\r\n", "\n").rstrip() + "\n"


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
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, build_dir = gen2_compiler

    assert gen2.is_file()
    assert (build_dir / "cinder_gen" / "compiler_main.c").is_file()
    assert (build_dir / "cinder_gen" / "checker.c").is_file()
    assert not (build_dir / "cinder_selfhost_gen2.c").exists()

    replay_source = build_dir / "cinder_selfhost_replay.c"
    assert replay_source.is_file()
    replay_text = replay_source.read_text(encoding="utf-8")
    assert "CINDER_SNAPSHOT_DIR" not in replay_text
    assert "cp -R" not in replay_text

    source = write_single_source(tmp_path)
    checked = run_gen1_without_python_on_path(gen2, tmp_path, "check", str(source))
    assert checked.returncode == 0, checked.stderr
    assert checked.stdout.strip() == f"ok: {source}"


def test_gen1_generated_compiler_project_builds_without_replay(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    _gen2, build_dir = gen2_compiler
    direct_gen2 = tmp_path / (
        "cinder-direct-gen2.exe" if shutil.which("cl") and not shutil.which("cc") else "cinder-direct-gen2"
    )

    compiled = compile_generated_project(build_dir, direct_gen2)

    assert compiled.returncode == 0, compiled.stderr
    assert direct_gen2.is_file()

    source = write_single_source(tmp_path)
    checked = run_gen1_without_python_on_path(direct_gen2, tmp_path, "check", str(source))
    assert checked.returncode == 0, checked.stderr
    assert checked.stdout.strip() == f"ok: {source}"


def test_gen1_and_gen2_emit_same_compiler_project_tree(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, gen1_generated = gen2_compiler
    gen2_generated = tmp_path / "gen2-generated"

    gen2_emitted = run_gen1(
        gen2,
        "emit-project",
        str(ROOT / "compiler_selfhost"),
        "-o",
        str(gen2_generated),
    )
    assert gen2_emitted.returncode == 0, gen2_emitted.stderr
    assert gen2_emitted.stdout.strip() == str(gen2_generated.resolve())

    assert collect_normalized_tree(gen2_generated) == collect_normalized_tree(gen1_generated)
