"""AST cloning and type-parameter substitution for user generics."""

from __future__ import annotations

import copy
from typing import Mapping

from cinder import ast
from cinder.types import Type, type_key


def specialization_suffix(type_args: tuple[Type, ...]) -> str:
    if not type_args:
        return ""
    return "_" + "_".join(type_key(argument) for argument in type_args)


def specialized_display_name(template_name: str, type_args: tuple[Type, ...]) -> str:
    if not type_args:
        return template_name
    from cinder.types import type_name

    return (
        f"{template_name}["
        + ", ".join(type_name(argument) for argument in type_args)
        + "]"
    )


def make_type_param_mapping(
    type_params: tuple[str, ...],
    argument_nodes: list[ast.TypeNode],
) -> dict[str, ast.TypeNode]:
    return {
        name: copy.deepcopy(node)
        for name, node in zip(type_params, argument_nodes, strict=True)
    }


def substitute_type_node(
    node: ast.TypeNode | None,
    mapping: Mapping[str, ast.TypeNode],
) -> ast.TypeNode | None:
    if node is None:
        return None
    match node:
        case ast.NamedTypeNode(name=name):
            replacement = mapping.get(name)
            if replacement is not None:
                return copy.deepcopy(replacement)
            return ast.NamedTypeNode(node.span, name)
        case ast.GenericTypeNode(base=base, arguments=arguments):
            return ast.GenericTypeNode(
                node.span,
                substitute_type_node(base, mapping),  # type: ignore[arg-type]
                [
                    substitute_type_node(argument, mapping)  # type: ignore[misc]
                    for argument in arguments
                ],
            )
        case ast.ConstTypeNode(inner=inner):
            return ast.ConstTypeNode(
                node.span,
                substitute_type_node(inner, mapping),  # type: ignore[arg-type]
            )
        case ast.PointerTypeNode(inner=inner):
            return ast.PointerTypeNode(
                node.span,
                substitute_type_node(inner, mapping),  # type: ignore[arg-type]
            )
        case ast.ReferenceTypeNode(inner=inner):
            return ast.ReferenceTypeNode(
                node.span,
                substitute_type_node(inner, mapping),  # type: ignore[arg-type]
            )
        case ast.ArrayTypeNode(inner=inner, length=length):
            return ast.ArrayTypeNode(
                node.span,
                substitute_type_node(inner, mapping),  # type: ignore[arg-type]
                length,
            )
        case ast.SliceTypeNode(inner=inner):
            return ast.SliceTypeNode(
                node.span,
                substitute_type_node(inner, mapping),  # type: ignore[arg-type]
            )
        case ast.DynTypeNode(interface=interface, is_const=is_const):
            return ast.DynTypeNode(
                node.span,
                substitute_type_node(interface, mapping),  # type: ignore[arg-type]
                is_const,
            )
        case ast.FunctionTypeNode(parameters=parameters, return_type=return_type):
            return ast.FunctionTypeNode(
                node.span,
                [
                    substitute_type_node(parameter, mapping)  # type: ignore[misc]
                    for parameter in parameters
                ],
                substitute_type_node(return_type, mapping),
            )
    raise AssertionError(f"unhandled type node: {node!r}")


