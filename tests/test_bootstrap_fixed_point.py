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
        "struct Resource:\n"
        "    value: i32\n\n"
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
