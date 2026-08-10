from __future__ import annotations

from collections.abc import Iterator
from dataclasses import fields, is_dataclass
from pathlib import Path

from cinder import ast
from cinder.compiler import Compiler
from cinder.ownership import ValueUseKind
from cinder.symbols import VariableSymbol


def compile_semantic(source: str, path: str = "value_use.ci"):
    return Compiler().compile_source(source, Path(path)).semantic


def iter_nodes(node: object) -> Iterator[object]:
    yield node
    if not is_dataclass(node) or isinstance(node, type):
        return
    for field in fields(node):
        value = getattr(node, field.name)
        if isinstance(value, list | tuple):
            for item in value:
                if is_dataclass(item) and not isinstance(item, type):
                    yield from iter_nodes(item)
        elif is_dataclass(value) and not isinstance(value, type):
            yield from iter_nodes(value)


def name_exprs(module: ast.Module, name: str) -> list[ast.NameExpr]:
    return [
        node for node in iter_nodes(module) if isinstance(node, ast.NameExpr) and node.name == name
    ]


def function_decl(module: ast.Module, name: str) -> ast.FunctionDecl:
    for item in module.functions:
        if item.name == name:
            return item
    raise AssertionError(f"function {name!r} not found")


def test_copy_local_read() -> None:
    semantic = compile_semantic("def main() -> i32:\n    value: i32 = 41\n    return value + 1\n")
    [expr] = name_exprs(semantic.module, "value")
    # initializer target is lvalue; only the return read remains
    resolution = semantic.value_use(expr)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.COPY
    assert isinstance(resolution.source, VariableSymbol)
    assert resolution.source.name == "value"
    assert resolution.source is semantic.name_symbols[id(expr)]


def test_copy_parameter_read() -> None:
    semantic = compile_semantic(
        "def add_one(value: i32) -> i32:\n"
        "    return value + 1\n"
        "\n"
        "def main() -> i32:\n"
        "    return add_one(1)\n"
    )
    [expr] = [
        node
        for node in iter_nodes(function_decl(semantic.module, "add_one"))
        if isinstance(node, ast.NameExpr) and node.name == "value"
    ]
    resolution = semantic.value_use(expr)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.COPY
    assert isinstance(resolution.source, VariableSymbol)
    assert resolution.source.is_parameter


def test_move_by_value_call_argument() -> None:
    semantic = compile_semantic(
        "def consume(values: List[i32]) -> i32:\n"
        "    return cast[i32](len(values))\n"
        "\n"
        "def main() -> i32:\n"
        "    values: List[i32] = [1, 2]\n"
        "    return consume(values)\n"
    )
    [expr] = [
        node
        for node in iter_nodes(function_decl(semantic.module, "main"))
        if isinstance(node, ast.NameExpr) and node.name == "values"
    ]
    resolution = semantic.value_use(expr)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.MOVE
    assert isinstance(resolution.source, VariableSymbol)
    assert resolution.source.name == "values"

    call = next(
        node
        for node in iter_nodes(function_decl(semantic.module, "main"))
        if isinstance(node, ast.CallExpr)
        and isinstance(node.callee, ast.NameExpr)
        and node.callee.name == "consume"
    )
    call_resolution = semantic.call_resolutions[id(call)]
    assert resolution.source in call_resolution.moved_variables


def test_move_return_of_move_only_parameter() -> None:
    semantic = compile_semantic(
        "def forward(values: List[i32]) -> List[i32]:\n"
        "    return values\n"
        "\n"
        "def main() -> i32:\n"
        "    result = forward([1])\n"
        "    return cast[i32](len(result))\n"
    )
    [expr] = [
        node
        for node in iter_nodes(function_decl(semantic.module, "forward"))
        if isinstance(node, ast.NameExpr) and node.name == "values"
    ]
    resolution = semantic.value_use(expr)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.MOVE


