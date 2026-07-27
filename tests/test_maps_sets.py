from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("maps_sets_test.ci")).c_source


def test_map_and_set_literals_views_and_operations_codegen() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        "    values = {1: 2, 3: 4}\n"
        "    values[5] = 6\n"
        "    values[3] += 1\n"
        "    keys = values.keys()\n"
        "    items = values.items()\n"
        "    selected = values.get(1)\n"
        "    left = {1, 2}\n"
        "    right = {2, 3}\n"
        "    joined = left | right\n"
        "    if 1 in keys and (3, 5) in items and selected.is_some:\n"
        "        return cast[i32](len(joined)) - 3\n"
        "    return 1\n"
    )

    assert "struct CinderMap_i32_i32" in generated
    assert "struct CinderSet_i32" in generated
    assert "struct CinderMapKeys_i32_i32" in generated
    assert "CinderMap_i32_i32_set" in generated
    assert "CinderMap_i32_i32_items_contains" in generated
    assert "CinderSet_i32_union" in generated
    assert "CinderOption_i32" in generated
    assert "CinderMap_i32_i32_drop(&values);" in generated
    assert "CinderSet_i32_drop(&joined);" in generated


def test_brace_literals_inside_fstrings_track_nested_colons_and_quotes() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        '    values = {"answer": 42}\n'
        '    print(f"{values["answer"]}")\n'
        '    print(f"{1 in {1: 2}}")\n'
        "    return 0\n"
    )
    assert "cinder_string_equal" in generated
    assert "CinderMap_ptr_const_char_i32" in generated


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "def main() -> i32:\n"
            "    value = {}\n"
            "    return 0\n",
            "cannot infer key and value types of an empty map literal",
        ),
        (
            "def main() -> i32:\n"
            "    value = set()\n"
            "    return 0\n",
            "empty set() requires a contextual Set[T] type",
        ),
        (
            "def main() -> i32:\n"
            "    value: Map[f64, i32] = {}\n"
            "    return 0\n",
            "Map key type f64 is not hashable",
        ),
        (
            "def main() -> i32:\n"
            "    value: Set[*i32] = set()\n"
            "    return 0\n",
            "Set element type *i32 is not hashable",
        ),
        (
            "def main() -> i32:\n"
            "    value = {1: 2, 3}\n"
            "    return 0\n",
            "map literal entries require ':' between key and value",
        ),
        (
            "def main() -> i32:\n"
            "    value = {1, 2: 3}\n"
            "    return 0\n",
            "cannot mix set elements and map entries",
        ),
        (
            "def main() -> i32:\n"
            "    value = {1: 2}\n"
            "    copied = value\n"
            "    return 0\n",
            "cannot copy move-only Map[i32, i32]",
        ),
        (
            "def consume(value: Set[i32]) -> void:\n"
            "    pass\n",
            "cannot own a Set by value",
        ),
        (
            "def main() -> i32:\n"
            "    values = {1: 2}\n"
            "    for key in values:\n"
            "        values[3] = key\n"
            "    return 0\n",
            "cannot insert into a Map while iterating over it",
        ),
        (
            "def main() -> i32:\n"
            "    values = {1: 2}\n"
            "    for key in values:\n"
            "        values[key] += 1\n"
            "    return 0\n",
            "cannot mutate a Map while iterating over it",
        ),
        (
            "def main() -> i32:\n"
            "    first = {1: 1}\n"
            "    second = {2: 2}\n"
            "    keys = first.keys()\n"
            "    keys = second.keys()\n"
            "    for key in keys:\n"
            "        second[3] = key\n"
            "    return 0\n",
            "cannot insert into a Map while iterating over it",
        ),
        (
            "def main() -> i32:\n"
            "    values = {1, 2}\n"
            "    for value in values:\n"
            "        values.add(value)\n"
            "    return 0\n",
            "cannot call Set.add while iterating over that Set",
        ),
    ],
)
def test_map_set_diagnostics(source: str, message: str) -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(source)
    assert message in str(captured.value)


