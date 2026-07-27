from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("option_test.ci")).c_source


def test_option_construction_access_and_match_codegen() -> None:
    generated = compile_source(
        "def choose(flag: bool) -> Option[i32]:\n"
        "    if flag:\n"
        "        return Some(7)\n"
        "    return None\n"
        "\n"
        "def main() -> i32:\n"
        "    inferred = Some(3)\n"
        "    selected = choose(true)\n"
        "    if inferred.is_none or not selected.is_some:\n"
        "        return 1\n"
        "    match selected:\n"
        "        case Some(value):\n"
        "            return value - 7\n"
        "        case None:\n"
        "            return 2\n"
    )

    assert "typedef struct CinderOption_i32 CinderOption_i32;" in generated
    assert "CinderOption_i32_Tag_Some" in generated
    assert 'cinder_panic("attempted to read None.value")' in generated
    assert ".data.value = 7" in generated


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "def main() -> i32:\n"
            "    value = None\n"
            "    return 0\n",
            "None requires a contextual Option[T] type",
        ),
        (
            "def main() -> i32:\n"
            "    value: Option[i32, i64] = None\n"
            "    return 0\n",
            "Option requires exactly one type argument",
        ),
        (
            "def main() -> i32:\n"
            "    value = Some(1)\n"
            "    match value:\n"
            "        case Some(number):\n"
            "            return number\n",
            "non-exhaustive match; missing None",
        ),
        (
            "def make() -> Option[i32]:\n"
            "    return Some(1)\n"
            "\n"
            "def main() -> i32:\n"
            "    return make().value\n",
            "Option.value requires an addressable Option",
        ),
        (
            "def make() -> Option[i32]:\n"
            "    return Some(1)\n"
            "\n"
            "def forward() -> Option[i32]:\n"
            "    return Some(make()?)\n",
            "'?' requires a Result value",
        ),
    ],
)
def test_option_diagnostics(source: str, message: str) -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(source)
    assert message in str(captured.value)


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_option_runs_end_to_end(tmp_path: Path) -> None:
    source = (
        "def parse(value: i32) -> Option[i32]:\n"
        "    if value < 0:\n"
        "        return None\n"
        "    return Some(value * 2)\n"
        "\n"
        "def main() -> i32:\n"
        "    present = parse(4)\n"
        "    missing = parse(-1)\n"
        "    if not present.is_some or not missing.is_none:\n"
        "        return 1\n"
        "    if present.value != 8:\n"
        "        return 2\n"
        "    match missing:\n"
        "        case Some(value):\n"
        "            return value + 3\n"
        "        case None:\n"
        "            return 0\n"
    )
    source_path = tmp_path / "option.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "option.exe" if shutil.which("cl") and not shutil.which("cc") else "option"
    )
    artifact = Compiler().build(
        source_path,
        output=executable,
        build_dir=tmp_path / "build",
    )
    result = subprocess.run(
        [str(artifact.executable)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
