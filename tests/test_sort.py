from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("sort_test.ci")).c_source


@pytest.mark.parametrize(
    ("type_name", "values"),
    [
        ("char", "['b', 'a']"),
        ("i8", "[2, 1]"),
        ("i16", "[2, 1]"),
        ("i32", "[2, 1]"),
        ("i64", "[2, 1]"),
        ("u8", "[2, 1]"),
        ("u16", "[2, 1]"),
        ("u32", "[2, 1]"),
        ("u64", "[2, 1]"),
        ("f32", "[2.0, 1.0]"),
        ("f64", "[2.0, 1.0]"),
        ("isize", "[2, 1]"),
        ("usize", "[2, 1]"),
        ("c_int", "[2, 1]"),
        ("c_long", "[2, 1]"),
        ("c_size_t", "[2, 1]"),
        ("bool", "[true, false]"),
        ("String", '["beta", "alpha"]'),
        # Keep explicit raw C-string sorting covered for low-level interop.
        ("const char*", '["beta", "alpha"]'),
    ],
)
def test_sort_supports_each_builtin_ordered_type(type_name: str, values: str) -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        f"    values: {type_name}[2] = {values}\n"
        "    sort(values)\n"
        "    return 0\n"
    )
    assert "cinder_sort(values.data, values.length" in generated


def test_sort_codegen_reuses_a_specialization_and_coerces_arrays() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        "    first: i32[3] = [3, 1, 2]\n"
        "    second: i32[2] = [5, 4]\n"
        "    sort(first)\n"
        "    sort(second)\n"
        "    return 0\n"
    )
    assert generated.count("int CinderSortCompare_i32(") == 1
    assert generated.count("void CinderSort_i32(") == 1
    assert "CinderSlice_i32){ .data = first, .length = 3" in generated
    assert "CinderSlice_i32){ .data = second, .length = 2" in generated


def test_sorted_returns_a_new_list_and_keeps_sort_behavior() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        "    values: List[i32] = [3, 1, 2]\n"
        "    ordered = sorted(values)\n"
        "    sort(values)\n"
        "    return ordered[0] - values[0]\n"
    )

    assert "CinderSorted_i32(" in generated
    assert "CinderSort_i32(" in generated


def test_sorted_borrows_addressable_list_fields_without_dropping_source() -> None:
    generated = compile_source(
        "struct Bundle:\n"
        "    items: List[i32]\n"
        "def main() -> i32:\n"
        "    bundle = Bundle(items=[3, 1, 2])\n"
        "    ordered = sorted(bundle.items)\n"
        "    return ordered[0] + bundle.items[0]\n"
    )

    assert "CinderSorted_i32(" in generated
    assert "__cinder_sorted_source_" not in generated


