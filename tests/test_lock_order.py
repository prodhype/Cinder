from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("lock_test.ci")).c_source


def test_single_lock_and_valid_nested_order_compile() -> None:
    generated = compile_source(
        "lock database\n"
        "lock cache after database\n"
        "lock session after cache\n"
        "def main() -> i32:\n"
        "    CriticalSection database:\n"
        "        CriticalSection cache:\n"
        "            CriticalSection session:\n"
        "                pass\n"
        "    return 0\n"
    )

    assert generated.count("cinder_lock_acquire(") == 3
    assert generated.count("cinder_lock_release(") == 3
    assert "CINDER_LOCK_STATE_INIT(0)" in generated
    assert "CINDER_LOCK_STATE_INIT(1)" in generated
    assert "CINDER_LOCK_STATE_INIT(2)" in generated


def test_reverse_acquisition_reports_both_locks() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "lock database\n"
            "lock cache after database\n"
            "def main() -> i32:\n"
            "    CriticalSection cache:\n"
            "        CriticalSection database:\n"
            "            pass\n"
            "    return 0\n"
        )

    rendered = str(captured.value)
    assert "cannot acquire 'database' while 'cache' is held" in rendered
    assert "lock order requires 'database' before 'cache'" in rendered


def test_transitive_reverse_acquisition_is_rejected() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "lock database\n"
            "lock cache after database\n"
            "lock session after cache\n"
            "def main() -> i32:\n"
            "    CriticalSection session:\n"
            "        CriticalSection database:\n"
            "            pass\n"
            "    return 0\n"
        )

    assert "lock order requires 'database' before 'session'" in str(captured.value)


def test_explicit_three_lock_cycle_reports_cycle() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "lock a after c\n"
            "lock b after a\n"
            "lock c after b\n"
            "def main() -> i32:\n"
            "    return 0\n"
        )

    assert "lock order contains a cycle: a -> b -> c -> a" in str(captured.value)


def test_inferred_acquisitions_share_the_explicit_graph() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "lock a\n"
            "lock b\n"
            "def one() -> void:\n"
            "    CriticalSection a:\n"
            "        CriticalSection b:\n"
            "            pass\n"
            "def two() -> void:\n"
            "    CriticalSection b:\n"
            "        CriticalSection a:\n"
            "            pass\n"
            "def main() -> i32:\n"
            "    return 0\n"
        )

    assert "lock order contains a cycle" in str(captured.value)


def test_independent_locks_need_no_declaration() -> None:
    compile_source(
        "lock database\n"
        "lock renderer\n"
        "def main() -> i32:\n"
        "    CriticalSection database:\n"
        "        pass\n"
        "    CriticalSection renderer:\n"
        "        pass\n"
        "    return 0\n"
    )


def test_static_alias_keeps_lock_identity() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "lock first\n"
            "lock second after first\n"
            "def main() -> i32:\n"
            "    alias = first\n"
            "    CriticalSection second:\n"
            "        CriticalSection alias:\n"
            "            pass\n"
            "    return 0\n"
        )

    assert "cannot acquire 'first' while 'second' is held" in str(captured.value)


def test_method_body_lock_order_is_validated() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "lock root\n"
            "lock cache after root\n"
            "struct Worker:\n"
            "    def update(self) -> void:\n"
            "        CriticalSection cache:\n"
            "            CriticalSection root:\n"
            "                pass\n"
            "def main() -> i32:\n"
            "    return 0\n"
        )

    assert "cannot acquire 'root' while 'cache' is held" in str(captured.value)


def test_conditional_alias_assignment_becomes_dynamic() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "lock root\n"
            "lock cache after root\n"
            "def check(flag: bool) -> void:\n"
            "    selected = root\n"
            "    if flag:\n"
            "        selected = cache\n"
            "    CriticalSection root:\n"
            "        CriticalSection selected:\n"
            "            pass\n"
            "def main() -> i32:\n"
            "    check(false)\n"
            "    return 0\n"
        )

    assert "cannot acquire a dynamic lock while another lock is held" in str(captured.value)


def test_reassigned_alias_becomes_dynamic() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "lock root\n"
            "lock cache after root\n"
            "def main() -> i32:\n"
            "    selected = root\n"
            "    selected = cache\n"
            "    CriticalSection root:\n"
            "        CriticalSection selected:\n"
            "            pass\n"
            "    return 0\n"
        )

    assert "cannot acquire a dynamic lock while another lock is held" in str(captured.value)


