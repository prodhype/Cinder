from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("collections_test.ci")).c_source


def test_lists_are_inferred_while_contextual_fixed_arrays_are_preserved() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        "    fixed: i32[2] = [1, 2]\n"
        "    values = [3, 4]\n"
        "    values.append(fixed[0])\n"
        "    pair = (values[0], 2.5)\n"
        "    return pair[0] + cast[i32](pair[1])\n"
    )

    assert "int32_t fixed[2] = { 1, 2 };" in generated
    assert "CinderList_i32 values = CinderList_i32_from_values" in generated
    assert "CinderList_i32_append((&(values)), (fixed)[0]);" in generated
    assert "CinderTuple_2_i32_f64 pair" in generated
    assert "CinderList_i32_drop(&values);" in generated


def test_typed_empty_list_and_empty_and_singleton_tuples_codegen() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        "    values: List[i32] = []\n"
        "    empty: Tuple[] = ()\n"
        "    single: Tuple[i32,] = (7,)\n"
        "    return cast[i32](len(values) + len(empty) + len(single))\n"
    )

    assert "CinderList_i32_from_values(NULL, 0)" in generated
    assert "CinderTuple_0 empty = { 0 };" in generated
    assert "CinderTuple_1_i32 single = { .item_0 = 7 };" in generated


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "def main() -> i32:\n"
            "    values = []\n"
            "    return 0\n",
            "cannot infer the element type of an empty list literal",
        ),
        (
            "def consume(values: List[i32]) -> void:\n"
            "    pass\n",
            "cannot own a List by value",
        ),
        (
            "def main() -> i32:\n"
            "    values = [1]\n"
            "    copied = values\n"
            "    return 0\n",
            "cannot copy move-only List[i32]",
        ),
        (
            "def main(index: i32, argv: **char) -> i32:\n"
            "    pair = (1, 2)\n"
            "    return pair[index]\n",
            "tuple index must be a non-negative integer literal",
        ),
        (
            "def main() -> i32:\n"
            "    pair = (1, 2)\n"
            "    return pair[2]\n",
            "tuple index 2 is out of range",
        ),
        (
            "def main() -> i32:\n"
            "    nested: List[List[i32]] = []\n"
            "    return 0\n",
            "invalid List element type List[i32]",
        ),
        (
            "class Resource:\n"
            "    def __del__(self):\n"
            "        pass\n"
            "\n"
            "def main() -> i32:\n"
            "    values: List[Resource] = []\n"
            "    return 0\n",
            "List element type Resource contains a class with a destructor",
        ),
        (
            "def main() -> i32:\n"
            "    values: Map[i32, i32]\n"
            "    return 0\n",
            "unsupported generic type 'Map'",
        ),
        (
            "def main() -> i32:\n"
            "    values: Set[i32]\n"
            "    return 0\n",
            "unsupported generic type 'Set'",
        ),
        (
            "def main() -> i32:\n"
            "    values = [1, 2]\n"
            "    for value in values:\n"
            "        values.append(value)\n"
            "    return 0\n",
            "cannot call List.append while iterating over that List",
        ),
    ],
)
def test_collection_diagnostics(source: str, message: str) -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(source)
    assert message in str(captured.value)


def test_const_list_reference_rejects_mutation() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "def mutate(values: &const List[i32]) -> void:\n"
            "    values.append(1)\n"
        )
    assert "cannot call mutating method 'append' on a const List" in str(
        captured.value
    )


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_native_tuples_and_lists_run_end_to_end(tmp_path: Path) -> None:
    source = (
        "calls: i32 = 0\n"
        "\n"
        "def make_pair() -> Tuple[i32, i32]:\n"
        "    calls += 1\n"
        "    return (1, 2)\n"
        "\n"
        "def make_values() -> List[i32]:\n"
        "    values: List[i32] = []\n"
        "    for value in range(0, 20):\n"
        "        values.append(value)\n"
        "    return values\n"
        "\n"
        "def total(values: &const List[i32]) -> i32:\n"
        "    result: i32 = 0\n"
        "    for value in values:\n"
        "        result += value\n"
        "    return result\n"
        "\n"
        "def main() -> i32:\n"
        "    values = make_values()\n"
        "    if len(values) != 20 or total(values) != 190:\n"
        "        return 1\n"
        "    sort(values)\n"
        "    popped = values.pop()\n"
        "    pair = (len(values), popped)\n"
        "    if pair[0] != 19 or pair[1] != 19:\n"
        "        return 2\n"
        "    if len(make_pair()) != 2 or calls != 1:\n"
        "        return 3\n"
        "    values.clear()\n"
        "    if len(values) != 0:\n"
        "        return 4\n"
        "    values = [4, 5]\n"
        "    if total(values) != 9:\n"
        "        return 5\n"
        "    pairs = [(1, 2), (3, 4)]\n"
        "    pairs.append((5, 6))\n"
        "    last_pair = pairs.pop()\n"
        "    if last_pair[0] != 5 or last_pair[1] != 6:\n"
        "        return 6\n"
        "    return 0\n"
    )
    source_path = tmp_path / "collections.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "collections.exe" if shutil.which("cl") and not shutil.which("cc") else "collections"
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


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_collection_specializations_work_across_modules(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"collection_modules\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "model.ci").write_text(
        "def make_values() -> List[i32]:\n"
        "    return [2, 3]\n"
        "\n"
        "def make_pair() -> Tuple[i32, i32]:\n"
        "    return (4, 5)\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import model\n"
        "\n"
        "def main() -> i32:\n"
        "    values = model.make_values()\n"
        "    pair = model.make_pair()\n"
        "    values.append(pair[0])\n"
        "    if len(values) != 3 or values[2] != 4 or pair[1] != 5:\n"
        "        return 1\n"
        "    return 0\n",
        encoding="utf-8",
    )
    executable = tmp_path / (
        "collection_modules.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "collection_modules"
    )
    artifact = Compiler().build(
        tmp_path,
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