def _rewrite_expression(
    expression: ast.Expression,
    mapping: Mapping[str, ast.TypeNode],
) -> None:
    match expression:
        case ast.CallExpr():
            expression.type_arguments = [
                substitute_type_node(argument, mapping)  # type: ignore[misc]
                for argument in expression.type_arguments
            ]
            _rewrite_expression(expression.callee, mapping)
            for argument in expression.arguments:
                _rewrite_expression(argument.value, mapping)
        case ast.AttributeExpr():
            _rewrite_expression(expression.value, mapping)
        case ast.IndexExpr():
            _rewrite_expression(expression.value, mapping)
            _rewrite_expression(expression.index, mapping)
        case ast.SliceExpr():
            _rewrite_expression(expression.value, mapping)
            if expression.start is not None:
                _rewrite_expression(expression.start, mapping)
            if expression.stop is not None:
                _rewrite_expression(expression.stop, mapping)
        case ast.UnaryExpr():
            _rewrite_expression(expression.operand, mapping)
        case ast.BinaryExpr():
            _rewrite_expression(expression.left, mapping)
            _rewrite_expression(expression.right, mapping)
        case ast.PropagateExpr():
            _rewrite_expression(expression.value, mapping)
        case ast.ListLiteralExpr():
            for element in expression.elements:
                _rewrite_expression(element, mapping)
        case ast.MapLiteralExpr():
            for entry in expression.entries:
                _rewrite_expression(entry.key, mapping)
                _rewrite_expression(entry.value, mapping)
        case ast.SetLiteralExpr():
            for element in expression.elements:
                _rewrite_expression(element, mapping)
        case ast.TupleLiteralExpr():
            for element in expression.elements:
                _rewrite_expression(element, mapping)
        case ast.CastExpr():
            expression.target_type = substitute_type_node(
                expression.target_type, mapping
            )  # type: ignore[assignment]
            _rewrite_expression(expression.value, mapping)
        case ast.AllocExpr():
            expression.element_type = substitute_type_node(
                expression.element_type, mapping
            )  # type: ignore[assignment]
            if expression.count is not None:
                _rewrite_expression(expression.count, mapping)
        case ast.FStringExpr():
            for part in expression.parts:
                if isinstance(part, ast.FStringExpression):
                    _rewrite_expression(part.expression, mapping)
        case ast.NameExpr() | ast.LiteralExpr() | ast.NoneExpr():
            return
        case _:
            for attribute in getattr(expression, "__slots__", ()):
                value = getattr(expression, attribute, None)
                if isinstance(value, ast.Expression):
                    _rewrite_expression(value, mapping)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, ast.Expression):
                            _rewrite_expression(item, mapping)
                        elif isinstance(item, ast.CallArgument):
                            _rewrite_expression(item.value, mapping)


def _rewrite_statement(
    statement: ast.Statement,
    mapping: Mapping[str, ast.TypeNode],
) -> None:
    match statement:
        case ast.VarDeclStmt():
            if statement.annotation is not None:
                statement.annotation = substitute_type_node(
                    statement.annotation, mapping
                )
            if statement.initializer is not None:
                _rewrite_expression(statement.initializer, mapping)
        case ast.AssignStmt():
            _rewrite_expression(statement.target, mapping)
            _rewrite_expression(statement.value, mapping)
        case ast.ExpressionStmt():
            _rewrite_expression(statement.expression, mapping)
        case ast.ReturnStmt():
            if statement.value is not None:
                _rewrite_expression(statement.value, mapping)
        case ast.DeferStmt():
            _rewrite_expression(statement.expression, mapping)
        case ast.IfStmt():
            for branch in statement.branches:
                _rewrite_expression(branch.condition, mapping)
                _rewrite_block(branch.body, mapping)
            if statement.else_body is not None:
                _rewrite_block(statement.else_body, mapping)
        case ast.WhileStmt():
            _rewrite_expression(statement.condition, mapping)
            _rewrite_block(statement.body, mapping)
        case ast.ForEachStmt():
            if statement.annotation is not None:
                statement.annotation = substitute_type_node(
                    statement.annotation, mapping
                )
            _rewrite_expression(statement.iterable, mapping)
            _rewrite_block(statement.body, mapping)
        case ast.ForCStmt():
            if statement.initializer is not None:
                _rewrite_statement(statement.initializer, mapping)
            if statement.condition is not None:
                _rewrite_expression(statement.condition, mapping)
            if statement.update is not None:
                _rewrite_statement(statement.update, mapping)
            _rewrite_block(statement.body, mapping)
        case ast.MatchStmt():
            _rewrite_expression(statement.value, mapping)
            for case in statement.cases:
                _rewrite_block(case.body, mapping)
        case ast.WithStmt():
            _rewrite_expression(statement.context, mapping)
            _rewrite_block(statement.body, mapping)
        case ast.UnsafeStmt():
            _rewrite_block(statement.body, mapping)
        case ast.BreakStmt() | ast.ContinueStmt() | ast.PassStmt():
            return
        case _:
            for attribute in getattr(statement, "__slots__", ()):
                value = getattr(statement, attribute, None)
                if isinstance(value, ast.Expression):
                    _rewrite_expression(value, mapping)
                elif isinstance(value, ast.Block):
                    _rewrite_block(value, mapping)
                elif isinstance(value, ast.TypeNode):
                    setattr(
                        statement,
                        attribute,
                        substitute_type_node(value, mapping),
                    )


