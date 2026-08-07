from __future__ import annotations

import os
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
    assert (
        'cinder_selfhost_string_builder_append_cstr(&text_parts, "alpha")'
        in emitted.stdout
    )
    assert "cinder_selfhost_list_append_value(&builder, (42))" in emitted.stdout
    assert "cinder_selfhost_list_append_value(&text_parts" not in emitted.stdout
    assert "cinder_selfhost_string_builder_append_value(&builder" not in emitted.stdout

    output = tmp_path / "append-dispatch"
    built = run_gen1(gen1_compiler, "build", str(source), "-o", str(output))
    assert built.returncode == 0, built.stderr
    executed = subprocess.run([str(output)], check=False)
    assert executed.returncode == 0


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
    assert "cinder_selfhost_string_builder_append_value(&phase_builder," in specializations
    assert (
        'cinder_selfhost_string_builder_append_cstr(&phase_builder, "_helpers")'
        in specializations
    )
    assert (
        'cinder_selfhost_string_builder_append_cstr(&phase_builder, "_layout")'
        in specializations
    )
    assert (
        'cinder_selfhost_string_builder_append_cstr(&option_builder, "CinderOption_")'
        in specializations
    )
    assert "cinder_selfhost_string_builder_append_value(&option_builder," in specializations
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
