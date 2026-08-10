from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed
from cinder.ir import (
    IRAtomicCompareExchange,
    IRAtomicFetch,
    IRAtomicInit,
    IRAtomicLoad,
    IRAtomicStore,
    validate_ir,
)
from cinder.ownership import (
    ValueUseKind,
    type_is_copyable,
    type_is_relocatable,
    type_needs_drop,
)
from cinder.symbols import AtomicIntrinsicKind
from cinder.types import U64, AtomicCompareExchangeResultType, AtomicType


def compile_unit(source: str):
    return Compiler().compile_source(source, Path("atomic_test.ci"))


def diagnostics(source: str) -> str:
    with pytest.raises(CompilationFailed) as captured:
        compile_unit(source)
    return str(captured.value)


def test_atomic_semantics_and_explicit_ir() -> None:
    unit = compile_unit(
        "from std.atomic import Atomic\n"
        "\n"
        "counter: Atomic[u64] = 0\n"
        "\n"
        "def main() -> i32:\n"
        "    counter.store(1)\n"
        "    old = counter.fetch_add(2)\n"
        "    result = counter.compare_exchange(expected=3, desired=4)\n"
        "    positional = counter.compare_exchange(4, 5)\n"
        "    if result.exchanged and result.observed == 3 and positional.exchanged and positional.observed == 4 and old == 1:\n"
        "        return 0\n"
        "    return 1\n"
    )

    assert unit.ir.atomic_types == (AtomicType(U64),)
    assert unit.ir.atomic_result_types == (AtomicCompareExchangeResultType(U64),)
    assert any(isinstance(operation, IRAtomicInit) for operation in unit.ir.atomic_operations)
    assert any(isinstance(operation, IRAtomicStore) for operation in unit.ir.atomic_operations)
    assert any(isinstance(operation, IRAtomicFetch) for operation in unit.ir.atomic_operations)
    assert any(
        isinstance(operation, IRAtomicCompareExchange) for operation in unit.ir.atomic_operations
    )
    assert {
        resolution.intrinsic for resolution in unit.semantic.atomic_call_resolutions.values()
    } == {
        AtomicIntrinsicKind.STORE,
        AtomicIntrinsicKind.FETCH_ADD,
        AtomicIntrinsicKind.COMPARE_EXCHANGE,
    }


def test_atomic_codegen_uses_c11_primitives_and_seq_cst() -> None:
    generated = compile_unit(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    value: Atomic[u64] = 1\n"
        "    loaded = value.load()\n"
        "    value.store(loaded)\n"
        "    exchanged = value.exchange(2)\n"
        "    added = value.fetch_add(3)\n"
        "    subtracted = value.fetch_sub(1)\n"
        "    anded = value.fetch_and(15)\n"
        "    ored = value.fetch_or(16)\n"
        "    xored = value.fetch_xor(7)\n"
        "    compared = value.compare_exchange(expected=0, desired=1)\n"
        "    return cast[i32](exchanged + added + subtracted + anded + ored + xored + loaded + compared.observed)\n"
    ).c_source

    assert "#include <stdatomic.h>" in generated
    assert "_Atomic(uint64_t) value;" in generated
    assert "atomic_init(&value.value, UINT64_C(1));" in generated
    for operation in (
        "atomic_load_explicit",
        "atomic_store_explicit",
        "atomic_exchange_explicit",
        "atomic_fetch_add_explicit",
        "atomic_fetch_sub_explicit",
        "atomic_fetch_and_explicit",
        "atomic_fetch_or_explicit",
        "atomic_fetch_xor_explicit",
        "atomic_compare_exchange_strong_explicit",
    ):
        assert operation in generated
    assert generated.count("memory_order_seq_cst") >= 10


def test_atomic_global_uses_static_atomic_initializer() -> None:
    generated = compile_unit(
        "from std.atomic import Atomic\n"
        "\n"
        "counter: Atomic[u32] = 7\n"
        "ready: Atomic[bool] = false\n"
        "size: Atomic[usize] = 0\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n"
    ).c_source

    assert "ATOMIC_VAR_INIT(7)" in generated
    assert "ATOMIC_VAR_INIT(false)" in generated
    assert "ATOMIC_VAR_INIT(0)" in generated


def test_atomic_c_generation_is_deterministic() -> None:
    source = (
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    counter: Atomic[u64] = 0\n"
        "    return cast[i32](counter.fetch_add(1))\n"
    )
    assert compile_unit(source).c_source == compile_unit(source).c_source