def _rewrite_block(block: ast.Block, mapping: Mapping[str, ast.TypeNode]) -> None:
    for statement in block.statements:
        _rewrite_statement(statement, mapping)


def _rewrite_function(
    declaration: ast.FunctionDecl,
    mapping: Mapping[str, ast.TypeNode],
) -> None:
    declaration.type_params = ()
    for parameter in declaration.parameters:
        if parameter.annotation is not None:
            parameter.annotation = substitute_type_node(
                parameter.annotation, mapping
            )
    if declaration.return_type is not None:
        declaration.return_type = substitute_type_node(
            declaration.return_type, mapping
        )
    if declaration.body is not None:
        _rewrite_block(declaration.body, mapping)


def specialize_struct(
    declaration: ast.StructDecl,
    mapping: Mapping[str, ast.TypeNode],
) -> ast.StructDecl:
    cloned = copy.deepcopy(declaration)
    cloned.type_params = ()
    for field in cloned.fields:
        field.annotation = substitute_type_node(field.annotation, mapping)  # type: ignore[assignment]
    for method in cloned.methods:
        _rewrite_function(method, mapping)
    return cloned


def specialize_class(
    declaration: ast.ClassDecl,
    mapping: Mapping[str, ast.TypeNode],
) -> ast.ClassDecl:
    cloned = copy.deepcopy(declaration)
    cloned.type_params = ()
    cloned.bases = [
        substitute_type_node(base, mapping)  # type: ignore[misc]
        for base in cloned.bases
    ]
    for field in cloned.fields:
        field.annotation = substitute_type_node(field.annotation, mapping)  # type: ignore[assignment]
    for method in cloned.methods:
        _rewrite_function(method, mapping)
    return cloned


def specialize_enum(
    declaration: ast.EnumDecl,
    _mapping: Mapping[str, ast.TypeNode],
) -> ast.EnumDecl:
    cloned = copy.deepcopy(declaration)
    cloned.type_params = ()
    return cloned


def specialize_union(
    declaration: ast.UnionDecl,
    mapping: Mapping[str, ast.TypeNode],
) -> ast.UnionDecl:
    cloned = copy.deepcopy(declaration)
    cloned.type_params = ()
    for field in cloned.fields:
        field.annotation = substitute_type_node(field.annotation, mapping)  # type: ignore[assignment]
    return cloned


def specialize_variant(
    declaration: ast.VariantDecl,
    mapping: Mapping[str, ast.TypeNode],
) -> ast.VariantDecl:
    cloned = copy.deepcopy(declaration)
    cloned.type_params = ()
    for case in cloned.cases:
        for field in case.fields:
            field.annotation = substitute_type_node(field.annotation, mapping)  # type: ignore[assignment]
    return cloned


def specialize_function(
    declaration: ast.FunctionDecl,
    mapping: Mapping[str, ast.TypeNode],
) -> ast.FunctionDecl:
    cloned = copy.deepcopy(declaration)
    _rewrite_function(cloned, mapping)
    return cloned