def test_indirect_call_while_holding_lock_is_rejected() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "lock root\n"
            "lock cache after root\n"
            "def acquire_root() -> void:\n"
            "    CriticalSection root:\n"
            "        pass\n"
            "def invoke(callback: def() -> void) -> void:\n"
            "    CriticalSection cache:\n"
            "        callback()\n"
            "def main() -> i32:\n"
            "    invoke(acquire_root)\n"
            "    return 0\n"
        )

    assert "cannot call a function with an unknown lock effect while a lock is held" in str(captured.value)


def test_function_effect_infers_caller_order() -> None:
    generated = compile_source(
        "lock database\n"
        "lock cache\n"
        "def update_cache() -> void:\n"
        "    CriticalSection cache:\n"
        "        pass\n"
        "def update() -> void:\n"
        "    CriticalSection database:\n"
        "        update_cache()\n"
        "def main() -> i32:\n"
        "    update()\n"
        "    return 0\n"
    )

    assert "CINDER_LOCK_STATE_INIT(0)" in generated
    assert "CINDER_LOCK_STATE_INIT(1)" in generated


def test_explicit_and_inferred_constraints_work_together() -> None:
    compile_source(
        "lock database\n"
        "lock cache after database\n"
        "def update_cache() -> void:\n"
        "    CriticalSection cache:\n"
        "        pass\n"
        "def main() -> i32:\n"
        "    CriticalSection database:\n"
        "        update_cache()\n"
        "    return 0\n"
    )


def test_caller_that_holds_later_lock_fails() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "lock database\n"
            "lock cache after database\n"
            "def update_database() -> void:\n"
            "    CriticalSection database:\n"
            "        pass\n"
            "def main() -> i32:\n"
            "    CriticalSection cache:\n"
            "        update_database()\n"
            "    return 0\n"
        )

    assert "cannot acquire 'database' while 'cache' is held" in str(captured.value)


def test_recursive_call_graph_without_reacquisition_is_valid() -> None:
    compile_source(
        "lock work\n"
        "def recurse(count: i32) -> void:\n"
        "    if count > 0:\n"
        "        recurse(count - 1)\n"
        "        return\n"
        "    CriticalSection work:\n"
        "        pass\n"
        "def main() -> i32:\n"
        "    recurse(2)\n"
        "    return 0\n"
    )


def test_dynamic_collection_codegen_sorts_once_and_releases_reverse() -> None:
    generated = compile_source(
        "lock database\n"
        "lock cache after database\n"
        "def main() -> i32:\n"
        "    locks: List[Lock] = [cache, database, database]\n"
        "    CriticalSection sorted(locks):\n"
        "        pass\n"
        "    return 0\n"
    )

    assert generated.count("CinderSorted_lock(") == 2
    assert "cinder_lock_acquire(" in generated
    assert "cinder_lock_release(" in generated
    assert "== __cinder_locks_" in generated
    assert "for (size_t __cinder_lock_release_" in generated


def test_plain_dynamic_list_requires_sorted() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "lock database\n"
            "def main() -> i32:\n"
            "    locks: List[Lock] = [database]\n"
            "    CriticalSection locks:\n"
            "        pass\n"
            "    return 0\n"
        )

    assert "sort the lock collection before you acquire it" in str(captured.value)


def test_sorted_lock_collection_cannot_change_before_acquisition() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "lock database\n"
            "lock cache\n"
            "def main() -> i32:\n"
            "    locks: List[Lock] = [database, cache]\n"
            "    ordered = sorted(locks)\n"
            "    ordered[0] = cache\n"
            "    CriticalSection ordered:\n"
            "        pass\n"
            "    return 0\n"
        )

    assert "cannot change a sorted lock collection" in str(captured.value)


def test_sorted_lock_collection_cannot_borrow_as_mutable_list_reference() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "lock first\n"
            "lock second after first\n"
            "def scramble(locks: &List[Lock], replacement: Lock) -> void:\n"
            "    locks[2] = replacement\n"
            "def main() -> i32:\n"
            "    locks: List[Lock] = [first, second, second]\n"
            "    ordered = sorted(locks)\n"
            "    scramble(ordered, first)\n"
            "    return 0\n"
        )

    assert "expected &List[Lock], got List[Lock]" in str(captured.value)