def test_move_initializer() -> None:
    semantic = compile_semantic(
        "def main() -> i32:\n"
        "    source: List[i32] = [1, 2]\n"
        "    values: List[i32] = source\n"
        "    return cast[i32](len(values))\n"
    )
    exprs = [
        node
        for node in iter_nodes(function_decl(semantic.module, "main"))
        if isinstance(node, ast.NameExpr) and node.name == "source"
    ]
    assert len(exprs) == 1
    resolution = semantic.value_use(exprs[0])
    assert resolution is not None
    assert resolution.kind is ValueUseKind.MOVE


def test_move_assignment_rhs() -> None:
    semantic = compile_semantic(
        "def main() -> i32:\n"
        "    source: List[i32] = [1, 2]\n"
        "    values: List[i32] = []\n"
        "    values = source\n"
        "    return cast[i32](len(values))\n"
    )
    assign = next(
        node
        for node in iter_nodes(function_decl(semantic.module, "main"))
        if isinstance(node, ast.AssignStmt) and node.operator == "="
    )
    assert isinstance(assign.value, ast.NameExpr)
    assert assign.value.name == "source"
    resolution = semantic.value_use(assign.value)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.MOVE


def test_borrow_reference_parameter() -> None:
    semantic = compile_semantic(
        "def inspect(value: &i32) -> i32:\n"
        "    return *value\n"
        "\n"
        "def main() -> i32:\n"
        "    value: i32 = 7\n"
        "    return inspect(value)\n"
    )
    [expr] = [
        node
        for node in iter_nodes(function_decl(semantic.module, "main"))
        if isinstance(node, ast.NameExpr) and node.name == "value"
    ]
    resolution = semantic.value_use(expr)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.BORROW


def test_address_operand() -> None:
    semantic = compile_semantic(
        "def main() -> i32:\n    value: i32 = 3\n    pointer: *i32 = &value\n    return *pointer\n"
    )
    unary = next(
        node
        for node in iter_nodes(function_decl(semantic.module, "main"))
        if isinstance(node, ast.UnaryExpr) and node.operator == "&"
    )
    assert isinstance(unary.operand, ast.NameExpr)
    resolution = semantic.value_use(unary.operand)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.ADDRESS
    assert semantic.value_use(unary) is None


def test_generic_atomic_inference_preserves_address_operand() -> None:
    semantic = compile_semantic(
        "from std.atomic import Atomic\n"
        "\n"
        "def read[T](cell: *Atomic[T]) -> T:\n"
        "    return cell.load()\n"
        "\n"
        "def main() -> i32:\n"
        "    cell: Atomic[u64] = 7\n"
        "    return cast[i32](read(&cell))\n"
    )
    unary = next(
        node
        for node in iter_nodes(function_decl(semantic.module, "main"))
        if isinstance(node, ast.UnaryExpr) and node.operator == "&"
    )
    assert isinstance(unary.operand, ast.NameExpr)
    resolution = semantic.value_use(unary.operand)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.ADDRESS


def test_atomic_method_receiver_is_address_use() -> None:
    semantic = compile_semantic(
        "from std.atomic import Atomic\n"
        "\n"
        "def main() -> i32:\n"
        "    counter: Atomic[u64] = 0\n"
        "    return cast[i32](counter.fetch_add(1))\n"
    )
    receiver = next(resolution.receiver for resolution in semantic.atomic_call_resolutions.values())
    assert isinstance(receiver, ast.NameExpr)
    resolution = semantic.value_use(receiver)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.ADDRESS


def test_assignment_target_has_no_value_use() -> None:
    semantic = compile_semantic(
        "def main() -> i32:\n"
        "    value: i32 = 0\n"
        "    other: i32 = 1\n"
        "    value = other\n"
        "    return value\n"
    )
    assign = next(
        node
        for node in iter_nodes(function_decl(semantic.module, "main"))
        if isinstance(node, ast.AssignStmt) and node.operator == "="
    )
    assert isinstance(assign.target, ast.NameExpr)
    assert assign.target.name == "value"
    assert semantic.value_use(assign.target) is None
    assert isinstance(assign.value, ast.NameExpr)
    rhs = semantic.value_use(assign.value)
    assert rhs is not None
    assert rhs.kind is ValueUseKind.COPY


