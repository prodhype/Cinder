from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("strings_test.ci")).c_source


def build_and_run(
    tmp_path: Path,
    source: str,
    *,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    source_path = tmp_path / "strings_test.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "strings_test.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "strings_test"
    )
    artifact = Compiler().build(
        source_path,
        output=executable,
        build_dir=tmp_path / "build",
    )
    return subprocess.run(
        [str(artifact.executable)],
        check=False,
        input=stdin,
        text=True,
        capture_output=True,
    )


pytestmark_native = pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)


def test_string_literals_and_owned_operations_codegen() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        '    text = "hé"\n'
        "    empty = String()\n"
        "    copied = text.clone()\n"
        '    copied.append("llo")\n'
        "    copied.append_char('!')\n"
        "    copied.reserve(128)\n"
        "    empty.clear()\n"
        "    moved = copied\n"
        "    print(text, moved)\n"
        "    return 0\n"
    )

    assert "CinderString text" in generated
    assert '.data = (char *)"hé"' in generated
    assert ".length = 3" in generated
    assert ".capacity = 0" in generated
    assert "CinderString empty" in generated
    assert "cinder_string_clone" in generated
    assert "cinder_string_append" in generated
    assert "cinder_string_append_char" in generated
    assert "cinder_string_reserve" in generated
    assert "cinder_string_clear" in generated
    assert "cinder_string_drop(&text);" in generated
    assert "cinder_string_drop(&moved);" in generated
    assert "cinder_string_drop(&copied);" not in generated


def test_string_move_reports_use_after_move() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "def consume(value: String) -> usize:\n"
            "    return len(value)\n"
            "\n"
            "def main() -> i32:\n"
            '    text = "owned"\n'
            "    moved = text\n"
            "    consume(moved)\n"
            "    print(text)\n"
            "    return 0\n"
        )

    assert "use of moved value text" in str(captured.value)


def test_string_self_move_assignment_is_rejected() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "def main() -> i32:\n"
            "    text = to_string(123)\n"
            "    text = text\n"
            "    return cast[i32](len(text))\n"
        )

    assert "cannot move-assign String to itself" in str(captured.value)


def test_string_concat_comparison_and_slice_codegen() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        '    left = "alpha"\n'
        '    right = "beta"\n'
        "    joined = left + right\n"
        "    middle = joined[1:7]\n"
        "    first = joined.byte_at(0)\n"
        "    if left < right and joined == left + right:\n"
        "        return cast[i32](first + len(middle))\n"
        "    return 1\n"
    )

    assert "cinder_string_concat" in generated
    assert "cinder_string_compare_value" in generated
    assert "cinder_string_equal_value" in generated
    assert "cinder_string_slice" in generated
    assert "cinder_string_byte_at" in generated


def test_string_direct_index_has_byte_at_guidance() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "def main() -> i32:\n"
            '    text = "abc"\n'
            "    return cast[i32](text[0])\n"
        )

    rendered = str(captured.value)
    assert "String" in rendered
    assert "byte_at" in rendered


def test_owned_string_rejects_nul_but_explicit_c_string_allows_it() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "def main() -> i32:\n"
            '    text = "a\\0b"\n'
            "    return cast[i32](len(text))\n"
        )
    assert "String literals cannot contain NUL bytes" in str(captured.value)

    generated = compile_source(
        "def main() -> i32:\n"
        '    text: const char* = "a\\0b"\n'
        "    return 0\n"
    )
    assert '"a\\000b"' in generated


@pytestmark_native
def test_string_growth_concat_comparisons_and_unicode_run(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "def main() -> i32:\n"
        '    text = "é"\n'
        "    if len(text) != 2:\n"
        "        return 1\n"
        "    text.reserve(4096)\n"
        "    for index in range(0, 1000):\n"
        '        text.append("ab")\n'
        "    text.append_char('!')\n"
        "    if len(text) != 2003:\n"
        "        return 2\n"
        '    joined = text + "世界"\n'
        "    if len(joined) != 2009:\n"
        "        return 3\n"
        '    if not ("alpha" < "beta" and "beta" > "alpha"):\n'
        "        return 4\n"
        '    if "same" != "same" or joined == text:\n'
        "        return 5\n"
        "    copied = joined.clone()\n"
        "    joined.clear()\n"
        "    if len(joined) != 0 or len(copied) != 2009:\n"
        "        return 6\n"
        "    return 0\n",
    )

    assert result.returncode == 0, result.stderr


