from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("owned_test.ci")).c_source


def test_owned_construction_deref_and_drop_codegen() -> None:
    generated = compile_source(
        "def main() -> i32:\n"
        "    value: Owned[i32] = Owned(42)\n"
        "    *value = *value + 1\n"
        "    return *value\n"
    )

    assert "typedef struct CinderOwned_i32 CinderOwned_i32;" in generated
    assert "CinderOwned_i32_new(42)" in generated
    assert "(*(value).ptr)" in generated
    assert "CinderOwned_i32_drop(&value);" in generated
    assert "free(owned->ptr);" in generated


def test_owned_recursive_option_layout() -> None:
    generated = compile_source(
        "struct Node:\n"
        "    value: i32\n"
        "    next: Option[Owned[Node]]\n"
        "\n"
        "def main() -> i32:\n"
        "    leaf: Owned[Node] = Owned(Node(value=1, next=None))\n"
        "    root: Owned[Node] = Owned(Node(value=2, next=Some(leaf)))\n"
        "    return (*root).value\n"
    )

    assert "struct CinderOwned_n_Node" in generated
    assert "Node *ptr;" in generated
    assert "CinderOption_owned_n_Node" in generated
    assert "CinderOwned_n_Node_drop(&root);" in generated
    assert "CinderOwned_n_Node_drop(&leaf);" not in generated


def test_owned_drops_destructor_payload() -> None:
    generated = compile_source(
        "class Resource:\n"
        "    label: i32\n"
        "\n"
        "    def __init__(self, label: i32):\n"
        "        self.label = label\n"
        "\n"
        "    def __del__(self):\n"
        "        print(self.label)\n"
        "\n"
        "def main() -> i32:\n"
        "    owned: Owned[Resource] = Owned(Resource(7))\n"
        "    return 0\n"
    )

    assert "Resource__drop(&((*owned->ptr)));" in generated
    assert "CinderOwned_n_Resource_drop(&owned);" in generated


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "def main() -> void:\n"
            "    first: Owned[i32] = Owned(1)\n"
            "    second = first\n"
            "    print(first)\n",
            "use of moved value first",
        ),
        (
            "def main() -> void:\n"
            "    value: Owned[*i32] = Owned(null)\n",
            "invalid Owned payload type *i32",
        ),
        (
            "owned_global: Owned[i32] = Owned(1)\n",
            "global 'owned_global' cannot own a collection",
        ),
        (
            "def main() -> void:\n"
            "    value = 1\n"
            "    print(*value)\n",
            "dereference requires a pointer, reference, or Owned value",
        ),
        (
            "def take(value: &i32) -> void:\n"
            "    print(value)\n"
            "\n"
            "def main() -> void:\n"
            "    owned: Owned[i32] = Owned(3)\n"
            "    take(owned)\n",
            "expected &i32, got Owned[i32]",
        ),
    ],
)
def test_owned_diagnostics(source: str, message: str) -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(source)
    assert message in str(captured.value)


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)
def test_owned_runs_end_to_end(tmp_path: Path) -> None:
    source = (
        "class Resource:\n"
        "    label: i32\n"
        "\n"
        "    def __init__(self, label: i32):\n"
        "        self.label = label\n"
        "\n"
        "    def __del__(self):\n"
        "        print(\"drop\", self.label)\n"
        "\n"
        "struct Node:\n"
        "    value: i32\n"
        "    next: Option[Owned[Node]]\n"
        "\n"
        "def bump(node: &Node) -> void:\n"
        "    node.value = node.value + 1\n"
        "\n"
        "def main() -> i32:\n"
        "    number: Owned[i32] = Owned(40)\n"
        "    *number = *number + 2\n"
        "    resource: Owned[Resource] = Owned(Resource(1))\n"
        "    leaf: Owned[Node] = Owned(Node(value=10, next=None))\n"
        "    root: Owned[Node] = Owned(Node(value=20, next=Some(leaf)))\n"
        "    bump(&*root)\n"
        "    if (*root).value != 21:\n"
        "        return 1\n"
        "    moved = root\n"
        "    if (*moved).value != 21:\n"
        "        return 2\n"
        "    return *number\n"
    )
    source_path = tmp_path / "owned.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / (
        "owned.exe" if shutil.which("cl") and not shutil.which("cc") else "owned"
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
    assert result.returncode == 42, result.stderr
    assert "drop 1" in result.stdout
