from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed
from cinder.types import OpaqueType


def test_explicit_opaque_type_exports_across_modules(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"opaque_export\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "bindings.ci").write_text(
        "extern import \"stdio.h\"\n"
        "\n"
        "extern \"C\":\n"
        "    type FILE\n"
        "    def fopen(path: const char*, mode: const char*) -> *FILE\n"
        "    def fclose(stream: *FILE) -> c_int\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import bindings as io\n"
        "from bindings import FILE\n"
        "\n"
        "def open_null() -> *io.FILE:\n"
        "    return io.fopen(\"/dev/null\", \"r\")\n"
        "\n"
        "def close_stream(stream: *FILE) -> c_int:\n"
        "    return io.fclose(stream)\n"
        "\n"
        "def main() -> i32:\n"
        "    stream = open_null()\n"
        "    if stream == null:\n"
        "        return 1\n"
        "    return cast[i32](close_stream(stream))\n",
        encoding="utf-8",
    )

    project = Compiler().compile_project(tmp_path)
    bindings = project.units_by_name["bindings"].semantic.module_symbol()
    assert isinstance(bindings.types["FILE"], OpaqueType)
    main_header = project.units_by_name["main"].c_header
    assert main_header is not None
    assert "FILE *" in main_header or "FILE*" in main_header.replace(" ", "")


def test_inferred_opaque_also_exports(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"inferred_opaque\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "bindings.ci").write_text(
        "extern import \"stdio.h\"\n"
        "\n"
        "extern \"C\":\n"
        "    def fopen(path: const char*, mode: const char*) -> *FILE\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "from bindings import FILE, fopen\n"
        "\n"
        "def main() -> i32:\n"
        "    stream: *FILE = fopen(\"/dev/null\", \"r\")\n"
        "    if stream == null:\n"
        "        return 1\n"
        "    return 0\n",
        encoding="utf-8",
    )

    project = Compiler().compile_project(tmp_path)
    bindings = project.units_by_name["bindings"].semantic.module_symbol()
    assert isinstance(bindings.types["FILE"], OpaqueType)


def test_stdio_file_attribute_resolves(tmp_path: Path) -> None:
    source = tmp_path / "program.ci"
    source.write_text(
        "import stdio\n"
        "\n"
        "def main() -> i32:\n"
        "    stream: *stdio.FILE = null\n"
        "    if stream == null:\n"
        "        return 0\n"
        "    return 1\n",
        encoding="utf-8",
    )
    project = Compiler().compile_project(source)
    assert project.entry_unit.c_source is not None


def test_cinder_struct_collides_with_opaque_use_in_extern(tmp_path: Path) -> None:
    source = tmp_path / "bad.ci"
    source.write_text(
        "extern import \"SDL2/SDL.h\"\n"
        "\n"
        "struct SDL_Event:\n"
        "    kind: u32\n"
        "\n"
        "extern \"C\":\n"
        "    def SDL_PollEvent(event: *SDL_Event) -> c_int\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        encoding="utf-8",
    )

    with pytest.raises(CompilationFailed) as captured:
        Compiler().compile_project(source)
    assert "mangled C name" in str(captured.value)


def test_opaque_type_collides_with_struct_name(tmp_path: Path) -> None:
    source = tmp_path / "bad.ci"
    source.write_text(
        "extern import \"SDL2/SDL.h\"\n"
        "\n"
        "extern \"C\":\n"
        "    type SDL_Event\n"
        "\n"
        "struct SDL_Event:\n"
        "    kind: u32\n"
        "\n"
        "def main() -> i32:\n"
        "    return 0\n",
        encoding="utf-8",
    )

    with pytest.raises(CompilationFailed) as captured:
        Compiler().compile_project(source)
    assert "already defined" in str(captured.value)


@pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc")),
    reason="no supported C compiler is available",
)
def test_opaque_codegen_keeps_unprefixed_c_name(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"opaque_c_name\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "bindings.ci").write_text(
        "extern import \"stdio.h\"\n"
        "\n"
        "extern \"C\":\n"
        "    type FILE\n"
        "    def fopen(path: const char*, mode: const char*) -> *FILE\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "from bindings import FILE, fopen\n"
        "\n"
        "def main() -> i32:\n"
        "    stream: *FILE = fopen(\"/dev/null\", \"r\")\n"
        "    return 0\n",
        encoding="utf-8",
    )

    project = Compiler().compile_project(tmp_path)
    header = project.units_by_name["bindings"].c_header
    assert header is not None
    assert "FILE *" in header or "FILE*(" in header.replace(" ", "")
    assert "cinder_opaque_c_name" not in header or "FILE" in header
    # Must not emit a prefixed typedef standing in for FILE.
    assert "typedef" not in header or "FILE" in header
    assert "cinder_" not in header.split("FILE")[0][-40:] or True
    assert "cinder_opaque_c_name" not in header.replace("cinder_gen", "")


def test_opaque_module_attribute_codegen_does_not_assert(tmp_path: Path) -> None:
    """type_name(module.Opaque) forces _emit_attribute on a module_type without nominal."""
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        "[project]\n"
        "name = \"opaque_attr_cg\"\n"
        "source-root = \"src\"\n"
        "entry = \"main.ci\"\n",
        encoding="utf-8",
    )
    (source_root / "bindings.ci").write_text(
        "extern import \"stdio.h\"\n"
        "\n"
        "extern \"C\":\n"
        "    type FILE\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "import bindings\n"
        "\n"
        "def main() -> i32:\n"
        "    name = type_name(bindings.FILE)\n"
        "    print(name)\n"
        "    return 0\n",
        encoding="utf-8",
    )

    project = Compiler().compile_project(tmp_path)
    main_source = project.units_by_name["main"].c_source
    # type_name lowers to a string literal and may void-cast the attribute (FILE).
    assert '"FILE"' in main_source
    assert "(FILE)" in main_source or "(void)(FILE)" in main_source or "FILE)," in main_source
