from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler

ROOT = Path(__file__).resolve().parents[1]


pytestmark = pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)


@pytest.fixture(scope="module")
def gen1_compiler(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build_root = tmp_path_factory.mktemp("bootstrap_gen1_build")
    executable = build_root / (
        "cinder-gen1.exe" if shutil.which("cl") and not shutil.which("cc") else "cinder-gen1"
    )
    artifact = Compiler().build(
        ROOT / "compiler_selfhost",
        output=executable,
        build_dir=build_root / "build",
    )
    return artifact.executable


@pytest.fixture(scope="module")
def gen2_compiler(gen1_compiler: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    build_root = tmp_path_factory.mktemp("bootstrap_gen2_build")
    gen2 = build_root / (
        "cinder-gen2.exe" if shutil.which("cl") and not shutil.which("cc") else "cinder-gen2"
    )
    build_dir = build_root / "build"
    built = run_gen1(
        gen1_compiler,
        "build",
        str(ROOT / "compiler_selfhost"),
        "-o",
        str(gen2),
        "--build-dir",
        str(build_dir),
    )
    assert built.returncode == 0, built.stderr
    assert built.stdout.strip() == str(gen2.resolve())
    assert gen2.is_file()
    return gen2, build_dir


@pytest.fixture(scope="module")
def gen3_compiler(
    gen2_compiler: tuple[Path, Path],
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    gen2, _gen2_build_dir = gen2_compiler
    build_root = tmp_path_factory.mktemp("bootstrap_gen3_build")
    gen3 = build_root / (
        "cinder-gen3.exe" if shutil.which("cl") and not shutil.which("cc") else "cinder-gen3"
    )
    built = run_gen1(
        gen2,
        "build",
        str(ROOT / "compiler_selfhost"),
        "-o",
        str(gen3),
        "--build-dir",
        str(build_root / "build"),
    )
    assert built.returncode == 0, built.stderr
    assert built.stdout.strip() == str(gen3.resolve())
    assert gen3.is_file()
    return gen3


def run_gen1(gen1: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(gen1), *arguments],
        check=False,
        text=True,
        capture_output=True,
    )


def run_gen1_without_python_on_path(
    gen1: Path,
    tmp_path: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    empty_path = tmp_path / "empty-bin"
    empty_path.mkdir()
    env = {**os.environ, "PATH": str(empty_path)}
    return subprocess.run(
        [str(gen1), *arguments],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )


def compile_generated_project(
    generated_root: Path,
    output: Path,
) -> subprocess.CompletedProcess[str]:
    compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    assert compiler is not None
    generated_sources = sorted((generated_root / "cinder_gen").rglob("*.c"))
    assert generated_sources
    return subprocess.run(
        [
            compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-O2",
            "-I",
            str(ROOT / "cinder" / "runtime"),
            "-I",
            str(generated_root),
            "-I",
            str(ROOT / "compiler_selfhost" / "src"),
            *(str(path) for path in generated_sources),
            str(ROOT / "cinder" / "runtime" / "cinder_runtime.c"),
            "-o",
            str(output),
        ],
        check=False,
        text=True,
        capture_output=True,
    )


def write_single_source(tmp_path: Path) -> Path:
    source = tmp_path / "single.ci"
    source.write_text("def main() -> i32:\n    return 42\n", encoding="utf-8")
    return source


def write_project(tmp_path: Path) -> Path:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"selfhost_cli_demo\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "maths.ci").write_text(
        "def answer() -> i32:\n    return 42\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import maths\n"
        "\n"
        "def main() -> i32:\n"
        "    return maths.answer()\n",
        encoding="utf-8",
    )
    return tmp_path / "cinder.toml"


def write_class_foundation_project(tmp_path: Path) -> Path:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        'name = "class_foundation"\n'
        'source-root = "src"\n'
        'entry = "main.ci"\n',
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "class Counter:\n"
        "    value: i32\n"
        "\n"
        "    def read(self) -> i32:\n"
        "        return read_counter(self)\n"
        "\n"
        "    def read_const(self: &const Counter) -> i32:\n"
        "        return read_counter(self)\n"
        "\n"
        "def read_counter(counter: &const Counter) -> i32:\n"
        "    return counter.value\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        encoding="utf-8",
    )
    return tmp_path / "cinder.toml"


def assert_compiler_lowers_imported_result_propagation(
    compiler: Path,
    tmp_path: Path,
) -> None:
    manifest = ROOT / "examples" / "module_project" / "cinder.toml"
    generated = tmp_path / "imported-result-generated"
    emitted = run_gen1(
        compiler,
        "emit-project",
        str(manifest),
        "-o",
        str(generated),
    )
    assert emitted.returncode == 0, emitted.stderr

    main_c = (generated / "cinder_gen" / "main.c").read_text(encoding="utf-8")
    imported_call = "cinder_module_demo_support_parser__parse(value)"
    assert "CinderResult_" in main_c
    assert f" cinder_result = {imported_call};" in main_c
    assert "if (cinder_result.tag == CinderResult_" in main_c
    assert ".data.err = cinder_result.data.err" in main_c
    assert "cinder_result.data.ok; })" in main_c
    assert "__auto_type token = 0;" not in main_c

    executable = tmp_path / (
        "module-project.exe" if shutil.which("cl") and not shutil.which("cc") else "module-project"
    )
    built = run_gen1(
        compiler,
        "build",
        str(manifest),
        "-o",
        str(executable),
        "--build-dir",
        str(tmp_path / "imported-result-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run(
        [str(executable)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "value=42\n"


def assert_compiler_lowers_result_state_fields(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "result_state_fields.ci"
    source.write_text(
        "enum Failure:\n"
        "    rejected\n"
        "\n"
        "def success() -> Result[i32, Failure]:\n"
        "    return Ok(42)\n"
        "\n"
        "def failure() -> Result[i32, Failure]:\n"
        "    return Err(Failure.rejected)\n"
        "\n"
        "def main() -> i32:\n"
        "    ok = success()\n"
        "    err = failure()\n"
        "    if not success().is_ok or success().is_err:\n"
        "        return 1\n"
        "    if failure().is_ok or not failure().is_err:\n"
        "        return 2\n"
        "    if not ok.is_ok or ok.is_err:\n"
        "        return 3\n"
        "    if err.is_ok or not err.is_err:\n"
        "        return 4\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    generated = emitted.stdout
    assert "CinderResult_i32_Failure_Tag_Ok" in generated
    assert "CinderResult_i32_Failure_Tag_Err" in generated
    assert ".is_ok" not in generated
    assert ".is_err" not in generated

    executable = tmp_path / (
        "result-state-fields.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "result-state-fields"
    )
    built = run_gen1(
        compiler,
        "build",
        str(source),
        "-o",
        str(executable),
        "--build-dir",
        str(tmp_path / "result-state-fields-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(executable)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr


def assert_compiler_uses_match_field_types_in_fstrings(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "match_field_fstrings.ci"
    source.write_text(
        "variant Event:\n"
        "    Number(source: i32)\n"
        "    Text(source: String)\n"
        "\n"
        "def report(event: Event) -> void:\n"
        "    match event:\n"
        "        case Event.Number(source):\n"
        '            print(f"number={source}")\n'
        "        case Event.Text(source):\n"
        '            print(f"text={source}")\n'
        "\n"
        "def main() -> i32:\n"
        "    report(Event.Number(7))\n"
        '    report(Event.Text("ok"))\n'
        '    match parse_i32("9"):\n'
        "        case Ok(source):\n"
        '            print(f"semantic={source}")\n'
        "        case Err(_):\n"
        "            return 1\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    generated = emitted.stdout
    assert generated.count('printf("%lld", (long long)(source));') == 2
    assert generated.count("cinder_selfhost_print_string_fragment(source);") == 1

    executable = tmp_path / (
        "match-field-fstrings.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "match-field-fstrings"
    )
    built = run_gen1(
        compiler,
        "build",
        str(source),
        "-o",
        str(executable),
        "--build-dir",
        str(tmp_path / "match-field-fstrings-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(executable)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "number=7\ntext=ok\nsemantic=9\n"

    dijkstra_executable = tmp_path / (
        "dijkstra-showcase.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "dijkstra-showcase"
    )
    dijkstra_built = run_gen1(
        compiler,
        "build",
        str(ROOT / "examples" / "dijkstra_showcase.ci"),
        "-o",
        str(dijkstra_executable),
        "--build-dir",
        str(tmp_path / "dijkstra-showcase-build"),
    )
    assert dijkstra_built.returncode == 0, dijkstra_built.stderr
    dijkstra_ran = subprocess.run(
        [str(dijkstra_executable)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert dijkstra_ran.returncode == 0, dijkstra_ran.stderr


def assert_compiler_borrows_list_for_binary_sort(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = ROOT / "examples" / "binary_sort.ci"
    emitted = run_gen1(compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    generated = emitted.stdout
    signature = "void cinder_binary_sort_binary_sort__binary_sort(CinderList values) {"
    assert signature in generated
    binary_sort_body = generated.split(signature, 1)[1].split("\n}\n", 1)[0]
    assert "free(values.data)" not in binary_sort_body
    assert "cinder_slice_list = &values" in generated
    assert (
        "(CinderList){ .data = (void *)cinder_slice_list->data, "
        ".length = cinder_slice_list->length, .capacity = 0 }"
    ) in generated

    executable = tmp_path / (
        "binary-sort.exe" if shutil.which("cl") and not shutil.which("cc") else "binary-sort"
    )
    built = run_gen1(
        compiler,
        "build",
        str(source),
        "-o",
        str(executable),
        "--build-dir",
        str(tmp_path / "binary-sort-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run(
        [str(executable)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "[3, 5, 10, 13, 14, 29, 37, 42]\n"
    assert ran.stderr == ""


def assert_compiler_orders_nested_option_result_specializations(
    compiler: Path,
    tmp_path: Path,
) -> None:
    expressive = ROOT / "examples" / "expressive_match.ci"
    emitted = run_gen1(compiler, "emit-c", str(expressive))
    assert emitted.returncode == 0, emitted.stderr
    generated = emitted.stdout
    result = generated.index("struct CinderResult_i32_ParseError {")
    option = generated.index("struct CinderOption_CinderResult_i32_ParseError {")
    assert result < option

    executable = tmp_path / (
        "expressive-match.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "expressive-match"
    )
    built = run_gen1(
        compiler,
        "build",
        str(expressive),
        "-o",
        str(executable),
        "--build-dir",
        str(tmp_path / "expressive-match-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(executable)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr

    ordering_source = tmp_path / "nested_specialization_order.ci"
    ordering_source.write_text(
        "enum Error:\n"
        "    invalid\n"
        "\n"
        "struct Holder:\n"
        "    value: Option[i32]\n"
        "\n"
        "def preserve(\n"
        "    nested: Option[Tuple[Result[i32, Error]]],\n"
        "    holder: Holder,\n"
        ") -> i32:\n"
        "    return 0\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        encoding="utf-8",
    )
    ordering_emitted = run_gen1(compiler, "emit-c", str(ordering_source))
    assert ordering_emitted.returncode == 0, ordering_emitted.stderr
    ordering_c = ordering_emitted.stdout
    ordinary_option = ordering_c.index("struct CinderOption_i32 {")
    nominal_prefix = (
        "cinder_nested_specialization_order_nested_specialization_order__"
    )
    holder = ordering_c.index(f"struct {nominal_prefix}Holder {{")
    error = ordering_c.index(f"typedef enum {nominal_prefix}Error {{")
    nested_result = ordering_c.index("struct CinderResult_i32_Error {")
    nested_tuple = ordering_c.index("struct CinderTuple_CinderResult_i32_Error {")
    nested_option = ordering_c.index(
        "struct CinderOption_CinderTuple_CinderResult_i32_Error {"
    )
    assert ordinary_option < holder
    assert error < nested_result < nested_tuple < nested_option

    ordering_executable = tmp_path / (
        "nested-specialization-order.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "nested-specialization-order"
    )
    ordering_built = run_gen1(
        compiler,
        "build",
        str(ordering_source),
        "-o",
        str(ordering_executable),
        "--build-dir",
        str(tmp_path / "nested-specialization-order-build"),
    )
    assert ordering_built.returncode == 0, ordering_built.stderr
    ordering_ran = subprocess.run(
        [str(ordering_executable)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert ordering_ran.returncode == 0, ordering_ran.stderr


def assert_compiler_emits_class_foundation(
    compiler: Path,
    tmp_path: Path,
) -> None:
    manifest = write_class_foundation_project(tmp_path)
    generated = tmp_path / "generated"
    emitted = run_gen1(
        compiler,
        "emit-project",
        str(manifest),
        "-o",
        str(generated),
    )
    assert emitted.returncode == 0, emitted.stderr

    header = (generated / "cinder_gen" / "main.cinder.h").read_text(encoding="utf-8")
    source = (generated / "cinder_gen" / "main.c").read_text(encoding="utf-8")
    counter = "cinder_class_foundation_main__Counter"
    assert f"struct {counter} {{\n    int32_t value;\n}};" in header
    assert f"{counter} *self" in header
    assert f"const {counter} * self" in header
    assert "int32_t self" not in header
    assert f"{counter} *self" in source
    assert "cinder_class_foundation_main__read_counter(self)" in source
    assert "cinder_class_foundation_main__read_counter(&self)" not in source

    executable = tmp_path / (
        "class-foundation.exe" if shutil.which("cl") and not shutil.which("cc") else "class-foundation"
    )
    compiled = compile_generated_project(generated, executable)
    assert compiled.returncode == 0, compiled.stderr
    assert subprocess.run([str(executable)], check=False).returncode == 0


def assert_compiler_lowers_class_dyn_dispatch(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "class_dyn.ci"
    source.write_text(
        "abstract class Base:\n"
        "    value: i32\n"
        "\n"
        "    def __init__(self, value: i32):\n"
        "        self.value = value\n"
        "\n"
        "    @abstractmethod\n"
        "    def evaluate(self) -> i32:\n"
        "        pass\n"
        "\n"
        "    def doubled(self) -> i32:\n"
        "        return self.evaluate() * 2\n"
        "\n"
        "class Child(Base):\n"
        "    extra: i32\n"
        "\n"
        "    def __init__(self, value: i32, extra: i32):\n"
        "        super().__init__(value)\n"
        "        self.extra = extra\n"
        "\n"
        "    @override\n"
        "    def evaluate(self) -> i32:\n"
        "        return self.value + self.extra\n"
        "\n"
        "def measure(value: &dyn Base) -> i32:\n"
        "    return value.doubled()\n"
        "\n"
        "def main() -> i32:\n"
        "    child = Child(20, 1)\n"
        "    if child.evaluate() != 21:\n"
        "        return 1\n"
        "    if measure(child) != 42:\n"
        "        return 2\n"
        "    return 0\n",
        encoding="utf-8",
    )
    build_dir = tmp_path / "class-dyn-build"
    executable = tmp_path / (
        "class-dyn.exe" if shutil.which("cl") and not shutil.which("cc") else "class-dyn"
    )
    built = run_gen1(
        compiler,
        "build",
        str(source),
        "-o",
        str(executable),
        "--build-dir",
        str(build_dir),
    )
    assert built.returncode == 0, built.stderr
    generated = (build_dir / "cinder_gen" / "class_dyn.c").read_text(encoding="utf-8")
    header = (build_dir / "cinder_gen" / "class_dyn.cinder.h").read_text(encoding="utf-8")
    assert "Base _base;" in header
    assert "typedef struct CinderDyn_" in header
    assert ".vtable->evaluate(" in generated
    assert "__as__" in generated
    assert "__vtable" in generated
    assert "super(" not in generated
    result = subprocess.run([str(executable)], check=False, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def assert_compiler_lowers_cross_module_dyn(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    manifest = tmp_path / "cinder.toml"
    manifest.write_text(
        "[project]\n"
        'name = "class_dyn_project"\n'
        'source-root = "src"\n'
        'entry = "main.ci"\n',
        encoding="utf-8",
    )
    (source_root / "shapes.ci").write_text(
        "abstract class Shape:\n"
        "    @abstractmethod\n"
        "    def area(self) -> i32:\n"
        "        pass\n"
        "\n"
        "    def scaled(self, factor: i32) -> i32:\n"
        "        return self.area() * factor\n"
        "\n"
        "def measure(shape: &dyn Shape) -> i32:\n"
        "    return shape.scaled(2)\n",
        encoding="utf-8",
    )
    (source_root / "models.ci").write_text(
        "from shapes import Shape\n"
        "\n"
        "class Circle(Shape):\n"
        "    radius: i32\n"
        "\n"
        "    def __init__(self, radius: i32):\n"
        "        self.radius = radius\n"
        "\n"
        "    @override\n"
        "    def area(self) -> i32:\n"
        "        return self.radius\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import shapes\n"
        "from models import Circle\n"
        "\n"
        "def main() -> i32:\n"
        "    circle = Circle(21)\n"
        "    return shapes.measure(circle) - 42\n",
        encoding="utf-8",
    )
    build_dir = tmp_path / "cross-module-class-dyn-build"
    executable = tmp_path / (
        "cross-module-class-dyn.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "cross-module-class-dyn"
    )
    built = run_gen1(
        compiler,
        "build",
        str(manifest),
        "-o",
        str(executable),
        "--build-dir",
        str(build_dir),
    )
    assert built.returncode == 0, built.stderr
    models_header = (build_dir / "cinder_gen" / "models.cinder.h").read_text(
        encoding="utf-8"
    )
    main_source = (build_dir / "cinder_gen" / "main.c").read_text(encoding="utf-8")
    assert "extern const CinderVTable_" in models_header
    assert ".object = (void *)(&circle)" in main_source
    assert "__as__" in main_source
    result = subprocess.run([str(executable)], check=False, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def assert_compiler_lowers_reflection_builtins(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "reflection_builtins.ci"
    source.write_text(
        "@reflect\n"
        "struct Record:\n"
        "    value: i32\n"
        "    private active: bool\n"
        "\n"
        "    def read(self: &const Record) -> i32:\n"
        "        return self.value\n"
        "\n"
        "@reflect\n"
        "abstract class Named:\n"
        "    @abstractmethod\n"
        "    def code(self) -> i32:\n"
        "        pass\n"
        "\n"
        "@reflect\n"
        "class Item(Named):\n"
        "    @override\n"
        "    def code(self) -> i32:\n"
        "        return 7\n"
        "\n"
        "static_assert(field_count(Record) == 2)\n"
        "static_assert(method_count(Record) == 1)\n"
        "static_assert(has_field(Record, \"active\"))\n"
        "static_assert(has_method(Record, \"read\"))\n"
        "static_assert(implements(Item, Named))\n"
        "\n"
        "def compile_time_field_count() -> i32:\n"
        "    count: i32 = 0\n"
        "    for field in comptime fields_of(Record):\n"
        "        if field.size > 0 and len(field.name) > 0:\n"
        "            count += 1\n"
        "    return count\n"
        "\n"
        "def dynamic_name(value: &dyn Named) -> String:\n"
        "    return type_name(value)\n"
        "\n"
        "def main() -> i32:\n"
        "    record = Record(value=42, active=true)\n"
        "    info = type_info(record)\n"
        "    if info.field_count != 2 or info.method_count != 1:\n"
        "        return 1\n"
        "    runtime_fields: i32 = 0\n"
        "    for field in fields(record):\n"
        "        runtime_fields += 1\n"
        "    if runtime_fields != 2 or compile_time_field_count() != 2:\n"
        "        return 2\n"
        "    item = Item()\n"
        "    if len(type_name(item)) != 4 or len(dynamic_name(item)) != 4:\n"
        "        return 3\n"
        "    return 0\n",
        encoding="utf-8",
    )
    build_dir = tmp_path / "reflection-builtins-build"
    executable = tmp_path / (
        "reflection-builtins.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "reflection-builtins"
    )
    built = run_gen1(
        compiler,
        "build",
        str(source),
        "-o",
        str(executable),
        "--build-dir",
        str(build_dir),
    )
    assert built.returncode == 0, built.stderr
    header = (build_dir / "cinder_gen" / "reflection_builtins.cinder.h").read_text(
        encoding="utf-8"
    )
    generated = (build_dir / "cinder_gen" / "reflection_builtins.c").read_text(
        encoding="utf-8"
    )
    assert "CinderFieldInfo" in generated
    assert "CinderMethodInfo" in generated
    assert "CinderTypeInfo" in generated
    assert ".type_info = &" in generated
    assert "CINDER_STATIC_ASSERT((2 == 2)" in header
    assert "comptime fields iteration 0" in generated
    assert "comptime fields iteration 1" in generated
    assert "__fields_of(" not in generated
    assert "__type_info(" not in generated
    assert "__type_name(" not in generated
    result = subprocess.run([str(executable)], check=False, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def collect_normalized_tree(root: Path) -> dict[str, str]:
    generated_root = root / "cinder_gen"
    assert generated_root.is_dir()
    result: dict[str, str] = {}
    for path in sorted(generated_root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(generated_root).as_posix()
            result[relative] = normalize_generated_text(path.read_text(encoding="utf-8"))
    return result


def normalize_generated_text(text: str) -> str:
    return text.replace("\r\n", "\n").rstrip() + "\n"


def test_gen1_check_and_emit_c(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = write_single_source(tmp_path)

    checked = run_gen1(gen1_compiler, "check", str(source))
    assert checked.returncode == 0, checked.stderr
    assert checked.stdout.strip() == f"ok: {source}"

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    assert "int main(void)" in emitted.stdout
    assert "return 42;" in emitted.stdout


def test_gen1_build_emits_top_level_globals(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "global.ci"
    source.write_text(
        "value: i32 = 42\n\n"
        "def main() -> i32:\n"
        "    return value\n",
        encoding="utf-8",
    )
    output = tmp_path / "global"

    built = run_gen1(gen1_compiler, "build", str(source), "-o", str(output))

    assert built.returncode == 0, built.stderr
    assert output.is_file()
    executed = subprocess.run([str(output)], check=False)
    assert executed.returncode == 42


def test_gen1_dispatches_append_by_receiver_type(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "append_dispatch.ci"
    source.write_text(
        "def main() -> i32:\n"
        "    text_parts = StringBuilder()\n"
        '    text_parts.append("alpha")\n'
        "    text = text_parts.finish()\n"
        "    builder: List[i32] = []\n"
        "    builder.append(42)\n"
        "    return cast[i32](len(text)) + builder[0] - 47\n",
        encoding="utf-8",
    )

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    assert "cinder_string_builder_append(&text_parts," in emitted.stdout
    assert '.data = (char *)"alpha"' in emitted.stdout
    assert "cinder_selfhost_list_append_value(&builder, (42))" in emitted.stdout
    assert "cinder_selfhost_list_append_value(&text_parts" not in emitted.stdout
    assert "cinder_selfhost_string_builder_append_value(&builder" not in emitted.stdout

    output = tmp_path / "append-dispatch"
    built = run_gen1(gen1_compiler, "build", str(source), "-o", str(output))
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False)
    assert executed.returncode == 0


def assert_compiler_lowers_complete_string_operations(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "complete_strings.ci"
    source.write_text(
        'extern import "string.h"\n'
        "\n"
        'extern "C":\n'
        "    def strlen(text: const char*) -> c_size_t\n"
        "\n"
        'const GREETING: String = "héllo"\n'
        "\n"
        "def main() -> i32:\n"
        "    working = GREETING.clone()\n"
        "    working.reserve(32)\n"
        '    working.append("!")\n'
        "    working.append_char('?')\n"
        '    if working != "héllo!?":\n'
        "        return 1\n"
        "    copied = working.clone()\n"
        "    working.clear()\n"
        "    if len(working) != 0 or len(copied) != 8:\n"
        "        return 2\n"
        "    builder = StringBuilder()\n"
        "    builder.reserve(16)\n"
        '    builder.append("build")\n'
        "    builder.append_char('-')\n"
        '    builder.append("up")\n'
        "    built = builder.finish()\n"
        '    if built != "build-up":\n'
        "        return 3\n"
        '    if not ("alpha" < "beta" and "alpha" <= "alpha" and "beta" > "alpha" and "beta" >= "beta"):\n'
        "        return 4\n"
        '    raw: const char* = "raw"\n'
        "    if strlen(raw) != 3 or strlen(built) != 8:\n"
        "        return 5\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    generated = emitted.stdout
    assert "const CinderString" in generated
    assert '.data = (char *)"héllo"' in generated
    assert '.length = sizeof("héllo") - 1' in generated
    assert "cinder_string_clone(" in generated
    assert "cinder_string_reserve(" in generated
    assert "cinder_string_append(" in generated
    assert "cinder_string_append_char(" in generated
    assert "cinder_string_clear(" in generated
    assert "cinder_string_builder_reserve(" in generated
    assert "cinder_string_builder_append(" in generated
    assert "cinder_string_builder_append_char(" in generated
    assert "cinder_string_builder_finish(" in generated
    assert "cinder_selfhost_string_compare(" in generated
    assert "strlen(cinder_string_cstr(&built))" in generated
    assert "cinder_selfhost_list_append_value(&working" not in generated
    assert "\n    clone(" not in generated
    assert "\n    reserve(" not in generated

    output = tmp_path / "complete-strings"
    built = run_gen1(compiler, "build", str(source), "-o", str(output))
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False)
    assert executed.returncode == 0


def test_gen1_lowers_complete_string_operations(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_lowers_complete_string_operations(gen1_compiler, tmp_path)


def test_gen2_lowers_complete_string_operations(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_lowers_complete_string_operations(gen2, tmp_path)


def test_gen1_emits_bitwise_and_shift_compound_assigns(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "compound_assign.ci"
    source.write_text(
        "def main() -> i32:\n"
        "    value: u64 = 15\n"
        "    mask: u64 = 2\n"
        "    value &= ~mask\n"
        "    value |= 2\n"
        "    value ^= 4\n"
        "    value <<= 1\n"
        "    value >>= 2\n"
        "    return cast[i32](value)\n",
        encoding="utf-8",
    )
    # 15 & ~2 = 13; | 2 = 15; ^ 4 = 11; << 1 = 22; >> 2 = 5

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    assert " &= " in emitted.stdout
    assert " |= " in emitted.stdout
    assert " ^= " in emitted.stdout
    assert " <<= " in emitted.stdout
    assert " >>= " in emitted.stdout
    # Regression: &= ~x must not lower to a plain assignment of ~x.
    assert " = ~" not in emitted.stdout

    output = tmp_path / "compound_assign"
    built = run_gen1(gen1_compiler, "build", str(source), "-o", str(output))
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False)
    assert executed.returncode == 5


def test_gen1_parse_i32_uses_runtime_helper_not_mangled_name(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "parse_i32_builtin.ci"
    source.write_text(
        "def main() -> i32:\n"
        "    result = parse_i32(\"42\")\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    assert "cinder_selfhost_parse_i32" in emitted.stdout
    assert "cinder_parse_i32" in emitted.stdout
    assert "__parse_i32" not in emitted.stdout

    output = tmp_path / "parse_i32_builtin"
    built = run_gen1(gen1_compiler, "build", str(source), "-o", str(output))
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False)
    assert executed.returncode == 0


def test_gen1_matches_parse_i32_result_tags_and_captures(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "parse_i32_match.ci"
    source.write_text(
        "def parse_or_error(text: String) -> i32:\n"
        "    match parse_i32(text):\n"
        "        case Ok(value):\n"
        "            return value\n"
        "        case Err(error):\n"
        "            return cast[i32](error)\n"
        "\n"
        "def main() -> i32:\n"
        '    if parse_or_error("42") != 42:\n'
        "        return 1\n"
        '    if parse_or_error("invalid") != 1:\n'
        "        return 2\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    assert (
        "cinder_match_value.tag == "
        "CinderResult_i32_n_CinderParseError_Tag_Ok"
    ) in emitted.stdout
    assert (
        "cinder_match_value.tag == "
        "CinderResult_i32_n_CinderParseError_Tag_Err"
    ) in emitted.stdout
    assert "__auto_type value = cinder_match_value.data.ok;" in emitted.stdout
    assert "__auto_type error = cinder_match_value.data.err;" in emitted.stdout
    assert "if (false)" not in emitted.stdout

    output = tmp_path / "parse_i32_match"
    built = run_gen1(gen1_compiler, "build", str(source), "-o", str(output))
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False)
    assert executed.returncode == 0


def assert_compiler_lowers_string_conversions(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "string_conversions.ci"
    source.write_text(
        "def require_i32(text: String) -> Result[i32, ConvertError]:\n"
        "    return parse_i32(text)\n"
        "\n"
        "def main() -> i32:\n"
        '    parse_i64("-2")\n'
        '    parse_u32("3")\n'
        '    parse_u64("4")\n'
        '    parse_isize("-5")\n'
        '    parse_usize("6")\n'
        '    parse_f32("1.25")\n'
        '    parse_f64("2.5")\n'
        '    match parse_bool("true"):\n'
        "        case Ok(value):\n"
        "            if to_string(value) != \"true\":\n"
        "                return 1\n"
        "        case Err(error):\n"
        "            return 2\n"
        '    match require_i32("42"):\n'
        "        case Ok(value):\n"
        '            if to_string(value) != "42":\n'
        "                return 3\n"
        "        case Err(error):\n"
        "            return 4\n"
        "    if to_string('Z') != \"Z\":\n"
        "        return 5\n"
        "    if to_string(cast[u32](7)) != \"7\":\n"
        "        return 6\n"
        "    if to_string(cast[f64](3.5)) != \"3.5\":\n"
        "        return 7\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    generated = emitted.stdout
    for name in (
        "bool",
        "i32",
        "i64",
        "u32",
        "u64",
        "isize",
        "usize",
        "f32",
        "f64",
    ):
        assert f"cinder_selfhost_parse_{name}(" in generated
        assert f"__parse_{name}" not in generated
    for name in ("bool", "i32", "char", "u32", "f64"):
        assert f"cinder_{name}_to_string(" in generated
    assert "CinderResult_i32_n_CinderParseError" in generated
    assert "cinder_string_conversions_string_conversions__ConvertError" not in generated
    assert "__to_string" not in generated

    output = tmp_path / "string-conversions"
    built = run_gen1(compiler, "build", str(source), "-o", str(output))
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False)
    assert executed.returncode == 0


def test_gen1_lowers_string_conversions(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_lowers_string_conversions(gen1_compiler, tmp_path)


def test_gen2_lowers_string_conversions(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_lowers_string_conversions(gen2, tmp_path)


def test_gen1_lowers_nested_guarded_capture_and_or_match_patterns(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "nested_match.ci"
    source.write_text(
        "def classify(value: Option[Result[i32, i32]]) -> i32:\n"
        "    match value:\n"
        "        case Some(Ok(score)) if score > 3:\n"
        "            return score\n"
        "        case Some(Err(_)) | None:\n"
        "            return 0\n"
        "        case original @ Some(Ok(_)):\n"
        "            if original.is_some:\n"
        "                return 1\n"
        "    return 2\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))

    assert emitted.returncode == 0, emitted.stderr
    generated = emitted.stdout
    assert "bool cinder_match_found = false;" in generated
    assert "cinder_match_value.data.value.data.ok" in generated
    assert "__auto_type score = cinder_match_value.data.value.data.ok;" in generated
    assert "__auto_type original = cinder_match_value;" in generated
    assert "CinderResult_i32_i32_Tag_Err" in generated
    assert generated.index("__auto_type score") < generated.index("if ((score > 3))")


def test_gen1_guarded_or_match_assigns_selected_binding_once(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "guarded_or_match.ci"
    source.write_text(
        "def classify(value: Result[i32, i32]) -> i32:\n"
        "    match value:\n"
        "        case Ok(number) | Err(number) if number == 2:\n"
        "            return 10\n"
        "        case Ok(_) | Err(_):\n"
        "            return 1\n"
        "    return 0\n"
        "\n"
        "def main() -> i32:\n"
        "    return classify(Ok(1)) + classify(Err(2)) - 11\n",
        encoding="utf-8",
    )

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    assert emitted.stdout.count("__auto_type number =") == 1
    assert "cinder_match_value.tag == CinderResult_i32_i32_Tag_Ok" in emitted.stdout
    assert "? cinder_match_value.data.ok : cinder_match_value.data.err" in emitted.stdout

    output = tmp_path / "guarded_or_match"
    built = run_gen1(gen1_compiler, "build", str(source), "-o", str(output))
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False)
    assert executed.returncode == 0


def test_gen1_rejects_or_match_alternatives_with_different_bindings(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid_or_match.ci"
    source.write_text(
        "def classify(value: Option[i32]) -> i32:\n"
        "    match value:\n"
        "        case Some(number) | None:\n"
        "            return number\n"
        "    return 0\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        encoding="utf-8",
    )

    checked = run_gen1(gen1_compiler, "check", str(source))
    assert checked.returncode == 1
    assert checked.stdout.startswith("E 316 ")


def test_gen1_lowers_imported_variant_match_payloads(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        'name = "match_imports"\n'
        'source-root = "src"\n'
        'entry = "main.ci"\n',
        encoding="utf-8",
    )
    (source_root / "model.ci").write_text(
        "variant Token:\n"
        "    Integer(value: i32)\n"
        "    End\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "from model import Token\n"
        "\n"
        "def read(token: Token) -> i32:\n"
        "    match token:\n"
        "        case Token.Integer(parsed):\n"
        "            return parsed\n"
        "        case Token.End:\n"
        "            return 0\n"
        "    return -1\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        encoding="utf-8",
    )

    generated = tmp_path / "generated"
    emitted = run_gen1(
        gen1_compiler,
        "emit-project",
        str(tmp_path / "cinder.toml"),
        "-o",
        str(generated),
    )
    assert emitted.returncode == 0, emitted.stderr
    main_c = (generated / "cinder_gen" / "main.c").read_text(encoding="utf-8")
    assert "cinder_match_imports_model__Token_Integer" in main_c
    assert "__auto_type parsed = cinder_match_value.data.Integer.value;" in main_c

    output = tmp_path / "match-imports"
    built = run_gen1(
        gen1_compiler,
        "build",
        str(tmp_path / "cinder.toml"),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "build"),
    )
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False)
    assert executed.returncode == 0


def test_gen1_lowers_local_enum_and_variant_constructor_expressions(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "local_constructors.ci"
    source.write_text(
        "enum ParseError:\n"
        "    negative\n"
        "\n"
        "variant Token:\n"
        "    Integer(value: i32)\n"
        "    End\n"
        "\n"
        "def parse(value: i32) -> Result[Token, ParseError]:\n"
        "    if value < 0:\n"
        "        return Err(ParseError.negative)\n"
        "    if value == 0:\n"
        "        return Ok(Token.End)\n"
        "    return Ok(Token.Integer(value))\n"
        "\n"
        "def main() -> i32:\n"
        "    parse(-1)\n"
        "    parse(0)\n"
        "    parse(42)\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    generated = emitted.stdout
    assert "__ParseError_negative" in generated
    assert "){ .tag = " in generated
    assert "__Token_Integer, .data.Integer = { .value = value }" in generated
    assert "__Token_End })" in generated

    output = tmp_path / "local-constructors"
    built = run_gen1(gen1_compiler, "build", str(source), "-o", str(output))
    assert built.returncode == 0, built.stderr
    assert subprocess.run([str(output)], check=False).returncode == 0


def test_gen1_lowers_imported_enum_and_variant_constructor_expressions(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    manifest = tmp_path / "cinder.toml"
    manifest.write_text(
        "[project]\n"
        'name = "constructor_imports"\n'
        'source-root = "src"\n'
        'entry = "main.ci"\n',
        encoding="utf-8",
    )
    (source_root / "model.ci").write_text(
        "enum ParseError:\n"
        "    negative\n"
        "\n"
        "variant Token:\n"
        "    Integer(value: i32)\n"
        "    End\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import model as m\n"
        "from model import ParseError as Failure, Token as Lexeme\n"
        "\n"
        "def qualified(value: i32) -> Result[m.Token, m.ParseError]:\n"
        "    if value < 0:\n"
        "        return Err(m.ParseError.negative)\n"
        "    if value == 0:\n"
        "        return Ok(m.Token.End)\n"
        "    return Ok(m.Token.Integer(value))\n"
        "\n"
        "def imported(value: i32) -> Result[Lexeme, Failure]:\n"
        "    if value < 0:\n"
        "        return Err(Failure.negative)\n"
        "    if value == 0:\n"
        "        return Ok(Lexeme.End)\n"
        "    return Ok(Lexeme.Integer(value))\n"
        "\n"
        "def main() -> i32:\n"
        "    qualified(42)\n"
        "    imported(0)\n"
        "    return 0\n",
        encoding="utf-8",
    )

    generated = tmp_path / "generated"
    emitted = run_gen1(
        gen1_compiler,
        "emit-project",
        str(manifest),
        "-o",
        str(generated),
    )
    assert emitted.returncode == 0, emitted.stderr
    main_c = (generated / "cinder_gen" / "main.c").read_text(encoding="utf-8")
    assert "cinder_constructor_imports_model__ParseError_negative" in main_c
    assert "cinder_constructor_imports_model__Token_Integer" in main_c
    assert "cinder_constructor_imports_model__Token_End" in main_c
    assert "m.ParseError" not in main_c
    assert "m.Token" not in main_c

    output = tmp_path / "imported-constructors"
    built = run_gen1(
        gen1_compiler,
        "build",
        str(manifest),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "build"),
    )
    assert built.returncode == 0, built.stderr
    assert subprocess.run([str(output)], check=False).returncode == 0


def test_gen1_lowers_constructors_in_affected_examples(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    expressive = run_gen1(
        gen1_compiler,
        "emit-c",
        str(ROOT / "examples" / "expressive_match.ci"),
    )
    assert expressive.returncode == 0, expressive.stderr
    assert "__Shape_Origin })" in expressive.stdout

    converted = run_gen1(
        gen1_compiler,
        "emit-c",
        str(ROOT / "examples" / "convert.ci"),
    )
    assert converted.returncode == 0, converted.stderr
    assert "cinder_match_value == CinderParseError_empty" in converted.stdout
    assert "cinder_match_value == CinderParseError_invalid" in converted.stdout
    assert "cinder_match_value == CinderParseError_overflow" in converted.stdout

    anti_examples = run_gen1(
        gen1_compiler,
        "emit-c",
        str(ROOT / "examples" / "anti_examples.ci"),
    )
    assert anti_examples.returncode == 0, anti_examples.stderr
    assert "__ParseError_negative" in anti_examples.stdout
    assert "__Token_Integer, .data.Integer = { .value = 11 }" in anti_examples.stdout

    generated = tmp_path / "module-project"
    module_project = run_gen1(
        gen1_compiler,
        "emit-project",
        str(ROOT / "examples" / "module_project" / "cinder.toml"),
        "-o",
        str(generated),
    )
    assert module_project.returncode == 0, module_project.stderr
    parser_c = (
        generated / "cinder_gen" / "support" / "parser.c"
    ).read_text(encoding="utf-8")
    assert "cinder_module_demo_model__ParseError_negative" in parser_c
    assert "cinder_module_demo_model__ParseError_too_large" in parser_c
    assert "cinder_module_demo_model__Token_Integer" in parser_c
    assert "model.ParseError" not in parser_c
    assert "model.Token" not in parser_c


def test_gen1_emit_c_cleans_up_with_scope_before_return(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "with_return.ci"
    source.write_text(
        "def main() -> i32:\n"
        "    with open(\"input.txt\", \"rb\") as file:\n"
        "        return 42\n",
        encoding="utf-8",
    )

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    materialized_return = emitted.stdout.index("__auto_type cinder_return_value = 42;")
    cleanup = emitted.stdout.index("fclose(file);", materialized_return)
    returned = emitted.stdout.index("return cinder_return_value;", cleanup)
    assert materialized_return < cleanup < returned


def test_gen1_drops_nominal_locals_on_live_return_path(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "nominal_cleanup.ci"
    source.write_text(
        "class Resource:\n"
        "    label: i32\n"
        "\n"
        "    def __init__(self, label: i32):\n"
        "        self.label = label\n"
        "\n"
        "    def __del__(self):\n"
        '        print("drop", self.label)\n'
        "\n"
        "def sum_values() -> i32:\n"
        "    first = Resource(1)\n"
        "    second: Resource = Resource(2)\n"
        "    return first.label + second.label\n"
        "\n"
        "def make(value: i32) -> Resource:\n"
        "    resource = Resource(value)\n"
        "    return resource\n"
        "\n"
        "def consume(owned: Resource) -> void:\n"
        "    pass\n"
        "\n"
        "def main() -> i32:\n"
        "    moved = make(3)\n"
        "    result = sum_values()\n"
        "    consume(Resource(4))\n"
        "    return result + moved.label - 6\n",
        encoding="utf-8",
    )

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    generated = emitted.stdout
    drop_second = generated.index("Resource__drop(&second);")
    materialized_return = generated.rfind(
        "__auto_type cinder_return_value =",
        0,
        drop_second,
    )
    drop_first = generated.index("Resource__drop(&first);", drop_second)
    returned = generated.index("return cinder_return_value;", drop_first)
    assert materialized_return >= 0
    assert materialized_return < drop_second < drop_first < returned

    moved_return = generated.index("__auto_type cinder_return_value = resource;")
    moved_return_end = generated.index("return cinder_return_value;", moved_return)
    assert "Resource__drop(&resource);" not in generated[moved_return:moved_return_end]
    assert "Resource__drop(&owned);" in generated

    output = tmp_path / "nominal-cleanup"
    built = run_gen1(
        gen1_compiler,
        "build",
        str(source),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "nominal-cleanup-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(output)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "drop 2\ndrop 1\ndrop 4\ndrop 3\n"


def test_gen1_borrows_drop_values_during_list_iteration(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "borrowed_list_iteration.ci"
    source.write_text(
        "def contains(values: &const List[String], expected: &const String) -> bool:\n"
        "    for item in values:\n"
        "        if item == expected:\n"
        "            return true\n"
        "    return false\n"
        "\n"
        "def main() -> i32:\n"
        '    values: List[String] = ["types", "syntax"]\n'
        '    expected = "types"\n'
        "    if not contains(values, expected):\n"
        "        return 1\n"
        '    if values[0] != "types":\n'
        "        return 2\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    assert "cinder_string_drop(&item);" not in emitted.stdout

    output = tmp_path / "borrowed-list-iteration"
    built = run_gen1(
        gen1_compiler,
        "build",
        str(source),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "borrowed-list-iteration-build"),
    )
    assert built.returncode == 0, built.stderr
    assert subprocess.run([str(output)], check=False).returncode == 0


def assert_compiler_drops_destructor_aggregates_on_discard_and_loop_exit(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "destructor_aggregate_cleanup.ci"
    source.write_text(
        "class Resource:\n"
        "    label: i32\n"
        "\n"
        "    def __init__(self, label: i32):\n"
        "        self.label = label\n"
        "\n"
        "    def __del__(self):\n"
        '        print("drop", self.label)\n'
        "\n"
        "struct ArrayHolder:\n"
        "    items: Resource[2]\n"
        "\n"
        "def exercise_fixed_array() -> void:\n"
        "    fixed: Resource[2] = [Resource(10), Resource(11)]\n"
        "\n"
        "def exercise_array_field() -> void:\n"
        "    holder = ArrayHolder(items=[Resource(12), Resource(13)])\n"
        "\n"
        "def take_numbers(values: List[i32]) -> i32:\n"
        "    return cast[i32](len(values))\n"
        "\n"
        "def exercise_nested_transfer() -> void:\n"
        "    nested: List[List[i32]] = [[1], [2, 3]]\n"
        "    inner = nested.pop()\n"
        '    print("moved inner", take_numbers(inner))\n'
        "\n"
        "def exercise_discarded_values() -> void:\n"
        "    Resource(20)\n"
        "    values: List[Resource] = []\n"
        "    values.append(Resource(21))\n"
        "    values.append(Resource(22))\n"
        "    values.pop()\n"
        "    values.append(Resource(23))\n"
        '    print("len", len(values))\n'
        "\n"
        "def exercise_loop_exits() -> void:\n"
        "    for label in range(30, 33):\n"
        "        current = Resource(label)\n"
        "        if label == 30:\n"
        "            continue\n"
        "        break\n"
        "\n"
        "def exercise_iterator_break() -> i32:\n"
        "    values: Map[i32, i32] = {1: 1}\n"
        "    for key in values:\n"
        "        break\n"
        "    values[2] = 2\n"
        "    return cast[i32](len(values))\n"
        "\n"
        "def main() -> i32:\n"
        "    exercise_fixed_array()\n"
        "    exercise_array_field()\n"
        "    exercise_nested_transfer()\n"
        "    exercise_discarded_values()\n"
        "    exercise_loop_exits()\n"
        "    if exercise_iterator_break() != 2:\n"
        "        return 1\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    generated = emitted.stdout
    assert "for (size_t cinder_drop_index_" in generated
    assert "__auto_type cinder_discarded_" in generated
    discarded_drop = generated.index("Resource__drop(&cinder_discarded_")
    popped = generated.index('pop from empty list', discarded_drop)
    popped_drop = generated.index("Resource__drop(&cinder_discarded_", popped)
    assert discarded_drop < popped < popped_drop
    drop_current = generated.index("Resource__drop(&current);")
    continue_statement = generated.index("continue;", drop_current)
    drop_before_break = generated.index("Resource__drop(&current);", continue_statement)
    break_statement = generated.index("break;", drop_before_break)
    assert drop_current < continue_statement < drop_before_break < break_statement
    inner_declaration = generated.index("__auto_type inner =")
    transfer_end = generated.index("\n}\n", inner_declaration)
    transfer_body = generated[inner_declaration:transfer_end]
    assert "free(inner.data);" not in transfer_body
    assert "CinderList_i32_drop(&inner);" not in transfer_body

    output = tmp_path / "destructor-aggregate-cleanup"
    built = run_gen1(
        compiler,
        "build",
        str(source),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "destructor-aggregate-cleanup-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(output)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == (
        "drop 11\n"
        "drop 10\n"
        "drop 13\n"
        "drop 12\n"
        "moved inner 2\n"
        "drop 20\n"
        "drop 22\n"
        "len 2\n"
        "drop 21\n"
        "drop 23\n"
        "drop 30\n"
        "drop 31\n"
    )


def test_gen1_drops_destructor_aggregates_on_discard_and_loop_exit(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_drops_destructor_aggregates_on_discard_and_loop_exit(
        gen1_compiler,
        tmp_path,
    )


def test_gen2_drops_destructor_aggregates_on_discard_and_loop_exit(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_drops_destructor_aggregates_on_discard_and_loop_exit(
        gen2,
        tmp_path,
    )


def assert_compiler_drops_replaced_index_values(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "replaced_index_values.ci"
    source.write_text(
        "class Resource:\n"
        "    label: i32\n"
        "\n"
        "    def __init__(self, label: i32):\n"
        "        self.label = label\n"
        "\n"
        "    def __del__(self):\n"
        '        print("drop", self.label)\n'
        "\n"
        "def replace_array_value() -> void:\n"
        "    values: Resource[1] = [Resource(1)]\n"
        "    values[0] = Resource(2)\n"
        "\n"
        "def replace_list_value() -> void:\n"
        "    values: List[Resource] = [Resource(3)]\n"
        "    values[0] = Resource(4)\n"
        "\n"
        "def main() -> i32:\n"
        "    replace_array_value()\n"
        "    replace_list_value()\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    assert emitted.stdout.count("Resource__drop(&(*cinder_target_") == 2

    output = tmp_path / "replaced-index-values"
    built = run_gen1(
        compiler,
        "build",
        str(source),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "replaced-index-values-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(output)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "drop 1\ndrop 2\ndrop 3\ndrop 4\n"


def test_gen1_drops_replaced_index_values(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_drops_replaced_index_values(gen1_compiler, tmp_path)


def test_gen2_drops_replaced_index_values(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_drops_replaced_index_values(gen2, tmp_path)


def assert_compiler_rejects_partial_member_moves(
    compiler: Path,
    tmp_path: Path,
) -> None:
    prefix = (
        "class Resource:\n"
        "    label: i32\n"
        "\n"
        "    def __init__(self, label: i32):\n"
        "        self.label = label\n"
        "\n"
        "    def __del__(self):\n"
        "        pass\n"
        "\n"
        "struct Holder:\n"
        "    value: Resource\n"
        "\n"
    )
    invalid_sources = (
        prefix
        + "def extract(holder: Holder) -> Resource:\n"
        "    return holder.value\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        prefix
        + "def consume(value: Resource) -> void:\n"
        "    pass\n"
        "\n"
        "def extract(holder: Holder) -> void:\n"
        "    consume(holder.value)\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        prefix
        + "def extract(holder: Holder) -> void:\n"
        "    values: List[Resource] = []\n"
        "    values.append(holder.value)\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        prefix
        + "def discard(holder: Holder) -> void:\n"
        "    holder.value\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        prefix
        + "def discard() -> void:\n"
        "    values: Resource[1] = [Resource(1)]\n"
        "    values[0]\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
    )
    for index, source_text in enumerate(invalid_sources):
        source = tmp_path / f"partial_member_move_{index}.ci"
        source.write_text(source_text, encoding="utf-8")
        checked = run_gen1(compiler, "check", str(source))
        assert checked.returncode == 1
        assert checked.stdout.startswith("E 254 ")

    borrowed = tmp_path / "borrowed_member.ci"
    borrowed.write_text(
        prefix
        + "def inspect(value: &const Resource) -> i32:\n"
        "    return value.label\n"
        "\n"
        "def main() -> i32:\n"
        "    holder = Holder(value=Resource(1))\n"
        "    return inspect(holder.value) - 1\n",
        encoding="utf-8",
    )
    checked = run_gen1(compiler, "check", str(borrowed))
    assert checked.returncode == 0, checked.stdout


def test_gen1_rejects_partial_member_moves(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_rejects_partial_member_moves(gen1_compiler, tmp_path)


def test_gen2_rejects_partial_member_moves(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_rejects_partial_member_moves(gen2, tmp_path)


def assert_compiler_rejects_shallow_nominal_map_copies(
    compiler: Path,
    tmp_path: Path,
) -> None:
    resource = (
        "class Resource:\n"
        "    text: String\n"
        "\n"
        "    def __init__(self, text: String):\n"
        "        self.text = text\n"
        "\n"
        "    def __del__(self):\n"
        '        print("drop", self.text)\n'
        "\n"
    )
    rejected = tmp_path / "nominal_map_get.ci"
    rejected.write_text(
        resource
        + "def main() -> i32:\n"
        '    values: Map[i32, Resource] = {1: Resource("owned")}\n'
        "    copied = values.get(1)\n"
        "    return 0\n",
        encoding="utf-8",
    )
    checked = run_gen1(compiler, "check", str(rejected))
    assert checked.returncode == 1
    assert checked.stdout.startswith("E 254 ")

    borrowed = tmp_path / "nominal_map_borrow.ci"
    borrowed.write_text(
        resource
        + "def inspect(value: &const Resource) -> i32:\n"
        "    return cast[i32](len(value.text))\n"
        "\n"
        "def main() -> i32:\n"
        '    values: Map[i32, Resource] = {1: Resource("owned")}\n'
        "    if inspect(values[1]) != 5:\n"
        "        return 1\n"
        "    return cast[i32](len(values)) - 1\n",
        encoding="utf-8",
    )
    emitted = run_gen1(compiler, "emit-c", str(borrowed))
    assert emitted.returncode == 0, emitted.stderr
    generated = emitted.stdout
    assert " *CinderMap_i32_Resource_at_ref(" in generated
    assert (
        "static inline CinderOption_Resource CinderMap_i32_Resource_get("
        not in generated
    )
    assert (
        "static inline CinderMap_i32_Resource CinderMap_i32_Resource_clone("
        not in generated
    )
    assert "_Resource__drop(&(self->entries[index].value));" in generated

    output = tmp_path / "nominal-map-borrow"
    built = run_gen1(
        compiler,
        "build",
        str(borrowed),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "nominal-map-borrow-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(output)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "drop owned\n"


def test_gen1_rejects_shallow_nominal_map_copies(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_rejects_shallow_nominal_map_copies(gen1_compiler, tmp_path)


def test_gen2_rejects_shallow_nominal_map_copies(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_rejects_shallow_nominal_map_copies(gen2, tmp_path)


def assert_compiler_supports_named_scalar_map_get(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "named_scalar_map_get.ci"
    source.write_text(
        "def main() -> i32:\n"
        "    bytes: Map[i32, u8] = {1: cast[u8](7)}\n"
        "    words: Map[i32, u32] = {1: cast[u32](11)}\n"
        "    sizes: Map[i32, usize] = {1: cast[usize](13)}\n"
        "    byte_value: Option[u8] = bytes.get(1)\n"
        "    word_value: Option[u32] = words.get(1)\n"
        "    size_value: Option[usize] = sizes.get(1)\n"
        "    if not byte_value.is_some or byte_value.value != cast[u8](7):\n"
        "        return 1\n"
        "    if not word_value.is_some or word_value.value != cast[u32](11):\n"
        "        return 2\n"
        "    if not size_value.is_some or size_value.value != cast[usize](13):\n"
        "        return 3\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    for helper in (
        "CinderMap_i32_u8_get",
        "CinderMap_i32_u32_get",
        "CinderMap_i32_usize_get",
    ):
        assert helper in emitted.stdout

    output = tmp_path / "named-scalar-map-get"
    built = run_gen1(
        compiler,
        "build",
        str(source),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "named-scalar-map-get-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(output)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr


def test_gen1_supports_named_scalar_map_get(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_supports_named_scalar_map_get(gen1_compiler, tmp_path)


def test_gen2_supports_named_scalar_map_get(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_supports_named_scalar_map_get(gen2, tmp_path)


def assert_compiler_rejects_consuming_borrowed_foreach_values(
    compiler: Path,
    tmp_path: Path,
) -> None:
    resource = (
        "class Resource:\n"
        "    text: String\n"
        "\n"
        "    def __init__(self, text: String):\n"
        "        self.text = text\n"
        "\n"
        "    def __del__(self):\n"
        '        print("drop", self.text)\n'
        "\n"
    )
    rejected_sources = (
        resource
        + "def consume(value: Resource) -> void:\n"
        "    pass\n"
        "\n"
        "def main() -> i32:\n"
        "    values: List[Resource] = []\n"
        '    values.append(Resource("owned"))\n'
        "    for item in values:\n"
        "        consume(item)\n"
        "    return 0\n",
        resource
        + "def consume(value: Resource) -> void:\n"
        "    pass\n"
        "\n"
        "def main() -> i32:\n"
        "    callback: def(Resource) -> void = consume\n"
        "    values: List[Resource] = []\n"
        '    values.append(Resource("owned"))\n'
        "    for item in values:\n"
        "        callback(item)\n"
        "    return 0\n",
        resource
        + "struct ConsumeEnv:\n"
        "    marker: i32\n"
        "\n"
        "def consume_with_env(env: &const ConsumeEnv, value: Resource) -> void:\n"
        "    pass\n"
        "\n"
        "def main() -> i32:\n"
        "    callback = closure(ConsumeEnv(marker=0), consume_with_env)\n"
        "    values: List[Resource] = []\n"
        '    values.append(Resource("owned"))\n'
        "    for item in values:\n"
        "        callback(item)\n"
        "    return 0\n",
    )
    for index, source_text in enumerate(rejected_sources):
        rejected = tmp_path / f"consumed_foreach_borrow_{index}.ci"
        rejected.write_text(source_text, encoding="utf-8")
        checked = run_gen1(compiler, "check", str(rejected))
        assert checked.returncode == 1
        assert checked.stdout.startswith("E 254 ")

    borrowed_callable = tmp_path / "callable_inspected_foreach_borrow.ci"
    borrowed_callable.write_text(
        resource
        + "def inspect(value: &const Resource) -> i32:\n"
        "    return cast[i32](len(value.text))\n"
        "\n"
        "def main() -> i32:\n"
        "    callback: def(&const Resource) -> i32 = inspect\n"
        "    values: List[Resource] = []\n"
        '    values.append(Resource("owned"))\n'
        "    total: i32 = 0\n"
        "    for item in values:\n"
        "        total += callback(item)\n"
        "    return total - 5\n",
        encoding="utf-8",
    )
    checked = run_gen1(compiler, "check", str(borrowed_callable))
    assert checked.returncode == 0, checked.stdout

    borrowed = tmp_path / "inspected_foreach_borrow.ci"
    borrowed.write_text(
        resource
        + "def inspect(value: &const Resource) -> i32:\n"
        "    return cast[i32](len(value.text))\n"
        "\n"
        "def main() -> i32:\n"
        "    values: List[Resource] = []\n"
        '    values.append(Resource("owned"))\n'
        "    total: i32 = 0\n"
        "    for item in values:\n"
        "        total += inspect(item)\n"
        "    return total - 5\n",
        encoding="utf-8",
    )
    emitted = run_gen1(compiler, "emit-c", str(borrowed))
    assert emitted.returncode == 0, emitted.stderr
    assert "_Resource__drop(&item);" not in emitted.stdout

    output = tmp_path / "inspected-foreach-borrow"
    built = run_gen1(
        compiler,
        "build",
        str(borrowed),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "inspected-foreach-borrow-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(output)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "drop owned\n"


def test_gen1_rejects_consuming_borrowed_foreach_values(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_rejects_consuming_borrowed_foreach_values(
        gen1_compiler,
        tmp_path,
    )


def test_gen2_rejects_consuming_borrowed_foreach_values(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_rejects_consuming_borrowed_foreach_values(gen2, tmp_path)


def assert_compiler_supports_file_valued_maps(
    compiler: Path,
    tmp_path: Path,
) -> None:
    first = tmp_path / "file_map_first.bin"
    second = tmp_path / "file_map_second.bin"
    source = tmp_path / "file_valued_map.ci"
    source.write_text(
        "def main() -> i32:\n"
        f'    files: Map[i32, File] = {{1: open("{first}", "wb")}}\n'
        "    payload: u8[1] = [65]\n"
        "    if files[1].write(payload) != 1:\n"
        "        return 1\n"
        f'    files[1] = open("{second}", "wb")\n'
        "    if len(files) != 1:\n"
        "        return 2\n"
        "    files.clear()\n"
        "    return cast[i32](len(files))\n",
        encoding="utf-8",
    )
    emitted = run_gen1(compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    generated = emitted.stdout
    for helper in (
        "CinderMap_i32_FILE_set",
        "CinderMap_i32_FILE_len",
        "CinderMap_i32_FILE_at_ref",
        "CinderMap_i32_FILE_clear",
    ):
        assert helper in generated
    assert "FILE * const *CinderMap_i32_FILE_lookup(" in generated
    assert "FILE * const *CinderMap_i32_FILE_at_ref(" in generated
    assert "fclose(self->entries[index].value);" in generated
    assert "CinderMap_i32_FILE_get(" not in generated
    assert "CinderMap_i32_FILE_clone(" not in generated

    output = tmp_path / "file-valued-map"
    built = run_gen1(
        compiler,
        "build",
        str(source),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "file-valued-map-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(output)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr
    assert first.read_bytes() == b"A"
    assert second.read_bytes() == b""


def test_gen1_supports_file_valued_maps(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_supports_file_valued_maps(gen1_compiler, tmp_path)


def test_gen2_supports_file_valued_maps(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_supports_file_valued_maps(gen2, tmp_path)


def aggregate_move_resource_definition() -> str:
    return (
        "class Resource:\n"
        "    label: i32\n"
        "    text: String\n"
        "\n"
        "    def __init__(self, label: i32, text: String):\n"
        "        self.label = label\n"
        "        self.text = text\n"
        "\n"
        "    def __del__(self):\n"
        '        print("drop", self.label)\n'
        "\n"
    )


def assert_compiler_validates_aggregate_literal_moves(
    compiler: Path,
    tmp_path: Path,
) -> None:
    prefix = (
        aggregate_move_resource_definition()
        + "struct Holder:\n"
        "    value: Resource\n"
        "    text: String\n"
        "\n"
    )
    invalid_initializers = (
        "    values: List[Resource] = [holder.value]\n",
        "    values: Map[i32, Resource] = {1: holder.value}\n",
        "    values: Tuple[Resource] = (holder.value,)\n",
        "    values: Resource[1] = [holder.value]\n",
    )
    for index, initializer in enumerate(invalid_initializers):
        rejected = tmp_path / f"partial_aggregate_move_{index}.ci"
        rejected.write_text(
            prefix
            + "def main() -> i32:\n"
            '    holder = Holder(value=Resource(9, "owned"), text="set")\n'
            + initializer
            + "    return 0\n",
            encoding="utf-8",
        )
        checked = run_gen1(compiler, "check", str(rejected))
        assert checked.returncode == 1
        assert checked.stdout.startswith("E 254 ")

    accepted = tmp_path / "nested_local_aggregate_moves.ci"
    accepted.write_text(
        aggregate_move_resource_definition()
        + "struct TextHolder:\n"
        "    text: String\n"
        "\n"
        + "def check_clones() -> i32:\n"
        '    set_value = "set"\n'
        "    set_values: Set[String] = {set_value}\n"
        '    key_holder = TextHolder(text="key")\n'
        "    key_values: Map[String, i32] = {key_holder.text: 1}\n"
        '    set_value.append("x")\n'
        '    key_holder.text.append("x")\n'
        '    if "set" not in set_values or "setx" in set_values:\n'
        "        return 1\n"
        '    if "key" not in key_values or "keyx" in key_values:\n'
        "        return 2\n"
        "    return 0\n"
        "\n"
        + "def exercise() -> void:\n"
        '    list_resource = Resource(1, "list")\n'
        "    list_values: List[Resource] = [list_resource]\n"
        '    map_resource = Resource(2, "map")\n'
        "    map_values: Map[i32, Resource] = {1: map_resource}\n"
        '    tuple_resource = Resource(3, "tuple")\n'
        "    tuple_values: Tuple[Resource] = (tuple_resource,)\n"
        '    array_resource = Resource(4, "array")\n'
        "    array_values: Resource[1] = [array_resource]\n"
        "\n"
        "def main() -> i32:\n"
        "    exercise()\n"
        "    return check_clones()\n",
        encoding="utf-8",
    )
    emitted = run_gen1(compiler, "emit-c", str(accepted))
    assert emitted.returncode == 0, emitted.stderr
    for name in (
        "list_resource",
        "map_resource",
        "tuple_resource",
        "array_resource",
    ):
        assert f"_Resource__drop(&{name});" not in emitted.stdout
    assert "cinder_string_drop(&set_value);" in emitted.stdout

    output = tmp_path / "nested-local-aggregate-moves"
    built = run_gen1(
        compiler,
        "build",
        str(accepted),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "nested-local-aggregate-moves-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(output)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr
    assert sorted(ran.stdout.splitlines()) == [
        "drop 1",
        "drop 2",
        "drop 3",
        "drop 4",
    ]


def test_gen1_validates_aggregate_literal_moves(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_validates_aggregate_literal_moves(gen1_compiler, tmp_path)


def test_gen2_validates_aggregate_literal_moves(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_validates_aggregate_literal_moves(gen2, tmp_path)


def assert_compiler_borrows_cloned_string_collection_inputs(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "cloned_string_collection_inputs.ci"
    source.write_text(
        "def main() -> i32:\n"
        '    names: Set[String] = {"seed"}\n'
        "    set_value = to_string(10)\n"
        "    names.add(set_value)\n"
        '    set_value.append("x")\n'
        '    if "10" not in names or "10x" in names:\n'
        "        return 1\n"
        "\n"
        "    scores: Map[String, i32] = {}\n"
        "    map_key = to_string(20)\n"
        "    scores[map_key] = 7\n"
        '    map_key.append("x")\n'
        '    if scores["20"] != 7 or "20x" in scores:\n'
        "        return 2\n"
        "\n"
        "    names.add(to_string(30))\n"
        "    names.add(to_string(30))\n"
        "    scores[to_string(40)] = 9\n"
        "    scores[to_string(40)] = 11\n"
        '    if "30" not in names or len(names) != 3:\n'
        "        return 3\n"
        '    if scores["40"] != 11 or len(scores) != 2:\n'
        "        return 4\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    generated = emitted.stdout
    assert "cinder_string_drop(&set_value);" in generated
    assert "cinder_string_drop(&map_key);" in generated
    assert generated.count("CinderString cinder_set_item_") == 2
    assert generated.count("cinder_string_drop(&cinder_set_item_") == 2
    assert generated.count("CinderString cinder_map_key_") == 2
    assert generated.count("cinder_string_drop(&cinder_map_key_") == 2

    output = tmp_path / (
        "cloned-string-collection-inputs.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "cloned-string-collection-inputs"
    )
    built = run_gen1(
        compiler,
        "build",
        str(source),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "cloned-string-collection-inputs-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(output)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr


def test_gen1_borrows_cloned_string_collection_inputs(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_borrows_cloned_string_collection_inputs(gen1_compiler, tmp_path)


def test_gen2_borrows_cloned_string_collection_inputs(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_borrows_cloned_string_collection_inputs(gen2, tmp_path)


def assert_compiler_validates_closure_environment_moves(
    compiler: Path,
    tmp_path: Path,
) -> None:
    prefix = (
        aggregate_move_resource_definition()
        + "struct Env:\n"
        "    resource: Resource\n"
        "\n"
        "struct Holder:\n"
        "    env: Env\n"
        "\n"
        "def read_env(env: &const Env) -> i32:\n"
        "    return env.resource.label\n"
        "\n"
    )
    rejected = tmp_path / "partial_closure_environment_move.ci"
    rejected.write_text(
        prefix
        + "def main() -> i32:\n"
        '    holder = Holder(env=Env(resource=Resource(8, "owned")))\n'
        "    callback = closure(holder.env, read_env)\n"
        "    return callback() - 8\n",
        encoding="utf-8",
    )
    checked = run_gen1(compiler, "check", str(rejected))
    assert checked.returncode == 1
    assert checked.stdout.startswith("E 254 ")

    accepted = tmp_path / "local_closure_environment_move.ci"
    accepted.write_text(
        prefix
        + "def main() -> i32:\n"
        '    env = Env(resource=Resource(7, "owned"))\n'
        "    callback = closure(env, read_env)\n"
        "    return callback() - 7\n",
        encoding="utf-8",
    )
    emitted = run_gen1(compiler, "emit-c", str(accepted))
    assert emitted.returncode == 0, emitted.stderr
    assert "_Env__drop(&env);" not in emitted.stdout
    assert "_Env__drop(&(self->env));" in emitted.stdout

    output = tmp_path / "local-closure-environment-move"
    built = run_gen1(
        compiler,
        "build",
        str(accepted),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "local-closure-environment-move-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(output)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "drop 7\n"


def test_gen1_validates_closure_environment_moves(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_validates_closure_environment_moves(gen1_compiler, tmp_path)


def test_gen2_validates_closure_environment_moves(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_validates_closure_environment_moves(gen2, tmp_path)


def assert_compiler_drops_specialized_nominal_locals(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "specialized_nominal_cleanup.ci"
    source.write_text(
        "class Resource:\n"
        "    label: i32\n"
        "\n"
        "    def __init__(self, label: i32):\n"
        "        self.label = label\n"
        "\n"
        "    def __del__(self):\n"
        '        print("drop", self.label)\n'
        "\n"
        "struct Box[T]:\n"
        "    value: T\n"
        "\n"
        "def exercise() -> void:\n"
        "    boxed: Box[Resource] = Box(value=Resource(1))\n"
        "    boxed = Box(value=Resource(2))\n"
        "\n"
        "def main() -> i32:\n"
        "    exercise()\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    assert "Box_Resource__drop" in emitted.stdout
    assert "Box_Resource__drop(&boxed);" in emitted.stdout

    output = tmp_path / "specialized-nominal-cleanup"
    built = run_gen1(
        compiler,
        "build",
        str(source),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "specialized-nominal-cleanup-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(output)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "drop 1\ndrop 2\n"


def test_gen1_drops_specialized_nominal_locals(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_drops_specialized_nominal_locals(gen1_compiler, tmp_path)


def test_gen2_drops_specialized_nominal_locals(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_drops_specialized_nominal_locals(gen2, tmp_path)


def test_gen1_lowers_owned_moves_and_recursive_drop_glue(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "owned_lowering.ci"
    source.write_text(
        "class Resource:\n"
        "    label: i32\n"
        "\n"
        "    def __init__(self, label: i32):\n"
        "        self.label = label\n"
        "\n"
        "    def __del__(self):\n"
        '        print("drop", self.label)\n'
        "\n"
        "struct Node:\n"
        "    value: i32\n"
        "    next: Option[Owned[Node]]\n"
        "\n"
        "def bump(node: &Node) -> void:\n"
        "    node.value = node.value + 1\n"
        "\n"
        "def early(flag: bool) -> i32:\n"
        "    value: Owned[Resource] = Owned(Resource(4))\n"
        "    if flag:\n"
        "        return 7\n"
        "    return 0\n"
        "\n"
        "def consume(value: Owned[Resource]) -> i32:\n"
        "    return (*value).label\n"
        "\n"
        "def main() -> i32:\n"
        "    number: Owned[i32] = Owned(40)\n"
        "    *number = *number + 2\n"
        "    resource: Owned[Resource] = Owned(Resource(1))\n"
        "    replacement: Owned[Resource] = Owned(Resource(2))\n"
        "    resource = replacement\n"
        "    leaf: Owned[Node] = Owned(Node(value=10, next=None))\n"
        "    root: Owned[Node] = Owned(Node(value=20, next=Some(leaf)))\n"
        "    bump(&*root)\n"
        "    moved = root\n"
        "    result: Result[Owned[Resource], i32] = Ok(Owned(Resource(3)))\n"
        "    print(early(true))\n"
        "    passed: Owned[Resource] = Owned(Resource(5))\n"
        "    print(consume(passed))\n"
        "    if (*moved).value != 21:\n"
        "        return 1\n"
        "    return *number\n",
        encoding="utf-8",
    )

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    generated = emitted.stdout
    assert "CinderOwned_i32_new(40)" in generated
    assert "(*(number).ptr)" in generated
    assert "(root).ptr" in generated
    assert "CinderOption_CinderOwned_Node_drop" in generated
    assert "CinderResult_CinderOwned_Resource_i32_drop" in generated
    assert "Resource__drop(&((*owned->ptr)))" in generated
    assert "CinderOwned_Node_drop(&moved);" in generated
    assert "CinderOwned_Node_drop(&leaf);" not in generated
    assert "CinderOwned_Node_drop(&root);" not in generated
    assert "cinder_move_" in generated

    output = tmp_path / "owned-lowering"
    built = run_gen1(
        gen1_compiler,
        "build",
        str(source),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "owned-lowering-build"),
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(output)], check=False, text=True, capture_output=True)
    assert ran.returncode == 42, ran.stderr
    assert ran.stdout == "drop 1\ndrop 4\n7\ndrop 5\n5\ndrop 3\ndrop 2\n"


def test_gen1_lowers_file_reads_and_scopes_repeated_with_bindings(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "file_reads.ci"
    source.write_text(
        "def main() -> i32:\n"
        '    path = "selfhost_file_reads.bin"\n'
        "\n"
        '    with open(path, "wb") as file:\n'
        "        payload: u8[12] = [104, 101, 108, 108, 111, 10, 119, 111, 114, 108, 100, 10]\n"
        "        if file.write(payload) != 12:\n"
        "            return 1\n"
        "\n"
        '    with open(path, "rb") as file:\n'
        "        chunk: u8[5]\n"
        "        counted = file.read(chunk)\n"
        "        if counted != 5:\n"
        "            return 2\n"
        "        if chunk[0] != 104 or chunk[4] != 111:\n"
        "            return 3\n"
        "        blank = file.read_line()\n"
        "        if blank.is_none or len(blank.value) != 0:\n"
        "            return 4\n"
        "\n"
        '    with open(path, "rb") as file:\n'
        "        first = file.read_line()\n"
        "        if first.is_none or len(first.value) != 5:\n"
        "            return 5\n"
        "        if first.value.byte_at(0) != 104 or first.value.byte_at(4) != 111:\n"
        "            return 6\n"
        "        second = file.read_line()\n"
        "        if second.is_none or len(second.value) != 5:\n"
        "            return 7\n"
        "        if second.value.byte_at(0) != 119 or second.value.byte_at(4) != 100:\n"
        "            return 8\n"
        "        eof = file.read_line()\n"
        "        if eof.is_some:\n"
        "            return 9\n"
        "\n"
        '    with open(path, "rb") as file:\n'
        "        text = file.read_text()\n"
        "        if len(text) != 12:\n"
        "            return 10\n"
        "        if text.byte_at(0) != 104 or text.byte_at(11) != 10:\n"
        "            return 11\n"
        "\n"
        '    with open(path, "rb") as file:\n'
        "        data = file.read_all()\n"
        "        if len(data) != 12:\n"
        "            return 12\n"
        "        if data[0] != 104 or data[11] != 10:\n"
        "            return 13\n"
        "        print(data)\n"
        "\n"
        '    with open(path, "rb") as file:\n'
        "        sliced: u8[5]\n"
        "        counted_slice = file.read(sliced[0:5])\n"
        "        if counted_slice != 5:\n"
        "            return 14\n"
        "        if sliced[0] != 104 or sliced[4] != 111:\n"
        "            return 15\n"
        "\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    assert "fread((void *)chunk, 1, cinder_read_length, file)" in emitted.stdout
    assert "__auto_type counted = read(" not in emitted.stdout
    assert "cinder_read_line(file" in emitted.stdout
    assert "= read_line(" not in emitted.stdout
    assert "CinderOption_String" in emitted.stdout
    assert "CinderOption_String_Tag_None" in emitted.stdout
    assert "cinder_selfhost_file_read_all(file)" in emitted.stdout
    assert "cinder_selfhost_print_u64_list" in emitted.stdout
    assert "cinder_read_slice_" in emitted.stdout
    assert emitted.stdout.count("FILE *file = fopen") == 6

    output = tmp_path / (
        "file_reads.exe" if shutil.which("cl") and not shutil.which("cc") else "file_reads"
    )
    built = run_gen1(gen1_compiler, "build", str(source), "-o", str(output))
    assert built.returncode == 0, built.stderr
    executed = subprocess.run(
        [str(output)],
        check=False,
        text=True,
        capture_output=True,
        cwd=tmp_path,
    )
    assert executed.returncode == 0, executed.stderr


def test_gen1_does_not_borrow_imported_call_string_slice_rvalue(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        'name = "rvalue_slice"\n'
        'source-root = "src"\n'
        'entry = "main.ci"\n',
        encoding="utf-8",
    )
    (source_root / "lexer.ci").write_text(
        "struct Lexer:\n"
        "    source: String\n"
        "\n"
        "def new_lexer(source: String) -> Lexer:\n"
        "    return Lexer(source=source)\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import lexer\n"
        "\n"
        "def main() -> i32:\n"
        '    module_source = "abc"\n'
        "    scan = lexer.new_lexer(module_source[0:len(module_source)])\n"
        "    return len(scan.source) - 3\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"

    emitted = run_gen1(
        gen1_compiler,
        "emit-project",
        str(tmp_path / "cinder.toml"),
        "-o",
        str(generated),
    )

    assert emitted.returncode == 0, emitted.stderr
    generated_source = (generated / "cinder_gen" / "main.c").read_text(encoding="utf-8")
    assert "cinder_string_slice(&module_source, 0, module_source.length)" in generated_source
    assert "&cinder_string_slice(" not in generated_source

    output = tmp_path / (
        "rvalue_slice.exe" if shutil.which("cl") and not shutil.which("cc") else "rvalue_slice"
    )
    built = run_gen1(
        gen1_compiler,
        "build",
        str(tmp_path / "cinder.toml"),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "build"),
    )
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False)
    assert executed.returncode == 0


@pytest.mark.parametrize(
    "source_text",
    [
        'def main() -> i32:\n    return "unterminated\n',
        "def main() -> i32\n",
    ],
)
def test_gen1_check_rejects_lexer_and_parser_diagnostics(
    gen1_compiler: Path,
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "invalid.ci"
    source.write_text(source_text, encoding="utf-8")

    checked = run_gen1(gen1_compiler, "check", str(source))

    assert checked.returncode == 1
    assert checked.stdout.startswith("E ")
    assert "ok:" not in checked.stdout


@pytest.mark.parametrize(
    "source_text",
    [
        'def main() -> i32:\n    return "oops"\n',
        'def main() -> i32:\n    value: i32 = "oops"\n    return value\n',
    ],
)
def test_gen1_check_rejects_incompatible_types(
    gen1_compiler: Path,
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "incompatible.ci"
    source.write_text(source_text, encoding="utf-8")

    checked = run_gen1(gen1_compiler, "check", str(source))

    assert checked.returncode == 1
    assert checked.stdout.startswith("E 107 ")
    assert "ok:" not in checked.stdout


def test_gen1_check_rejects_cyclic_module_imports(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\nsource-root = \"src\"\nentry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text("import a\n", encoding="utf-8")
    (source_root / "a.ci").write_text("import b\n", encoding="utf-8")
    (source_root / "b.ci").write_text("import a\n", encoding="utf-8")

    checked = run_gen1(gen1_compiler, "check", str(tmp_path))

    assert checked.returncode == 1
    assert checked.stderr.strip() == "project error: cyclic module dependency: a -> b -> a"
    assert "ok:" not in checked.stdout


def test_gen1_check_rejects_ambiguous_module_layout(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    package_root = source_root / "maths"
    package_root.mkdir(parents=True)
    (tmp_path / "cinder.toml").write_text(
        "[project]\nsource-root = \"src\"\nentry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text("import maths\n", encoding="utf-8")
    file_candidate = source_root / "maths.ci"
    package_candidate = package_root / "__init__.ci"
    file_candidate.write_text("value: i32 = 1\n", encoding="utf-8")
    package_candidate.write_text("value: i32 = 2\n", encoding="utf-8")

    checked = run_gen1(gen1_compiler, "check", str(tmp_path))

    assert checked.returncode == 1
    assert checked.stderr.strip() == (
        "project error: module 'maths' is ambiguous: "
        f"both {file_candidate} and {package_candidate} exist"
    )
    assert "ok:" not in checked.stdout


@pytest.mark.parametrize("source_kind", ["file", "project"])
def test_gen1_check_rejects_missing_entry_file(
    gen1_compiler: Path,
    tmp_path: Path,
    source_kind: str,
) -> None:
    if source_kind == "file":
        source = tmp_path / "missing.ci"
        expected_entry = source
    else:
        source = tmp_path / "missing-project"
        source.mkdir()
        expected_entry = source / "src" / "main.ci"

    checked = run_gen1(gen1_compiler, "check", str(source))

    assert checked.returncode == 1
    assert checked.stderr.strip() == f"project error: entry file not found: {expected_entry}"
    assert "panic:" not in checked.stderr
    assert "ok:" not in checked.stdout


def test_gen1_check_rejects_missing_explicit_manifest(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "missing-project" / "cinder.toml"

    checked = run_gen1(gen1_compiler, "check", str(manifest))

    assert checked.returncode == 1
    assert checked.stderr.strip() == f"project error: manifest file not found: {manifest}"
    assert "panic:" not in checked.stderr
    assert "ok:" not in checked.stdout


def test_gen1_check_rejects_unknown_imported_module_member(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    manifest = write_project(tmp_path)
    main = tmp_path / "src" / "main.ci"
    main.write_text(
        "import maths\n\ndef main() -> i32:\n    return maths.absent()\n",
        encoding="utf-8",
    )

    checked = run_gen1(gen1_compiler, "check", str(manifest))

    assert checked.returncode == 1
    assert checked.stdout.startswith("E 48 ")
    assert "ok:" not in checked.stdout


@pytest.mark.parametrize(
    "import_source, expression",
    [
        ("from maths import absent", "absent()"),
        ("from maths import absent as missing", "missing()"),
    ],
)
def test_gen1_check_rejects_unknown_from_import_member(
    gen1_compiler: Path,
    tmp_path: Path,
    import_source: str,
    expression: str,
) -> None:
    manifest = write_project(tmp_path)
    main = tmp_path / "src" / "main.ci"
    main.write_text(
        f"{import_source}\n\ndef main() -> i32:\n    return {expression}\n",
        encoding="utf-8",
    )

    checked = run_gen1(gen1_compiler, "check", str(manifest))

    assert checked.returncode == 1
    assert checked.stdout.startswith("E 48 ")
    assert "ok:" not in checked.stdout


@pytest.mark.parametrize(
    "import_source, expression",
    [
        ("import maths as m", "m.answer()"),
        ("from maths import answer as result", "result()"),
    ],
)
def test_gen1_check_binds_explicit_import_aliases(
    gen1_compiler: Path,
    tmp_path: Path,
    import_source: str,
    expression: str,
) -> None:
    manifest = write_project(tmp_path)
    main = tmp_path / "src" / "main.ci"
    main.write_text(
        f"{import_source}\n\ndef main() -> i32:\n    return {expression}\n",
        encoding="utf-8",
    )

    checked = run_gen1(gen1_compiler, "check", str(manifest))

    assert checked.returncode == 0, checked.stdout
    assert checked.stdout.strip() == f"ok: {manifest}"


def test_gen1_check_is_native_and_does_not_require_python_on_path(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = write_single_source(tmp_path)

    checked = run_gen1_without_python_on_path(
        gen1_compiler,
        tmp_path,
        "check",
        str(source),
    )

    assert checked.returncode == 0, checked.stderr
    assert checked.stdout.strip() == f"ok: {source}"


def test_gen1_emit_project_build_and_run(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    manifest = write_project(tmp_path)
    generated = tmp_path / "generated"
    executable = tmp_path / (
        "selfhost_cli_demo.exe" if shutil.which("cl") and not shutil.which("cc") else "selfhost_cli_demo"
    )

    emitted = run_gen1(gen1_compiler, "emit-project", str(manifest), "-o", str(generated))
    assert emitted.returncode == 0, emitted.stderr
    assert emitted.stdout.strip() == str(generated.resolve())
    assert (generated / "cinder_gen" / "main.c").is_file()
    assert (generated / "cinder_gen" / "main.cinder.h").is_file()
    assert (generated / "cinder_gen" / "maths.c").is_file()
    assert (generated / "cinder_gen" / "maths.cinder.h").is_file()

    built = run_gen1(
        gen1_compiler,
        "build",
        str(manifest),
        "-o",
        str(executable),
        "--build-dir",
        str(tmp_path / "build"),
    )
    assert built.returncode == 0, built.stderr
    assert built.stdout.strip() == str(executable.resolve())
    assert subprocess.run([str(executable)], check=False).returncode == 42

    ran = run_gen1(gen1_compiler, "run", str(manifest))
    assert ran.returncode == 42


def test_gen1_lowers_imported_result_propagation(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_lowers_imported_result_propagation(gen1_compiler, tmp_path)


def test_gen2_lowers_imported_result_propagation(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_lowers_imported_result_propagation(gen2, tmp_path)


def test_gen1_lowers_result_state_fields(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_lowers_result_state_fields(gen1_compiler, tmp_path)


def test_gen2_lowers_result_state_fields(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_lowers_result_state_fields(gen2, tmp_path)


def test_gen1_uses_match_field_types_in_fstrings(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_uses_match_field_types_in_fstrings(gen1_compiler, tmp_path)


def test_gen2_uses_match_field_types_in_fstrings(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_uses_match_field_types_in_fstrings(gen2, tmp_path)


def test_gen1_borrows_list_for_binary_sort(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_borrows_list_for_binary_sort(gen1_compiler, tmp_path)


def test_gen2_borrows_list_for_binary_sort(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_borrows_list_for_binary_sort(gen2, tmp_path)


def test_gen1_orders_nested_option_result_specializations(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_orders_nested_option_result_specializations(gen1_compiler, tmp_path)


def test_gen2_orders_nested_option_result_specializations(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_orders_nested_option_result_specializations(gen2, tmp_path)


def test_gen1_emits_complete_class_with_owner_typed_self(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_emits_class_foundation(gen1_compiler, tmp_path)


def test_gen2_emits_complete_class_with_owner_typed_self(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_emits_class_foundation(gen2, tmp_path)


def test_gen1_lowers_class_dyn_dispatch(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_lowers_class_dyn_dispatch(gen1_compiler, tmp_path)


def test_gen2_lowers_class_dyn_dispatch(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_lowers_class_dyn_dispatch(gen2, tmp_path)


def test_gen1_lowers_reflection_builtins(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_lowers_reflection_builtins(gen1_compiler, tmp_path)


def test_gen2_lowers_reflection_builtins(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_lowers_reflection_builtins(gen2, tmp_path)


def test_gen1_lowers_cross_module_dyn(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_lowers_cross_module_dyn(gen1_compiler, tmp_path)


def test_gen2_lowers_cross_module_dyn(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_lowers_cross_module_dyn(gen2, tmp_path)


def assert_compiler_monomorphizes_user_generics(
    compiler: Path,
    tmp_path: Path,
) -> None:
    emitted = run_gen1(compiler, "emit-c", str(ROOT / "examples" / "generics.ci"))
    assert emitted.returncode == 0, emitted.stderr
    c_source = emitted.stdout
    for name in ("__Box_i32", "__Tagged_i32", "__identity_i32", "__Writer_i32"):
        assert name in c_source
    assert "int32_t value;" in c_source
    assert "int32_t item" in c_source
    assert "CinderVTable_" in c_source
    assert "Writer_i32" in c_source
    assert "__T value" not in c_source
    assert "__T item" not in c_source
    assert c_source.count("__identity_i32(int32_t value)") == 2

    executable = tmp_path / (
        "generics.exe" if shutil.which("cl") and not shutil.which("cc") else "generics"
    )
    built = run_gen1(
        compiler,
        "build",
        str(ROOT / "examples" / "generics.ci"),
        "-o",
        str(executable),
        "--build-dir",
        str(tmp_path / "build"),
    )
    assert built.returncode == 0, built.stderr
    result = subprocess.run(
        [str(executable)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.stdout == "40\n"
    assert result.returncode == 42


def test_gen1_monomorphizes_user_generics(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_monomorphizes_user_generics(gen1_compiler, tmp_path)


def test_gen2_monomorphizes_user_generics(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_monomorphizes_user_generics(gen2, tmp_path)


def test_gen1_reports_specialization_only_type_error(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "bad_generic.ci"
    source.write_text(
        "struct Marker:\n"
        "    value: i32\n"
        "\n"
        "def add_one[T](value: T) -> T:\n"
        "    return value + 1\n"
        "\n"
        "def main() -> i32:\n"
        "    marker = Marker(value=1)\n"
        "    add_one[Marker](marker)\n"
        "    return 0\n",
        encoding="utf-8",
    )
    checked = run_gen1(gen1_compiler, "check", str(source))
    assert checked.returncode == 1
    assert "E 107" in checked.stdout


def test_gen1_emits_explicit_and_multiple_user_specializations(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "multiple_generics.ci"
    source.write_text(
        "struct Box[T]:\n"
        "    value: T\n"
        "    def get(self: &const Box[T]) -> T:\n"
        "        return self.value\n"
        "\n"
        "def identity[T](value: T) -> T:\n"
        "    return value\n"
        "\n"
        "def main() -> i32:\n"
        "    integer: Box[i32] = Box(value=1)\n"
        "    decimal: Box[f64] = Box(value=2.5)\n"
        "    return identity[i32](integer.get()) + cast[i32](decimal.get()) - 2\n",
        encoding="utf-8",
    )
    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    assert "__Box_i32" in emitted.stdout
    assert "__Box_f64" in emitted.stdout
    assert "__Box_i32_get" in emitted.stdout
    assert "__Box_f64_get" in emitted.stdout
    assert "__identity_i32" in emitted.stdout
    assert "__identity_i32(int32_t value)" in emitted.stdout
    assert "#define get" not in emitted.stdout
    assert "__T value" not in emitted.stdout


def test_gen1_substitutes_nested_user_generic_types(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "nested_generics.ci"
    source.write_text(
        "struct Box[T]:\n"
        "    value: T\n"
        "\n"
        "struct Wrapper[T]:\n"
        "    inner: Box[T]\n"
        "\n"
        "def echo[T](value: T) -> T:\n"
        "    return value\n"
        "\n"
        "def main() -> i32:\n"
        "    box: Box[i32] = Box(value=1)\n"
        "    wrapped: Wrapper[i32] = Wrapper(inner=box)\n"
        "    echoed: Box[i32] = echo[Box[i32]](wrapped.inner)\n"
        "    return echoed.value\n",
        encoding="utf-8",
    )
    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    assert "__Wrapper_i32" in emitted.stdout
    assert "__Box_i32 inner;" in emitted.stdout
    assert "__echo_Box_i32" in emitted.stdout
    assert "__T" not in emitted.stdout

    executable = tmp_path / (
        "nested-generics.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "nested-generics"
    )
    built = run_gen1(
        gen1_compiler,
        "build",
        str(source),
        "-o",
        str(executable),
        "--build-dir",
        str(tmp_path / "nested-build"),
    )
    assert built.returncode == 0, built.stderr
    assert subprocess.run([str(executable)], check=False).returncode == 1


def test_gen1_validates_specialized_abstract_override(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "bad_generic_override.ci"
    source.write_text(
        "abstract class Writer[T]:\n"
        "    @abstractmethod\n"
        "    def write(self, item: T) -> void:\n"
        "        pass\n"
        "\n"
        "class BadWriter(Writer[i32]):\n"
        "    def write(self, item: f64) -> void:\n"
        "        pass\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        encoding="utf-8",
    )
    checked = run_gen1(gen1_compiler, "check", str(source))
    assert checked.returncode == 1
    assert "E 179" in checked.stdout


def test_gen1_monomorphizes_anti_example_box(
    gen1_compiler: Path,
) -> None:
    emitted = run_gen1(
        gen1_compiler,
        "emit-c",
        str(ROOT / "examples" / "anti_examples.ci"),
    )
    assert emitted.returncode == 0, emitted.stderr
    assert "__Box_i32" in emitted.stdout
    assert "int32_t value;" in emitted.stdout
    assert "__T value" not in emitted.stdout


@pytest.mark.parametrize(
    ("name", "source_text", "code"),
    [
        (
            "bare_generic",
            "struct Box[T]:\n"
            "    value: T\n\n"
            "def main() -> i32:\n"
            "    value: Box = Box(value=1)\n"
            "    return 0\n",
            352,
        ),
        (
            "generic_arity",
            "struct Box[T]:\n"
            "    value: T\n\n"
            "def main() -> i32:\n"
            "    value: Box[i32, i32] = Box(value=1)\n"
            "    return 0\n",
            352,
        ),
        (
            "generic_inference",
            "def identity[T](value: T) -> T:\n"
            "    return value\n\n"
            "def main() -> i32:\n"
            "    identity()\n"
            "    return 0\n",
            355,
        ),
    ],
)
def test_gen1_reports_user_generic_diagnostics(
    gen1_compiler: Path,
    tmp_path: Path,
    name: str,
    source_text: str,
    code: int,
) -> None:
    source = tmp_path / f"{name}.ci"
    source.write_text(source_text, encoding="utf-8")
    checked = run_gen1(gen1_compiler, "check", str(source))
    assert checked.returncode == 1
    assert f"E {code}" in checked.stdout


def test_gen1_preserves_runtime_generic_specializations(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\nname = \"specialized\"\nsource-root = \"src\"\nentry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "enum Resource:\n"
        "    value\n\n"
        "def preserve(\n"
        "    lists: List[List[i32]],\n"
        "    resources: Set[Resource],\n"
        "    mapping: Map[i32, List[i32]],\n"
        "    option: Option[List[i32]],\n"
        "    file: Option[File*],\n"
        "    result: Result[List[i32], i32],\n"
        "    pair: Tuple[List[i32], i32],\n"
        "    nested_pair: Tuple[Tuple[i32], i64],\n"
        "    nested_single: Tuple[Tuple[i32, i64]],\n"
        ") -> i32:\n"
        "    return 0\n\n"
            "def inferred_total() -> i32:\n"
            "    values = [1, 2, 3]\n"
            "    return len(values)\n\n"
        "def main() -> i32:\n"
            "    return inferred_total() - 3\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"

    emitted = run_gen1(
        gen1_compiler,
        "emit-project",
        str(tmp_path / "cinder.toml"),
        "-o",
        str(generated),
    )

    assert emitted.returncode == 0, emitted.stderr
    header = (generated / "cinder_gen" / "main.cinder.h").read_text(encoding="utf-8")
    for specialized_name in (
        "CinderList_i32",
        "CinderList_CinderList_i32",
        "CinderSet_Resource",
        "CinderMap_i32_CinderList_i32",
        "CinderOption_CinderList_i32",
        "CinderOption_FILE_ptr",
        "CinderResult_CinderList_i32_i32",
        "CinderTuple_CinderList_i32_i32",
        "CinderTuple_CinderTuple_i32_i64__CinderTuple_argument_26_CinderTuple_argument_3_i32_argument_3_i64",
        "CinderTuple_CinderTuple_i32_i64__CinderTuple_argument_41_CinderTuple_argument_3_i32_argument_3_i64",
    ):
        assert specialized_name in header
    assert "struct CinderList_i32 {" in header
    assert "int32_t *data;" in header
    assert "struct CinderList_CinderList_i32 {" in header
    assert "CinderList_i32 *data;" in header
    assert "typedef CinderList CinderList_i32;" not in header
    assert "typedef int32_t CinderOption_CinderList_i32;" not in header
    assert "struct CinderOption_CinderList_i32 {" in header
    assert "CinderOption_CinderList_i32_Tag_Some = 1" in header
    assert "CinderList_i32 value;" in header
    assert "FILE * value;" in header
    assert "struct CinderTuple_CinderList_i32_i32 {" in header
    assert "CinderList_i32 item_0;" in header
    assert "int32_t item_1;" in header
    assert "CinderMap_i32_CinderList_i32_Entry *entries;" in header
    assert "CinderSet_Resource_Entry *entries;" in header
    result_name = "CinderResult_CinderList_i32_i32"
    assert f"typedef enum {result_name}_Tag" in header
    assert f"{result_name}_Tag_Ok = 0" in header
    assert f"{result_name}_Tag_Err = 1" in header
    assert "CinderList_i32 ok;" in header
    assert "int32_t err;" in header
    generated_source = (generated / "cinder_gen" / "main.c").read_text(encoding="utf-8")
    assert "CinderList_i32 cinder_list = (CinderList_i32){0};" in generated_source

    executable = tmp_path / "specialized"
    built = run_gen1(
        gen1_compiler,
        "build",
        str(tmp_path / "cinder.toml"),
        "-o",
        str(executable),
        "--build-dir",
        str(tmp_path / "build"),
    )
    assert built.returncode == 0, built.stderr
    assert subprocess.run([str(executable)], check=False).returncode == 0


def test_gen1_emits_specialized_map_and_set_helpers(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "maps_sets.ci"
    source.write_text(
        "struct Bundle:\n"
        "    scores: Map[i32, i32]\n\n"
        "def main() -> i32:\n"
        "    values = {1, 2, 2}\n"
        "    values.add(3)\n"
        "    bundle = Bundle(scores={1: 10, 2: 20})\n"
        "    groups: Map[i32, List[i32]] = {1: [10]}\n"
        "    groups[2] = [20]\n"
        "    groups[2] = [21]\n"
        "    maybe: Option[List[i32]] = groups.get(1)\n"
        "    if len(values) != 3:\n"
        "        return 1\n"
        "    if len(bundle.scores) != 2:\n"
        "        return 2\n"
        "    if bundle.scores[1] != 10:\n"
        "        return 3\n"
        "    if groups[2][0] != 21:\n"
        "        return 4\n"
        "    if not maybe.is_some:\n"
        "        return 5\n"
        "    if maybe.value[0] != 10:\n"
        "        return 6\n"
        "    return 0\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"

    emitted = run_gen1(
        gen1_compiler,
        "emit-project",
        str(source),
        "-o",
        str(generated),
    )

    assert emitted.returncode == 0, emitted.stderr
    header = next((generated / "cinder_gen").glob("*.cinder.h")).read_text(encoding="utf-8")
    generated_source = next((generated / "cinder_gen").glob("*.c")).read_text(encoding="utf-8")
    for helper in (
        "CinderSet_i32_add",
        "CinderSet_i32_len",
        "CinderSet_i32_drop",
        "CinderMap_i32_i32_at",
        "CinderMap_i32_i32_len",
        "CinderMap_i32_CinderList_i32_set",
        "CinderMap_i32_CinderList_i32_get",
        "CinderMap_i32_CinderList_i32_drop",
    ):
        assert helper in header or helper in generated_source
    assert "CinderList_i32_drop(&(*existing));" in header
    assert "CinderList_i32_drop(&(self->entries[index].value));" in header
    assert "CinderSet_i32_add(&values, 3)" in generated_source
    assert "CinderMap_i32_CinderList_i32_set(&groups, 2" in generated_source
    assert "CinderMap_i32_CinderList_i32_get(&groups, 1)" in generated_source
    assert "CinderMap_i32_CinderList_i32_drop(&groups);" in generated_source

    executable = tmp_path / "maps-sets"
    built = run_gen1(
        gen1_compiler,
        "build",
        str(source),
        "-o",
        str(executable),
        "--build-dir",
        str(tmp_path / "build"),
    )
    assert built.returncode == 0, built.stderr
    assert subprocess.run([str(executable)], check=False).returncode == 0


def assert_compiler_builds_and_runs_closures_example(
    compiler: Path,
    tmp_path: Path,
) -> None:
    executable = tmp_path / (
        "closures.exe" if shutil.which("cl") and not shutil.which("cc") else "closures"
    )
    build_dir = tmp_path / "closures-build"
    built = run_gen1(
        compiler,
        "build",
        str(ROOT / "examples" / "closures.ci"),
        "-o",
        str(executable),
        "--build-dir",
        str(build_dir),
    )

    assert built.returncode == 0, built.stderr
    header = (build_dir / "cinder_gen" / "closures.cinder.h").read_text(
        encoding="utf-8"
    )
    generated = (build_dir / "cinder_gen" / "closures.c").read_text(
        encoding="utf-8"
    )
    assert " env;" in header
    assert "(*call)(" in header
    assert "void * callback" not in header
    assert "__closure(" not in generated
    assert ".call = cinder_closures_closures__add_with_env" in generated
    assert "->call(&" in generated

    ran = subprocess.run([str(executable)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "add: 42\ncounter: 15\ncounter: 22\n"


def test_gen1_builds_and_runs_closures_example(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_builds_and_runs_closures_example(gen1_compiler, tmp_path)


def test_gen2_builds_and_runs_closures_example(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_builds_and_runs_closures_example(gen2, tmp_path)


def test_gen1_builds_and_runs_print_example(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    executable = tmp_path / (
        "print.exe" if shutil.which("cl") and not shutil.which("cc") else "print"
    )
    build_dir = tmp_path / "print-build"
    built = run_gen1(
        gen1_compiler,
        "build",
        str(ROOT / "examples" / "print.ci"),
        "-o",
        str(executable),
        "--build-dir",
        str(build_dir),
    )

    assert built.returncode == 0, built.stderr
    generated = (build_dir / "cinder_gen" / "print.c").read_text(encoding="utf-8")
    assert "CinderMap_String_i32_print" in generated
    assert "CinderSet_i32_print" in generated
    assert "CinderTuple_i32_String_print" in generated
    assert "CinderMap_String_i32_clear(&scores)" in generated
    assert "CinderSet_i32_clear(&primes)" in generated
    assert "cinder_selfhost_list_clear(&scores)" not in generated
    assert "cinder_selfhost_list_clear(&primes)" not in generated

    ran = subprocess.run([str(executable)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == (
        "print is available without importing stdio\n"
        "multiple values: Cinder 3 true\n"
        "default formats: string=Cinder bool=true char=C int=3 float=3.14159\n"
        "explicit scalar formats: string=Cinder bool=true char=C\n"
        "integer formats: d=3 i=3 u=3 o=3 x=3 X=3\n"
        "large integers: signed=-9223372036854775808 unsigned=18446744073709551615 hex=FFFFFFFFFFFFFFFF\n"
        "base values: hex=DEADBEEF octal=755 binary 0b1010110011110000=44272\n"
        "float formats: f=3.141590 F=3.141590 e=3.141590e+00 E=3.141590E+00 g=3.14159 G=3.14159\n"
        "float precision: f=3.14 F=3.14 e=3.142e+00 E=3.142E+00 g=3.142 G=3.142\n"
        "expressions: count + 1=4 nested=Cinder #3\n"
        "escaped braces {like this} and a literal percent 100%\n"
        "[1, 2, 3]\n"
        "{'Ada': 1, 'Grace': 2}\n"
        "{5, 3, 2}\n"
        "(1, 'ready')\n"
        "values=[1, 2, 3]\n"
    )

    fstring_source = tmp_path / "collection_fstrings.ci"
    fstring_source.write_text(
        "def main() -> i32:\n"
        "    scores: Map[String, i32] = {\"Ada\": 1}\n"
        "    defer scores.clear()\n"
        "    primes: Set[i32] = {2}\n"
        "    defer primes.clear()\n"
        "    pair: Tuple[i32, String] = (1, \"ready\")\n"
        "    singleton: Tuple[i32] = (1,)\n"
        "    nested: Map[String, List[i32]] = {\"numbers\": [1, 2]}\n"
        "    defer nested.clear()\n"
        "    print(f\"scores={scores} primes={primes} pair={pair} singleton={singleton} nested={nested}\")\n"
        "    return 0\n",
        encoding="utf-8",
    )
    fstring_executable = tmp_path / (
        "collection-fstrings.exe"
        if shutil.which("cl") and not shutil.which("cc")
        else "collection-fstrings"
    )
    fstring_build = run_gen1(
        gen1_compiler,
        "build",
        str(fstring_source),
        "-o",
        str(fstring_executable),
        "--build-dir",
        str(tmp_path / "fstring-build"),
    )
    assert fstring_build.returncode == 0, fstring_build.stderr
    fstring_ran = subprocess.run(
        [str(fstring_executable)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert fstring_ran.returncode == 0, fstring_ran.stderr
    assert fstring_ran.stdout == (
        "scores={'Ada': 1} primes={2} pair=(1, 'ready') singleton=(1,) "
        "nested={'numbers': [1, 2]}\n"
    )


def test_gen1_map_set_hash_and_equality_strategies(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "map_set_hashing.ci"
    source.write_text(
        "enum Tone:\n"
        "    red\n"
        "    green\n"
        "    blue\n"
        "\n"
        "def make_alpha() -> *char:\n"
        "    text = alloc[char](6)\n"
        "    text[0] = 'a'\n"
        "    text[1] = 'l'\n"
        "    text[2] = 'p'\n"
        "    text[3] = 'h'\n"
        "    text[4] = 'a'\n"
        "    text[5] = '\\0'\n"
        "    return text\n"
        "\n"
        "def check_c_strings() -> i32:\n"
        "    first = make_alpha()\n"
        "    second = make_alpha()\n"
        "    if first == second:\n"
        "        return 10\n"
        "    scores: Map[const char*, i32] = {first: 7}\n"
        "    names: Set[const char*] = {first}\n"
        "    if scores[second] != 7:\n"
        "        return 11\n"
        "    names.add(second)\n"
        "    if len(names) != 1:\n"
        "        return 12\n"
        "    scores[second] = 9\n"
        "    names.add(second)\n"
        "    if len(scores) != 1 or len(names) != 1:\n"
        "        return 13\n"
        "    first[0] = 'z'\n"
        "    free(first)\n"
        "    if scores[second] != 9:\n"
        "        return 14\n"
        "    names.add(second)\n"
        "    if len(names) != 1:\n"
        "        return 15\n"
        "    free(second)\n"
        "    return 0\n"
        "\n"
        "def check_enums() -> i32:\n"
        "    scores: Map[Tone, i32] = {Tone.red: 10, Tone.green: 20}\n"
        "    tones: Set[Tone] = {Tone.red, Tone.green, Tone.red}\n"
        "    scores[Tone.blue] = 30\n"
        "    scores[Tone.green] = 21\n"
        "    tones.add(Tone.blue)\n"
        "    tones.add(Tone.green)\n"
        "    if len(scores) != 3 or len(tones) != 3:\n"
        "        return 20\n"
        "    if scores[Tone.red] != 10 or scores[Tone.green] != 21:\n"
        "        return 21\n"
        "    if scores[Tone.blue] != 30:\n"
        "        return 22\n"
        "    return 0\n"
        "\n"
        "def check_strings() -> i32:\n"
        "    scores: Map[String, i32] = {\"alpha\": 7}\n"
        "    names: Set[String] = {\"alpha\", \"alpha\"}\n"
        "    if scores[\"alpha\"] != 7 or len(names) != 1:\n"
        "        return 25\n"
        "    return 0\n"
        "\n"
        "def check_scalar_types() -> i32:\n"
        "    bools: Set[bool] = {true}\n"
        "    chars: Set[char] = {'a'}\n"
        "    i8s: Set[i8] = {cast[i8](1)}\n"
        "    i16s: Set[i16] = {cast[i16](1)}\n"
        "    i64s: Set[i64] = {cast[i64](1)}\n"
        "    u8s: Set[u8] = {cast[u8](1)}\n"
        "    u16s: Set[u16] = {cast[u16](1)}\n"
        "    u32s: Set[u32] = {cast[u32](1)}\n"
        "    u64s: Set[u64] = {cast[u64](1)}\n"
        "    isizes: Set[isize] = {cast[isize](1)}\n"
        "    usizes: Set[usize] = {cast[usize](1)}\n"
        "    c_ints: Set[c_int] = {cast[c_int](1)}\n"
        "    c_longs: Set[c_long] = {cast[c_long](1)}\n"
        "    c_sizes: Set[c_size_t] = {cast[c_size_t](1)}\n"
        "    return cast[i32](len(bools) + len(chars) + len(i8s) + len(i16s)"
        " + len(i64s) + len(u8s) + len(u16s) + len(u32s) + len(u64s)"
        " + len(isizes) + len(usizes) + len(c_ints) + len(c_longs)"
        " + len(c_sizes)) - 14\n"
        "\n"
        "def check_scalar_growth() -> i32:\n"
        "    scores: Map[i32, i32] = {}\n"
        "    values: Set[i32] = {0}\n"
        "    for index in range(0, 128):\n"
        "        scores[index] = index * 3\n"
        "        values.add(index)\n"
        "    for index in range(0, 128):\n"
        "        scores[index] = scores[index] + 1\n"
        "        values.add(index)\n"
        "    if len(scores) != 128 or len(values) != 128:\n"
        "        return 30\n"
        "    for index in range(0, 128):\n"
        "        if scores[index] != index * 3 + 1:\n"
        "            return 31\n"
        "    return 0\n"
        "\n"
        "def main() -> i32:\n"
        "    result = check_c_strings()\n"
        "    if result != 0:\n"
        "        return result\n"
        "    result = check_enums()\n"
        "    if result != 0:\n"
        "        return result\n"
        "    result = check_strings()\n"
        "    if result != 0:\n"
        "        return result\n"
        "    result = check_scalar_types()\n"
        "    if result != 0:\n"
        "        return result\n"
        "    return check_scalar_growth()\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"

    emitted = run_gen1(
        gen1_compiler,
        "emit-project",
        str(source),
        "-o",
        str(generated),
    )

    assert emitted.returncode == 0, emitted.stderr
    generated_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((generated / "cinder_gen").glob("*.[ch]"))
    )
    assert "cinder_hash_string(key)" in generated_text
    assert "cinder_hash_string(value)" in generated_text
    assert "cinder_string_equal(left, right)" in generated_text
    assert "cinder_string_hash_value(&(key))" in generated_text
    assert "cinder_string_equal_value(&(left), &(right))" in generated_text
    assert "cinder_clone_string(key)" in generated_text
    assert "cinder_clone_string(value)" in generated_text
    assert "free((void *)(self->entries[index].key));" in generated_text
    assert "free((void *)(self->entries[index].value));" in generated_text
    assert "free((void *)(key));" not in generated_text
    assert "free((void *)(value));" not in generated_text
    assert "cinder_hash_u64((uint64_t)(key))" in generated_text
    assert "cinder_hash_u64((uint64_t)(value))" in generated_text
    assert "_hash(old_entries[index].value)" in generated_text
    assert "_hash(self->entries[entry_index].key)" in generated_text

    executable = tmp_path / "map-set-hashing"
    built = run_gen1(
        gen1_compiler,
        "build",
        str(source),
        "-o",
        str(executable),
        "--build-dir",
        str(tmp_path / "build"),
    )
    assert built.returncode == 0, built.stderr
    assert subprocess.run([str(executable)], check=False).returncode == 0


def test_gen1_map_set_supports_imported_enum_keys(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\nname = \"enum_keys\"\nsource-root = \"src\"\nentry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "tones.ci").write_text(
        "enum Tone:\n"
        "    red\n"
        "    green\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import tones\n"
        "from tones import Tone as Shade\n"
        "\n"
        "def main() -> i32:\n"
        "    scores: Map[Shade, i32] = {Shade.red: 1}\n"
        "    shades: Set[tones.Tone] = {Shade.red, Shade.green}\n"
        "    scores[Shade.green] = 2\n"
        "    if len(scores) != 2 or len(shades) != 2:\n"
        "        return 1\n"
        "    return scores[Shade.green] - 2\n",
        encoding="utf-8",
    )
    executable = tmp_path / "imported-enum-keys"

    built = run_gen1(
        gen1_compiler,
        "build",
        str(tmp_path / "cinder.toml"),
        "-o",
        str(executable),
        "--build-dir",
        str(tmp_path / "build"),
    )

    assert built.returncode == 0, built.stderr
    assert subprocess.run([str(executable)], check=False).returncode == 0


@pytest.mark.parametrize(
    ("source_text", "code"),
    [
        ("def reject(value: Map[f64, i32]) -> void:\n    pass\n", 297),
        ("def reject(value: Map[*i32, i32]) -> void:\n    pass\n", 297),
        (
            "def reject(value: Map[Map[i32, i32], i32]) -> void:\n"
            "    pass\n",
            297,
        ),
        (
            "struct Item:\n"
            "    value: i32\n"
            "\n"
            "def reject(value: Map[Item, i32]) -> void:\n"
            "    pass\n",
            297,
        ),
        ("def reject(value: Set[f64]) -> void:\n    pass\n", 300),
        ("def reject(value: Set[*i32]) -> void:\n    pass\n", 300),
        (
            "def reject(value: Set[Map[i32, i32]]) -> void:\n"
            "    pass\n",
            300,
        ),
        (
            "def main() -> i32:\n"
            "    values = {1.5: 1}\n"
            "    return 0\n",
            297,
        ),
        (
            "def main() -> i32:\n"
            "    values = {1.5}\n"
            "    return 0\n",
            300,
        ),
    ],
)
def test_gen1_rejects_non_hashable_map_and_set_types(
    gen1_compiler: Path,
    tmp_path: Path,
    source_text: str,
    code: int,
) -> None:
    source = tmp_path / "invalid_hash_type.ci"
    source.write_text(source_text, encoding="utf-8")

    checked = run_gen1(gen1_compiler, "check", str(source))

    assert checked.returncode == 1
    assert checked.stdout.startswith(f"E {code} ")


def assert_compiler_propagates_expected_aggregate_types(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "expected_aggregates.ci"
    source.write_text(
        "struct Bundle:\n"
        "    values: List[i32]\n"
        "    fixed: i32[3]\n"
        "\n"
        "class Holder:\n"
        "    values: List[i32]\n"
        "\n"
        "    def __init__(self, values: List[i32]):\n"
        "        self.values = values\n"
        "\n"
        "    def replace(self, values: List[i32]) -> void:\n"
        "        self.values = values\n"
        "\n"
        "def consume(values: List[i32]) -> i32:\n"
        "    return cast[i32](len(values))\n"
        "\n"
        "def main() -> i32:\n"
        "    values = [1, 2]\n"
        "    values = [3, 4]\n"
        "    rows: List[i32][2] = [[5], [6, 7]]\n"
        "    named = Bundle(values=[8, 9], fixed=[10, 11, 12])\n"
        "    positional = Bundle([13], [14, 15, 16])\n"
        "    holder = Holder([17])\n"
        "    replacement = [18, 19]\n"
        "    holder.replace(replacement)\n"
        "    if len(values) != 2 or values[0] != 3:\n"
        "        return 1\n"
        "    if len(rows[0]) != 1 or len(rows[1]) != 2:\n"
        "        return 2\n"
        "    if named.fixed[2] != 12 or positional.fixed[0] != 14:\n"
        "        return 3\n"
        "    if len(named.values) != 2 or len(positional.values) != 1:\n"
        "        return 4\n"
        "    if len(holder.values) != 2:\n"
        "        return 5\n"
        "    if consume([20, 21]) != 2:\n"
        "        return 6\n"
        "    return 0\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"

    emitted = run_gen1(
        compiler,
        "emit-project",
        str(source),
        "-o",
        str(generated),
    )

    assert emitted.returncode == 0, emitted.stderr
    generated_source = next((generated / "cinder_gen").glob("*.c"))
    source_text = generated_source.read_text(encoding="utf-8")
    assert "struct CinderList_i32 {" in source_text
    assert "int32_t *data;" in source_text
    assert "CinderList_i32 cinder_list = (CinderList_i32){0};" in source_text
    assert "values = ({ CinderList_i32 cinder_list" in source_text
    assert "values = ({ CinderList cinder_list" not in source_text
    assert "CinderList_i32 rows[2] = {({" in source_text
    assert "CinderList_i32 rows[2] = {{5}, {6, 7}};" not in source_text
    assert ".fixed = {10, 11, 12}" in source_text
    assert "cinder_list; }), {14, 15, 16}" in source_text
    assert "Holder_replace(&holder, replacement)" in source_text
    assert "Holder_replace(&holder, &replacement)" not in source_text
    executable = tmp_path / "expected-aggregates"
    compiled = compile_generated_project(generated, executable)
    assert compiled.returncode == 0, compiled.stderr
    assert subprocess.run([str(executable)], check=False).returncode == 0


def test_gen1_propagates_expected_aggregate_types(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_propagates_expected_aggregate_types(gen1_compiler, tmp_path)


def test_gen2_propagates_expected_aggregate_types(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_propagates_expected_aggregate_types(gen2, tmp_path)


def test_gen1_propagates_aggregate_types_in_affected_examples(
    gen1_compiler: Path,
) -> None:
    aggregate = run_gen1(
        gen1_compiler,
        "emit-c",
        str(ROOT / "examples" / "aggregate_ownership.ci"),
    )
    assert aggregate.returncode == 0, aggregate.stderr
    assert "CinderList_i32 rows[2] = {({" in aggregate.stdout
    assert "CinderList_i32 rows[2] = {{1}, {2, 3}};" not in aggregate.stdout
    assert "Portfolio_replace_holdings(&portfolio, replacement)" in aggregate.stdout
    assert "Portfolio_replace_holdings(&portfolio, &replacement)" not in aggregate.stdout

    dijkstra = run_gen1(
        gen1_compiler,
        "emit-c",
        str(ROOT / "examples" / "dijkstra_showcase.ci"),
    )
    assert dijkstra.returncode == 0, dijkstra.stderr
    assert ".weights = {0, 7, 9, 0, 0, 14" in dijkstra.stdout
    assert ".weights = ({ CinderList cinder_list" not in dijkstra.stdout

    anti_examples = run_gen1(
        gen1_compiler,
        "emit-c",
        str(ROOT / "examples" / "anti_examples.ci"),
    )
    assert anti_examples.returncode == 0, anti_examples.stderr
    assert "values = ({ CinderList_i32 cinder_list" in anti_examples.stdout
    assert "values = ({ CinderList cinder_list" not in anti_examples.stdout


def test_gen1_emits_inferred_list_specialization(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "inferred.ci"
    source.write_text(
        "def main() -> i32:\n"
        "    values = [1, 2, 3]\n"
        "    return len(values) - 3\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"

    emitted = run_gen1(
        gen1_compiler,
        "emit-project",
        str(source),
        "-o",
        str(generated),
    )

    assert emitted.returncode == 0, emitted.stderr
    generated_source = next((generated / "cinder_gen").glob("*.c"))
    source_text = generated_source.read_text(encoding="utf-8")
    assert "struct CinderList_i32 {" in source_text
    assert "int32_t *data;" in source_text
    assert "CinderList_i32 cinder_list = (CinderList_i32){0};" in source_text
    executable = tmp_path / "inferred"
    compiled = compile_generated_project(generated, executable)
    assert compiled.returncode == 0, compiled.stderr
    assert subprocess.run([str(executable)], check=False).returncode == 0


def test_gen1_drops_explicit_and_inferred_file_list_elements(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    explicit = tmp_path / "explicit_file_list.ci"
    explicit.write_text(
        "def main() -> i32:\n"
        "    files: List[File] = []\n"
        '    files.append(open("explicit_file_list.txt", "w"))\n'
        "    return len(files) - 1\n",
        encoding="utf-8",
    )
    explicit_emitted = run_gen1(gen1_compiler, "emit-c", str(explicit))
    assert explicit_emitted.returncode == 0, explicit_emitted.stderr
    explicit_drop_start = explicit_emitted.stdout.index(
        "static inline void CinderList_FILE_drop(CinderList_FILE *self) {"
    )
    explicit_drop_end = explicit_emitted.stdout.index("#endif", explicit_drop_start)
    explicit_drop = explicit_emitted.stdout[explicit_drop_start:explicit_drop_end]
    assert "for (size_t index = 0; index < self->length; index += 1)" in explicit_drop
    assert "fclose(self->data[index]);" in explicit_drop

    inferred = tmp_path / "inferred_file_list.ci"
    inferred.write_text(
        "def open_files() -> List[File]:\n"
        "    files: List[File] = []\n"
        '    files.append(open("inferred_file_list.txt", "w"))\n'
        "    return files\n"
        "\n"
        "def main() -> i32:\n"
        "    files = open_files()\n"
        "    return len(files) - 1\n",
        encoding="utf-8",
    )
    generated = tmp_path / "inferred-file-list-generated"
    inferred_emitted = run_gen1(
        gen1_compiler,
        "emit-project",
        str(inferred),
        "-o",
        str(generated),
    )
    assert inferred_emitted.returncode == 0, inferred_emitted.stderr
    generated_source = generated / "cinder_gen" / "inferred_file_list.c"
    source_text = generated_source.read_text(encoding="utf-8")
    inferred_drop_start = source_text.index(
        "static inline void CinderList_FILE_drop(CinderList_FILE *self) {"
    )
    inferred_drop_end = source_text.index("#endif", inferred_drop_start)
    inferred_drop = source_text[inferred_drop_start:inferred_drop_end]
    assert "for (size_t index = 0; index < self->length; index += 1)" in inferred_drop
    assert "fclose(self->data[index]);" in inferred_drop

    executable = tmp_path / "inferred-file-list"
    compiled = compile_generated_project(generated, executable)
    assert compiled.returncode == 0, compiled.stderr


def test_gen1_builds_and_runs_result_specialization_example(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    executable = tmp_path / (
        "types_and_results.exe" if shutil.which("cl") and not shutil.which("cc") else "types_and_results"
    )
    build_dir = tmp_path / "build"

    built = run_gen1(
        gen1_compiler,
        "build",
        str(ROOT / "examples" / "types_and_results.ci"),
        "-o",
        str(executable),
        "--build-dir",
        str(build_dir),
    )

    assert built.returncode == 0, built.stderr
    generated = (build_dir / "cinder_gen" / "types_and_results.c").read_text(
        encoding="utf-8"
    )
    assert ".data.ok =" in generated
    assert ".data.err =" in generated
    assert "cinder_result.tag ==" in generated
    assert "cinder_match_value.data.Integer.value" in generated

    ran = subprocess.run([str(executable)], check=False, text=True, capture_output=True)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "value=42\n"


def test_gen1_canonicalizes_qualified_specialization_names(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    (source_root / "support").mkdir(parents=True)
    (tmp_path / "cinder.toml").write_text(
        "[project]\nname = \"specialized\"\nsource-root = \"src\"\nentry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "support" / "errors.ci").write_text(
        "struct MathError:\n"
        "    code: i32\n\n"
        "struct OtherError:\n"
        "    code: i64\n",
        encoding="utf-8",
    )
    (source_root / "support" / "other_errors.ci").write_text(
        "struct MathError:\n"
        "    code: i64\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import support.errors as calculations\n"
        "import support.errors as failures\n"
        "import support.other_errors as alternatives\n\n"
        "def preserve(\n"
        "    first: Result[i32, calculations.MathError],\n"
        "    same: Result[i32, failures.MathError],\n"
        "    other: Result[i32, calculations.OtherError],\n"
        "    colliding: Result[i32, alternatives.MathError],\n"
        ") -> i32:\n"
        "    return 0\n\n"
        "def main() -> i32:\n"
        "    return 0\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"

    emitted = run_gen1(
        gen1_compiler,
        "emit-project",
        str(tmp_path / "cinder.toml"),
        "-o",
        str(generated),
    )

    assert emitted.returncode == 0, emitted.stderr
    header = (generated / "cinder_gen" / "main.cinder.h").read_text(encoding="utf-8")
    math_error = "CinderResult_i32_MathError__CinderResult_argument_3_i32_argument_"
    other_error = "CinderResult_i32_OtherError"
    assert header.count(f"#ifndef CINDER_SPECIALIZED_{math_error}") == 2
    assert "cinder_specialized_support_errors__MathError" in header
    assert "cinder_specialized_support_other_errors__MathError" in header
    assert other_error in header
    assert "CinderResult_i32_calculations" not in header
    assert "CinderResult_i32_failures" not in header


def test_gen1_distinguishes_structural_specialization_arguments(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\nname = \"structural\"\nsource-root = \"src\"\nentry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "struct A_argument_cinder_structural_main__B:\n"
        "    value: i32\n\n"
        "struct A:\n"
        "    value: i32\n\n"
        "struct B:\n"
        "    value: i32\n\n"
        "def preserve(\n"
        "    integers: List[i32[2]],\n"
        "    strings: List[String[4]],\n"
        "    slice: List[[]i32],\n"
        "    callback: List[def(i32) -> i64],\n"
        "    predicate: List[def(i64) -> i32],\n"
        "    callback_argument: List[def(def(i32) -> i32)],\n"
        "    callback_return: List[def() -> def(i32) -> i32],\n"
        "    commented_arrow_argument: List[def # -> not a return\n"
        "        (i32)],\n"
        "    delimited_nominal: List[def(A_argument_cinder_structural_main__B)],\n"
        "    separate_nominals: List[def(A, B)],\n"
        ") -> i32:\n"
        "    return 0\n\n"
        "def main() -> i32:\n"
        "    return 0\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"

    emitted = run_gen1(
        gen1_compiler,
        "emit-project",
        str(tmp_path / "cinder.toml"),
        "-o",
        str(generated),
    )

    assert emitted.returncode == 0, emitted.stderr
    header = (generated / "cinder_gen" / "main.cinder.h").read_text(encoding="utf-8")
    for specialized_name in (
        "CinderList_i32_array_2",
        "CinderList_String_array_4",
        "CinderList_i32_slice",
        "CinderList_function_argument_i32_returns_i64_end",
        "CinderList_function_argument_i64_returns_i32_end",
        "CinderList_function_argument_function_argument_i32_returns_i32_end_end",
        "CinderList_function_returns_function_argument_i32_returns_i32_end_end",
        "CinderList_function_argument_i32_end",
        "CinderList_function_argument_A_argument_cinder_structural_main__B_end",
        "CinderList_function_argument_A_argument_B_end",
    ):
        assert specialized_name in header
    assert "int32_t (*data)[2];" in header
    assert "CinderString (*data)[4];" in header
    compiled = compile_generated_project(generated, tmp_path / "structural")
    assert compiled.returncode == 0, compiled.stderr
    assert "CinderList_value" not in header


def test_gen1_distinguishes_pointer_and_reference_specialization_arguments(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\nname = \"indirection\"\nsource-root = \"src\"\nentry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "struct Thing:\n"
        "    value: i32\n\n"
        "struct Thing_ptr:\n"
        "    value: i32\n\n"
        "def preserve(\n"
        "    pointer: List[i32*],\n"
        "    reference: List[&i32],\n"
        "    nominal_pointer: List[Thing*],\n"
        "    structural_suffix: List[Thing_ptr],\n"
        ") -> i32:\n"
        "    return 0\n\n"
        "def main() -> i32:\n"
        "    return 0\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"

    emitted = run_gen1(
        gen1_compiler,
        "emit-project",
        str(tmp_path / "cinder.toml"),
        "-o",
        str(generated),
    )

    assert emitted.returncode == 0, emitted.stderr
    header = (generated / "cinder_gen" / "main.cinder.h").read_text(encoding="utf-8")
    assert "CinderList_i32_ptr" in header
    assert "CinderList_i32_ref" in header
    assert (
        "CinderList_Thing_ptr__"
        "CinderList_argument_41_pointer_30_cinder_indirection_main__Thing"
    ) in header
    assert (
        "CinderList_Thing_ptr__"
        "CinderList_argument_34_cinder_indirection_main__Thing_ptr"
    ) in header


def test_gen1_preserves_const_specialization_arguments(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\nname = \"const_specialization\"\nsource-root = \"src\"\nentry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "def preserve(\n"
        "    const_result: Result[const i32, i32],\n"
        "    mutable_result: Result[i32, i32],\n"
        "    const_owned: Owned[const i32],\n"
        "    mutable_owned: Owned[i32],\n"
        "    const_pointer: List[*const i32],\n"
        "    mutable_pointer: List[*i32],\n"
        ") -> i32:\n"
        "    return 0\n\n"
        "def main() -> i32:\n"
        "    return 0\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"

    emitted = run_gen1(
        gen1_compiler,
        "emit-project",
        str(tmp_path / "cinder.toml"),
        "-o",
        str(generated),
    )

    assert emitted.returncode == 0, emitted.stderr
    header = (generated / "cinder_gen" / "main.cinder.h").read_text(encoding="utf-8")
    for specialized_name in (
        "CinderResult_i32_const_i32",
        "CinderResult_i32_i32",
        "CinderOwned_i32_const",
        "CinderOwned_i32",
        "CinderList_i32_const_ptr",
        "CinderList_i32_ptr",
    ):
        assert specialized_name in header


def test_gen1_build_accepts_equals_form_ldflag(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = write_single_source(tmp_path)
    missing_link_input = tmp_path / "missing-link-input.o"

    built = run_gen1(
        gen1_compiler,
        "build",
        str(source),
        f"--ldflag={missing_link_input}",
        "--build-dir",
        str(tmp_path / "build"),
    )

    assert built.returncode == 2
    assert "toolchain error: C compiler failed" in built.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX execvp pathname regression")
def test_gen1_run_executes_default_artifact_from_current_directory(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    write_project(tmp_path)
    (tmp_path / "cinder").symlink_to(ROOT / "cinder", target_is_directory=True)

    ran = subprocess.run(
        [str(gen1_compiler), "run", "."],
        cwd=tmp_path,
        check=False,
        text=True,
        capture_output=True,
    )

    assert ran.returncode == 42, ran.stderr
    assert (tmp_path / "selfhost_cli_demo").is_file()


def test_gen1_builds_compiler_sources_into_gen2(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, build_dir = gen2_compiler

    assert gen2.is_file()
    assert (build_dir / "cinder_gen" / "compiler_main.c").is_file()
    assert (build_dir / "cinder_gen" / "checker.c").is_file()
    assert not (build_dir / "cinder_selfhost_gen2.c").exists()

    assert not (build_dir / "cinder_selfhost_replay.c").exists()

    specializations = (
        build_dir / "cinder_gen" / "codegen_specializations.c"
    ).read_text(encoding="utf-8")
    assert "cinder_string_builder_append(&phase_builder," in specializations
    assert '.data = (char *)"_helpers"' in specializations
    assert '.data = (char *)"_layout"' in specializations
    assert '.data = (char *)"CinderOption_"' in specializations
    assert "cinder_string_builder_append(&option_builder," in specializations
    assert "cinder_selfhost_list_append_value(&phase_builder" not in specializations
    assert "cinder_selfhost_list_append_value(&option_builder" not in specializations

    source = write_single_source(tmp_path)
    checked = run_gen1_without_python_on_path(gen2, tmp_path, "check", str(source))
    assert checked.returncode == 0, checked.stderr
    assert checked.stdout.strip() == f"ok: {source}"


def test_gen1_generated_compiler_project_builds_without_replay(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    _gen2, build_dir = gen2_compiler
    direct_gen2 = tmp_path / (
        "cinder-direct-gen2.exe" if shutil.which("cl") and not shutil.which("cc") else "cinder-direct-gen2"
    )

    compiled = compile_generated_project(build_dir, direct_gen2)

    assert compiled.returncode == 0, compiled.stderr
    assert direct_gen2.is_file()

    source = write_single_source(tmp_path)
    checked = run_gen1_without_python_on_path(direct_gen2, tmp_path, "check", str(source))
    assert checked.returncode == 0, checked.stderr
    assert checked.stdout.strip() == f"ok: {source}"


def test_gen1_and_gen2_emit_same_compiler_project_tree(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, gen1_generated = gen2_compiler
    gen2_generated = tmp_path / "gen2-generated"

    gen2_emitted = run_gen1(
        gen2,
        "emit-project",
        str(ROOT / "compiler_selfhost"),
        "-o",
        str(gen2_generated),
    )
    assert gen2_emitted.returncode == 0, gen2_emitted.stderr
    assert gen2_emitted.stdout.strip() == str(gen2_generated.resolve())

    assert collect_normalized_tree(gen2_generated) == collect_normalized_tree(gen1_generated)


def test_gen1_map_views_and_set_algebra_end_to_end(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "collection_parity.ci"
    source.write_text(
        "def view_contains(words: &const Map[String, i32], wanted: String) -> bool:\n"
        "    for key in words.keys():\n"
        "        if key == wanted:\n"
        "            return true\n"
        "    return false\n"
        "\n"
        "def main() -> i32:\n"
        '    words: Map[String, i32] = {"one": 1, "two": 2}\n'
        "    keys: MapKeys[String, i32] = words.keys()\n"
        "    values: MapValues[String, i32] = words.values()\n"
        "    items: MapItems[String, i32] = words.items()\n"
        '    words["three"] = 3\n'
        "    if len(keys) != 3 or len(values) != 3 or len(items) != 3:\n"
        "        return 1\n"
        '    if "three" not in keys or 3 not in values or ("two", 2) not in items:\n'
        "        return 2\n"
        "    key_count: i32 = 0\n"
        "    for key in keys:\n"
        "        key_count += 1\n"
        "    value_total: i32 = 0\n"
        "    for value in values:\n"
        "        value_total += value\n"
        "    item_total: i32 = 0\n"
        "    for item in items:\n"
        "        item_total += item[1]\n"
        "    if key_count != 3 or value_total != 6 or item_total != 6:\n"
        "        return 3\n"
        '    if not view_contains(&words, "two"):\n'
        "        return 10\n"
        '    words["four"] = 4\n'
        '    if len(keys) != 4 or "four" not in keys:\n'
        "        return 11\n"
        "    left = {1, 2, 3}\n"
        "    right = {3, 4}\n"
        "    united = left | right\n"
        "    common = left & right\n"
        "    difference = left - right\n"
        "    symmetric = left ^ right\n"
        "    if len(united) != 4 or 4 not in united or len(common) != 1 or 3 not in common:\n"
        "        return 4\n"
        "    if len(difference) != 2 or 1 not in difference or len(symmetric) != 3 or 4 not in symmetric:\n"
        "        return 5\n"
        "    method_union = left.union(right)\n"
        "    method_intersection = left.intersection(right)\n"
        "    method_difference = left.difference(right)\n"
        "    method_symmetric = left.symmetric_difference(right)\n"
        "    if len(method_union) != 4 or len(method_intersection) != 1:\n"
        "        return 6\n"
        "    if len(method_difference) != 2 or len(method_symmetric) != 3:\n"
        "        return 7\n"
        "    left |= right\n"
        "    left &= {2, 3, 4}\n"
        "    left -= {3}\n"
        "    left ^= {5}\n"
        "    left.update({6, 7})\n"
        "    if len(left) != 5 or 2 not in left or 4 not in left or 5 not in left or 6 not in left or 7 not in left:\n"
        "        return 8\n"
        '    string_left: Set[String] = {"a", "b"}\n'
        '    string_right: Set[String] = {"b", "c"}\n'
        "    string_union = string_left | string_right\n"
        '    if len(string_union) != 3 or "a" not in string_union or "c" not in string_union:\n'
        "        return 9\n"
        "    return 0\n",
        encoding="utf-8",
    )

    emitted = run_gen1(gen1_compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    assert "struct CinderMapKeys_String_i32" in emitted.stdout
    assert "struct CinderMapValues_String_i32" in emitted.stdout
    assert "struct CinderMapItems_String_i32" in emitted.stdout
    assert "CinderSet_i32_union" in emitted.stdout
    assert "CinderSet_i32_intersection" in emitted.stdout
    assert "CinderSet_i32_difference" in emitted.stdout
    assert "CinderSet_i32_symmetric_difference" in emitted.stdout
    assert "CinderSet_i32_update" in emitted.stdout

    output = tmp_path / "collection-parity"
    built = run_gen1(gen1_compiler, "build", str(source), "-o", str(output))
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False, capture_output=True, text=True)
    assert executed.returncode == 0, executed.stderr


def test_gen1_map_views_cross_module_boundaries(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        'name = "map_view_project"\n'
        'source-root = "src"\n'
        'entry = "main.ci"\n',
        encoding="utf-8",
    )
    (source_root / "views.ci").write_text(
        "def keys(values: &const Map[i32, String]) -> MapKeys[i32, String]:\n"
        "    return values.keys()\n"
        "\n"
        "def values(values: &const Map[i32, String]) -> MapValues[i32, String]:\n"
        "    return values.values()\n"
        "\n"
        "def items(values: &const Map[i32, String]) -> MapItems[i32, String]:\n"
        "    return values.items()\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import views\n"
        "\n"
        "def main() -> i32:\n"
        '    words: Map[i32, String] = {1: "one", 2: "two"}\n'
        "    keys: MapKeys[i32, String] = views.keys(&words)\n"
        "    values: MapValues[i32, String] = views.values(&words)\n"
        "    items: MapItems[i32, String] = views.items(&words)\n"
        '    words[3] = "three"\n'
        "    if len(keys) != 3 or 3 not in keys:\n"
        "        return 1\n"
        '    if "three" not in values or (2, "two") not in items:\n'
        "        return 2\n"
        "    seen: i32 = 0\n"
        "    for item in items:\n"
        '        if item[0] == 2 and item[1] == "two":\n'
        "            seen = 1\n"
        "    if seen != 1:\n"
        "        return 3\n"
        "    return 0\n",
        encoding="utf-8",
    )

    generated = tmp_path / "generated"
    emitted = run_gen1(
        gen1_compiler,
        "emit-project",
        str(tmp_path / "cinder.toml"),
        "-o",
        str(generated),
    )
    assert emitted.returncode == 0, emitted.stderr
    header = (generated / "cinder_gen" / "views.cinder.h").read_text(encoding="utf-8")
    assert "CinderMapKeys_i32_String" in header
    assert "CinderMapValues_i32_String" in header
    assert "CinderMapItems_i32_String" in header

    output = tmp_path / "map-view-project"
    built = run_gen1(
        gen1_compiler,
        "build",
        str(tmp_path / "cinder.toml"),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "build"),
    )
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False, capture_output=True, text=True)
    assert executed.returncode == 0, executed.stderr


def assert_compiler_preserves_atomic_generic_specializations(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "atomic_generic_specializations.ci"
    source.write_text(
        "from std.atomic import Atomic\n"
        "\n"
        "def read[T](cell: *Atomic[T]) -> T:\n"
        "    return cell.load()\n"
        "\n"
        "def main() -> i32:\n"
        "    small: Atomic[u32] = 7\n"
        "    wide: Atomic[u64] = 0x100000001\n"
        "    if read[u32](&small) != 7:\n"
        "        return 1\n"
        "    if read[u64](&wide) != 0x100000001:\n"
        "        return 2\n"
        "    return 0\n",
        encoding="utf-8",
    )

    checked = run_gen1(compiler, "check", str(source))
    assert checked.returncode == 0, checked.stderr

    emitted = run_gen1(compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    u32_function = re.search(
        r"uint32_t [^(]*__read_u32\(CinderAtomic_u32 \* cell\) \{(?P<body>.*?)\n\}",
        emitted.stdout,
        re.DOTALL,
    )
    u64_function = re.search(
        r"uint64_t [^(]*__read_u64\(CinderAtomic_u64 \* cell\) \{(?P<body>.*?)\n\}",
        emitted.stdout,
        re.DOTALL,
    )
    assert u32_function is not None
    assert u64_function is not None
    u32_body = u32_function.group("body")
    u64_body = u64_function.group("body")
    assert "CinderAtomic_u32 *cinder_atomic_receiver_" in u32_body
    assert "CinderAtomic_u64 *cinder_atomic_receiver_" not in u32_body
    assert "CinderAtomic_u64 *cinder_atomic_receiver_" in u64_body
    assert "CinderAtomic_u32 *cinder_atomic_receiver_" not in u64_body
    assert "atomic_load_explicit" in u32_body
    assert "atomic_load_explicit" in u64_body

    output = tmp_path / "atomic-generic-specializations"
    built = run_gen1(
        compiler,
        "build",
        str(source),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "atomic-generic-specializations-build"),
    )
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False, capture_output=True, text=True)
    assert executed.returncode == 0, executed.stderr


def assert_compiler_supports_atomic_scalars(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "atomic_scalars.ci"
    source.write_text(
        "from std.atomic import Atomic\n"
        "\n"
        "global_counter: Atomic[u64] = 0\n"
        "\n"
        "def main() -> i32:\n"
        "    ready: Atomic[bool] = false\n"
        "    counter: Atomic[u64] = 1\n"
        "    small: Atomic[u32] = 4\n"
        "    index: Atomic[usize] = 6\n"
        "    converted_ready: Atomic[bool] = 1\n"
        "    converted_counter: Atomic[u64] = 2.0\n"
        "    if not converted_ready.load() or converted_counter.load() != 2:\n"
        "        return 17\n"
        "    converted_ready.store(0)\n"
        "    converted_counter.store(3.0)\n"
        "    if converted_ready.load() or converted_counter.load() != 3:\n"
        "        return 18\n"
        "    if ready.exchange(true):\n"
        "        return 1\n"
        "    ready_result = ready.compare_exchange(expected=true, desired=false)\n"
        "    if not ready_result.exchanged or not ready_result.observed:\n"
        "        return 2\n"
        "    if ready.load():\n"
        "        return 3\n"
        "    ready_ref: &const Atomic[bool] = &ready\n"
        "    if ready_ref.load():\n"
        "        return 4\n"
        "    if small.fetch_add(2) != 4 or small.load() != 6:\n"
        "        return 13\n"
        "    if index.fetch_sub(1) != 6 or index.load() != 5:\n"
        "        return 14\n"
        "    const counter_ref: *Atomic[u64] = &counter\n"
        "    if counter_ref.load() != 1:\n"
        "        return 15\n"
        "    if global_counter.fetch_add(1) != 0 or global_counter.load() != 1:\n"
        "        return 16\n"
        "    counter_ref.store(2)\n"
        "    if counter.exchange(3) != 2:\n"
        "        return 5\n"
        "    if counter.fetch_add(4) != 3:\n"
        "        return 6\n"
        "    if counter.fetch_sub(2) != 7:\n"
        "        return 7\n"
        "    if counter.fetch_and(6) != 5:\n"
        "        return 8\n"
        "    if counter.fetch_or(1) != 4:\n"
        "        return 9\n"
        "    if counter.fetch_xor(7) != 5:\n"
        "        return 10\n"
        "    exchanged = counter.compare_exchange(expected=2, desired=9)\n"
        "    if not exchanged.exchanged or exchanged.observed != 2:\n"
        "        return 11\n"
        "    observed = counter.compare_exchange(desired=10, expected=0)\n"
        "    if observed.exchanged or observed.observed != 9:\n"
        "        return 12\n"
        "    return 0\n",
        encoding="utf-8",
    )

    checked = run_gen1(compiler, "check", str(source))
    assert checked.returncode == 0, checked.stderr

    emitted = run_gen1(compiler, "emit-c", str(source))
    assert emitted.returncode == 0, emitted.stderr
    for snippet in (
        "#include <stdatomic.h>",
        "_Atomic(uint32_t) value;",
        "_Atomic(uint64_t) value;",
        "_Atomic(size_t) value;",
        "ATOMIC_VAR_INIT(",
        "atomic_init(",
        "atomic_load_explicit(",
        "atomic_store_explicit(",
        "atomic_exchange_explicit(",
        "atomic_compare_exchange_strong_explicit(",
        "atomic_fetch_add_explicit(",
        "atomic_fetch_sub_explicit(",
        "atomic_fetch_and_explicit(",
        "atomic_fetch_or_explicit(",
        "atomic_fetch_xor_explicit(",
        "memory_order_seq_cst",
    ):
        assert snippet in emitted.stdout

    generated = tmp_path / "atomic-generated"
    emitted_project = run_gen1(
        compiler,
        "emit-project",
        str(source),
        "-o",
        str(generated),
    )
    assert emitted_project.returncode == 0, emitted_project.stderr
    header = generated / "cinder_gen" / "atomic_scalars.cinder.h"
    header_text = header.read_text(encoding="utf-8")
    assert "typedef struct CinderAtomic_u64 CinderAtomic_u64;" in header_text
    assert "#ifndef __cplusplus" in header_text
    assert (
        "#ifndef __cplusplus\n"
        "struct CinderAtomic_u64 { _Atomic(uint64_t) value; };\n"
        "#endif"
    ) in header_text

    output = tmp_path / "atomic-scalars"
    built = run_gen1(compiler, "build", str(source), "-o", str(output))
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False, capture_output=True, text=True)
    assert executed.returncode == 0, executed.stderr

    pointer_only = tmp_path / "atomic_pointer_only.ci"
    pointer_only.write_text(
        "from std.atomic import Atomic\n"
        "\n"
        "cell: Atomic[u64] = 13\n"
        "pointer: *Atomic[u64] = &cell\n"
        "\n"
        "def identity(cell: *Atomic[u64]) -> *Atomic[u64]:\n"
        "    return cell\n"
        "\n"
        "def read_const(cell: *const Atomic[u64]) -> u64:\n"
        "    return cell.load()\n"
        "\n"
        "def main() -> i32:\n"
        "    if identity(pointer).load() != 13:\n"
        "        return 1\n"
        "    if read_const(pointer) != 13:\n"
        "        return 2\n"
        "    return 0\n",
        encoding="utf-8",
    )
    pointer_emitted = run_gen1(compiler, "emit-c", str(pointer_only))
    assert pointer_emitted.returncode == 0, pointer_emitted.stderr
    assert "#include <stdatomic.h>" in pointer_emitted.stdout
    assert "_Atomic(uint64_t) value;" in pointer_emitted.stdout
    assert "CinderAtomic_u64 *" in pointer_emitted.stdout
    assert "const CinderAtomic_u64 *" in pointer_emitted.stdout
    assert "std_atomic__Atomic" not in pointer_emitted.stdout
    pointer_output = tmp_path / "atomic-pointer-only"
    pointer_built = run_gen1(
        compiler,
        "build",
        str(pointer_only),
        "-o",
        str(pointer_output),
        "--build-dir",
        str(tmp_path / "atomic-pointer-only-build"),
    )
    assert pointer_built.returncode == 0, pointer_built.stderr
    pointer_executed = subprocess.run(
        [str(pointer_output)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert pointer_executed.returncode == 0, pointer_executed.stderr

    nested_only = tmp_path / "atomic_nested_specializations.ci"
    nested_only.write_text(
        "from std.atomic import Atomic\n"
        "\n"
        "def accept_nested_atomic_pointers(\n"
        "    optional: Option[*Atomic[u64]],\n"
        "    result: Result[*Atomic[u64], *Atomic[u32]],\n"
        "    pair: Tuple[*Atomic[u64], *Atomic[u32]],\n"
        "    values: List[*Atomic[u64]],\n"
        "    owned: Owned[*Atomic[u64]],\n"
        "    mapping: Map[i32, *Atomic[u64]],\n"
        "    view: MapValues[i32, *Atomic[u64]],\n"
        ") -> i32:\n"
        "    return 0\n"
        "\n"
        "def main() -> i32:\n"
        "    cell: Atomic[u64] = 1\n"
        "    values: List[*Atomic[u64]] = []\n"
        "    defer values.clear()\n"
        "    values.append(&cell)\n"
        "    values[0].store(4)\n"
        "    if values[0].load() != 4:\n"
        "        return 1\n"
        "    return 0\n",
        encoding="utf-8",
    )
    nested_checked = run_gen1(compiler, "check", str(nested_only))
    assert nested_checked.returncode == 0, nested_checked.stderr
    nested_emitted = run_gen1(compiler, "emit-c", str(nested_only))
    assert nested_emitted.returncode == 0, nested_emitted.stderr
    for snippet in (
        "#include <stdatomic.h>",
        "typedef struct CinderAtomic_u64 CinderAtomic_u64;",
        "CinderAtomic_u64 * value;",
        "CinderAtomic_u64 * ok;",
        "CinderAtomic_u32 * err;",
        "CinderAtomic_u64 * item_0;",
        "CinderAtomic_u32 * item_1;",
        "((CinderAtomic_u64 * *)",
    ):
        assert snippet in nested_emitted.stdout
    assert "std_atomic__Atomic" not in nested_emitted.stdout
    nested_output = tmp_path / "atomic-nested-specializations"
    nested_built = run_gen1(
        compiler,
        "build",
        str(nested_only),
        "-o",
        str(nested_output),
        "--build-dir",
        str(tmp_path / "atomic-nested-specializations-build"),
    )
    assert nested_built.returncode == 0, nested_built.stderr
    nested_executed = subprocess.run(
        [str(nested_output)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert nested_executed.returncode == 0, nested_executed.stderr

    invalid_cases = (
        (
            "from std.atomic import Atomic\n"
            "def main() -> i32:\n"
            "    value: Atomic[String] = \"bad\"\n"
            "    return 0\n",
            394,
        ),
        (
            "from std.atomic import Atomic\n"
            "def main() -> i32:\n"
            "    value: Atomic[u64] = 0\n"
            "    loaded: u64 = value\n"
            "    return 0\n",
            400,
        ),
        (
            "from std.atomic import Atomic\n"
            "def main() -> i32:\n"
            "    value: Atomic[u64] = 0\n"
            "    value = 1\n"
            "    return 0\n",
            401,
        ),
        (
            "from std.atomic import Atomic\n"
            "def main() -> i32:\n"
            "    value: Atomic[bool] = false\n"
            "    value.fetch_add(true)\n"
            "    return 0\n",
            403,
        ),
        (
            "from std.atomic import Atomic\n"
            "def main() -> i32:\n"
            "    value: Atomic[u64] = [1]\n"
            "    return 0\n",
            107,
        ),
        (
            "from std.atomic import Atomic\n"
            "def main() -> i32:\n"
            "    value: Atomic[u64] = 0\n"
            "    value.store([1])\n"
            "    return 0\n",
            107,
        ),
        (
            "from std.atomic import Atomic\n"
            "def main() -> i32:\n"
            "    value: Atomic[u64] = 0\n"
            "    value.compare_exchange(expected=0, desired=[1])\n"
            "    return 0\n",
            107,
        ),
        (
            "from std.atomic import Atomic\n"
            "\n"
            "def load64(cell: *Atomic[u64]) -> u64:\n"
            "    return cell.load()\n"
            "\n"
            "def main() -> i32:\n"
            "    narrow: Atomic[u32] = 0\n"
            "    load64(&narrow)\n"
            "    return 0\n",
            107,
        ),
        (
            "from std.atomic import Atomic\n"
            "\n"
            "def store64(cell: *Atomic[u64]) -> void:\n"
            "    cell.store(1)\n"
            "\n"
            "def main() -> i32:\n"
            "    value: Atomic[u64] = 0\n"
            "    readonly: *const Atomic[u64] = &value\n"
            "    store64(readonly)\n"
            "    return 0\n",
            107,
        ),
        (
            "from std.atomic import Atomic\n"
            "\n"
            "def load64(cell: *Atomic[u64]) -> u64:\n"
            "    return cell.load()\n"
            "\n"
            "def main() -> i32:\n"
            "    value: Atomic[u64] = 0\n"
            "    pointer: *Atomic[u64] = &value\n"
            "    load64(&pointer)\n"
            "    return 0\n",
            107,
        ),
        (
            "from std.atomic import Atomic\n"
            "def main() -> i32:\n"
            "    value: Atomic[u64] = 0\n"
            "    pointer: *Atomic[u64] = &value\n"
            "    indirect: **Atomic[u64] = &pointer\n"
            "    indirect.load()\n"
            "    return 0\n",
            403,
        ),
        (
            "from std.atomic import Atomic\n"
            "\n"
            "struct Box[T]:\n"
            "    value: T\n"
            "\n"
            "def main() -> i32:\n"
            "    boxed: Box[Atomic[u64]]\n"
            "    return 0\n",
            395,
        ),
    )
    for index, (invalid_source, code) in enumerate(invalid_cases):
        invalid = tmp_path / f"invalid_atomic_{index}.ci"
        invalid.write_text(invalid_source, encoding="utf-8")
        rejected = run_gen1(compiler, "check", str(invalid))
        assert rejected.returncode == 1
        assert rejected.stdout.startswith(f"E {code} ")


def assert_compiler_supports_atomic_import_forms(
    compiler: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    manifest = tmp_path / "cinder.toml"
    manifest.write_text(
        '[project]\nname = "atomic_imports"\nsource-root = "src"\nentry = "main.ci"\n',
        encoding="utf-8",
    )
    (source_root / "state.ci").write_text(
        "from std.atomic import Atomic as A\n"
        "\n"
        "counter: A[u64] = 0\n"
        "\n"
        "def pointer() -> *A[u64]:\n"
        "    return &counter\n",
        encoding="utf-8",
    )
    (source_root / "api.ci").write_text(
        "from std.atomic import Atomic\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import std.atomic as atom\n"
        "import api\n"
        "import state\n"
        "\n"
        "global_counter: atom.Atomic[u64] = 4\n"
        "api_counter: api.Atomic[u64] = 5\n"
        "\n"
        "def main() -> i32:\n"
        "    local_counter: atom.Atomic[u64] = 2\n"
        "    if local_counter.fetch_add(1) != 2 or local_counter.load() != 3:\n"
        "        return 1\n"
        "    if global_counter.load() != 4:\n"
        "        return 2\n"
        "    if state.counter.fetch_add(3) != 0 or state.counter.load() != 3:\n"
        "        return 3\n"
        "    if api_counter.exchange(6) != 5 or api_counter.load() != 6:\n"
        "        return 4\n"
        "    if state.pointer().fetch_add(2) != 3 or state.counter.load() != 5:\n"
        "        return 5\n"
        "    return 0\n",
        encoding="utf-8",
    )

    checked = run_gen1(compiler, "check", str(manifest))
    assert checked.returncode == 0, checked.stderr

    generated = tmp_path / "atomic-import-generated"
    emitted = run_gen1(
        compiler,
        "emit-project",
        str(manifest),
        "-o",
        str(generated),
    )
    assert emitted.returncode == 0, emitted.stderr
    generated_text = (
        (generated / "cinder_gen" / "main.c").read_text(encoding="utf-8")
        + (generated / "cinder_gen" / "state.c").read_text(encoding="utf-8")
    )
    imported_pointer_call = "cinder_atomic_imports_state__pointer()"
    assert "CinderAtomic_u64" in generated_text
    assert "atomic_fetch_add_explicit" in generated_text
    assert re.search(
        rf"cinder_atomic_receiver_\d+ = {re.escape(imported_pointer_call)}",
        generated_text,
    )
    assert f"fetch_add(&{imported_pointer_call}" not in generated_text
    assert f"= &({imported_pointer_call})" not in generated_text
    assert "std_atomic__Atomic" not in generated_text
    assert "Atomic_u64_fetch_add" not in generated_text
    assert "api__Atomic" not in generated_text

    output = tmp_path / "atomic-imports"
    built = run_gen1(
        compiler,
        "build",
        str(manifest),
        "-o",
        str(output),
        "--build-dir",
        str(tmp_path / "atomic-import-build"),
    )
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False, capture_output=True, text=True)
    assert executed.returncode == 0, executed.stderr


def test_gen1_preserves_atomic_generic_specializations(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_preserves_atomic_generic_specializations(gen1_compiler, tmp_path)


def test_gen2_preserves_atomic_generic_specializations(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_preserves_atomic_generic_specializations(gen2, tmp_path)


def test_gen3_preserves_atomic_generic_specializations(
    gen3_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_preserves_atomic_generic_specializations(gen3_compiler, tmp_path)


def test_gen1_supports_atomic_scalars(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_supports_atomic_scalars(gen1_compiler, tmp_path)


def test_gen2_supports_atomic_scalars(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_supports_atomic_scalars(gen2, tmp_path)


def test_gen3_supports_atomic_scalars(
    gen3_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_supports_atomic_scalars(gen3_compiler, tmp_path)


def test_gen1_supports_atomic_import_forms(
    gen1_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_supports_atomic_import_forms(gen1_compiler, tmp_path)


def test_gen2_supports_atomic_import_forms(
    gen2_compiler: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    gen2, _build_dir = gen2_compiler
    assert_compiler_supports_atomic_import_forms(gen2, tmp_path)


def test_gen3_supports_atomic_import_forms(
    gen3_compiler: Path,
    tmp_path: Path,
) -> None:
    assert_compiler_supports_atomic_import_forms(gen3_compiler, tmp_path)