@pytestmark_native
def test_string_byte_length_byte_at_and_owned_slice_run(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "def main() -> i32:\n"
        '    text = "Aé中Z"\n'
        "    if len(text) != 7:\n"
        "        return 1\n"
        "    if text.byte_at(1) != 0xC3 or text.byte_at(2) != 0xA9:\n"
        "        return 2\n"
        "    middle = text[1:6]\n"
        '    if middle != "é中" or len(middle) != 5:\n'
        "        return 3\n"
        "    middle.append_char('!')\n"
        '    if middle != "é中!" or text != "Aé中Z":\n'
        "        return 4\n"
        "    return 0\n",
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "operation",
    [
        'text = "x"\n    text.byte_at(1)',
        'text = "é"\n    text[1:2]',
        'text = "x"\n    text[0:2]',
    ],
    ids=["byte-at-out-of-range", "slice-non-boundary", "slice-out-of-range"],
)
@pytestmark_native
def test_invalid_string_byte_operations_panic(
    tmp_path: Path,
    operation: str,
) -> None:
    result = build_and_run(
        tmp_path,
        "def main() -> i32:\n"
        f"    {operation}\n"
        "    return 0\n",
    )

    assert result.returncode != 0
    assert "panic:" in result.stderr


def test_string_builder_codegen_and_cleanup() -> None:
    generated = compile_source(
        "def build() -> String:\n"
        "    builder = StringBuilder()\n"
        "    builder.reserve(128)\n"
        '    builder.append("hello")\n'
        "    builder.append_char('!')\n"
        "    return builder.finish()\n"
        "\n"
        "def abandon() -> void:\n"
        "    builder = StringBuilder()\n"
        '    builder.append("unused")\n'
    )

    assert "CinderStringBuilder builder" in generated
    assert "cinder_string_builder_reserve" in generated
    assert "cinder_string_builder_append" in generated
    assert "cinder_string_builder_append_char" in generated
    assert "cinder_string_builder_finish" in generated
    assert "cinder_string_builder_drop(&builder);" in generated


def test_string_builder_finish_consumes_builder() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "def main() -> i32:\n"
            "    builder = StringBuilder()\n"
            '    builder.append("done")\n'
            "    text = builder.finish()\n"
            '    builder.append("again")\n'
            "    return cast[i32](len(text))\n"
        )

    assert "use of moved value builder" in str(captured.value)


@pytestmark_native
def test_string_builder_finish_runs(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "def main() -> i32:\n"
        "    builder = StringBuilder()\n"
        "    builder.reserve(1024)\n"
        "    for index in range(0, 300):\n"
        '        builder.append("é")\n'
        "    builder.append_char('!')\n"
        "    text = builder.finish()\n"
        "    if len(text) != 601:\n"
        "        return 1\n"
        '    if text[598:601] != "é!":\n'
        "        return 2\n"
        "    empty_builder = StringBuilder()\n"
        "    empty = empty_builder.finish()\n"
        "    return cast[i32](len(empty))\n",
    )

    assert result.returncode == 0, result.stderr


@pytestmark_native
def test_const_string_global_uses_static_storage(tmp_path: Path) -> None:
    source = (
        'const GREETING: String = "héllo"\n'
        "\n"
        "def main() -> i32:\n"
        '    if GREETING != "héllo":\n'
        "        return 1\n"
        "    return 0\n"
    )
    generated = compile_source(source)

    assert "const CinderString GREETING" in generated
    assert '.data = (char *)"héllo"' in generated
    assert ".length = 6" in generated
    assert ".capacity = 0" in generated
    assert "cinder_string_drop(&GREETING)" not in generated

    result = build_and_run(tmp_path, source)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "source",
    [
        'greeting: String = "hello"\n',
        "const GREETING: String = String()\n",
    ],
    ids=["mutable", "runtime-initialized"],
)
def test_non_static_string_globals_are_rejected(source: str) -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(source)

    rendered = str(captured.value)
    assert "global" in rendered
    assert "String" in rendered


def test_extern_string_arguments_borrow_cstr_codegen() -> None:
    generated = compile_source(
        'extern import "string.h"\n'
        'extern import "stdio.h"\n'
        "\n"
        'extern "C":\n'
        "    def strlen(text: const char*) -> c_size_t\n"
        "    def printf(format: const char*, ...) -> c_int\n"
        "\n"
        "def main() -> i32:\n"
        '    text = "hello"\n'
        "    if strlen(text) != 5:\n"
        "        return 1\n"
        '    printf("%s\\n", text)\n'
        "    print(text)\n"
        "    return 0\n"
    )

    assert "strlen(cinder_string_cstr" in generated
    assert "printf(" in generated
    assert generated.count("cinder_string_cstr") >= 2
    assert "cinder_string_drop(&text);" in generated


