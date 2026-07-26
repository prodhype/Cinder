from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cinder.diagnostics import Span


@dataclass(slots=True)
class Node:
    span: Span


@dataclass(slots=True)
class TypeNode(Node):
    pass


@dataclass(slots=True)
class NamedTypeNode(TypeNode):
    name: str


@dataclass(slots=True)
class GenericTypeNode(TypeNode):
    base: TypeNode
    arguments: list[TypeNode]


@dataclass(slots=True)
class ConstTypeNode(TypeNode):
    inner: TypeNode


@dataclass(slots=True)
class PointerTypeNode(TypeNode):
    inner: TypeNode


@dataclass(slots=True)
class ReferenceTypeNode(TypeNode):
    inner: TypeNode


@dataclass(slots=True)
class ArrayTypeNode(TypeNode):
    inner: TypeNode
    length: int


@dataclass(slots=True)
class SliceTypeNode(TypeNode):
    inner: TypeNode


@dataclass(slots=True)
class DynTypeNode(TypeNode):
    interface: TypeNode
    is_const: bool = False


@dataclass(slots=True)
class Parameter(Node):
    name: str
    annotation: TypeNode | None
    is_variadic: bool = False


@dataclass(slots=True)
class FieldDecl(Node):
    name: str
    annotation: TypeNode
    is_private: bool = False


@dataclass(slots=True)
class Block(Node):
    statements: list[Statement] = field(default_factory=list)


@dataclass(slots=True)
class TopLevel(Node):
    pass


@dataclass(slots=True)
class ImportDecl(TopLevel):
    module: str
    alias: str | None = None


@dataclass(slots=True)
class FromImportDecl(TopLevel):
    module: str
    names: list[tuple[str, str | None]] = field(default_factory=list)


@dataclass(slots=True)
class ExternImportDecl(TopLevel):
    header: str
    system: bool = True


@dataclass(slots=True)
class FunctionDecl(TopLevel):
    name: str
    parameters: list[Parameter]
    return_type: TypeNode | None
    body: Block | None
    decorators: tuple[str, ...] = ()
    is_extern: bool = False
    owner: str | None = None

    @property
    def is_exported(self) -> bool:
        return "export" in self.decorators or self.name == "main"


@dataclass(slots=True)
class StructDecl(TopLevel):
    name: str
    fields: list[FieldDecl]
    methods: list[FunctionDecl]
    decorators: tuple[str, ...] = ()


@dataclass(slots=True)
class ClassDecl(TopLevel):
    name: str
    bases: list[TypeNode]
    fields: list[FieldDecl]
    methods: list[FunctionDecl]
    decorators: tuple[str, ...] = ()
    is_abstract: bool = False


@dataclass(slots=True)
class EnumMemberDecl(Node):
    name: str
    value: int | None = None


@dataclass(slots=True)
class EnumDecl(TopLevel):
    name: str
    members: list[EnumMemberDecl]
    decorators: tuple[str, ...] = ()


@dataclass(slots=True)
class UnionDecl(TopLevel):
    name: str
    fields: list[FieldDecl]
    decorators: tuple[str, ...] = ()


@dataclass(slots=True)
class VariantCaseDecl(Node):
    name: str
    fields: list[FieldDecl]


@dataclass(slots=True)
class VariantDecl(TopLevel):
    name: str
    cases: list[VariantCaseDecl]
    decorators: tuple[str, ...] = ()


@dataclass(slots=True)
class GlobalDecl(TopLevel):
    name: str
    annotation: TypeNode | None
    initializer: Expression | None
    is_const: bool = False


@dataclass(slots=True)
class StaticAssertDecl(TopLevel):
    condition: Expression
    message: str | None = None


@dataclass(slots=True)
class Module(Node):
    path: Path
    items: list[TopLevel]

    @property
    def imports(self) -> list[ImportDecl]:
        return [item for item in self.items if isinstance(item, ImportDecl)]

    @property
    def from_imports(self) -> list[FromImportDecl]:
        return [item for item in self.items if isinstance(item, FromImportDecl)]

    @property
    def extern_imports(self) -> list[ExternImportDecl]:
        return [item for item in self.items if isinstance(item, ExternImportDecl)]

    @property
    def structs(self) -> list[StructDecl]:
        return [item for item in self.items if isinstance(item, StructDecl)]

    @property
    def classes(self) -> list[ClassDecl]:
        return [item for item in self.items if isinstance(item, ClassDecl)]

    @property
    def enums(self) -> list[EnumDecl]:
        return [item for item in self.items if isinstance(item, EnumDecl)]

    @property
    def unions(self) -> list[UnionDecl]:
        return [item for item in self.items if isinstance(item, UnionDecl)]

    @property
    def variants(self) -> list[VariantDecl]:
        return [item for item in self.items if isinstance(item, VariantDecl)]

    @property
    def functions(self) -> list[FunctionDecl]:
        return [item for item in self.items if isinstance(item, FunctionDecl)]

    @property
    def globals(self) -> list[GlobalDecl]:
        return [item for item in self.items if isinstance(item, GlobalDecl)]

    @property
    def static_asserts(self) -> list[StaticAssertDecl]:
        return [item for item in self.items if isinstance(item, StaticAssertDecl)]