def test_atomic_pointer_declarations_emit_opaque_cell_type_without_operations() -> None:
    unit = compile_unit(
        "from std.atomic import Atomic\n"
        "\n"
        "def identity(cell: *Atomic[u64]) -> *Atomic[u64]:\n"
        "    return cell\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n"
    )

    assert unit.ir.atomic_operations == ()
    assert unit.ir.atomic_types == (AtomicType(U64),)
    assert "#include <stdatomic.h>" in unit.c_source
    assert "_Atomic(uint64_t) value;" in unit.c_source


def test_atomic_generic_pointer_inference_checks_argument_once() -> None:
    generated = compile_unit(
        "from std.atomic import Atomic\n"
        "\n"
        "def read[T](cell: *Atomic[T]) -> T:\n"
        "    return cell.load()\n"
        "\n"
        "def main() -> i32:\n"
        "    cell: Atomic[u64] = 7\n"
        "    return cast[i32](read(&cell))\n"
    ).c_source

    assert "read_u64" in generated
    assert "atomic_load_explicit" in generated


def test_atomic_rejects_receiver_beyond_one_pointer_layer() -> None:
    rendered = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    cell: Atomic[u64] = 0\n"
        "    pointer: *Atomic[u64] = &cell\n"
        "    indirect: **Atomic[u64] = &pointer\n"
        "    return cast[i32](indirect.load())\n"
    )

    assert "has no member 'load'" in rendered


def test_atomic_receiver_records_address_use() -> None:
    unit = compile_unit(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    counter: Atomic[u64] = 0\n"
        "    return cast[i32](counter.fetch_add(1))\n"
    )
    call = next(iter(unit.semantic.atomic_call_resolutions.values()))
    use = unit.semantic.value_use(call.receiver)
    assert use is not None
    assert use.kind is ValueUseKind.ADDRESS


def test_atomic_storage_is_noncopyable_immobile_and_not_droppable() -> None:
    atomic_type = AtomicType(U64)
    classes = {}
    structs = {}
    assert not type_is_copyable(atomic_type, classes=classes, structs=structs)
    assert not type_is_relocatable(atomic_type, classes=classes, structs=structs)
    assert not type_needs_drop(atomic_type, classes=classes, structs=structs)


@pytest.mark.parametrize("payload", ["i32", "u16", "f64", "String", "List[u64]"])
def test_atomic_rejects_unsupported_payload(payload: str) -> None:
    rendered = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        f"    value: Atomic[{payload}] = 0\n"
        "    return 0\n"
    )
    assert "unsupported atomic element type" in rendered
    assert "bool, u32, u64, and usize" in rendered


@pytest.mark.parametrize(
    "method",
    ["fetch_add", "fetch_sub", "fetch_and", "fetch_or", "fetch_xor"],
)
def test_atomic_bool_rejects_fetch_operations(method: str) -> None:
    rendered = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    ready: Atomic[bool] = false\n"
        f"    ready.{method}(true)\n"
        "    return 0\n"
    )
    assert f"{method} is not available on Atomic[bool]" in rendered


def test_atomic_rejects_implicit_load_store_copy_and_constructor() -> None:
    implicit_load = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    counter: Atomic[u64] = 0\n"
        "    value: u64 = counter\n"
        "    return cast[i32](value)\n"
    )
    assert "not implicitly loaded" in implicit_load

    implicit_store = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    counter: Atomic[u64] = 0\n"
        "    counter = 1\n"
        "    return 0\n"
    )
    assert "ordinary assignment cannot mutate or replace an Atomic cell" in implicit_store

    copied = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    first: Atomic[u64] = 0\n"
        "    second: Atomic[u64] = first\n"
        "    return 0\n"
    )
    assert "cannot copy an Atomic cell" in copied

    constructed = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    value = Atomic[u64](0)\n"
        "    return 0\n"
    )
    assert "Atomic[u64] cannot be constructed" in constructed


def test_atomic_method_arguments_are_checked_semantically() -> None:
    wrong_type = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    counter: Atomic[u64] = 0\n"
        '    counter.store("bad")\n'
        "    return 0\n"
    )
    assert "expected u64, got String" in wrong_type

    wrong_shape = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    counter: Atomic[u64] = 0\n"
        "    counter.load(1)\n"
        "    counter.compare_exchange(expected=0, replacement=1)\n"
        "    return 0\n"
    )
    assert "too many arguments for 'load'" in wrong_shape
    assert "has no parameter 'replacement'" in wrong_shape
    assert "missing argument 'desired'" in wrong_shape