def test_deferred_by_value_call_records_move() -> None:
    semantic = compile_semantic(
        "def consume(values: List[i32]) -> void:\n"
        "    pass\n"
        "\n"
        "def main() -> i32:\n"
        "    values: List[i32] = [1]\n"
        "    defer consume(values)\n"
        "    return 0\n"
    )
    [expr] = [
        node
        for node in iter_nodes(function_decl(semantic.module, "main"))
        if isinstance(node, ast.NameExpr) and node.name == "values"
    ]
    resolution = semantic.value_use(expr)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.MOVE


def test_deferred_reference_call_records_borrow() -> None:
    semantic = compile_semantic(
        "def inspect(value: &i32) -> void:\n"
        "    pass\n"
        "\n"
        "def main() -> i32:\n"
        "    value: i32 = 1\n"
        "    defer inspect(value)\n"
        "    return 0\n"
    )
    [expr] = [
        node
        for node in iter_nodes(function_decl(semantic.module, "main"))
        if isinstance(node, ast.NameExpr) and node.name == "value"
    ]
    resolution = semantic.value_use(expr)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.BORROW


def test_module_local_global_has_no_value_use() -> None:
    semantic = compile_semantic("counter: i32 = 1\n\ndef main() -> i32:\n    return counter\n")
    [expr] = name_exprs(semantic.module, "counter")
    assert semantic.value_use(expr) is None


