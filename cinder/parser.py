from __future__ import annotations

import ast as python_ast
from pathlib import Path
from typing import NoReturn

from cinder import ast
from cinder.diagnostics import CompilationFailed, DiagnosticBag, Span
from cinder.lexer import Token, TokenKind, lex

_ASSIGNMENT_KINDS: dict[TokenKind, str] = {
    TokenKind.ASSIGN: "=",
    TokenKind.PLUS_ASSIGN: "+=",
    TokenKind.MINUS_ASSIGN: "-=",
    TokenKind.STAR_ASSIGN: "*=",
    TokenKind.SLASH_ASSIGN: "/=",
    TokenKind.PERCENT_ASSIGN: "%=",
    TokenKind.AMPERSAND_ASSIGN: "&=",
    TokenKind.PIPE_ASSIGN: "|=",
    TokenKind.CARET_ASSIGN: "^=",
    TokenKind.SHIFT_LEFT_ASSIGN: "<<=",
    TokenKind.SHIFT_RIGHT_ASSIGN: ">>=",
}


_BINARY_PRECEDENCE: dict[TokenKind, tuple[int, str]] = {
    TokenKind.OR: (1, "or"),
    TokenKind.AND: (2, "and"),
    TokenKind.PIPE: (3, "|"),
    TokenKind.CARET: (4, "^"),
    TokenKind.AMPERSAND: (5, "&"),
    TokenKind.EQUAL: (6, "=="),
    TokenKind.NOT_EQUAL: (6, "!="),
    TokenKind.LESS: (6, "<"),
    TokenKind.LESS_EQUAL: (6, "<="),
    TokenKind.GREATER: (6, ">"),
    TokenKind.GREATER_EQUAL: (6, ">="),
    TokenKind.IN: (6, "in"),
    TokenKind.SHIFT_LEFT: (7, "<<"),
    TokenKind.SHIFT_RIGHT: (7, ">>"),
    TokenKind.PLUS: (8, "+"),
    TokenKind.MINUS: (8, "-"),
    TokenKind.STAR: (9, "*"),
    TokenKind.SLASH: (9, "/"),
    TokenKind.PERCENT: (9, "%"),
}


class _ParseAbort(Exception):
    pass


