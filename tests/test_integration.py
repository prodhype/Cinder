from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from cinder.compiler import Compiler


pytestmark = pytest.mark.skipif(
    not any(shutil.which(name) for name in ("cc", "clang", "gcc", "cl")),
    reason="no supported C compiler is available",
)


def build_and_run(
    tmp_path: Path,
    source: str,
    *,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    source_path = tmp_path / "program.ci"
    source_path.write_text(source, encoding="utf-8")
    executable = tmp_path / ("program.exe" if shutil.which("cl") and not shutil.which("cc") else "program")
    artifact = Compiler().build(
        source_path,
        output=executable,
        build_dir=tmp_path / "build",
    )
    return subprocess.run(
        [str(artifact.executable)],
        check=False,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_native_struct_slice_and_range_program(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "import stdio\n"
        "\n"
        "struct Counter:\n"
        "    value: i32\n"
        "\n"
        "    def add(self, amount: i32) -> void:\n"
        "        self.value += amount\n"
        "\n"
        "def sum(values: []const i32) -> i32:\n"
        "    total: i32 = 0\n"
        "    for value in values:\n"
        "        total += value\n"
        "    return total\n"
        "\n"
        "def main() -> i32:\n"
        "    values: i32[4] = [1, 2, 3, 4]\n"
        "    counter = Counter(value=0)\n"
        "    for index in range(0, 3):\n"
        "        counter.add(index)\n"
        "    stdio.printf(\"%d %d\\n\", sum(values), counter.value)\n"
        "    return 0\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "10 3\n"


def test_c_header_interop(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "import stdio\n"
        "extern import \"ctype.h\"\n"
        "\n"
        "extern \"C\":\n"
        "    def toupper(character: c_int) -> c_int\n"
        "\n"
        "def main() -> i32:\n"
        "    stdio.printf(\"%c\\n\", toupper('a'))\n"
        "    return 0\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "A\n"


def test_runtime_wall_time_returns_fractional_seconds(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "extern \"C\":\n"
        "    def cinder_wall_time() -> f64\n"
        "\n"
        "def main() -> i32:\n"
        "    started = cinder_wall_time()\n"
        "    finished = cinder_wall_time()\n"
        "    if finished < started:\n"
        "        return 1\n"
        "    print(f\"{finished - started:.6f}\")\n"
        "    return 0\n",
    )
    assert result.returncode == 0, result.stderr
    assert float(result.stdout) >= 0.0


def test_builtin_print_and_fstrings(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "def main() -> i32:\n"
        "    name = \"Ada\"\n"
        "    value: i32 = 42\n"
        "    pi: f64 = 3.14159\n"
        "    print()\n"
        "    print(\"plain\", value)\n"
        "    print(f\"hello {name} {value:x} {pi:.2f} {{ok}} 100%\", true, 'Z')\n"
        "    return 0\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "\nplain 42\nhello Ada 2a 3.14 {ok} 100% true Z\n"


def test_builtin_input_reads_stdin_with_optional_prompt(tmp_path: Path) -> None:
    long_line = "x" * 130
    result = build_and_run(
        tmp_path,
        "def main() -> i32:\n"
        "    name = input(\"Name: \")\n"
        "    blank = input()\n"
        "    long_line = input()\n"
        "    print(name)\n"
        "    print(len(blank))\n"
        "    print(len(long_line))\n"
        "    return 0\n",
        stdin=f"Ada\n\n{long_line}\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "Name: Ada\n0\n130\n"


def test_builtin_input_panics_on_eof_before_line(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "def main() -> i32:\n"
        "    input()\n"
        "    return 0\n",
        stdin="",
    )
    assert result.returncode != 0
    assert "panic: input reached EOF" in result.stderr


def test_unsigned_integer_explicit_decimal_print(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "def main() -> i32:\n"
        "    value: u64 = 18446744073709551615\n"
        "    print(f\"{value:d}\")\n"
        "    return 0\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "18446744073709551615\n"


def test_nested_fstrings_and_signed_integer_radix_formats(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "calls: i32 = 0\n"
        "\n"
        "def minimum_i64() -> i64:\n"
        "    calls += 1\n"
        "    return -9223372036854775807 - 1\n"
        "\n"
        "def main() -> i32:\n"
        "    value: i32 = 42\n"
        "    print(f\"outer {f'inner {value}'}\")\n"
        "    print(f\"{minimum_i64():x} {minimum_i64():X} {minimum_i64():o}\")\n"
        "    if calls != 3:\n"
        "        return 1\n"
        "    return 0\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "outer inner 42\n"
        "-8000000000000000 -8000000000000000 -1000000000000000000000\n"
    )


def test_print_lists_maps_sets_and_tuples(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "def main() -> i32:\n"
        "    values = [5, 1, 4]\n"
        "    defer values.clear()\n"
        "    scores = {\"Ada\": 3, \"Grace\": 5}\n"
        "    defer scores.clear()\n"
        "    primes = {2}\n"
        "    defer primes.clear()\n"
        "    empty_set: Set[i32] = set()\n"
        "    defer empty_set.clear()\n"
        "    summary = (9, 3)\n"
        "    singleton = (1,)\n"
        "    print(values)\n"
        "    print(scores)\n"
        "    print(primes)\n"
        "    print(empty_set)\n"
        "    print(summary)\n"
        "    print(singleton)\n"
        "    print(f\"values={values}\")\n"
        "    print(values, summary)\n"
        "    return 0\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "[5, 1, 4]\n"
        "{'Ada': 3, 'Grace': 5}\n"
        "{2}\n"
        "set()\n"
        "(9, 3)\n"
        "(1,)\n"
        "values=[5, 1, 4]\n"
        "[5, 1, 4] (9, 3)\n"
    )


def test_native_classes_dyn_reflection_and_destructor_order(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "import stdio\n"
        "\n"
        "drop_trace: i32 = 0\n"
        "\n"
        "@reflect\n"
        "abstract class Shape:\n"
        "    name: const char*\n"
        "\n"
        "    def __init__(self, name: const char*):\n"
        "        self.name = name\n"
        "\n"
        "    def __del__(self):\n"
        "        drop_trace = drop_trace * 10 + 1\n"
        "\n"
        "    @abstractmethod\n"
        "    def area(self) -> f64:\n"
        "        pass\n"
        "\n"
        "    def scaled(self, factor: f64) -> f64:\n"
        "        return self.area() * factor\n"
        "\n"
        "@reflect\n"
        "class Circle(Shape):\n"
        "    radius: f64\n"
        "\n"
        "    def __init__(self, radius: f64):\n"
        "        super().__init__(\"circle\")\n"
        "        self.radius = radius\n"
        "\n"
        "    def __del__(self):\n"
        "        drop_trace = drop_trace * 10 + 2\n"
        "\n"
        "    @override\n"
        "    def area(self) -> f64:\n"
        "        return self.radius * self.radius\n"
        "\n"
        "def measure(shape: &dyn Shape) -> i32:\n"
        "    if type_name(shape) != \"Circle\":\n"
        "        return -1\n"
        "    if type_info(shape).field_count != 2:\n"
        "        return -5\n"
        "    dynamic_count: usize = 0\n"
        "    for field in fields(shape):\n"
        "        dynamic_count += 1\n"
        "    for method in methods(shape):\n"
        "        dynamic_count += 1\n"
        "    if dynamic_count != 4:\n"
        "        return -6\n"
        "    return cast[i32](shape.scaled(3.0))\n"
        "\n"
        "def compile_member_count() -> usize:\n"
        "    count: usize = 0\n"
        "    for field in comptime fields_of(Circle):\n"
        "        count += 1\n"
        "    for method in comptime methods_of(Circle):\n"
        "        count += 1\n"
        "    return count\n"
        "\n"
        "def use_circle() -> i32:\n"
        "    circle = Circle(2.0)\n"
        "    info = type_info(circle)\n"
        "    if info.field_count != 2:\n"
        "        return -2\n"
        "    if info.method_count != 2:\n"
        "        return -3\n"
        "    if compile_member_count() != 4:\n"
        "        return -4\n"
        "    runtime_count: usize = 0\n"
        "    for field in fields(circle):\n"
        "        runtime_count += 1\n"
        "    for method in methods(circle):\n"
        "        runtime_count += 1\n"
        "    if runtime_count != 4:\n"
        "        return -7\n"
        "    return measure(circle)\n"
        "\n"
        "def main() -> i32:\n"
        "    result = use_circle()\n"
        "    stdio.printf(\"%d %d\\n\", result, drop_trace)\n"
        "    if result != 12:\n"
        "        return 1\n"
        "    if drop_trace != 21:\n"
        "        return 2\n"
        "    return 0\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "12 21\n"


def test_native_aggregate_ownership_drops_nested_lists(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "import stdio\n"
        "\n"
        "struct Bundle:\n"
        "    items: List[i32]\n"
        "\n"
        "class Holder:\n"
        "    items: List[i32]\n"
        "\n"
        "    def __init__(self, items: List[i32]):\n"
        "        self.items = items\n"
        "\n"
        "def consume(values: List[i32]) -> i32:\n"
        "    return cast[i32](len(values))\n"
        "\n"
        "def main() -> i32:\n"
        "    nested: List[List[i32]] = [[1, 2], [3]]\n"
        "    bundle = Bundle(items=[4, 5, 6])\n"
        "    holder = Holder([7])\n"
        "    total = consume(nested.pop()) + cast[i32](len(bundle.items)) "
        "+ cast[i32](len(holder.items))\n"
        "    stdio.printf(\"%d\\n\", total)\n"
        "    return 0\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "5\n"


def test_native_list_pop_move_out_runs_each_destructor_once(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "class Resource:\n"
        "    label: i32\n"
        "\n"
        "    def __init__(self, label: i32):\n"
        "        self.label = label\n"
        "\n"
        "    def __del__(self):\n"
        "        print(f\"drop {self.label}\")\n"
        "\n"
        "def main() -> i32:\n"
        "    values: List[Resource] = []\n"
        "    values.append(Resource(1))\n"
        "    values.append(Resource(2))\n"
        "    values.pop()\n"
        "    values.append(Resource(3))\n"
        "    print(f\"len={len(values)}\")\n"
        "    return 0\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "drop 2\nlen=2\ndrop 1\ndrop 3\n"


def test_native_multiple_abstract_interfaces(tmp_path: Path) -> None:
    result = build_and_run(
        tmp_path,
        "abstract class Named:\n"
        "    @abstractmethod\n"
        "    def name_code(self) -> i32:\n"
        "        pass\n"
        "\n"
        "abstract class Sized:\n"
        "    @abstractmethod\n"
        "    def size(self) -> i32:\n"
        "        pass\n"
        "\n"
        "class Thing(Named, Sized):\n"
        "    value: i32\n"
        "\n"
        "    def __init__(self, value: i32):\n"
        "        self.value = value\n"
        "\n"
        "    @override\n"
        "    def name_code(self) -> i32:\n"
        "        return 40\n"
        "\n"
        "    @override\n"
        "    def size(self) -> i32:\n"
        "        return self.value\n"
        "\n"
        "def read_name(value: &dyn Named) -> i32:\n"
        "    return value.name_code()\n"
        "\n"
        "def read_size(value: &dyn Sized) -> i32:\n"
        "    return value.size()\n"
        "\n"
        "def main() -> i32:\n"
        "    thing = Thing(2)\n"
        "    return read_name(thing) + read_size(thing) - 42\n",
    )
    assert result.returncode == 0, result.stderr