@pytest.mark.parametrize("statement", ["counter.load", "print(counter.load)"])
def test_atomic_method_attributes_must_be_called(statement: str) -> None:
    rendered = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    counter: Atomic[u64] = 0\n"
        f"    {statement}\n"
        "    return 0\n"
    )

    assert "C403" in rendered
    assert "atomic method 'load' must be called" in rendered


def test_atomic_requires_initializer_and_rejects_by_value_storage() -> None:
    missing = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    value: Atomic[u64]\n"
        "    return 0\n"
    )
    assert "atomic local 'value' requires an initializer" in missing

    field = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "struct Holder:\n"
        "    value: Atomic[u64]\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n"
    )
    assert "cannot contain atomic storage" in field

    parameter = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "def consume(value: Atomic[u64]) -> void:\n"
        "    pass\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n"
    )
    assert "cannot pass atomic storage by value" in parameter


def test_late_generic_specialization_rejects_atomic_fields() -> None:
    field = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "struct Box[T]:\n"
        "    value: T\n"
        "\n"
        "def main() -> i32:\n"
        "    boxed: Box[Atomic[u64]]\n"
        "    return 0\n"
    )
    assert "C395" in field
    assert "struct field Box.value cannot contain atomic storage" in field

    generated = compile_unit(
        "from std.atomic import Atomic\n"
        "\n"
        "struct Box[T]:\n"
        "    value: T\n"
        "\n"
        "def main() -> i32:\n"
        "    boxed: Box[*Atomic[u64]]\n"
        "    return 0\n"
    ).c_source
    assert "CinderAtomic_u64 *value;" in generated


def test_atomic_reference_receiver_is_supported() -> None:
    generated = compile_unit(
        "from std.atomic import Atomic\n"
        "\n"
        "def increment(counter: &Atomic[u64]) -> u64:\n"
        "    return counter.fetch_add(1)\n"
        "\n"
        "def main() -> i32:\n"
        "    counter: Atomic[u64] = 0\n"
        "    return cast[i32](increment(&counter))\n"
    ).c_source
    assert "atomic_fetch_add_explicit" in generated


@pytest.mark.parametrize("handle_type", ("*Atomic[u64]", "&Atomic[u64]"))
def test_atomic_const_handle_binding_can_mutate_cell(handle_type: str) -> None:
    generated = compile_unit(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    cell: Atomic[u64] = 0\n"
        f"    const handle: {handle_type} = &cell\n"
        "    handle.store(5)\n"
        "    return cast[i32](handle.load())\n"
    ).c_source

    assert "atomic_store_explicit" in generated


def test_atomic_const_pointee_rejects_mutation() -> None:
    rendered = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    cell: Atomic[u64] = 0\n"
        "    handle: *const Atomic[u64] = &cell\n"
        "    handle.store(5)\n"
        "    return 0\n"
    )

    assert "cannot mutate an Atomic cell through a const receiver" in rendered


def test_atomic_pointer_argument_requires_matching_element_type() -> None:
    rendered = diagnostics(
        "from std.atomic import Atomic\n"
        "\n"
        "def load64(cell: *Atomic[u64]) -> u64:\n"
        "    return cell.load()\n"
        "\n"
        "def main() -> i32:\n"
        "    narrow: Atomic[u32] = 0\n"
        "    load64(&narrow)\n"
        "    return 0\n"
    )

    assert "expected *Atomic[u64], got *Atomic[u32]" in rendered


def test_atomic_ir_validation_rejects_malformed_operation() -> None:
    unit = compile_unit(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    counter: Atomic[u64] = 0\n"
        "    return cast[i32](counter.load())\n"
    )
    operation = next(
        operation for operation in unit.ir.atomic_operations if isinstance(operation, IRAtomicLoad)
    )
    malformed = replace(operation, result_type=AtomicCompareExchangeResultType(U64))
    invalid_module = replace(
        unit.ir,
        atomic_operations=tuple(
            malformed if item is operation else item for item in unit.ir.atomic_operations
        ),
    )
    with pytest.raises(ValueError, match="wrong result type"):
        validate_ir(invalid_module)


