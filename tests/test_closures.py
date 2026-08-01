from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("closure_test.ci")).c_source


def test_closure_pass_store_and_call_codegen() -> None:
    generated = compile_source(
        "struct AddEnv:\n"
        "    delta: i32\n"
        "\n"
        "\n"
        "def add_impl(env: &const AddEnv, value: i32) -> i32:\n"
        "    return value + env.delta\n"
        "\n"
        "\n"
        "def apply(callback: closure[const AddEnv](i32) -> i32, value: i32) -> i32:\n"
        "    return callback(value)\n"
        "\n"
        "\n"
        "def main() -> i32:\n"
        "    callback = closure(AddEnv(delta=2), add_impl)\n"
        "    typed: closure[const AddEnv](i32) -> i32 = closure(AddEnv(delta=3), add_impl)\n"
        "    return apply(callback, 40) + typed(1)\n"
    )

    assert "AddEnv env;" in generated
    assert "int32_t (*call)(const AddEnv *, int32_t);" in generated
    assert ".call = add_impl" in generated
    assert "->call(&" in generated


def test_closure_nested_in_function_pointer_return_is_declared() -> None:
    generated = compile_source(
        "struct Env:\n"
        "    value: i32\n"
        "\n"
        "\n"
        "def accept(factory: def() -> closure[const Env]() -> i32) -> i32:\n"
        "    return 0\n"
    )

    assert "typedef struct CinderClosure_closure_const_env_n_Env_ret_i32" in generated


def test_closure_mutable_environment_codegen() -> None:
    generated = compile_source(
        "struct CounterEnv:\n"
        "    value: i32\n"
        "\n"
        "\n"
        "def next_value(env: &CounterEnv, delta: i32) -> i32:\n"
        "    env.value += delta\n"
        "    return env.value\n"
        "\n"
        "\n"
        "def main() -> i32:\n"
        "    counter: closure[CounterEnv](i32) -> i32 = closure(CounterEnv(value=0), next_value)\n"
        "    return counter(5)\n"
    )

    assert "int32_t (*call)(CounterEnv *, int32_t);" in generated
    assert "counter" in generated


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "struct Env:\n"
            "    value: i32\n"
            "\n"
            "\n"
            "def bad(value: i32) -> i32:\n"
            "    return value\n"
            "\n"
            "\n"
            "def main() -> i32:\n"
            "    callback = closure(Env(value=1), bad)\n"
            "    return callback(1)\n",
            "closure adapter first parameter must be an environment reference",
        ),
        (
            "struct Env:\n"
            "    value: i32\n"
            "\n"
            "\n"
            "def apply(env: &const Env, value: i32) -> i32:\n"
            "    return value + env.value\n"
            "\n"
            "\n"
            "def main() -> i32:\n"
            "    callback = closure(Env(value=1), apply)\n"
            "    return callback(value=1)\n",
            "closure calls do not support named arguments",
        ),
        (
            "struct Env:\n"
            "    value: i32\n"
            "\n"
            "\n"
            "def apply(env: &const Env, value: i32) -> i32:\n"
            "    return value + env.value\n"
            "\n"
            "\n"
            "def main() -> i32:\n"
            "    callback: def(i32) -> i32 = closure(Env(value=1), apply)\n"
            "    return callback(1)\n",
            "expected def(i32) -> i32, got closure[const Env](i32) -> i32",
        ),
        (
            "struct Env:\n"
            "    text: String\n"
            "\n"
            "\n"
            "def length(env: &const Env) -> usize:\n"
            "    return len(env.text)\n"
            "\n"
            "\n"
            "def main() -> i32:\n"
            "    env = Env(text=\"hi\")\n"
            "    callback = closure(env, length)\n"
            "    return len(env.text)\n",
            "use of moved value env",
        ),
        (
            "struct Env:\n"
            "    callback: closure[Env]() -> i32\n"
            "\n"
            "\n"
            "def main() -> i32:\n"
            "    return 0\n",
            "recursive by-value aggregate layout",
        ),
    ],
)
def test_closure_diagnostics(source: str, message: str) -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(source)
    assert message in str(captured.value)


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_closures_run_end_to_end(tmp_path: Path) -> None:
    source = (
        "struct CounterEnv:\n"
        "    value: i32\n"
        "\n"
        "\n"
        "def next_value(env: &CounterEnv, delta: i32) -> i32:\n"
        "    env.value += delta\n"
        "    return env.value\n"
        "\n"
        "\n"
        "def main() -> i32:\n"
        "    counter = closure(CounterEnv(value=1), next_value)\n"
        "    if counter(2) != 3:\n"
        "        return 1\n"
        "    if counter(4) != 7:\n"
        "        return 2\n"
        "    return 0\n"
    )
    source_path = tmp_path / "closures.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "closures.exe" if shutil.which("cl") and not shutil.which("cc") else "closures"
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