def test_sorted_drops_materialized_rvalue_list_source() -> None:
    generated = compile_source(
        "def get_values() -> List[i32]:\n"
        "    return [3, 1, 2]\n"
        "def main() -> i32:\n"
        "    ordered = sorted(get_values())\n"
        "    return ordered[0]\n"
    )

    assert "CinderList_i32 __cinder_sorted_source_" in generated
    assert "CinderList_i32_drop(&__cinder_sorted_source_" in generated


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "def main() -> i32:\n"
            "    sort()\n"
            "    return 0\n",
            "sort expects exactly one positional argument",
        ),
        (
            "def main() -> i32:\n"
            "    values: i32[1] = [1]\n"
            "    sort(values=values)\n"
            "    return 0\n",
            "sort expects exactly one positional argument",
        ),
        (
            "def main() -> i32:\n"
            "    sort(1)\n"
            "    return 0\n",
            "sort requires an array or slice",
        ),
        (
            "def consume(values: []const i32) -> void:\n"
            "    sort(values)\n",
            "sort requires mutable elements",
        ),
        (
            "const values: i32[2] = [2, 1]\n"
            "def main() -> i32:\n"
            "    sort(values)\n"
            "    return 0\n",
            "sort requires mutable elements",
        ),
        (
            "const values: i32[2] = [2, 1]\n"
            "def main() -> i32:\n"
            "    sort(values[0:2])\n"
            "    return 0\n",
            "sort requires mutable elements",
        ),
        (
            "const values: i32[2] = [2, 1]\n"
            "def main() -> i32:\n"
            "    view = values[0:2]\n"
            "    sort(view)\n"
            "    return 0\n",
            "sort requires mutable elements",
        ),
        (
            "def main() -> i32:\n"
            "    sort([2, 1])\n"
            "    return 0\n",
            "sort requires an addressable fixed array",
        ),
        (
            "struct Item:\n"
            "    value: i32\n"
            "def main() -> i32:\n"
            "    values: Item[1] = [Item(value=1)]\n"
            "    sort(values)\n"
            "    return 0\n",
            "sort does not support elements of type Item",
        ),
        (
            "def main() -> i32:\n"
            "    values: i32*[1] = [null]\n"
            "    sort(values)\n"
            "    return 0\n",
            "sort does not support elements of type *i32",
        ),
    ],
)
def test_sort_rejects_invalid_calls(source: str, message: str) -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(source)
    assert message in str(captured.value)


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_sort_runs_stably_for_arrays_slices_enums_and_strings(tmp_path: Path) -> None:
    source = (
        "enum Priority:\n"
        "    high = 20\n"
        "    low = -4\n"
        "    normal = 7\n"
        "\n"
        "struct Bundle:\n"
        "    items: List[i32]\n"
        "\n"
        "calls: i32 = 0\n"
        "\n"
        "def view(values: []i32) -> []i32:\n"
        "    calls += 1\n"
        "    return values\n"
        "\n"
        "def main() -> i32:\n"
        "    numbers: i32[6] = [9, 4, 3, 2, 1, 8]\n"
        "    sort(view(numbers[1:5]))\n"
        "    if calls != 1 or numbers[0] != 9 or numbers[1] != 1 or numbers[4] != 4 or numbers[5] != 8:\n"
        "        return 1\n"
        "\n"
        "    flags: bool[3] = [true, false, true]\n"
        "    sort(flags)\n"
        "    if flags[0] or not flags[1] or not flags[2]:\n"
        "        return 2\n"
        "\n"
        "    priorities: Priority[3] = [Priority.high, Priority.low, Priority.normal]\n"
        "    sort(priorities)\n"
        "    if priorities[0] != Priority.low or priorities[2] != Priority.high:\n"
        "        return 3\n"
        "\n"
        "    first: char[2] = ['a', '\\0']\n"
        "    second: char[2] = ['a', '\\0']\n"
        "    last: char[2] = ['z', '\\0']\n"
        "    words: char*[3] = [last, first, second]\n"
        "    sort(words)\n"
        "    if words[0] != first or words[1] != second or words[2] != last:\n"
        "        return 4\n"
        "\n"
        '    owned_words: String[4] = ["zeta", "alpha", "éclair", "beta"]\n'
        "    sort(owned_words)\n"
        '    if owned_words[0] != "alpha" or owned_words[1] != "beta":\n'
        "        return 5\n"
        '    if owned_words[2] != "zeta" or owned_words[3] != "éclair":\n'
        "        return 6\n"
        "\n"
        '    word_list: List[String] = ["zeta", "alpha"]\n'
        "    ordered_words = sorted(word_list)\n"
        '    if ordered_words[0] != "alpha" or word_list[0] != "zeta":\n'
        "        return 7\n"
        "\n"
        "    bundle = Bundle(items=[3, 1, 2])\n"
        "    ordered_items = sorted(bundle.items)\n"
        "    if ordered_items[0] != 1 or bundle.items[0] != 3 or len(bundle.items) != 3:\n"
        "        return 8\n"
        "\n"
        "    single: f64[1] = [1.5]\n"
        "    sort(numbers[0:0])\n"
        "    sort(single)\n"
        "    return 0\n"
    )
    source_path = tmp_path / "sort_program.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "sort_program.exe" if shutil.which("cl") and not shutil.which("cc") else "sort_program"
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
