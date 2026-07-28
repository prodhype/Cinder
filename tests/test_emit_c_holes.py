from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("emit_c_holes.ci")).c_source


def assert_compile_error(source: str, message: str) -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(source)
    assert message in str(captured.value)


def test_a1_aggregate_unsafe_cast_is_rejected() -> None:
    assert_compile_error(
        "struct A:\n"
        "    x: i32\n"
        "\n"
        "struct B:\n"
        "    y: i32\n"
        "\n"
        "def main() -> i32:\n"
        "    a: A = A(x=1)\n"
        "    b: B\n"
        "    unsafe:\n"
        "        b = cast[B](a)\n"
        "    return b.y\n",
        "cannot cast from A to B",
    )


def test_a2_type_key_separates_nominal_ptr_i32_from_pointer() -> None:
    generated = compile_source(
        "struct ptr_i32:\n"
        "    x: i32\n"
        "\n"
        "def id[T](value: T) -> T:\n"
        "    return value\n"
        "\n"
        "def main() -> i32:\n"
        "    s: ptr_i32 = ptr_i32(x=10)\n"
        "    p: *i32 = alloc[i32]()\n"
        "    *p = 20\n"
        "    a = id[ptr_i32](s)\n"
        "    b = id[*i32](p)\n"
        "    return a.x + *b\n"
    )
    assert "id_n_ptr_i32" in generated
    assert "id_ptr_i32" in generated
    assert "id_n_ptr_i32" != "id_ptr_i32"


def test_a2_list_helpers_separate_nominal_ptr_i32_from_pointer() -> None:
    generated = compile_source(
        "struct ptr_i32:\n"
        "    x: i32\n"
        "\n"
        "def main() -> i32:\n"
        "    a: List[ptr_i32] = [ptr_i32(x=1)]\n"
        "    p: *i32 = alloc[i32]()\n"
        "    *p = 2\n"
        "    b: List[*i32] = [p]\n"
        "    return (a[0].x) + (*b[0])\n"
    )
    assert "CinderList_n_ptr_i32" in generated
    assert "CinderList_ptr_i32" in generated
    assert "CinderList_n_ptr_i32" != "CinderList_ptr_i32"


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_a2_type_key_collision_programs_compile(tmp_path: Path) -> None:
    for name, source in (
        (
            "typekey",
            "struct ptr_i32:\n"
            "    x: i32\n"
            "\n"
            "def id[T](value: T) -> T:\n"
            "    return value\n"
            "\n"
            "def main() -> i32:\n"
            "    s: ptr_i32 = ptr_i32(x=10)\n"
            "    p: *i32 = alloc[i32]()\n"
            "    *p = 20\n"
            "    a = id[ptr_i32](s)\n"
            "    b = id[*i32](p)\n"
            "    return a.x + *b\n",
        ),
        (
            "list",
            "struct ptr_i32:\n"
            "    x: i32\n"
            "\n"
            "def main() -> i32:\n"
            "    a: List[ptr_i32] = [ptr_i32(x=1)]\n"
            "    p: *i32 = alloc[i32]()\n"
            "    *p = 2\n"
            "    b: List[*i32] = [p]\n"
            "    return (a[0].x) + (*b[0])\n",
        ),
    ):
        source_path = tmp_path / f"{name}.ci"
        source_path.write_text(source, encoding="utf-8")
        executable = tmp_path / f"{name}_program"
        Compiler().build(
            source_path,
            output=executable,
            build_dir=tmp_path / f"{name}_build",
        )


def test_b1_match_list_return_is_rejected() -> None:
    assert_compile_error(
        "def take() -> List[i32]:\n"
        "    o: Option[List[i32]] = Some([1, 2, 3])\n"
        "    match o:\n"
        "        case Some(v):\n"
        "            return v\n"
        "        case None:\n"
        "            return []\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        "returning List[i32] would copy a move-only value",
    )


def test_b1_match_list_assignment_is_rejected() -> None:
    assert_compile_error(
        "def main() -> i32:\n"
        "    o: Option[List[i32]] = Some([1, 2, 3])\n"
        "    match o:\n"
        "        case Some(v):\n"
        "            xs: List[i32] = v\n"
        "            return len(xs)\n"
        "        case None:\n"
        "            return 0\n",
        "cannot copy move-only List[i32]",
    )


def test_b1_match_result_return_is_rejected() -> None:
    assert_compile_error(
        "enum E:\n"
        "    bad\n"
        "\n"
        "def take() -> List[i32]:\n"
        "    r: Result[List[i32], E] = Ok([1, 2, 3])\n"
        "    match r:\n"
        "        case Ok(v):\n"
        "            return v\n"
        "        case Err(_):\n"
        "            return []\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        "returning List[i32] would copy a move-only value",
    )


def test_b1_match_owned_return_is_rejected() -> None:
    assert_compile_error(
        "def take() -> Owned[i32]:\n"
        "    o: Option[Owned[i32]] = Some(Owned(5))\n"
        "    match o:\n"
        "        case Some(v):\n"
        "            return v\n"
        "        case None:\n"
        "            return Owned(0)\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        "returning Owned[i32] would copy a move-only value",
    )


def test_b1_match_class_return_is_rejected() -> None:
    assert_compile_error(
        "class R:\n"
        "    n: i32\n"
        "    def __init__(self, n: i32) -> void:\n"
        "        self.n = n\n"
        "    def __del__(self) -> void:\n"
        "        print(\"drop\", self.n)\n"
        "\n"
        "def take() -> R:\n"
        "    o: Option[R] = Some(R(5))\n"
        "    match o:\n"
        "        case Some(v):\n"
        "            return v\n"
        "        case None:\n"
        "            return R(0)\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        "returning R would copy a move-only value",
    )


def test_b1_match_non_owning_payload_still_allowed() -> None:
    generated = compile_source(
        "def choose(flag: bool) -> Option[i32]:\n"
        "    if flag:\n"
        "        return Some(7)\n"
        "    return None\n"
        "\n"
        "def main() -> i32:\n"
        "    selected = choose(true)\n"
        "    match selected:\n"
        "        case Some(value):\n"
        "            return value - 7\n"
        "        case None:\n"
        "            return 2\n"
    )
    assert "CinderOption_i32_Tag_Some" in generated