pytestmark_native = pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc")),
    reason="no C11 atomic-capable compiler is available",
)


@pytestmark_native
def test_atomic_operations_compile_and_run(tmp_path: Path) -> None:
    source = tmp_path / "main.ci"
    source.write_text(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    counter: Atomic[u64] = 1\n"
        "    ready: Atomic[bool] = false\n"
        "    if ready.exchange(true):\n"
        "        return 10\n"
        "    ready_result = ready.compare_exchange(expected=true, desired=false)\n"
        "    if not ready_result.exchanged or not ready_result.observed:\n"
        "        return 11\n"
        "    ready_ref: &const Atomic[bool] = &ready\n"
        "    if ready_ref.load():\n"
        "        return 12\n"
        "    if counter.load() != 1:\n"
        "        return 1\n"
        "    counter.store(5)\n"
        "    if counter.exchange(7) != 5:\n"
        "        return 2\n"
        "    if counter.fetch_add(3) != 7:\n"
        "        return 3\n"
        "    if counter.fetch_sub(2) != 10:\n"
        "        return 4\n"
        "    if counter.fetch_and(6) != 8:\n"
        "        return 5\n"
        "    if counter.fetch_or(9) != 0:\n"
        "        return 6\n"
        "    if counter.fetch_xor(3) != 9:\n"
        "        return 7\n"
        "    success = counter.compare_exchange(expected=10, desired=20)\n"
        "    if not success.exchanged or success.observed != 10:\n"
        "        return 8\n"
        "    failure = counter.compare_exchange(expected=10, desired=30)\n"
        "    if failure.exchanged or failure.observed != 20:\n"
        "        return 9\n"
        "    return 0\n",
        encoding="utf-8",
    )
    executable = tmp_path / "atomic"
    Compiler().build(source, output=executable, build_dir=tmp_path / "build")
    result = subprocess.run(
        [str(executable)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


@pytestmark_native
def test_atomic_argument_evaluation_is_once_and_left_to_right(
    tmp_path: Path,
) -> None:
    source = tmp_path / "main.ci"
    source.write_text(
        "from std.atomic import Atomic\n"
        "\n"
        "counter: Atomic[u64] = 0\n"
        "order: u64 = 0\n"
        "\n"
        "def get_counter() -> *Atomic[u64]:\n"
        "    order = order * 10 + 1\n"
        "    return &counter\n"
        "\n"
        "def get_delta() -> u64:\n"
        "    order = order * 10 + 2\n"
        "    return 3\n"
        "\n"
        "def get_expected() -> u64:\n"
        "    order = order * 10 + 3\n"
        "    return 3\n"
        "\n"
        "def get_desired() -> u64:\n"
        "    order = order * 10 + 4\n"
        "    return 4\n"
        "\n"
        "def main() -> i32:\n"
        "    old = get_counter().fetch_add(get_delta())\n"
        "    if old != 0 or counter.load() != 3 or order != 12:\n"
        "        return 1\n"
        "    order = 0\n"
        "    result = get_counter().compare_exchange(\n"
        "        desired=get_desired(),\n"
        "        expected=get_expected(),\n"
        "    )\n"
        "    if not result.exchanged or result.observed != 3:\n"
        "        return 2\n"
        "    if counter.load() != 4 or order != 143:\n"
        "        return 3\n"
        "    return 0\n",
        encoding="utf-8",
    )
    executable = tmp_path / "atomic_order"
    Compiler().build(source, output=executable, build_dir=tmp_path / "build")
    result = subprocess.run(
        [str(executable)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


@pytestmark_native
def test_atomic_calls_preserve_short_circuit_and_loop_behavior(
    tmp_path: Path,
) -> None:
    source = tmp_path / "main.ci"
    source.write_text(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    counter: Atomic[u64] = 0\n"
        "    if false and counter.fetch_add(100) == 0:\n"
        "        return 1\n"
        "    iterations: i32 = 0\n"
        "    while counter.fetch_add(1) < 2:\n"
        "        iterations += 1\n"
        "    if iterations != 2 or counter.load() != 3:\n"
        "        return 2\n"
        "    return 0\n",
        encoding="utf-8",
    )
    executable = tmp_path / "atomic_control_flow"
    Compiler().build(source, output=executable, build_dir=tmp_path / "build")
    result = subprocess.run(
        [str(executable)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