@pytestmark_native
def test_extern_string_arguments_borrow_without_moving(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        'extern import "string.h"\n'
        'extern import "stdio.h"\n'
        "\n"
        'extern "C":\n'
        "    def strlen(text: const char*) -> c_size_t\n"
        "    def printf(format: const char*, ...) -> c_int\n"
        "\n"
        "def main() -> i32:\n"
        '    text = "hello"\n'
        "    if strlen(text) != 5:\n"
        "        return 1\n"
        '    printf("%s\\n", text)\n'
        '    if text != "hello":\n'
        "        return 2\n"
        "    return 0\n",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "hello\n"


@pytest.mark.parametrize(
    "source",
    [
        (
            "def main() -> i32:\n"
            '    text = "owned"\n'
            "    raw: const char* = text\n"
            "    return 0\n"
        ),
        (
            'extern "C":\n'
            "    def consume(text: String) -> void\n"
        ),
        (
            'extern "C":\n'
            "    def produce() -> String\n"
        ),
    ],
    ids=["implicit-storage", "extern-parameter", "extern-return"],
)
def test_string_cstr_storage_and_extern_signatures_are_rejected(source: str) -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(source)

    rendered = str(captured.value)
    assert "String" in rendered
    assert "extern" in rendered or "expected *const char" in rendered


def test_string_collections_codegen_clone_and_drop_elements() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        '    words: List[String] = ["beta", "alpha"]\n'
        '    words.append("gamma")\n'
        "    sort(words)\n"
        '    key = "alpha"\n'
        "    scores: Map[String, i32] = {key: 7}\n"
        "    names: Set[String] = {key}\n"
        '    key.append(" changed")\n'
        '    if scores["alpha"] == 7 and "alpha" in names:\n'
        "        return 0\n"
        "    return 1\n"
    )

    assert "CinderList_string" in generated
    assert "CinderMap_string_i32" in generated
    assert "CinderSet_string" in generated
    assert "cinder_string_clone" in generated
    assert "cinder_string_hash_value" in generated
    assert "cinder_string_compare_value" in generated
    assert "CinderList_string_drop(&words);" in generated
    assert "CinderMap_string_i32_drop(&scores);" in generated
    assert "CinderSet_string_drop(&names);" in generated


@pytestmark_native
def test_string_collections_clone_keys_sort_and_drop_run(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "def main() -> i32:\n"
        '    key = "alpha"\n'
        "    scores: Map[String, i32] = {key: 7}\n"
        "    names: Set[String] = {key}\n"
        '    key.append(" changed")\n'
        '    if scores["alpha"] != 7 or "alpha" not in names:\n'
        "        return 1\n"
        '    if key in names or scores.get(key).is_some:\n'
        "        return 2\n"
        '    words: List[String] = ["zeta", "éclair", "alpha"]\n'
        "    sort(words)\n"
        '    if words[0] != "alpha" or words[1] != "zeta" or words[2] != "éclair":\n'
        "        return 3\n"
        "    last = words.pop()\n"
        '    if last != "éclair" or len(words) != 2:\n'
        "        return 4\n"
        "    names.add(last)\n"
        '    if "éclair" not in names:\n'
        "        return 5\n"
        "    return 0\n",
    )

    assert result.returncode == 0, result.stderr


@pytestmark_native
def test_string_borrows_from_owning_aggregates_run(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "struct Holder:\n"
        "    text: String\n"
        "\n"
        "def make_pair() -> Tuple[String, String]:\n"
        "    return (to_string(11), to_string(22))\n"
        "\n"
        "def make_holder() -> Holder:\n"
        "    return Holder(text=to_string(33))\n"
        "\n"
        "def make_result() -> Result[String, i32]:\n"
        "    return Ok(to_string(44))\n"
        "\n"
        "def main() -> i32:\n"
        "    pair = make_pair()\n"
        '    if pair[0] != "11" or pair[1] != "22":\n'
        "        return 1\n"
        '    if make_pair()[0] != "11":\n'
        "        return 2\n"
        "    holder = make_holder()\n"
        '    if holder.text != "33":\n'
        "        return 3\n"
        '    if make_holder().text != "33":\n'
        "        return 4\n"
        "    result = make_result()\n"
        '    if result.value != "44":\n'
        "        return 5\n"
        '    values: Map[String, String] = {"answer": to_string(55)}\n'
        '    if values["answer"] != "55":\n'
        "        return 6\n"
        '    got = values.get("answer")\n'
        "    if got.is_none:\n"
        "        return 7\n"
        '    got.value.append("!")\n'
        '    if got.value != "55!" or values["answer"] != "55":\n'
        "        return 8\n"
        "    seen: i32 = 0\n"
        "    for value in values.values():\n"
        '        if value == "55":\n'
        "            seen += 1\n"
        "    for item in values.items():\n"
        '        if item[0] == "answer" and item[1] == "55":\n'
        "            seen += 1\n"
        "    if seen != 2:\n"
        "        return 9\n"
        "    return 0\n",
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "operation",
    [
        'text.append("!")',
        "consume(text)",
    ],
    ids=["mutate", "move"],
)
def test_string_collection_iteration_bindings_are_borrowed(
    operation: str,
) -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "def consume(text: String) -> void:\n"
            "    pass\n"
            "\n"
            "def main() -> i32:\n"
            '    values: List[String] = ["item"]\n'
            "    for text in values:\n"
            f"        {operation}\n"
            "    return 0\n"
        )

    rendered = str(captured.value)
    assert "const" in rendered or "copy move-only String" in rendered