@dataclass(slots=True)
class Statement(Node):
    pass


@dataclass(slots=True)
class VarDeclStmt(Statement):
    name: str
    annotation: TypeNode | None
    initializer: Expression | None
    is_const: bool = False


@dataclass(slots=True)
class AssignStmt(Statement):
    target: Expression
    operator: str
    value: Expression


@dataclass(slots=True)
class ExpressionStmt(Statement):
    expression: Expression


@dataclass(slots=True)
class ReturnStmt(Statement):
    value: Expression | None


@dataclass(slots=True)
class IfBranch(Node):
    condition: Expression
    body: Block


@dataclass(slots=True)
class IfStmt(Statement):
    branches: list[IfBranch]
    else_body: Block | None


@dataclass(slots=True)
class WhileStmt(Statement):
    condition: Expression
    body: Block


@dataclass(slots=True)
class ForEachStmt(Statement):
    name: str
    annotation: TypeNode | None
    iterable: Expression
    body: Block
    is_comptime: bool = False


@dataclass(slots=True)
class ForCStmt(Statement):
    initializer: Statement | None
    condition: Expression | None
    update: Statement | None
    body: Block


@dataclass(slots=True)
class MatchPattern(Node):
    path: tuple[str, ...] | None
    bindings: list[str] = field(default_factory=list)
    is_wildcard: bool = False


@dataclass(slots=True)
class MatchCase(Node):
    pattern: MatchPattern
    body: Block


@dataclass(slots=True)
class MatchStmt(Statement):
    value: Expression
    cases: list[MatchCase]


@dataclass(slots=True)
class BreakStmt(Statement):
    pass


@dataclass(slots=True)
class ContinueStmt(Statement):
    pass


@dataclass(slots=True)
class PassStmt(Statement):
    pass


@dataclass(slots=True)
class DeferStmt(Statement):
    expression: Expression


@dataclass(slots=True)
class UnsafeStmt(Statement):
    body: Block


@dataclass(slots=True)
class Expression(Node):
    pass


@dataclass(slots=True)
class NameExpr(Expression):
    name: str


@dataclass(slots=True)
class LiteralExpr(Expression):
    value: int | float | str | bool | None
    literal_kind: str
    raw: str


@dataclass(slots=True)
class FStringText(Node):
    value: str


@dataclass(slots=True)
class FStringExpression(Node):
    expression: Expression
    format_spec: str | None = None


FStringPart = FStringText | FStringExpression


@dataclass(slots=True)
class FStringExpr(Expression):
    parts: list[FStringPart]


@dataclass(slots=True)
class UnaryExpr(Expression):
    operator: str
    operand: Expression


@dataclass(slots=True)
class BinaryExpr(Expression):
    left: Expression
    operator: str
    right: Expression


@dataclass(slots=True)
class AttributeExpr(Expression):
    value: Expression
    name: str


@dataclass(slots=True)
class IndexExpr(Expression):
    value: Expression
    index: Expression


@dataclass(slots=True)
class SliceExpr(Expression):
    value: Expression
    start: Expression | None
    stop: Expression | None


@dataclass(slots=True)
class CallArgument(Node):
    value: Expression
    name: str | None = None


@dataclass(slots=True)
class CallExpr(Expression):
    callee: Expression
    arguments: list[CallArgument]


@dataclass(slots=True)
class PropagateExpr(Expression):
    value: Expression


@dataclass(slots=True)
class ListLiteralExpr(Expression):
    elements: list[Expression]


@dataclass(slots=True)
class TupleLiteralExpr(Expression):
    elements: list[Expression]


@dataclass(slots=True)
class CastExpr(Expression):
    target_type: TypeNode
    value: Expression


@dataclass(slots=True)
class AllocExpr(Expression):
    element_type: TypeNode
    count: Expression | None


type TopLevelItem = (
    ImportDecl
    | FromImportDecl
    | ExternImportDecl
    | FunctionDecl
    | StructDecl
    | ClassDecl
    | EnumDecl
    | UnionDecl
    | VariantDecl
    | GlobalDecl
    | StaticAssertDecl
)
