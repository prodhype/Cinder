from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed
from cinder.project import ProjectError


def write_project(root: Path) -> tuple[Path, Path, Path]:
    source_root = root / "src"
    source_root.mkdir(parents=True)
    manifest = root / "cinder.toml"
    manifest.write_text(
        "[project]\n"
        "name = \"module_demo\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n",
        encoding="utf-8",
    )
    model = source_root / "model.ci"
    model.write_text(
        "struct Vec2:\n"
        "    x: i32\n"
        "    y: i32\n"
        "\n"
        "    def sum(self: &const Vec2) -> i32:\n"
        "        return self.x + self.y\n"
        "\n"
        "enum ParseError:\n"
        "    invalid\n"
        "\n"
        "variant Token:\n"
        "    Integer(value: i32)\n"
        "    End\n"
        "\n"
        "answer: i32 = 40\n"
        "const offset: i32 = 2\n"
        "\n"
        "def parse(ok: bool) -> Result[i32, ParseError]:\n"
        "    if ok:\n"
        "        return Ok(42)\n"
        "    return Err(ParseError.invalid)\n",
        encoding="utf-8",
    )
    main = source_root / "main.ci"
    main.write_text(
        "import stdio\n"
        "import model\n"
        "from model import ParseError, Token, parse\n"
        "\n"
        "def consume(ok: bool) -> Result[i32, ParseError]:\n"
        "    value = parse(ok)?\n"
        "    return Ok(value + model.offset)\n"
        "\n"
        "def main() -> i32:\n"
        "    vector = model.Vec2(x=20, y=22)\n"
        "    token = Token.Integer(vector.sum())\n"
        "    result = consume(true)\n"
        "    match token:\n"
        "        case Token.Integer(value):\n"
        "            stdio.printf(\"token=%d \", value)\n"
        "        case Token.End:\n"
        "            stdio.printf(\"end \")\n"
        "    match result:\n"
        "        case Ok(value):\n"
        "            stdio.printf(\"result=%d \", value)\n"
        "        case Err(error):\n"
        "            stdio.printf(\"error=%d \", cast[i32](error))\n"
        "    stdio.printf(\"global=%d\\n\", model.answer)\n"
        "    return 0\n",
        encoding="utf-8",
    )
    return manifest, main, model


def test_project_graph_generates_one_translation_unit_and_header_per_module(
    tmp_path: Path,
) -> None:
    manifest, _, _ = write_project(tmp_path)
    project = Compiler().compile_project(manifest)

    assert [unit.module_name for unit in project.units] == ["model", "main"]
    assert all(unit.header_name is not None for unit in project.units)
    assert all(unit.generated_source_name is not None for unit in project.units)
    assert project.entry_unit.module_name == "main"

    main_header = project.units_by_name["main"].c_header
    assert main_header is not None
    assert '#include "cinder_gen/model.cinder.h"' in main_header
    assert "extern int32_t" in project.units_by_name["model"].c_header


def test_project_cycle_has_a_source_diagnostic(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\nsource-root = \"src\"\nentry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import a\ndef main() -> i32:\n    return 0\n",
        encoding="utf-8",
    )
    (source_root / "a.ci").write_text("import b\n", encoding="utf-8")
    (source_root / "b.ci").write_text("import a\n", encoding="utf-8")

    with pytest.raises(CompilationFailed) as captured:
        Compiler().compile_project(tmp_path)
    rendered = str(captured.value)
    assert "cyclic module dependency: a -> b -> a" in rendered
    assert "import a" in rendered


def test_missing_local_module_has_a_source_diagnostic(tmp_path: Path) -> None:
    main = tmp_path / "main.ci"
    main.write_text(
        "import missing\ndef main() -> i32:\n    return 0\n",
        encoding="utf-8",
    )
    with pytest.raises(CompilationFailed) as captured:
        Compiler().compile_project(main)
    rendered = str(captured.value)
    assert "cannot resolve local module 'missing'" in rendered
    assert "missing.ci" in rendered