def test_imported_global_has_no_value_use(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    (tmp_path / "cinder.toml").write_text(
        '[project]\nname = "value_use_import"\nsource-root = "src"\nentry = "main.ci"\n',
        encoding="utf-8",
    )
    (source_root / "util.ci").write_text(
        "counter: i32 = 7\n",
        encoding="utf-8",
    )
    (source_root / "main.ci").write_text(
        "from util import counter\n\ndef main() -> i32:\n    return counter\n",
        encoding="utf-8",
    )
    project = Compiler().compile_project(tmp_path)
    semantic = project.units_by_name["main"].semantic
    [expr] = name_exprs(semantic.module, "counter")
    assert semantic.value_use(expr) is None


def test_named_arguments_record_correct_kinds() -> None:
    semantic = compile_semantic(
        "def pair(first: List[i32], second: &i32) -> i32:\n"
        "    return cast[i32](len(first)) + second\n"
        "\n"
        "def main() -> i32:\n"
        "    values: List[i32] = [1, 2]\n"
        "    number: i32 = 3\n"
        "    return pair(second=number, first=values)\n"
    )
    main = function_decl(semantic.module, "main")
    call = next(
        node
        for node in iter_nodes(main)
        if isinstance(node, ast.CallExpr)
        and isinstance(node.callee, ast.NameExpr)
        and node.callee.name == "pair"
    )
    by_name = {argument.name: argument.value for argument in call.arguments}
    first = semantic.value_use(by_name["first"])
    second = semantic.value_use(by_name["second"])
    assert first is not None and first.kind is ValueUseKind.MOVE
    assert second is not None and second.kind is ValueUseKind.BORROW


def test_list_to_slice_argument_records_borrow() -> None:
    semantic = compile_semantic(
        "def first(values: []const i32) -> i32:\n"
        "    return values[0]\n"
        "\n"
        "def main() -> i32:\n"
        "    values: List[i32] = [7, 8]\n"
        "    return first(values)\n"
    )
    [expr] = [
        node
        for node in iter_nodes(function_decl(semantic.module, "main"))
        if isinstance(node, ast.NameExpr) and node.name == "values"
    ]
    resolution = semantic.value_use(expr)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.BORROW


def test_dyn_argument_records_borrow() -> None:
    semantic = compile_semantic(
        "abstract class Shape:\n"
        "    @abstractmethod\n"
        "    def area(self) -> f64:\n"
        "        pass\n"
        "\n"
        "class Circle(Shape):\n"
        "    radius: f64\n"
        "\n"
        "    def __init__(self, radius: f64):\n"
        "        self.radius = radius\n"
        "\n"
        "    @override\n"
        "    def area(self) -> f64:\n"
        "        return self.radius * self.radius\n"
        "\n"
        "def measure(shape: &dyn Shape) -> f64:\n"
        "    return shape.area()\n"
        "\n"
        "def main() -> i32:\n"
        "    circle = Circle(1.0)\n"
        "    return cast[i32](measure(circle))\n"
    )
    call = next(
        node
        for node in iter_nodes(function_decl(semantic.module, "main"))
        if isinstance(node, ast.CallExpr)
        and isinstance(node.callee, ast.NameExpr)
        and node.callee.name == "measure"
    )
    argument = call.arguments[0].value
    assert isinstance(argument, ast.NameExpr)
    resolution = semantic.value_use(argument)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.BORROW


def _named_initializer(module: ast.Module, field_name: str) -> ast.Expression:
    for node in iter_nodes(function_decl(module, "main")):
        if isinstance(node, ast.CallExpr):
            for argument in node.arguments:
                if argument.name == field_name:
                    return argument.value
    raise AssertionError(f"initializer for field {field_name!r} not found")


def test_struct_reference_field_records_borrow() -> None:
    semantic = compile_semantic(
        "struct Holder:\n"
        "    value: &i32\n"
        "\n"
        "def main() -> i32:\n"
        "    number: i32 = 3\n"
        "    holder = Holder(value=number)\n"
        "    return *holder.value\n"
    )
    expr = _named_initializer(semantic.module, "value")
    assert isinstance(expr, ast.NameExpr)
    resolution = semantic.value_use(expr)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.BORROW


def test_struct_dyn_field_records_borrow() -> None:
    semantic = compile_semantic(
        "abstract class Shape:\n"
        "    @abstractmethod\n"
        "    def area(self) -> f64:\n"
        "        pass\n"
        "\n"
        "class Circle(Shape):\n"
        "    radius: f64\n"
        "\n"
        "    def __init__(self, radius: f64):\n"
        "        self.radius = radius\n"
        "\n"
        "    @override\n"
        "    def area(self) -> f64:\n"
        "        return self.radius * self.radius\n"
        "\n"
        "struct Holder:\n"
        "    shape: &dyn Shape\n"
        "\n"
        "def main() -> i32:\n"
        "    circle = Circle(1.0)\n"
        "    holder = Holder(shape=circle)\n"
        "    return cast[i32](holder.shape.area())\n"
    )
    expr = _named_initializer(semantic.module, "shape")
    assert isinstance(expr, ast.NameExpr)
    resolution = semantic.value_use(expr)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.BORROW


def test_struct_list_to_slice_field_records_borrow() -> None:
    semantic = compile_semantic(
        "struct View:\n"
        "    items: []const i32\n"
        "\n"
        "def main() -> i32:\n"
        "    values: List[i32] = [7, 8]\n"
        "    view = View(items=values)\n"
        "    return view.items[0]\n"
    )
    expr = _named_initializer(semantic.module, "items")
    assert isinstance(expr, ast.NameExpr)
    resolution = semantic.value_use(expr)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.BORROW


def test_struct_move_only_field_records_move() -> None:
    semantic = compile_semantic(
        "struct Bundle:\n"
        "    items: List[i32]\n"
        "\n"
        "def main() -> i32:\n"
        "    values: List[i32] = [1, 2]\n"
        "    bundle = Bundle(items=values)\n"
        "    return cast[i32](len(bundle.items))\n"
    )
    expr = _named_initializer(semantic.module, "items")
    assert isinstance(expr, ast.NameExpr)
    resolution = semantic.value_use(expr)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.MOVE


def test_variant_copyable_payload_records_copy() -> None:
    semantic = compile_semantic(
        "variant Token:\n"
        "    Integer(value: i32)\n"
        "\n"
        "def main() -> i32:\n"
        "    number: i32 = 9\n"
        "    token = Token.Integer(number)\n"
        "    match token:\n"
        "        case Integer(value):\n"
        "            return value\n"
    )
    call = next(
        node
        for node in iter_nodes(function_decl(semantic.module, "main"))
        if isinstance(node, ast.CallExpr)
        and isinstance(node.callee, ast.AttributeExpr)
        and node.callee.name == "Integer"
    )
    argument = call.arguments[0].value
    assert isinstance(argument, ast.NameExpr)
    resolution = semantic.value_use(argument)
    assert resolution is not None
    assert resolution.kind is ValueUseKind.COPY