class Parser:
    def __init__(self, tokens: list[Token], source: str, path: Path) -> None:
        self.tokens = tokens
        self.source = source
        self.path = path
        self.index = 0
        self.diagnostics = DiagnosticBag()

    def parse(self) -> ast.Module:
        items: list[ast.TopLevel] = []
        start_span = self.current.span

        try:
            while not self.at(TokenKind.EOF):
                if self.match(TokenKind.NEWLINE):
                    continue

                decorators = self.parse_decorators()
                if self.at(TokenKind.IMPORT):
                    self._reject_decorators(decorators)
                    items.append(self.parse_import())
                elif self.at(TokenKind.FROM):
                    self._reject_decorators(decorators)
                    items.append(self.parse_from_import())
                elif self.at(TokenKind.EXTERN):
                    self._reject_decorators(decorators)
                    items.extend(self.parse_extern())
                elif self.at(TokenKind.STRUCT):
                    items.append(self.parse_struct(decorators))
                elif self.at(TokenKind.CLASS) or self.at(TokenKind.ABSTRACT):
                    items.append(self.parse_class(decorators))
                elif self.at(TokenKind.ENUM):
                    items.append(self.parse_enum(decorators))
                elif self.at(TokenKind.UNION):
                    items.append(self.parse_union(decorators))
                elif self.at(TokenKind.VARIANT):
                    items.append(self.parse_variant(decorators))
                elif self.at(TokenKind.DEF):
                    items.append(self.parse_function(decorators, owner=None, is_extern=False))
                elif (
                    self.at(TokenKind.NAME)
                    and self.current.lexeme == "static_assert"
                    and self.peek().kind is TokenKind.LEFT_PAREN
                ):
                    self._reject_decorators(decorators)
                    items.append(self.parse_static_assert())
                elif self.at(TokenKind.CONST) or (
                    self.at(TokenKind.NAME)
                    and self.peek().kind in (TokenKind.COLON, TokenKind.ASSIGN)
                ):
                    self._reject_decorators(decorators)
                    items.append(self.parse_global())
                else:
                    self.error(
                        "expected an import, type, function, or global declaration",
                        self.current.span,
                        code="P002",
                    )
        except _ParseAbort:
            pass

        if self.diagnostics.has_errors:
            raise CompilationFailed(self.diagnostics.items, self.source)

        end_span = self.current.span
        return ast.Module(
            span=start_span.merge(end_span),
            path=self.path,
            items=items,
        )

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def peek(self, offset: int = 1) -> Token:
        position = min(self.index + offset, len(self.tokens) - 1)
        return self.tokens[position]

    def at(self, *kinds: TokenKind) -> bool:
        return self.current.kind in kinds

    def advance(self) -> Token:
        token = self.current
        if token.kind is not TokenKind.EOF:
            self.index += 1
        return token

    def match(self, *kinds: TokenKind) -> Token | None:
        if self.at(*kinds):
            return self.advance()
        return None

    def expect(
        self,
        kind: TokenKind,
        message: str | None = None,
        *,
        code: str = "P003",
    ) -> Token:
        if self.at(kind):
            return self.advance()
        self.error(message or f"expected {kind.value!r}", self.current.span, code=code)

    def error(
        self,
        message: str,
        span: Span,
        *,
        code: str,
        note: str | None = None,
    ) -> NoReturn:
        self.diagnostics.error(message, span, code=code, note=note)
        raise _ParseAbort

    def _reject_decorators(self, decorators: tuple[str, ...]) -> None:
        if decorators:
            self.error(
                "decorators are only valid on type and function declarations",
                self.current.span,
                code="P004",
            )

    def parse_decorators(self) -> tuple[str, ...]:
        decorators: list[str] = []
        while self.match(TokenKind.AT):
            name = self.expect(TokenKind.NAME, "expected decorator name", code="P005")
            decorators.append(name.lexeme)
            self.expect(TokenKind.NEWLINE, "expected newline after decorator", code="P006")
        return tuple(decorators)

    def parse_import(self) -> ast.ImportDecl:
        start = self.expect(TokenKind.IMPORT).span
        module = self.parse_dotted_name()
        alias: str | None = None
        if self.match(TokenKind.AS):
            alias = self.expect(TokenKind.NAME, "expected import alias", code="P007").lexeme
        end = self.expect(TokenKind.NEWLINE, "expected newline after import", code="P008").span
        return ast.ImportDecl(start.merge(end), module, alias)

    def parse_from_import(self) -> ast.FromImportDecl:
        start = self.expect(TokenKind.FROM).span
        module = self.parse_dotted_name()
        self.expect(TokenKind.IMPORT, "expected 'import'", code="P009")
        names: list[tuple[str, str | None]] = []
        while True:
            name = self.expect(TokenKind.NAME, "expected imported name", code="P010").lexeme
            alias: str | None = None
            if self.match(TokenKind.AS):
                alias = self.expect(TokenKind.NAME, "expected import alias", code="P011").lexeme
            names.append((name, alias))
            if not self.match(TokenKind.COMMA):
                break
        end = self.expect(TokenKind.NEWLINE, "expected newline after import", code="P012").span
        return ast.FromImportDecl(start.merge(end), module, names)

    def parse_extern(self) -> list[ast.TopLevel]:
        start = self.expect(TokenKind.EXTERN).span
        if self.match(TokenKind.IMPORT):
            header = self.expect(TokenKind.STRING, "expected a quoted C header", code="P013")
            self.expect(TokenKind.NEWLINE, "expected newline after external import", code="P014")
            value = _decode_string(header)
            return [ast.ExternImportDecl(start.merge(header.span), value, True)]

        abi = self.expect(TokenKind.STRING, "expected 'import' or an ABI string", code="P015")
        abi_value = _decode_string(abi)
        if abi_value != "C":
            self.error(
                f"unsupported external ABI {abi_value!r}",
                abi.span,
                code="P016",
                note="the first compiler supports only extern \"C\"",
            )
        self.expect(TokenKind.COLON, "expected ':' after ABI", code="P017")
        self.expect(TokenKind.NEWLINE, "expected newline after external block", code="P018")
        self.expect(TokenKind.INDENT, "expected an indented external block", code="P019")

        declarations: list[ast.TopLevel] = []
        while not self.at(TokenKind.DEDENT, TokenKind.EOF):
            if self.match(TokenKind.NEWLINE):
                continue
            decorators = self.parse_decorators()
            if not self.at(TokenKind.DEF):
                self.error(
                    "only function declarations are allowed in extern blocks",
                    self.current.span,
                    code="P020",
                )
            declarations.append(
                self.parse_function(decorators, owner=None, is_extern=True)
            )
        self.expect(TokenKind.DEDENT, "expected end of external block", code="P021")
        return declarations

    def parse_dotted_name(self) -> str:
        parts = [self.expect(TokenKind.NAME, "expected a module name", code="P022").lexeme]
        while self.match(TokenKind.DOT):
            parts.append(self.expect(TokenKind.NAME, "expected name after '.'", code="P023").lexeme)
        return ".".join(parts)

    def parse_type_params(self) -> tuple[str, ...]:
        if not self.match(TokenKind.LEFT_BRACKET):
            return ()
        names: list[str] = []
        if not self.at(TokenKind.RIGHT_BRACKET):
            while True:
                name = self.expect(TokenKind.NAME, "expected type parameter name", code="P141")
                if name.lexeme in names:
                    self.error(
                        f"duplicate type parameter {name.lexeme!r}",
                        name.span,
                        code="P142",
                    )
                names.append(name.lexeme)
                if not self.match(TokenKind.COMMA):
                    break
                if self.at(TokenKind.RIGHT_BRACKET):
                    break
        self.expect(TokenKind.RIGHT_BRACKET, "expected ']' after type parameters", code="P143")
        if not names:
            self.error("type parameter list cannot be empty", self.tokens[self.index - 1].span, code="P144")
        return tuple(names)

    def _looks_like_generic_call(self) -> bool:
        """True when the next tokens are `[...](` with balanced brackets."""
        if not self.at(TokenKind.NAME) or self.peek().kind is not TokenKind.LEFT_BRACKET:
            return False
        depth = 0
        index = self.index + 1
        while index < len(self.tokens):
            kind = self.tokens[index].kind
            if kind is TokenKind.LEFT_BRACKET:
                depth += 1
            elif kind is TokenKind.RIGHT_BRACKET:
                depth -= 1
                if depth == 0:
                    return (
                        index + 1 < len(self.tokens)
                        and self.tokens[index + 1].kind is TokenKind.LEFT_PAREN
                    )
            elif kind in (TokenKind.NEWLINE, TokenKind.EOF, TokenKind.DEDENT, TokenKind.INDENT):
                return False
            index += 1
        return False

    def parse_struct(self, decorators: tuple[str, ...]) -> ast.StructDecl:
        start = self.expect(TokenKind.STRUCT).span
        name_token = self.expect(TokenKind.NAME, "expected struct name", code="P024")
        type_params = self.parse_type_params()
        self.expect(TokenKind.COLON, "expected ':' after struct name", code="P025")
        self.expect(TokenKind.NEWLINE, "expected newline after struct declaration", code="P026")
        self.expect(TokenKind.INDENT, "expected an indented struct body", code="P027")

        fields: list[ast.FieldDecl] = []
        methods: list[ast.FunctionDecl] = []
        while not self.at(TokenKind.DEDENT, TokenKind.EOF):
            if self.match(TokenKind.NEWLINE):
                continue
            member_decorators = self.parse_decorators()
            if self.at(TokenKind.DEF):
                methods.append(
                    self.parse_function(
                        member_decorators,
                        owner=name_token.lexeme,
                        is_extern=False,
                    )
                )
                continue
            if member_decorators:
                self.error(
                    "field declarations cannot have decorators",
                    self.current.span,
                    code="P028",
                )

            is_private = self.match(TokenKind.PRIVATE) is not None
            field_name = self.expect(TokenKind.NAME, "expected field or method", code="P029")
            self.expect(TokenKind.COLON, "expected ':' after field name", code="P030")
            annotation = self.parse_type()
            end = self.expect(TokenKind.NEWLINE, "expected newline after field", code="P031").span
            fields.append(
                ast.FieldDecl(
                    field_name.span.merge(end),
                    field_name.lexeme,
                    annotation,
                    is_private,
                )
            )

        end = self.expect(TokenKind.DEDENT, "expected end of struct body", code="P032").span
        if not fields and not methods:
            self.error("struct body cannot be empty", start.merge(end), code="P033")
        return ast.StructDecl(
            start.merge(end),
            name_token.lexeme,
            fields,
            methods,
            decorators,
            type_params,
        )

    def parse_class(self, decorators: tuple[str, ...]) -> ast.ClassDecl:
        is_abstract = self.match(TokenKind.ABSTRACT) is not None
        start = self.tokens[self.index - 1].span if is_abstract else self.current.span
        self.expect(TokenKind.CLASS, "expected 'class' after 'abstract'", code="P124")
        name_token = self.expect(TokenKind.NAME, "expected class name", code="P125")
        type_params = self.parse_type_params()

        bases: list[ast.TypeNode] = []
        if self.match(TokenKind.LEFT_PAREN):
            if not self.at(TokenKind.RIGHT_PAREN):
                while True:
                    bases.append(self.parse_type())
                    if not self.match(TokenKind.COMMA):
                        break
                    if self.at(TokenKind.RIGHT_PAREN):
                        break
            self.expect(TokenKind.RIGHT_PAREN, "expected ')' after class bases", code="P126")

        self.expect(TokenKind.COLON, "expected ':' after class declaration", code="P127")
        self.expect(TokenKind.NEWLINE, "expected newline after class declaration", code="P128")
        self.expect(TokenKind.INDENT, "expected an indented class body", code="P129")

        fields: list[ast.FieldDecl] = []
        methods: list[ast.FunctionDecl] = []
        saw_pass = False
        while not self.at(TokenKind.DEDENT, TokenKind.EOF):
            if self.match(TokenKind.NEWLINE):
                continue
            if self.match(TokenKind.PASS):
                self.expect(TokenKind.NEWLINE, "expected newline after pass", code="P130")
                saw_pass = True
                continue

            member_decorators = self.parse_decorators()
            if self.at(TokenKind.DEF):
                methods.append(
                    self.parse_function(
                        member_decorators,
                        owner=name_token.lexeme,
                        is_extern=False,
                    )
                )
                continue
            if member_decorators:
                self.error(
                    "field declarations cannot have decorators",
                    self.current.span,
                    code="P131",
                )

            is_private = self.match(TokenKind.PRIVATE) is not None
            field_name = self.expect(TokenKind.NAME, "expected field or method", code="P132")
            self.expect(TokenKind.COLON, "expected ':' after field name", code="P133")
            annotation = self.parse_type()
            end = self.expect(TokenKind.NEWLINE, "expected newline after field", code="P134").span
            fields.append(
                ast.FieldDecl(
                    field_name.span.merge(end),
                    field_name.lexeme,
                    annotation,
                    is_private,
                )
            )

        end = self.expect(TokenKind.DEDENT, "expected end of class body", code="P135").span
        if not fields and not methods and not saw_pass:
            self.error("class body cannot be empty; use 'pass' explicitly", start.merge(end), code="P136")
        return ast.ClassDecl(
            start.merge(end),
            name_token.lexeme,
            bases,
            fields,
            methods,
            decorators,
            is_abstract,
            type_params,
        )


    def parse_enum(self, decorators: tuple[str, ...]) -> ast.EnumDecl:
        start = self.expect(TokenKind.ENUM).span
        name_token = self.expect(TokenKind.NAME, "expected enum name", code="P083")
        type_params = self.parse_type_params()
        self.expect(TokenKind.COLON, "expected ':' after enum name", code="P084")
        self.expect(TokenKind.NEWLINE, "expected newline after enum declaration", code="P085")
        self.expect(TokenKind.INDENT, "expected an indented enum body", code="P086")

        members: list[ast.EnumMemberDecl] = []
        while not self.at(TokenKind.DEDENT, TokenKind.EOF):
            if self.match(TokenKind.NEWLINE):
                continue
            member = self.expect(TokenKind.NAME, "expected enum member", code="P087")
            value: int | None = None
            if self.match(TokenKind.ASSIGN):
                sign = -1 if self.match(TokenKind.MINUS) else 1
                literal = self.expect(
                    TokenKind.INTEGER,
                    "enum value must be an integer literal",
                    code="P088",
                )
                assert isinstance(literal.value, int)
                value = sign * literal.value
            end = self.expect(TokenKind.NEWLINE, "expected newline after enum member", code="P089")
            members.append(ast.EnumMemberDecl(member.span.merge(end.span), member.lexeme, value))

        end = self.expect(TokenKind.DEDENT, "expected end of enum body", code="P090").span
        if not members:
            self.error("enum body cannot be empty", start.merge(end), code="P091")
        return ast.EnumDecl(start.merge(end), name_token.lexeme, members, decorators, type_params)

    def parse_union(self, decorators: tuple[str, ...]) -> ast.UnionDecl:
        start = self.expect(TokenKind.UNION).span
        name_token = self.expect(TokenKind.NAME, "expected union name", code="P092")
        type_params = self.parse_type_params()
        self.expect(TokenKind.COLON, "expected ':' after union name", code="P093")
        self.expect(TokenKind.NEWLINE, "expected newline after union declaration", code="P094")
        self.expect(TokenKind.INDENT, "expected an indented union body", code="P095")

        fields: list[ast.FieldDecl] = []
        while not self.at(TokenKind.DEDENT, TokenKind.EOF):
            if self.match(TokenKind.NEWLINE):
                continue
            is_private = self.match(TokenKind.PRIVATE) is not None
            field_name = self.expect(TokenKind.NAME, "expected union field", code="P096")
            self.expect(TokenKind.COLON, "expected ':' after union field", code="P097")
            annotation = self.parse_type()
            end = self.expect(TokenKind.NEWLINE, "expected newline after union field", code="P098").span
            fields.append(
                ast.FieldDecl(field_name.span.merge(end), field_name.lexeme, annotation, is_private)
            )

        end = self.expect(TokenKind.DEDENT, "expected end of union body", code="P099").span
        if not fields:
            self.error("union body cannot be empty", start.merge(end), code="P100")
        return ast.UnionDecl(start.merge(end), name_token.lexeme, fields, decorators, type_params)

    def parse_variant(self, decorators: tuple[str, ...]) -> ast.VariantDecl:
        start = self.expect(TokenKind.VARIANT).span
        name_token = self.expect(TokenKind.NAME, "expected variant name", code="P101")
        type_params = self.parse_type_params()
        self.expect(TokenKind.COLON, "expected ':' after variant name", code="P102")
        self.expect(TokenKind.NEWLINE, "expected newline after variant declaration", code="P103")
        self.expect(TokenKind.INDENT, "expected an indented variant body", code="P104")

        cases: list[ast.VariantCaseDecl] = []
        while not self.at(TokenKind.DEDENT, TokenKind.EOF):
            if self.match(TokenKind.NEWLINE):
                continue
            case_name = self.expect(TokenKind.NAME, "expected variant case", code="P105")
            fields: list[ast.FieldDecl] = []
            if self.match(TokenKind.LEFT_PAREN):
                if not self.at(TokenKind.RIGHT_PAREN):
                    while True:
                        field_name = self.expect(
                            TokenKind.NAME,
                            "expected variant payload field",
                            code="P106",
                        )
                        self.expect(TokenKind.COLON, "expected ':' after payload field", code="P107")
                        annotation = self.parse_type()
                        fields.append(
                            ast.FieldDecl(
                                field_name.span.merge(annotation.span),
                                field_name.lexeme,
                                annotation,
                                False,
                            )
                        )
                        if not self.match(TokenKind.COMMA):
                            break
                        if self.at(TokenKind.RIGHT_PAREN):
                            break
                self.expect(TokenKind.RIGHT_PAREN, "expected ')' after variant payload", code="P108")
            end = self.expect(TokenKind.NEWLINE, "expected newline after variant case", code="P109")
            cases.append(ast.VariantCaseDecl(case_name.span.merge(end.span), case_name.lexeme, fields))

        end = self.expect(TokenKind.DEDENT, "expected end of variant body", code="P110").span
        if not cases:
            self.error("variant body cannot be empty", start.merge(end), code="P111")
        return ast.VariantDecl(start.merge(end), name_token.lexeme, cases, decorators, type_params)

    def parse_function(
        self,
        decorators: tuple[str, ...],
        *,
        owner: str | None,
        is_extern: bool,
    ) -> ast.FunctionDecl:
        start = self.expect(TokenKind.DEF).span
        name = self.expect(TokenKind.NAME, "expected function name", code="P034")
        type_params = () if owner is not None or is_extern else self.parse_type_params()
        self.expect(TokenKind.LEFT_PAREN, "expected '(' after function name", code="P035")
        parameters: list[ast.Parameter] = []
        saw_variadic = False
        if not self.at(TokenKind.RIGHT_PAREN):
            while True:
                if self.match(TokenKind.ELLIPSIS):
                    ellipsis = self.tokens[self.index - 1]
                    parameters.append(ast.Parameter(ellipsis.span, "...", None, True))
                    saw_variadic = True
                else:
                    parameter_name = self.expect(TokenKind.NAME, "expected parameter name", code="P036")
                    annotation: ast.TypeNode | None = None
                    if self.match(TokenKind.COLON):
                        annotation = self.parse_type()
                    parameters.append(
                        ast.Parameter(
                            parameter_name.span if annotation is None else parameter_name.span.merge(annotation.span),
                            parameter_name.lexeme,
                            annotation,
                            False,
                        )
                    )
                if saw_variadic and not self.at(TokenKind.RIGHT_PAREN):
                    self.error(
                        "variadic marker must be the final parameter",
                        self.current.span,
                        code="P037",
                    )
                if not self.match(TokenKind.COMMA):
                    break
                if self.at(TokenKind.RIGHT_PAREN):
                    break
        close = self.expect(TokenKind.RIGHT_PAREN, "expected ')' after parameters", code="P038")

        return_type: ast.TypeNode | None = None
        if self.match(TokenKind.ARROW):
            return_type = self.parse_type()

        if is_extern:
            if self.match(TokenKind.COLON):
                body = self.parse_suite_after_colon(start)
                if not (
                    len(body.statements) == 1
                    and isinstance(body.statements[0], ast.PassStmt)
                ):
                    self.error(
                        "external declarations may only use a 'pass' body",
                        body.span,
                        code="P039",
                    )
            else:
                self.expect(TokenKind.NEWLINE, "expected newline after external declaration", code="P040")
            body = None
            end = return_type.span if return_type is not None else close.span
        else:
            colon = self.expect(TokenKind.COLON, "expected ':' before function body", code="P041")
            body = self.parse_suite_after_colon(colon.span)
            end = body.span

        return ast.FunctionDecl(
            start.merge(end),
            name.lexeme,
            parameters,
            return_type,
            body,
            decorators,
            is_extern,
            owner,
            type_params,
        )

    def parse_global(self) -> ast.GlobalDecl:
        is_const = self.match(TokenKind.CONST) is not None
        name = self.expect(TokenKind.NAME, "expected global name", code="P042")
        annotation: ast.TypeNode | None = None
        initializer: ast.Expression | None = None
        if self.match(TokenKind.COLON):
            annotation = self.parse_type()
        if self.match(TokenKind.ASSIGN):
            initializer = self.parse_expression()
        if annotation is None and initializer is None:
            self.error(
                "global declaration needs a type or initializer",
                name.span,
                code="P043",
            )
        end = self.expect(TokenKind.NEWLINE, "expected newline after global", code="P044").span
        return ast.GlobalDecl(
            name.span.merge(end),
            name.lexeme,
            annotation,
            initializer,
            is_const,
        )

    def parse_static_assert(self) -> ast.StaticAssertDecl:
        start = self.expect(TokenKind.NAME).span
        self.expect(TokenKind.LEFT_PAREN, "expected '(' after static_assert", code="P137")
        condition = self.parse_expression()
        message: str | None = None
        if self.match(TokenKind.COMMA):
            message_token = self.expect(
                TokenKind.STRING,
                "static_assert message must be a string literal",
                code="P138",
            )
            message = _decode_string(message_token)
        self.expect(TokenKind.RIGHT_PAREN, "expected ')' after static_assert", code="P139")
        end = self.expect(TokenKind.NEWLINE, "expected newline after static_assert", code="P140")
        return ast.StaticAssertDecl(start.merge(end.span), condition, message)

    def parse_suite_after_colon(self, colon_span: Span) -> ast.Block:
        self.expect(TokenKind.NEWLINE, "expected newline before block", code="P045")
        self.expect(TokenKind.INDENT, "expected an indented block", code="P046")
        statements: list[ast.Statement] = []
        while not self.at(TokenKind.DEDENT, TokenKind.EOF):
            if self.match(TokenKind.NEWLINE):
                continue
            statements.append(self.parse_statement())
        end = self.expect(TokenKind.DEDENT, "expected end of block", code="P047").span
        if not statements:
            self.error(
                "block cannot be empty; use 'pass' explicitly",
                colon_span.merge(end),
                code="P048",
            )
        return ast.Block(colon_span.merge(end), statements)

    def parse_statement(self) -> ast.Statement:
        if self.at(TokenKind.IF):
            return self.parse_if()
        if self.at(TokenKind.WHILE):
            return self.parse_while()
        if self.at(TokenKind.FOR):
            return self.parse_for()
        if self.at(TokenKind.MATCH):
            return self.parse_match()
        if self.at(TokenKind.RETURN):
            start = self.advance().span
            value = None if self.at(TokenKind.NEWLINE) else self.parse_expression()
            end = self.expect(TokenKind.NEWLINE, "expected newline after return", code="P049").span
            return ast.ReturnStmt(start.merge(end), value)
        if self.at(TokenKind.BREAK):
            start = self.advance().span
            end = self.expect(TokenKind.NEWLINE, "expected newline after break", code="P050").span
            return ast.BreakStmt(start.merge(end))
        if self.at(TokenKind.CONTINUE):
            start = self.advance().span
            end = self.expect(TokenKind.NEWLINE, "expected newline after continue", code="P051").span
            return ast.ContinueStmt(start.merge(end))
        if self.at(TokenKind.PASS):
            start = self.advance().span
            end = self.expect(TokenKind.NEWLINE, "expected newline after pass", code="P052").span
            return ast.PassStmt(start.merge(end))
        if self.at(TokenKind.DEFER):
            start = self.advance().span
            expression = self.parse_expression()
            end = self.expect(TokenKind.NEWLINE, "expected newline after defer", code="P053").span
            return ast.DeferStmt(start.merge(end), expression)
        if self.at(TokenKind.WITH):
            return self.parse_with()
        if self.at(TokenKind.UNSAFE):
            start = self.advance().span
            colon = self.expect(TokenKind.COLON, "expected ':' after unsafe", code="P054")
            body = self.parse_suite_after_colon(colon.span)
            return ast.UnsafeStmt(start.merge(body.span), body)

        statement = self.parse_simple_statement()
        self.expect(TokenKind.NEWLINE, "expected newline after statement", code="P055")
        return statement

    def parse_simple_statement(self) -> ast.Statement:
        is_const = self.match(TokenKind.CONST) is not None
        if self.at(TokenKind.NAME) and self.peek().kind is TokenKind.COLON:
            name = self.advance()
            self.advance()
            annotation = self.parse_type()
            initializer = None
            if self.match(TokenKind.ASSIGN):
                initializer = self.parse_expression()
            return ast.VarDeclStmt(
                name.span if initializer is None else name.span.merge(initializer.span),
                name.lexeme,
                annotation,
                initializer,
                is_const,
            )

        if is_const:
            name = self.expect(TokenKind.NAME, "expected constant name", code="P056")
            self.expect(TokenKind.ASSIGN, "inferred constant requires an initializer", code="P057")
            initializer = self.parse_expression()
            return ast.VarDeclStmt(
                name.span.merge(initializer.span),
                name.lexeme,
                None,
                initializer,
                True,
            )

        expression = self.parse_expression()
        assignment = self.match(*_ASSIGNMENT_KINDS.keys())
        if assignment is not None:
            value = self.parse_expression()
            return ast.AssignStmt(
                expression.span.merge(value.span),
                expression,
                _ASSIGNMENT_KINDS[assignment.kind],
                value,
            )
        return ast.ExpressionStmt(expression.span, expression)

    def parse_if(self) -> ast.IfStmt:
        start = self.expect(TokenKind.IF).span
        condition = self.parse_expression()
        colon = self.expect(TokenKind.COLON, "expected ':' after condition", code="P058")
        body = self.parse_suite_after_colon(colon.span)
        branches = [ast.IfBranch(condition.span.merge(body.span), condition, body)]

        while self.match(TokenKind.ELIF):
            branch_start = self.tokens[self.index - 1].span
            branch_condition = self.parse_expression()
            branch_colon = self.expect(TokenKind.COLON, "expected ':' after condition", code="P059")
            branch_body = self.parse_suite_after_colon(branch_colon.span)
            branches.append(
                ast.IfBranch(
                    branch_start.merge(branch_body.span),
                    branch_condition,
                    branch_body,
                )
            )

        else_body: ast.Block | None = None
        if self.match(TokenKind.ELSE):
            else_start = self.tokens[self.index - 1].span
            colon = self.expect(TokenKind.COLON, "expected ':' after else", code="P060")
            else_body = self.parse_suite_after_colon(colon.span)
            end = else_start.merge(else_body.span)
        else:
            end = branches[-1].span

        return ast.IfStmt(start.merge(end), branches, else_body)

    def parse_while(self) -> ast.WhileStmt:
        start = self.expect(TokenKind.WHILE).span
        condition = self.parse_expression()
        colon = self.expect(TokenKind.COLON, "expected ':' after while condition", code="P061")
        body = self.parse_suite_after_colon(colon.span)
        return ast.WhileStmt(start.merge(body.span), condition, body)

    def parse_with(self) -> ast.WithStmt:
        start = self.expect(TokenKind.WITH).span
        context = self.parse_expression()
        self.expect(TokenKind.AS, "expected 'as' after with expression", code="P090")
        name = self.expect(TokenKind.NAME, "expected name after 'as'", code="P091").lexeme
        colon = self.expect(TokenKind.COLON, "expected ':' after with binding", code="P092")
        body = self.parse_suite_after_colon(colon.span)
        return ast.WithStmt(start.merge(body.span), context, name, body)

    def parse_for(self) -> ast.Statement:
        start = self.expect(TokenKind.FOR).span
        saved_index = self.index
        annotation: ast.TypeNode | None = None
        if self.at(TokenKind.NAME):
            name = self.advance()
            if self.match(TokenKind.COLON):
                annotation = self.parse_type()
            if self.match(TokenKind.IN):
                is_comptime = self.match(TokenKind.COMPTIME) is not None
                iterable = self.parse_expression()
                colon = self.expect(TokenKind.COLON, "expected ':' after for iterable", code="P062")
                body = self.parse_suite_after_colon(colon.span)
                return ast.ForEachStmt(
                    start.merge(body.span),
                    name.lexeme,
                    annotation,
                    iterable,
                    body,
                    is_comptime,
                )
        self.index = saved_index

        initializer: ast.Statement | None = None
        if not self.at(TokenKind.SEMICOLON):
            initializer = self.parse_simple_statement()
        self.expect(TokenKind.SEMICOLON, "expected ';' in C-style for loop", code="P063")

        condition: ast.Expression | None = None
        if not self.at(TokenKind.SEMICOLON):
            condition = self.parse_expression()
        self.expect(TokenKind.SEMICOLON, "expected second ';' in C-style for loop", code="P064")

        update: ast.Statement | None = None
        if not self.at(TokenKind.COLON):
            update = self.parse_simple_statement()
        colon = self.expect(TokenKind.COLON, "expected ':' after for clause", code="P065")
        body = self.parse_suite_after_colon(colon.span)
        return ast.ForCStmt(start.merge(body.span), initializer, condition, update, body)

    def parse_match(self) -> ast.MatchStmt:
        start = self.expect(TokenKind.MATCH).span
        value = self.parse_expression()
        self.expect(TokenKind.COLON, "expected ':' after match value", code="P112")
        self.expect(TokenKind.NEWLINE, "expected newline after match", code="P113")
        self.expect(TokenKind.INDENT, "expected an indented match body", code="P114")

        cases: list[ast.MatchCase] = []
        while not self.at(TokenKind.DEDENT, TokenKind.EOF):
            if self.match(TokenKind.NEWLINE):
                continue
            case_start = self.expect(TokenKind.CASE, "expected 'case' in match", code="P115").span
            pattern_start = self.current.span
            if self.at(TokenKind.NAME) and self.current.lexeme == "_":
                wildcard = self.advance()
                pattern = ast.MatchPattern(wildcard.span, None, [], True)
            else:
                pattern_token = self.match(TokenKind.NAME, TokenKind.NONE)
                if pattern_token is None:
                    self.error("expected match pattern", self.current.span, code="P116")
                parts = [pattern_token.lexeme]
                while self.match(TokenKind.DOT):
                    parts.append(
                        self.expect(TokenKind.NAME, "expected pattern name after '.'", code="P117").lexeme
                    )
                bindings: list[str] = []
                pattern_end = self.tokens[self.index - 1].span
                if self.match(TokenKind.LEFT_PAREN):
                    if not self.at(TokenKind.RIGHT_PAREN):
                        while True:
                            binding = self.expect(
                                TokenKind.NAME,
                                "pattern bindings must be names",
                                code="P118",
                            )
                            bindings.append(binding.lexeme)
                            pattern_end = binding.span
                            if not self.match(TokenKind.COMMA):
                                break
                            if self.at(TokenKind.RIGHT_PAREN):
                                break
                    close = self.expect(TokenKind.RIGHT_PAREN, "expected ')' after pattern", code="P119")
                    pattern_end = close.span
                pattern = ast.MatchPattern(
                    pattern_start.merge(pattern_end),
                    tuple(parts),
                    bindings,
                    False,
                )
            colon = self.expect(TokenKind.COLON, "expected ':' after case pattern", code="P120")
            body = self.parse_suite_after_colon(colon.span)
            cases.append(ast.MatchCase(case_start.merge(body.span), pattern, body))

        end = self.expect(TokenKind.DEDENT, "expected end of match body", code="P121").span
        if not cases:
            self.error("match body cannot be empty", start.merge(end), code="P122")
        return ast.MatchStmt(start.merge(end), value, cases)

    def parse_type(self) -> ast.TypeNode:
        start = self.current.span
        wrappers: list[str] = []
        while True:
            if self.match(TokenKind.STAR):
                wrappers.append("pointer")
                continue
            if self.match(TokenKind.AMPERSAND):
                wrappers.append("reference")
                continue
            if self.at(TokenKind.LEFT_BRACKET) and self.peek().kind is TokenKind.RIGHT_BRACKET:
                self.advance()
                self.advance()
                wrappers.append("slice")
                continue
            break

        is_const = self.match(TokenKind.CONST) is not None

        if self.match(TokenKind.DYN):
            if wrappers != ["reference"]:
                self.error(
                    "dynamic interface types must use '&dyn Interface'",
                    start,
                    code="P141",
                )
            interface_start = self.current.span
            interface_name = self.expect(TokenKind.NAME, "expected interface name after 'dyn'", code="P142")
            parts = [interface_name.lexeme]
            while self.match(TokenKind.DOT):
                parts.append(
                    self.expect(TokenKind.NAME, "expected interface name after '.'", code="P143").lexeme
                )
            interface = ast.NamedTypeNode(interface_start.merge(interface_name.span), ".".join(parts))
            return ast.DynTypeNode(start.merge(interface.span), interface, is_const)

        if self.match(TokenKind.DEF):
            self.expect(TokenKind.LEFT_PAREN, "expected '(' after 'def' in function type", code="P160")
            parameters: list[ast.TypeNode] = []
            if not self.at(TokenKind.RIGHT_PAREN):
                while True:
                    parameters.append(self.parse_type())
                    if not self.match(TokenKind.COMMA):
                        break
                    if self.at(TokenKind.RIGHT_PAREN):
                        break
            close_paren = self.expect(
                TokenKind.RIGHT_PAREN,
                "expected ')' after function type parameters",
                code="P161",
            )
            return_type: ast.TypeNode | None = None
            if self.match(TokenKind.ARROW):
                return_type = self.parse_type()
            result: ast.TypeNode = ast.FunctionTypeNode(
                start.merge((return_type.span if return_type is not None else close_paren.span)),
                parameters,
                return_type,
            )
            if is_const:
                result = ast.ConstTypeNode(start.merge(result.span), result)
            for wrapper in reversed(wrappers):
                if wrapper == "pointer":
                    result = ast.PointerTypeNode(start.merge(result.span), result)
                elif wrapper == "reference":
                    result = ast.ReferenceTypeNode(start.merge(result.span), result)
                else:
                    result = ast.SliceTypeNode(start.merge(result.span), result)
            return result

        name_token = self.expect(TokenKind.NAME, "expected type name", code="P066")
        parts = [name_token.lexeme]
        while self.match(TokenKind.DOT):
            parts.append(self.expect(TokenKind.NAME, "expected type name after '.'", code="P067").lexeme)
        result: ast.TypeNode = ast.NamedTypeNode(start.merge(name_token.span), ".".join(parts))

        if self.at(TokenKind.LEFT_BRACKET) and not (
            self.peek().kind is TokenKind.INTEGER
            and self.peek(2).kind is TokenKind.RIGHT_BRACKET
        ):
            self.advance()
            arguments: list[ast.TypeNode] = []
            if not self.at(TokenKind.RIGHT_BRACKET):
                while True:
                    arguments.append(self.parse_type())
                    if not self.match(TokenKind.COMMA):
                        break
                    if self.at(TokenKind.RIGHT_BRACKET):
                        break
            close = self.expect(TokenKind.RIGHT_BRACKET, "expected ']' after generic arguments", code="P123")
            result = ast.GenericTypeNode(result.span.merge(close.span), result, arguments)

        if is_const:
            result = ast.ConstTypeNode(start.merge(result.span), result)

        while True:
            if self.match(TokenKind.STAR):
                result = ast.PointerTypeNode(result.span.merge(self.tokens[self.index - 1].span), result)
                continue
            if self.match(TokenKind.LEFT_BRACKET):
                left = self.tokens[self.index - 1]
                length = self.expect(TokenKind.INTEGER, "array length must be an integer literal", code="P068")
                close = self.expect(TokenKind.RIGHT_BRACKET, "expected ']' after array length", code="P069")
                assert isinstance(length.value, int)
                if length.value <= 0:
                    self.error("array length must be positive", length.span, code="P070")
                result = ast.ArrayTypeNode(left.span.merge(close.span), result, length.value)
                continue
            break

        for wrapper in reversed(wrappers):
            if wrapper == "pointer":
                result = ast.PointerTypeNode(start.merge(result.span), result)
            elif wrapper == "reference":
                result = ast.ReferenceTypeNode(start.merge(result.span), result)
            else:
                result = ast.SliceTypeNode(start.merge(result.span), result)
        return result

    def parse_expression(self, minimum_precedence: int = 0) -> ast.Expression:
        left = self.parse_unary()
        while True:
            is_not_in = (
                self.current.kind is TokenKind.NOT
                and self.peek().kind is TokenKind.IN
            )
            binary = (6, "not in") if is_not_in else _BINARY_PRECEDENCE.get(self.current.kind)
            if binary is None:
                break
            precedence, operator = binary
            if precedence < minimum_precedence:
                break
            self.advance()
            if is_not_in:
                self.advance()
            right = self.parse_expression(precedence + 1)
            left = ast.BinaryExpr(left.span.merge(right.span), left, operator, right)
        return left

    def parse_unary(self) -> ast.Expression:
        if self.at(
            TokenKind.PLUS,
            TokenKind.MINUS,
            TokenKind.NOT,
            TokenKind.BANG,
            TokenKind.TILDE,
            TokenKind.AMPERSAND,
            TokenKind.STAR,
        ):
            token = self.advance()
            operator = "not" if token.kind in (TokenKind.NOT, TokenKind.BANG) else token.lexeme
            operand = self.parse_unary()
            return ast.UnaryExpr(token.span.merge(operand.span), operator, operand)
        return self.parse_postfix()

    def parse_postfix(self) -> ast.Expression:
        expression = self.parse_primary()
        while True:
            if self.match(TokenKind.LEFT_PAREN):
                arguments: list[ast.CallArgument] = []
                if not self.at(TokenKind.RIGHT_PAREN):
                    while True:
                        argument_start = self.current.span
                        argument_name: str | None = None
                        if self.at(TokenKind.NAME) and self.peek().kind is TokenKind.ASSIGN:
                            argument_name = self.advance().lexeme
                            self.advance()
                        value = self.parse_expression()
                        arguments.append(
                            ast.CallArgument(argument_start.merge(value.span), value, argument_name)
                        )
                        if not self.match(TokenKind.COMMA):
                            break
                        if self.at(TokenKind.RIGHT_PAREN):
                            break
                close = self.expect(TokenKind.RIGHT_PAREN, "expected ')' after arguments", code="P071")
                expression = ast.CallExpr(
                    expression.span.merge(close.span),
                    expression,
                    arguments,
                )
                continue

            if self.match(TokenKind.DOT):
                name = self.match(TokenKind.NAME, TokenKind.UNION)
                if name is None:
                    self.error(
                        "expected member name after '.'",
                        self.current.span,
                        code="P072",
                    )
                expression = ast.AttributeExpr(expression.span.merge(name.span), expression, name.lexeme)
                continue

            if self.match(TokenKind.LEFT_BRACKET):
                if self.match(TokenKind.COLON):
                    start_expr = None
                    stop_expr = None if self.at(TokenKind.RIGHT_BRACKET) else self.parse_expression()
                    close = self.expect(TokenKind.RIGHT_BRACKET, "expected ']' after slice", code="P073")
                    expression = ast.SliceExpr(
                        expression.span.merge(close.span), expression, start_expr, stop_expr
                    )
                    continue

                first = self.parse_expression()
                if self.match(TokenKind.COLON):
                    stop_expr = None if self.at(TokenKind.RIGHT_BRACKET) else self.parse_expression()
                    close = self.expect(TokenKind.RIGHT_BRACKET, "expected ']' after slice", code="P074")
                    expression = ast.SliceExpr(
                        expression.span.merge(close.span), expression, first, stop_expr
                    )
                else:
                    close = self.expect(TokenKind.RIGHT_BRACKET, "expected ']' after index", code="P075")
                    expression = ast.IndexExpr(expression.span.merge(close.span), expression, first)
                continue

            if self.match(TokenKind.QUESTION):
                question = self.tokens[self.index - 1]
                expression = ast.PropagateExpr(expression.span.merge(question.span), expression)
                continue
            break
        return expression

    def parse_primary(self) -> ast.Expression:
        token = self.current
        if self.match(TokenKind.INTEGER):
            assert isinstance(token.value, int)
            return ast.LiteralExpr(token.span, token.value, "integer", token.lexeme)
        if self.match(TokenKind.FLOAT):
            assert isinstance(token.value, float)
            return ast.LiteralExpr(token.span, token.value, "float", token.lexeme)
        if self.match(TokenKind.STRING):
            return ast.LiteralExpr(token.span, _decode_string(token), "string", token.lexeme)
        if self.match(TokenKind.FSTRING):
            return self.parse_fstring(token)
        if self.match(TokenKind.CHAR):
            return ast.LiteralExpr(token.span, _decode_string(token), "char", token.lexeme)
        if self.match(TokenKind.TRUE):
            return ast.LiteralExpr(token.span, True, "bool", token.lexeme)
        if self.match(TokenKind.FALSE):
            return ast.LiteralExpr(token.span, False, "bool", token.lexeme)
        if self.match(TokenKind.NULL):
            return ast.LiteralExpr(token.span, None, "null", token.lexeme)
        if self.match(TokenKind.NONE):
            return ast.NoneExpr(token.span)

        if self.at(TokenKind.NAME) and token.lexeme in ("cast", "alloc") and self.peek().kind is TokenKind.LEFT_BRACKET:
            builtin = self.advance()
            self.advance()
            target_type = self.parse_type()
            self.expect(TokenKind.RIGHT_BRACKET, "expected ']' after builtin type", code="P076")
            self.expect(TokenKind.LEFT_PAREN, "expected '(' after typed builtin", code="P077")
            if builtin.lexeme == "cast":
                value = self.parse_expression()
                close = self.expect(TokenKind.RIGHT_PAREN, "expected ')' after cast", code="P078")
                return ast.CastExpr(builtin.span.merge(close.span), target_type, value)

            count = None if self.at(TokenKind.RIGHT_PAREN) else self.parse_expression()
            close = self.expect(TokenKind.RIGHT_PAREN, "expected ')' after allocation", code="P079")
            return ast.AllocExpr(builtin.span.merge(close.span), target_type, count)

        if self._looks_like_generic_call():
            name_token = self.advance()
            self.expect(TokenKind.LEFT_BRACKET)
            type_arguments: list[ast.TypeNode] = []
            if not self.at(TokenKind.RIGHT_BRACKET):
                while True:
                    type_arguments.append(self.parse_type())
                    if not self.match(TokenKind.COMMA):
                        break
                    if self.at(TokenKind.RIGHT_BRACKET):
                        break
            self.expect(TokenKind.RIGHT_BRACKET, "expected ']' after type arguments", code="P145")
            self.expect(TokenKind.LEFT_PAREN, "expected '(' after type arguments", code="P146")
            arguments: list[ast.CallArgument] = []
            if not self.at(TokenKind.RIGHT_PAREN):
                while True:
                    argument_start = self.current.span
                    argument_name: str | None = None
                    if self.at(TokenKind.NAME) and self.peek().kind is TokenKind.ASSIGN:
                        argument_name = self.advance().lexeme
                        self.advance()
                    value = self.parse_expression()
                    arguments.append(
                        ast.CallArgument(argument_start.merge(value.span), value, argument_name)
                    )
                    if not self.match(TokenKind.COMMA):
                        break
                    if self.at(TokenKind.RIGHT_PAREN):
                        break
            close = self.expect(TokenKind.RIGHT_PAREN, "expected ')' after arguments", code="P071")
            return ast.CallExpr(
                name_token.span.merge(close.span),
                ast.NameExpr(name_token.span, name_token.lexeme),
                arguments,
                type_arguments,
            )

        if self.match(TokenKind.NAME):
            return ast.NameExpr(token.span, token.lexeme)

        if self.match(TokenKind.LEFT_PAREN):
            if self.match(TokenKind.RIGHT_PAREN):
                return ast.TupleLiteralExpr(token.span.merge(self.tokens[self.index - 1].span), [])

            first = self.parse_expression()
            if self.match(TokenKind.COMMA):
                tuple_elements = [first]
                while not self.at(TokenKind.RIGHT_PAREN):
                    tuple_elements.append(self.parse_expression())
                    if not self.match(TokenKind.COMMA):
                        break
                close = self.expect(TokenKind.RIGHT_PAREN, "expected ')' after tuple literal", code="P080")
                return ast.TupleLiteralExpr(token.span.merge(close.span), tuple_elements)

            close = self.expect(TokenKind.RIGHT_PAREN, "expected ')'", code="P080")
            first.span = token.span.merge(close.span)
            return first

        if self.match(TokenKind.LEFT_BRACKET):
            elements: list[ast.Expression] = []
            if not self.at(TokenKind.RIGHT_BRACKET):
                while True:
                    elements.append(self.parse_expression())
                    if not self.match(TokenKind.COMMA):
                        break
                    if self.at(TokenKind.RIGHT_BRACKET):
                        break
            close = self.expect(TokenKind.RIGHT_BRACKET, "expected ']' after list literal", code="P081")
            return ast.ListLiteralExpr(token.span.merge(close.span), elements)

        if self.match(TokenKind.LEFT_BRACE):
            if self.match(TokenKind.RIGHT_BRACE):
                return ast.MapLiteralExpr(
                    token.span.merge(self.tokens[self.index - 1].span),
                    [],
                )

            first = self.parse_expression()
            if self.match(TokenKind.COLON):
                value = self.parse_expression()
                entries = [ast.MapEntry(first.span.merge(value.span), first, value)]
                while self.match(TokenKind.COMMA):
                    if self.at(TokenKind.RIGHT_BRACE):
                        break
                    key = self.parse_expression()
                    if not self.match(TokenKind.COLON):
                        self.error(
                            "map literal entries require ':' between key and value",
                            key.span,
                            code="P144",
                        )
                    entry_value = self.parse_expression()
                    entries.append(
                        ast.MapEntry(
                            key.span.merge(entry_value.span),
                            key,
                            entry_value,
                        )
                    )
                close = self.expect(
                    TokenKind.RIGHT_BRACE,
                    "expected '}' after map literal",
                    code="P145",
                )
                return ast.MapLiteralExpr(token.span.merge(close.span), entries)

            elements = [first]
            while self.match(TokenKind.COMMA):
                if self.at(TokenKind.RIGHT_BRACE):
                    break
                element = self.parse_expression()
                if self.at(TokenKind.COLON):
                    self.error(
                        "cannot mix set elements and map entries in one literal",
                        element.span.merge(self.current.span),
                        code="P146",
                    )
                elements.append(element)
            close = self.expect(
                TokenKind.RIGHT_BRACE,
                "expected '}' after set literal",
                code="P147",
            )
            return ast.SetLiteralExpr(token.span.merge(close.span), elements)

        self.error("expected an expression", token.span, code="P082")

    def parse_fstring(self, token: Token) -> ast.FStringExpr:
        if len(token.lexeme) < 3:
            self.error("invalid f-string literal", token.span, code="P083")
        quote = token.lexeme[1]
        content = token.lexeme[2:-1]
        parts: list[ast.FStringPart] = []
        literal_start = 0
        index = 0

        def append_literal(until: int) -> None:
            nonlocal literal_start
            if until <= literal_start:
                literal_start = until
                return
            raw = content[literal_start:until]
            parts.append(ast.FStringText(token.span, _decode_string_fragment(raw, quote)))
            literal_start = until

        while index < len(content):
            character = content[index]
            if character == "{":
                if index + 1 < len(content) and content[index + 1] == "{":
                    append_literal(index)
                    parts.append(ast.FStringText(token.span, "{"))
                    index += 2
                    literal_start = index
                    continue
                append_literal(index)
                expression_start = index + 1
                expression_end, format_spec, close = self._scan_fstring_expression(
                    content,
                    expression_start,
                    token,
                )
                expression_text = content[expression_start:expression_end].strip()
                if not expression_text:
                    self.error("empty f-string expression", token.span, code="P084")
                expression = self._parse_fstring_expression(
                    expression_text,
                    token,
                    expression_start + len(content[expression_start:expression_end]) - len(content[expression_start:expression_end].lstrip()),
                )
                parts.append(ast.FStringExpression(expression.span, expression, format_spec))
                index = close + 1
                literal_start = index
                continue
            if character == "}":
                if index + 1 < len(content) and content[index + 1] == "}":
                    append_literal(index)
                    parts.append(ast.FStringText(token.span, "}"))
                    index += 2
                    literal_start = index
                    continue
                self.error("single '}' is not allowed in an f-string", token.span, code="P085")
            index += 1

        append_literal(len(content))
        return ast.FStringExpr(token.span, parts)

    def _scan_fstring_expression(
        self,
        content: str,
        start: int,
        token: Token,
    ) -> tuple[int, str | None, int]:
        index = start
        brackets: list[str] = []
        format_start: int | None = None
        while index < len(content):
            character = content[index]
            if character in ('"', "'"):
                index = _skip_quoted_text(content, index)
                continue
            if character in "([{":
                if format_start is not None and not brackets:
                    self.error(
                        "nested replacement fields are not supported in f-string format specs",
                        token.span,
                        code="P086",
                    )
                brackets.append({"(": ")", "[": "]", "{": "}"}[character])
                index += 1
                continue
            if character in ")]}":
                if brackets:
                    if character == brackets[-1]:
                        brackets.pop()
                    index += 1
                    continue
                if character == "}":
                    if format_start is None:
                        return index, None, index
                    spec = content[format_start + 1 : index].strip()
                    return format_start, spec, index
                index += 1
                continue
            if character == ":" and not brackets and format_start is None:
                format_start = index
                index += 1
                continue
            index += 1
        self.error("unterminated f-string expression", token.span, code="P087")

    def _parse_fstring_expression(
        self,
        expression_text: str,
        token: Token,
        content_column: int,
    ) -> ast.Expression:
        try:
            tokens = lex(expression_text, self.path)
        except CompilationFailed as error:
            note = error.diagnostics[0].message if error.diagnostics else None
            self.error("invalid f-string expression", token.span, code="P088", note=note)

        parser = Parser(tokens, expression_text, self.path)
        try:
            expression = parser.parse_expression()
            parser.match(TokenKind.NEWLINE)
            if not parser.at(TokenKind.EOF):
                parser.error("expected end of f-string expression", parser.current.span, code="P089")
        except _ParseAbort:
            note = parser.diagnostics.items[0].message if parser.diagnostics.items else None
            self.error("invalid f-string expression", token.span, code="P088", note=note)
        if parser.diagnostics.has_errors:
            note = parser.diagnostics.items[0].message if parser.diagnostics.items else None
            self.error("invalid f-string expression", token.span, code="P088", note=note)
        self._offset_expression_spans(
            expression,
            token.span.start_line,
            token.span.start_column + 2 + content_column,
        )
        return expression

    def _offset_expression_spans(
        self,
        expression: ast.Expression,
        line: int,
        column: int,
    ) -> None:
        expression.span = _offset_span(expression.span, line, column)
        match expression:
            case ast.UnaryExpr(operand=operand):
                self._offset_expression_spans(operand, line, column)
            case ast.BinaryExpr(left=left, right=right):
                self._offset_expression_spans(left, line, column)
                self._offset_expression_spans(right, line, column)
            case ast.AttributeExpr(value=value):
                self._offset_expression_spans(value, line, column)
            case ast.IndexExpr(value=value, index=index):
                self._offset_expression_spans(value, line, column)
                self._offset_expression_spans(index, line, column)
            case ast.SliceExpr(value=value, start=start_expr, stop=stop_expr):
                self._offset_expression_spans(value, line, column)
                if start_expr is not None:
                    self._offset_expression_spans(start_expr, line, column)
                if stop_expr is not None:
                    self._offset_expression_spans(stop_expr, line, column)
            case ast.CallExpr(callee=callee, arguments=arguments):
                self._offset_expression_spans(callee, line, column)
                for argument in arguments:
                    argument.span = _offset_span(argument.span, line, column)
                    self._offset_expression_spans(argument.value, line, column)
            case ast.PropagateExpr(value=value):
                self._offset_expression_spans(value, line, column)
            case ast.ListLiteralExpr(elements=elements) | ast.TupleLiteralExpr(elements=elements):
                for element in elements:
                    self._offset_expression_spans(element, line, column)
            case ast.SetLiteralExpr(elements=elements):
                for element in elements:
                    self._offset_expression_spans(element, line, column)
            case ast.MapLiteralExpr(entries=entries):
                for entry in entries:
                    entry.span = _offset_span(entry.span, line, column)
                    self._offset_expression_spans(entry.key, line, column)
                    self._offset_expression_spans(entry.value, line, column)
            case ast.CastExpr(target_type=target_type, value=value):
                target_type.span = _offset_span(target_type.span, line, column)
                self._offset_expression_spans(value, line, column)
            case ast.AllocExpr(element_type=element_type, count=count):
                element_type.span = _offset_span(element_type.span, line, column)
                if count is not None:
                    self._offset_expression_spans(count, line, column)
            case ast.FStringExpr(parts=parts):
                for part in parts:
                    part.span = _offset_span(part.span, line, column)
                    if isinstance(part, ast.FStringExpression):
                        self._offset_expression_spans(part.expression, line, column)
            case _:
                return


def _decode_string(token: Token) -> str:
    try:
        value = python_ast.literal_eval(token.lexeme)
    except (SyntaxError, ValueError):
        return token.lexeme[1:-1]
    return str(value)


def _decode_string_fragment(raw: str, quote: str) -> str:
    try:
        value = python_ast.literal_eval(f"{quote}{raw}{quote}")
    except (SyntaxError, ValueError):
        return raw
    return str(value)


def _skip_quoted_text(text: str, start: int) -> int:
    quote = text[start]
    index = start + 1
    escaped = False
    while index < len(text):
        character = text[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\":
            escaped = True
            index += 1
            continue
        if character == quote:
            return index + 1
        index += 1
    return index


def _offset_span(span: Span, line: int, column: int) -> Span:
    if span.start_line == 1:
        start_line = line
        start_column = column + span.start_column - 1
    else:
        start_line = line + span.start_line - 1
        start_column = span.start_column
    if span.end_line == 1:
        end_line = line
        end_column = column + span.end_column - 1
    else:
        end_line = line + span.end_line - 1
        end_column = span.end_column
    return Span(span.path, start_line, start_column, end_line, end_column)


def parse(tokens: list[Token], source: str, path: Path) -> ast.Module:
    return Parser(tokens, source, path).parse()