def test_amalgamated_output_has_no_generated_header_dependency(tmp_path: Path) -> None:
    _, main, _ = write_project(tmp_path)
    generated = Compiler().emit_c(main)
    assert "Amalgamated project: module_demo" in generated
    assert '#include "cinder_gen/' not in generated
    assert "int main(void)" in generated
    assert "typedef struct" in generated


pytestmark_native = pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)


@pytestmark_native
def test_multi_module_project_builds_runs_and_preserves_unchanged_generated_files(
    tmp_path: Path,
) -> None:
    manifest, _, _ = write_project(tmp_path)
    compiler = Compiler()
    output = tmp_path / ("module_demo.exe" if shutil.which("cl") and not shutil.which("cc") else "module_demo")
    build_dir = tmp_path / "build"

    first = compiler.build(manifest, output=output, build_dir=build_dir)
    mtimes = {
        path: path.stat().st_mtime_ns
        for path in (*first.generated_headers, *first.generated_sources)
    }
    second = compiler.build(tmp_path, output=output, build_dir=build_dir)

    assert len(second.generated_sources) == 2
    assert len(second.generated_headers) == 2
    assert all(path.stat().st_mtime_ns == mtimes[path] for path in mtimes)

    result = subprocess.run(
        [str(second.executable)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "token=42 result=44 global=40\n"


def test_dotted_module_alias_resolves_dependency_first(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    support = source_root / "support"
    support.mkdir(parents=True)
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"dotted_demo\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (support / "math.ci").write_text(
        "enum MathError:\n"
        "    negative\n"
        "\n"
        "def double(value: i32) -> Result[i32, MathError]:\n"
        "    if value < 0:\n"
        "        return Err(MathError.negative)\n"
        "    return Ok(value * 2)\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import support.math as calculations\n"
        "\n"
        "def calculate(value: i32) -> Result[i32, calculations.MathError]:\n"
        "    doubled = calculations.double(value)?\n"
        "    return Ok(doubled + 2)\n"
        "\n"
        "def error_code(error: calculations.MathError) -> i32:\n"
        "    match error:\n"
        "        case calculations.MathError.negative:\n"
        "            return 1\n"
        "\n"
        "def main() -> i32:\n"
        "    result = calculate(20)\n"
        "    match result:\n"
        "        case Ok(value):\n"
        "            return value - 42\n"
        "        case Err(error):\n"
        "            return cast[i32](error) + 1\n",
        encoding="utf-8",
    )

    project = Compiler().compile_project(tmp_path)
    assert [unit.module_name for unit in project.units] == ["support.math", "main"]
    main_header = project.units_by_name["main"].c_header
    assert main_header is not None
    assert '#include "cinder_gen/support/math.cinder.h"' in main_header


def test_emit_project_cli_writes_complete_generated_tree(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cinder.cli import main as cli_main

    manifest, _, _ = write_project(tmp_path)
    output = tmp_path / "generated"

    assert cli_main(["emit-project", str(manifest), "-o", str(output)]) == 0
    assert capsys.readouterr().out.strip() == str(output.resolve())
    assert (output / "cinder_gen" / "model.c").is_file()
    assert (output / "cinder_gen" / "model.cinder.h").is_file()
    assert (output / "cinder_gen" / "main.c").is_file()
    assert (output / "cinder_gen" / "main.cinder.h").is_file()


def test_manifest_rejects_undocumented_keys(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "main.ci").write_text(
        "def main() -> i32:\n    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "source_root = \"src\"\n"
        "entry = \"main.ci\"\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectError) as captured:
        Compiler().compile_project(tmp_path)
    assert "unknown [project] key(s)" in str(captured.value)


def test_manifest_rejects_project_names_that_escape_build_paths(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "main.ci").write_text(
        "def main() -> i32:\n    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"../outside\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectError) as captured:
        Compiler().compile_project(tmp_path)
    assert "must use only ASCII letters" in str(captured.value)


@pytest.mark.skipif(
    not shutil.which("cc") or not shutil.which("c++"),
    reason="C and C++ compilers are required",
)
def test_generated_header_is_usable_from_cpp(tmp_path: Path) -> None:
    runtime_include = Path(__file__).resolve().parents[1] / "cinder" / "runtime"
    source = tmp_path / "library.ci"
    source.write_text(
        "@export\n"
        "def answer() -> i32:\n"
        "    return 42\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"
    emitted = Compiler().emit_project(source, generated)
    assert len(emitted.sources) == 1

    object_file = tmp_path / "library.o"
    compile_c = subprocess.run(
        [
            shutil.which("cc") or "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
            f"-I{runtime_include}",
            f"-I{generated}",
            "-c",
            str(emitted.sources[0]),
            "-o",
            str(object_file),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert compile_c.returncode == 0, compile_c.stderr

    consumer = tmp_path / "consumer.cpp"
    consumer.write_text(
        '#include "cinder_gen/library.cinder.h"\n'
        "int main() { return answer() - 42; }\n",
        encoding="utf-8",
    )
    executable = tmp_path / "consumer"
    compile_cpp = subprocess.run(
        [
            shutil.which("c++") or "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
            f"-I{runtime_include}",
            f"-I{generated}",
            str(consumer),
            str(object_file),
            "-o",
            str(executable),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert compile_cpp.returncode == 0, compile_cpp.stderr
    assert subprocess.run([str(executable)], check=False).returncode == 0


@pytestmark_native
def test_cross_module_class_interface_and_reflection_abi(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    manifest = tmp_path / "cinder.toml"
    manifest.write_text(
        "[project]\n"
        "name = \"class_abi\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "shapes.ci").write_text(
        "@reflect\n"
        "abstract class Shape:\n"
        "    @abstractmethod\n"
        "    def area(self) -> f64:\n"
        "        pass\n"
        "\n"
        "    def scaled(self, factor: f64) -> f64:\n"
        "        return self.area() * factor\n"
        "\n"
        "def measure(shape: &dyn Shape) -> f64:\n"
        "    return shape.scaled(2.0)\n",
        encoding="utf-8",
    )
    (source_root / "models.ci").write_text(
        "from shapes import Shape\n"
        "\n"
        "@reflect\n"
        "class Circle(Shape):\n"
        "    radius: f64\n"
        "\n"
        "    def __init__(self, radius: f64):\n"
        "        self.radius = radius\n"
        "\n"
        "    @override\n"
        "    def area(self) -> f64:\n"
        "        return 3.0 * self.radius * self.radius\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import shapes\n"
        "from models import Circle\n"
        "\n"
        "def main() -> i32:\n"
        "    circle = Circle(2.0)\n"
        "    if type_info(circle).field_count != 1:\n"
        "        return 2\n"
        "    result = shapes.measure(circle)\n"
        "    if result > 23.9:\n"
        "        return 0\n"
        "    return 1\n",
        encoding="utf-8",
    )

    compiler = Compiler()
    project = compiler.compile_project(manifest)
    shapes_header = project.units_by_name["shapes"].c_header
    models_header = project.units_by_name["models"].c_header
    assert shapes_header is not None
    assert models_header is not None
    assert "typedef struct CinderDyn_" in shapes_header
    assert "const CinderTypeInfo *type_info;" in shapes_header
    assert '#include "cinder_gen/shapes.cinder.h"' in models_header
    assert "__as__" in models_header
    assert "__vtable" in models_header

    executable = tmp_path / (
        "class_abi.exe" if shutil.which("cl") and not shutil.which("cc") else "class_abi"
    )
    artifact = compiler.build(manifest, output=executable, build_dir=tmp_path / "build")
    result = subprocess.run(
        [str(artifact.executable)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    not shutil.which("cc") or not shutil.which("c++"),
    reason="C and C++ compilers are required",
)
def test_reflected_class_header_is_usable_from_cpp(tmp_path: Path) -> None:
    runtime_include = Path(__file__).resolve().parents[1] / "cinder" / "runtime"
    source = tmp_path / "counter.ci"
    source.write_text(
        "@reflect\n"
        "class Counter:\n"
        "    value: i32\n"
        "\n"
        "    def __init__(self, value: i32):\n"
        "        self.value = value\n"
        "\n"
        "    def add(self, amount: i32) -> i32:\n"
        "        self.value += amount\n"
        "        return self.value\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"
    emitted = Compiler().emit_project(source, generated)
    unit = emitted.project.entry_unit
    class_ = unit.semantic.classes["Counter"]
    constructor_name = f"{class_.c_name}__new"
    method_name = class_.methods["add"].c_name
    type_info_name = f"{class_.c_name}__type_info"

    object_file = tmp_path / "counter.o"
    compile_c = subprocess.run(
        [
            shutil.which("cc") or "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
            f"-I{runtime_include}",
            f"-I{generated}",
            "-c",
            str(emitted.sources[0]),
            "-o",
            str(object_file),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert compile_c.returncode == 0, compile_c.stderr

    consumer = tmp_path / "consumer.cpp"
    consumer.write_text(
        '#include "cinder_gen/counter.cinder.h"\n'
        "int main() {\n"
        f"    auto counter = {constructor_name}(40);\n"
        f"    if ({type_info_name}.field_count != 1) return 1;\n"
        f"    return {method_name}(&counter, 2) - 42;\n"
        "}\n",
        encoding="utf-8",
    )
    executable = tmp_path / "consumer"
    compile_cpp = subprocess.run(
        [
            shutil.which("c++") or "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
            f"-I{runtime_include}",
            f"-I{generated}",
            str(consumer),
            str(object_file),
            "-o",
            str(executable),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert compile_cpp.returncode == 0, compile_cpp.stderr
    assert subprocess.run([str(executable)], check=False).returncode == 0


def test_manifest_rejects_unknown_top_level_table(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "main.ci").write_text(
        "def main() -> i32:\n    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"demo\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n"
        "\n"
        "[packaging]\n"
        "bundle = true\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectError) as captured:
        Compiler().compile_project(tmp_path)
    assert "unknown top-level table(s)" in str(captured.value)
    assert "packaging" in str(captured.value)


def test_manifest_rejects_unknown_native_keys(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "main.ci").write_text(
        "def main() -> i32:\n    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"demo\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n"
        "\n"
        "[native]\n"
        "libs = [\"SDL2\"]\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectError) as captured:
        Compiler().compile_project(tmp_path)
    assert "unknown [native] key(s)" in str(captured.value)


@pytest.mark.parametrize(
    ("libraries_line", "needle"),
    [
        ('libraries = ["-lSDL2"]\n', "not a flag"),
        ('libraries = ["path/SDL2"]\n', "without path separators"),
    ],
)
def test_manifest_rejects_invalid_native_libraries(
    tmp_path: Path,
    libraries_line: str,
    needle: str,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "main.ci").write_text(
        "def main() -> i32:\n    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"demo\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n"
        "\n"
        "[native]\n"
        f"{libraries_line}",
        encoding="utf-8",
    )

    with pytest.raises(ProjectError) as captured:
        Compiler().compile_project(tmp_path)
    assert needle in str(captured.value)


def test_native_paths_resolve_relative_to_project_root(tmp_path: Path) -> None:
    from cinder.project import resolve_project

    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "main.ci").write_text(
        "def main() -> i32:\n    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "vendor" / "include").mkdir(parents=True)
    (tmp_path / "vendor" / "lib").mkdir(parents=True)
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"demo\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n"
        "\n"
        "[native]\n"
        "include-dirs = [\"vendor/include\"]\n"
        "library-dirs = [\"vendor/lib\"]\n"
        "link-files = [\"vendor/lib/libdemo.a\"]\n"
        "libraries = [\"demo\"]\n"
        "cflags = [\"-pthread\"]\n"
        "ldflags = [\"-Wl,-dead_strip\"]\n",
        encoding="utf-8",
    )

    config = resolve_project(tmp_path)
    assert config.include_dirs == ((tmp_path / "vendor" / "include").resolve(),)
    assert config.library_dirs == ((tmp_path / "vendor" / "lib").resolve(),)
    assert config.link_files == ((tmp_path / "vendor" / "lib" / "libdemo.a").resolve(),)
    assert config.libraries == ("demo",)
    assert config.c_flags == ("-pthread",)
    assert config.linker_flags == ("-Wl,-dead_strip",)


def test_empty_native_table_is_allowed(tmp_path: Path) -> None:
    from cinder.project import resolve_project

    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "main.ci").write_text(
        "def main() -> i32:\n    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"demo\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n"
        "\n"
        "[native]\n",
        encoding="utf-8",
    )

    config = resolve_project(tmp_path)
    assert config.libraries == ()
    assert config.include_dirs == ()


@pytestmark_native
def test_native_link_files_and_libraries_build(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    vendor_lib = tmp_path / "vendor" / "lib"
    vendor_lib.mkdir(parents=True)

    stub_c = tmp_path / "stub.c"
    stub_c.write_text("int native_answer(void) { return 7; }\n", encoding="utf-8")
    stub_o = tmp_path / "stub.o"
    archive = vendor_lib / "libnative_answer.a"
    compile_stub = subprocess.run(
        [
            shutil.which("cc") or "cc",
            "-c",
            str(stub_c),
            "-o",
            str(stub_o),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert compile_stub.returncode == 0, compile_stub.stderr
    archive_stub = subprocess.run(
        [shutil.which("ar") or "ar", "rcs", str(archive), str(stub_o)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert archive_stub.returncode == 0, archive_stub.stderr

    (source_root / "main.ci").write_text(
        "extern \"C\":\n"
        "    def native_answer() -> c_int\n"
        "\n"
        "def main() -> i32:\n"
        "    return cast[i32](native_answer() - 7)\n",
        encoding="utf-8",
    )
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"native_link_demo\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n"
        "\n"
        "[native]\n"
        "library-dirs = [\"vendor/lib\"]\n"
        "libraries = [\"native_answer\"]\n"
        "link-files = [\"vendor/lib/libnative_answer.a\"]\n"
        "cflags = [\"-DCINDER_NATIVE_PRESENT\"]\n",
        encoding="utf-8",
    )

    artifact = Compiler().build(
        tmp_path,
        output=tmp_path / "program",
        build_dir=tmp_path / "build",
    )
    command = artifact.toolchain.command
    assert str(archive.resolve()) in command
    assert f"-L{(tmp_path / 'vendor' / 'lib').resolve()}" in command
    assert "-lnative_answer" in command
    assert "-DCINDER_NATIVE_PRESENT" in command
    assert command.index(str(archive.resolve())) < command.index("-lnative_answer")

    result = subprocess.run(
        [str(artifact.executable)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr


@pytestmark_native
def test_cli_cflags_and_ldflags_append_after_manifest(tmp_path: Path) -> None:
    from cinder.compiler import CompilerOptions

    is_msvc = bool(shutil.which("cl") and not any(shutil.which(name) for name in ("cc", "clang", "gcc")))
    if is_msvc:
        manifest_cflag = "/DCINDER_NATIVE_FLAG"
        cli_cflag = "/DCINDER_CLI_FLAG"
        manifest_ldflag = "/OPT:REF"
        cli_ldflag = "/OPT:ICF"
    elif sys.platform == "darwin":
        manifest_cflag = "-DCINDER_NATIVE_FLAG"
        cli_cflag = "-DCINDER_CLI_FLAG"
        manifest_ldflag = "-Wl,-dead_strip"
        cli_ldflag = "-Wl,-x"
    else:
        manifest_cflag = "-DCINDER_NATIVE_FLAG"
        cli_cflag = "-DCINDER_CLI_FLAG"
        manifest_ldflag = "-Wl,--as-needed"
        cli_ldflag = "-Wl,--no-as-needed"

    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "main.ci").write_text(
        "def main() -> i32:\n    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"flag_order\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n"
        "\n"
        "[native]\n"
        f"cflags = [\"{manifest_cflag}\"]\n"
        f"ldflags = [\"{manifest_ldflag}\"]\n",
        encoding="utf-8",
    )

    artifact = Compiler(
        CompilerOptions(
            c_flags=(cli_cflag,),
            linker_flags=(cli_ldflag,),
        )
    ).build(
        tmp_path,
        output=tmp_path / "program",
        build_dir=tmp_path / "build",
    )
    command = list(artifact.toolchain.command)
    assert command.index(manifest_cflag) < command.index(cli_cflag)
    assert command.index(manifest_ldflag) < command.index(cli_ldflag)