def test_sorted_lock_collection_can_borrow_as_const_list_reference() -> None:
    compile_source(
        "lock first\n"
        "lock second after first\n"
        "def count_locks(locks: &const List[Lock]) -> i32:\n"
        "    return cast[i32](len(locks))\n"
        "def main() -> i32:\n"
        "    locks: List[Lock] = [first, second, second]\n"
        "    ordered = sorted(locks)\n"
        "    return count_locks(ordered)\n"
    )


def test_unknown_dynamic_lock_cannot_nest() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "lock database\n"
            "def use(selected: Lock) -> void:\n"
            "    CriticalSection database:\n"
            "        CriticalSection selected:\n"
            "            pass\n"
            "def main() -> i32:\n"
            "    use(database)\n"
            "    return 0\n"
        )

    assert "cannot acquire a dynamic lock while another lock is held" in str(captured.value)


def write_project(root: Path) -> Path:
    source_root = root / "src"
    source_root.mkdir()
    (root / "cinder.toml").write_text(
        '[project]\nname = "locks"\nsource-root = "src"\nentry = "main.ci"\n',
        encoding="utf-8",
    )
    (source_root / "database.ci").write_text(
        "lock transaction\n"
        "lock cache after transaction\n"
        "def update_cache() -> void:\n"
        "    CriticalSection cache:\n"
        "        pass\n",
        encoding="utf-8",
    )
    (source_root / "session.ci").write_text(
        "lock active\n",
        encoding="utf-8",
    )
    entry = source_root / "main.ci"
    entry.write_text(
        "import database\n"
        "import session\n"
        "lockorder database.cache before session.active\n"
        "def main() -> i32:\n"
        "    CriticalSection database.transaction:\n"
        "        database.update_cache()\n"
        "        CriticalSection session.active:\n"
        "            pass\n"
        "    return 0\n",
        encoding="utf-8",
    )
    return entry


def test_cross_module_order_and_function_effect(tmp_path: Path) -> None:
    entry = write_project(tmp_path)
    project = Compiler().compile_project(entry)

    transaction = project.units_by_name["database"].semantic.locks["transaction"]
    cache = project.units_by_name["database"].semantic.locks["cache"]
    active = project.units_by_name["session"].semantic.locks["active"]
    assert transaction.canonical_key is not None
    assert transaction.canonical_key < cache.canonical_key < active.canonical_key


pytestmark_native = pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)


def build_and_run(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    source_path = tmp_path / "main.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "program.exe" if shutil.which("cl") and not shutil.which("cc") else "program"
    )
    Compiler().build(source_path, output=executable, build_dir=tmp_path / "build")
    return subprocess.run(
        [str(executable)],
        check=False,
        text=True,
        capture_output=True,
        timeout=5,
    )


@pytestmark_native
def test_dynamic_duplicates_and_tie_break_run(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "lock zeta\n"
        "lock alpha\n"
        "calls: i32 = 0\n"
        "def get_locks() -> List[Lock]:\n"
        "    calls += 1\n"
        "    return [zeta, alpha, alpha]\n"
        "def main() -> i32:\n"
        "    ordered = sorted(get_locks())\n"
        "    if calls != 1 or ordered[0] != alpha or ordered[2] != zeta:\n"
        "        return 1\n"
        "    CriticalSection ordered:\n"
        "        pass\n"
        "    return 0\n",
    )

    assert result.returncode == 0, result.stderr


@pytestmark_native
def test_cleanup_after_return_break_continue_and_propagation(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "lock resource\n"
        "enum Failure:\n"
        "    stopped\n"
        "def fail() -> Result[i32, Failure]:\n"
        "    return Err(Failure.stopped)\n"
        "def return_early() -> void:\n"
        "    CriticalSection resource:\n"
        "        return\n"
        "def loop_exits() -> void:\n"
        "    for value in range(0, 2):\n"
        "        CriticalSection resource:\n"
        "            if value == 0:\n"
        "                continue\n"
        "            break\n"
        "def propagate() -> Result[i32, Failure]:\n"
        "    CriticalSection resource:\n"
        "        value = fail()?\n"
        "        return Ok(value)\n"
        "def main() -> i32:\n"
        "    return_early()\n"
        "    return_early()\n"
        "    loop_exits()\n"
        "    loop_exits()\n"
        "    propagate()\n"
        "    CriticalSection resource:\n"
        "        pass\n"
        "    return 0\n",
    )

    assert result.returncode == 0, result.stderr