def test_map_view_reassignment_tracks_latest_backing_map() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        "    first = {1: 1}\n"
        "    second = {2: 2}\n"
        "    keys = first.keys()\n"
        "    keys = second.keys()\n"
        "    for key in keys:\n"
        "        first[3] = key\n"
        "    return 0\n"
    )

    assert "CinderMapKeys_i32_i32" in generated


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_maps_sets_run_end_to_end_with_growth_order_and_strings(
    tmp_path: Path,
) -> None:
    source = (
        "def main() -> i32:\n"
        "    dynamic_key = input()\n"
        "    words: Map[const char*, i32] = {dynamic_key: 7, \"other\": 9}\n"
        "    if dynamic_key != \"alpha\":\n"
        "        return 1\n"
        "    free(cast[void*](dynamic_key))\n"
        "    if words[\"alpha\"] != 7:\n"
        "        return 2\n"
        "\n"
        "    values: Map[i32, i32] = {}\n"
        "    for index in range(0, 100):\n"
        "        values[index] = index * 2\n"
        "    values[20] = 999\n"
        "    removed = values.pop(10)\n"
        "    values[10] = 20\n"
        "    if not removed.is_some or removed.value != 20:\n"
        "        return 3\n"
        "    position: i32 = 0\n"
        "    for key in values:\n"
        "        if position < 99:\n"
        "            expected = position\n"
        "            if position >= 10:\n"
        "                expected += 1\n"
        "            if key != expected:\n"
        "                return 4\n"
        "        elif key != 10:\n"
        "            return 5\n"
        "        position += 1\n"
        "    if position != 100 or values[20] != 999:\n"
        "        return 6\n"
        "\n"
        "    live = values.keys()\n"
        "    values[100] = 200\n"
        "    if len(live) != 101 or 100 not in live:\n"
        "        return 7\n"
        "    if 999 not in values.values() or (100, 200) not in values.items():\n"
        "        return 8\n"
        "\n"
        "    left = {1, 2, 3}\n"
        "    right = {3, 4}\n"
        "    united = left | right\n"
        "    common = left.intersection(right)\n"
        "    difference = left - right\n"
        "    symmetric = left ^ right\n"
        "    if united != {1, 2, 3, 4} or common != {3}:\n"
        "        return 9\n"
        "    if difference != {1, 2} or symmetric != {1, 2, 4}:\n"
        "        return 10\n"
        "    if not (common < united and united > common):\n"
        "        return 11\n"
        "    left |= right\n"
        "    left &= {2, 3, 4}\n"
        "    left -= {3}\n"
        "    left ^= {5}\n"
        "    left.update({6, 7})\n"
        "    left.discard(99)\n"
        "    left.remove(2)\n"
        "    if left != {4, 5, 6, 7}:\n"
        "        return 12\n"
        "\n"
        "    names = {\"first\", \"second\", \"first\"}\n"
        "    popped = names.pop()\n"
        "    match popped:\n"
        "        case Some(text):\n"
        "            free(cast[void*](text))\n"
        "        case None:\n"
        "            return 13\n"
        "    return 0\n"
    )
    source_path = tmp_path / "maps_sets.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "maps_sets.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "maps_sets"
    )
    artifact = Compiler().build(
        source_path,
        output=executable,
        build_dir=tmp_path / "build",
    )
    result = subprocess.run(
        [str(artifact.executable)],
        input="alpha\n",
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_hidden_mutation_during_iteration_panics(tmp_path: Path) -> None:
    source = (
        "def mutate(values: &Map[i32, i32]) -> void:\n"
        "    values[3] = 4\n"
        "\n"
        "def main() -> i32:\n"
        "    values = {1: 2}\n"
        "    for key in values:\n"
        "        mutate(values)\n"
        "    return 0\n"
    )
    source_path = tmp_path / "iterator_guard.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "iterator_guard.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "iterator_guard"
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
    assert result.returncode != 0
    assert "cannot structurally mutate Map during iteration" in result.stderr


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_hidden_compound_map_mutation_during_iteration_panics(
    tmp_path: Path,
) -> None:
    source = (
        "def mutate(values: &Map[i32, i32]) -> void:\n"
        "    values[1] += 1\n"
        "\n"
        "def main() -> i32:\n"
        "    values = {1: 2}\n"
        "    for key in values:\n"
        "        mutate(values)\n"
        "    return 0\n"
    )
    source_path = tmp_path / "iterator_guard_compound.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "iterator_guard_compound.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "iterator_guard_compound"
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
    assert result.returncode != 0
    assert "cannot mutate Map during iteration" in result.stderr


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_char_map_set_keys_compile_and_run(tmp_path: Path) -> None:
    source = (
        "def main() -> i32:\n"
        "    annotated_map: Map[char, i32] = {'a': 1}\n"
        "    annotated_set: Set[char] = {'a', 'b'}\n"
        "    inferred_map = {'x': 24, 'y': 25}\n"
        "    inferred_set = {'m', 'n'}\n"
        "    annotated_map['b'] = 2\n"
        "    annotated_map['a'] += 3\n"
        "    if annotated_map['a'] != 4 or annotated_map['b'] != 2:\n"
        "        return 1\n"
        "    if 'b' not in annotated_set or 'z' in annotated_set:\n"
        "        return 2\n"
        "    if inferred_map['x'] != 24 or 'n' not in inferred_set:\n"
        "        return 3\n"
        "    return 0\n"
    )
    source_path = tmp_path / "char_maps_sets.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "char_maps_sets.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "char_maps_sets"
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
def test_map_set_specializations_work_across_modules(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        'name = "map_set_modules"\n'
        'source-root = "src"\n'
        'entry = "main.ci"\n',
        encoding="utf-8",
    )
    (source_root / "model.ci").write_text(
        "def make_map() -> Map[i32, i32]:\n"
        "    return {1: 2, 3: 4}\n"
        "\n"
        "def make_set() -> Set[i32]:\n"
        "    return {2, 4, 6}\n"
        "\n"
        "def keys(values: &const Map[i32, i32]) -> MapKeys[i32, i32]:\n"
        "    return values.keys()\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import model\n"
        "\n"
        "def main() -> i32:\n"
        "    values = model.make_map()\n"
        "    numbers = model.make_set()\n"
        "    keys = model.keys(values)\n"
        "    if len(keys) != 2 or 3 not in keys:\n"
        "        return 1\n"
        "    if values[1] != 2 or 6 not in numbers:\n"
        "        return 2\n"
        "    return 0\n",
        encoding="utf-8",
    )
    executable = tmp_path / (
        "map_set_modules.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "map_set_modules"
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


@pytest.mark.skipif(
    not shutil.which("cc") or not shutil.which("c++"),
    reason="C and C++ compilers are required",
)
def test_collection_generated_header_is_usable_from_cpp(tmp_path: Path) -> None:
    runtime_dir = Path(__file__).resolve().parents[1] / "cinder" / "runtime"
    source = tmp_path / "library.ci"
    source.write_text(
        "@export\n"
        "def numbers() -> Set[i32]:\n"
        "    return {1, 2, 3}\n"
        "\n"
        "@export\n"
        "def lookup() -> Map[i32, i32]:\n"
        "    return {4: 5}\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"
    emitted = Compiler().emit_project(source, generated)

    library_object = tmp_path / "library.o"
    compile_library = subprocess.run(
        [
            shutil.which("cc") or "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
            f"-I{runtime_dir}",
            f"-I{generated}",
            "-c",
            str(emitted.sources[0]),
            "-o",
            str(library_object),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert compile_library.returncode == 0, compile_library.stderr

    runtime_object = tmp_path / "runtime.o"
    compile_runtime = subprocess.run(
        [
            shutil.which("cc") or "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
            f"-I{runtime_dir}",
            "-c",
            str(runtime_dir / "cinder_runtime.c"),
            "-o",
            str(runtime_object),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert compile_runtime.returncode == 0, compile_runtime.stderr

    consumer = tmp_path / "consumer.cpp"
    consumer.write_text(
        '#include "cinder_gen/library.cinder.h"\n'
        "int main() {\n"
        "    auto set = numbers();\n"
        "    auto map = lookup();\n"
        "    int result = 0;\n"
        "    if (!CinderSet_i32_contains(&set, 2)) result = 1;\n"
        "    if (CinderMap_i32_i32_lookup_or_panic(&map, 4) != 5) result = 2;\n"
        "    CinderSet_i32_drop(&set);\n"
        "    CinderMap_i32_i32_drop(&map);\n"
        "    return result;\n"
        "}\n",
        encoding="utf-8",
    )
    executable = tmp_path / "consumer"
    compile_consumer = subprocess.run(
        [
            shutil.which("c++") or "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
            f"-I{runtime_dir}",
            f"-I{generated}",
            str(consumer),
            str(library_object),
            str(runtime_object),
            "-o",
            str(executable),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert compile_consumer.returncode == 0, compile_consumer.stderr
    assert subprocess.run([str(executable)], check=False).returncode == 0
