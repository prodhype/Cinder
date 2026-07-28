from __future__ import annotations

from pathlib import Path

import pytest

from cinder.compiler import Compiler
from cinder.diagnostics import CompilationFailed


def compile_source(source: str) -> str:
    return Compiler().compile_source(source, Path("milestone.ci")).c_source


def test_enum_union_variant_and_result_codegen_is_explicit() -> None:
    generated = compile_source(
        "enum Error:\n"
        "    invalid\n"
        "    missing = 4\n"
        "\n"
        "union Number:\n"
        "    integer: i32\n"
        "    real: f64\n"
        "\n"
        "variant Token:\n"
        "    Integer(value: i32)\n"
        "    End\n"
        "\n"
        "def parse(value: i32) -> Result[Token, Error]:\n"
        "    if value < 0:\n"
        "        return Err(Error.invalid)\n"
        "    return Ok(Token.Integer(value))\n"
        "\n"
        "def main() -> i32:\n"
        "    number = Number(integer=7)\n"
        "    result = parse(number.integer)\n"
        "    match result:\n"
        "        case Ok(token):\n"
        "            match token:\n"
        "                case Integer(value):\n"
        "                    return value - 7\n"
        "                case End:\n"
        "                    return 0\n"
        "        case Err(error):\n"
        "            return cast[i32](error)\n"
        "    return 0\n"
    )
    assert "typedef enum Error" in generated
    assert "union Number" in generated
    assert "typedef enum Token_Tag" in generated
    assert "struct Token" in generated
    assert "typedef struct CinderResult_n_Token_n_Error" in generated
    assert ".tag = Token_Tag_Integer" in generated
    assert ".integer = 7" in generated
    assert 'cinder_panic("invalid tag in exhaustive match")' in generated


def test_result_propagation_lowers_to_an_ordinary_early_return() -> None:
    generated = compile_source(
        "enum Error:\n"
        "    invalid\n"
        "\n"
        "def parse(value: i32) -> Result[i32, Error]:\n"
        "    if value < 0:\n"
        "        return Err(Error.invalid)\n"
        "    return Ok(value)\n"
        "\n"
        "def increment(value: i32) -> Result[i32, Error]:\n"
        "    parsed = parse(value)?\n"
        "    return Ok(parsed + 1)\n"
    )
    assert "__cinder_result_" in generated
    assert ".tag == CinderResult_i32_n_Error_Tag_Err" in generated
    assert "return ((CinderResult_i32_n_Error)" in generated
    assert ".data.ok" in generated


def test_match_must_be_exhaustive() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "variant Token:\n"
            "    Integer(value: i32)\n"
            "    End\n"
            "\n"
            "def consume(token: Token) -> i32:\n"
            "    match token:\n"
            "        case Integer(value):\n"
            "            return value\n"
            "    return 0\n"
        )
    assert "non-exhaustive match; missing End" in str(captured.value)


def test_variant_pattern_payload_arity_is_checked() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "variant Pair:\n"
            "    Values(left: i32, right: i32)\n"
            "\n"
            "def consume(pair: Pair) -> i32:\n"
            "    match pair:\n"
            "        case Values(value):\n"
            "            return value\n"
            "    return 0\n"
        )
    assert "expects 2 bindings, got 1" in str(captured.value)


def test_result_propagation_requires_a_result_return_type() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "enum Error:\n"
            "    invalid\n"
            "\n"
            "def parse() -> Result[i32, Error]:\n"
            "    return Ok(1)\n"
            "\n"
            "def consume() -> i32:\n"
            "    return parse()?\n"
        )
    assert "a function using '?' must return Result" in str(captured.value)


def test_enum_aliases_are_rejected_for_distinguishable_matching() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "enum State:\n"
            "    ready = 1\n"
            "    running = 1\n"
        )
    assert "enum value 1 is already used by 'ready'" in str(captured.value)


def test_void_result_payloads_compile() -> None:
    generated = compile_source(
        "enum Error:\n"
        "    failed\n"
        "\n"
        "def validate(ok: bool) -> Result[void, Error]:\n"
        "    if not ok:\n"
        "        return Err(Error.failed)\n"
        "    return Ok()\n"
        "\n"
        "def consume(ok: bool) -> Result[i32, Error]:\n"
        "    validate(ok)?\n"
        "    return Ok(42)\n"
    )
    assert "CinderResult_void_n_Error" in generated
    assert "((void)0)" in generated


def test_result_propagation_requires_compatible_error_types() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "enum SourceError:\n"
            "    failed\n"
            "\n"
            "enum TargetError:\n"
            "    failed\n"
            "\n"
            "def source() -> Result[i32, SourceError]:\n"
            "    return Err(SourceError.failed)\n"
            "\n"
            "def consume() -> Result[i32, TargetError]:\n"
            "    return Ok(source()?)\n"
        )
    assert "cannot propagate SourceError" in str(captured.value)


def test_result_void_success_and_propagation_codegen() -> None:
    generated = compile_source(
        "enum Error:\n"
        "    invalid\n"
        "\n"
        "def validate(value: i32) -> Result[void, Error]:\n"
        "    if value < 0:\n"
        "        return Err(Error.invalid)\n"
        "    return Ok()\n"
        "\n"
        "def consume(value: i32) -> Result[i32, Error]:\n"
        "    validate(value)?\n"
        "    return Ok(value)\n"
    )
    assert "CinderResult_void_n_Error" in generated
    assert "CinderResult_void_n_Error_Tag_Ok" in generated
    void_definition = generated.split(
        "\nstruct CinderResult_void_n_Error\n{", 1
    )[1].split("\n};", 1)[0]
    assert " ok;" not in void_definition


def test_result_propagation_preserves_deferred_cleanup_on_error() -> None:
    generated = compile_source(
        "enum Error:\n"
        "    invalid\n"
        "\n"
        "def parse() -> Result[i32, Error]:\n"
        "    return Err(Error.invalid)\n"
        "\n"
        "def consume() -> Result[i32, Error]:\n"
        "    allocation = alloc[i32](1)\n"
        "    defer free(allocation)\n"
        "    value = parse()?\n"
        "    return Ok(value)\n"
    )
    tag_test = generated.index(".tag == CinderResult_i32_n_Error_Tag_Err")
    cleanup = generated.index("free(allocation);", tag_test)
    propagated_return = generated.index("return __cinder_propagate_", cleanup)
    assert tag_test < cleanup < propagated_return


def test_propagation_rejects_short_circuit_right_operand() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "enum Error:\n"
            "    invalid\n"
            "\n"
            "def parse() -> Result[bool, Error]:\n"
            "    return Ok(true)\n"
            "\n"
            "def consume(enabled: bool) -> Result[bool, Error]:\n"
            "    return Ok(enabled and parse()?)\n"
        )
    assert "right side of 'and'" in str(captured.value)



def test_match_rejects_unknown_qualified_pattern_owner() -> None:
    with pytest.raises(CompilationFailed) as captured:
        compile_source(
            "variant Token:\n"
            "    Integer(value: i32)\n"
            "\n"
            "def consume(token: Token) -> i32:\n"
            "    match token:\n"
            "        case nonsense.Token.Integer(value):\n"
            "            return value\n"
        )
    assert "unknown pattern owner 'nonsense.Token'" in str(captured.value)
