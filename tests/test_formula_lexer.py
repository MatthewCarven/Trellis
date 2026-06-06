"""Tests for trellis.formula.lexer."""

import pytest

from trellis.formula.errors import ParseError
from trellis.formula.lexer import Token, TokenKind, tokenize


def toks(src):
    """Helper: tokenize and return list of (kind, value) tuples (positions omitted)."""
    return [(t.kind, t.value) for t in tokenize(src)]


# --- Whitespace & EOF --------------------------------------------------


def test_empty_source_yields_only_eof():
    result = list(tokenize(""))
    assert len(result) == 1
    assert result[0].kind == TokenKind.EOF


def test_whitespace_only_yields_only_eof():
    assert toks("  \t\n  ") == [(TokenKind.EOF, "")]


def test_eof_always_at_end():
    result = list(tokenize("42"))
    assert result[-1].kind == TokenKind.EOF


# --- Numbers ----------------------------------------------------------


def test_integer():
    assert toks("42") == [(TokenKind.NUMBER, 42), (TokenKind.EOF, "")]


def test_zero():
    assert toks("0") == [(TokenKind.NUMBER, 0), (TokenKind.EOF, "")]


def test_decimal():
    assert toks("3.14") == [(TokenKind.NUMBER, 3.14), (TokenKind.EOF, "")]


def test_leading_dot_decimal():
    assert toks(".5") == [(TokenKind.NUMBER, 0.5), (TokenKind.EOF, "")]


def test_trailing_dot_decimal():
    assert toks("5.") == [(TokenKind.NUMBER, 5.0), (TokenKind.EOF, "")]


def test_scientific_lowercase():
    assert toks("1e3") == [(TokenKind.NUMBER, 1000.0), (TokenKind.EOF, "")]


def test_scientific_negative_exp():
    assert toks("1.5e-3") == [(TokenKind.NUMBER, 0.0015), (TokenKind.EOF, "")]


def test_scientific_uppercase_with_plus():
    assert toks("1E+2") == [(TokenKind.NUMBER, 100.0), (TokenKind.EOF, "")]


def test_integer_value_is_int():
    """Plain integers produce int, not float."""
    result = list(tokenize("42"))
    assert isinstance(result[0].value, int)
    assert not isinstance(result[0].value, bool)


def test_decimal_value_is_float():
    result = list(tokenize("3.14"))
    assert isinstance(result[0].value, float)


def test_bad_exponent_raises():
    with pytest.raises(ParseError, match="exponent"):
        list(tokenize("1e"))


# --- Strings ----------------------------------------------------------


def test_simple_string():
    assert toks('"hello"') == [(TokenKind.STRING, "hello"), (TokenKind.EOF, "")]


def test_empty_string():
    assert toks('""') == [(TokenKind.STRING, ""), (TokenKind.EOF, "")]


def test_string_with_escaped_quote():
    assert toks('"a""b"') == [(TokenKind.STRING, 'a"b'), (TokenKind.EOF, "")]


def test_string_with_multiple_escapes():
    assert toks('"""hi"""') == [(TokenKind.STRING, '"hi"'), (TokenKind.EOF, "")]


def test_string_with_punctuation_inside():
    assert toks('"hello, world!"') == [
        (TokenKind.STRING, "hello, world!"),
        (TokenKind.EOF, ""),
    ]


def test_unterminated_string_raises():
    with pytest.raises(ParseError, match="Unterminated"):
        list(tokenize('"unclosed'))


# --- Identifiers ------------------------------------------------------


def test_simple_ident():
    assert toks("SUM") == [(TokenKind.IDENT, "SUM"), (TokenKind.EOF, "")]


def test_ident_lowercase():
    assert toks("sum") == [(TokenKind.IDENT, "sum"), (TokenKind.EOF, "")]


def test_cell_ref_looks_like_ident():
    """Cell refs are lexed as IDENT; the parser decides what they really are."""
    assert toks("A1") == [(TokenKind.IDENT, "A1"), (TokenKind.EOF, "")]
    assert toks("AA10") == [(TokenKind.IDENT, "AA10"), (TokenKind.EOF, "")]


def test_ident_with_underscore():
    assert toks("my_func") == [(TokenKind.IDENT, "my_func"), (TokenKind.EOF, "")]


def test_ident_starting_with_underscore():
    assert toks("_private") == [(TokenKind.IDENT, "_private"), (TokenKind.EOF, "")]


# --- Operators -------------------------------------------------------


@pytest.mark.parametrize("op", list("+-*/^%&="))
def test_single_char_operators(op):
    assert toks(op) == [(TokenKind.OP, op), (TokenKind.EOF, "")]


def test_lt_alone():
    assert toks("<") == [(TokenKind.OP, "<"), (TokenKind.EOF, "")]


def test_gt_alone():
    assert toks(">") == [(TokenKind.OP, ">"), (TokenKind.EOF, "")]


def test_le():
    assert toks("<=") == [(TokenKind.OP, "<="), (TokenKind.EOF, "")]


def test_ge():
    assert toks(">=") == [(TokenKind.OP, ">="), (TokenKind.EOF, "")]


def test_ne():
    assert toks("<>") == [(TokenKind.OP, "<>"), (TokenKind.EOF, "")]


# --- Punctuation -----------------------------------------------------


def test_lparen():
    assert toks("(") == [(TokenKind.LPAREN, "("), (TokenKind.EOF, "")]


def test_rparen():
    assert toks(")") == [(TokenKind.RPAREN, ")"), (TokenKind.EOF, "")]


def test_comma():
    assert toks(",") == [(TokenKind.COMMA, ","), (TokenKind.EOF, "")]


def test_colon():
    assert toks(":") == [(TokenKind.COLON, ":"), (TokenKind.EOF, "")]


# --- Composite tokenization ------------------------------------------


def test_function_call():
    assert toks("SUM(A1:A5)") == [
        (TokenKind.IDENT, "SUM"),
        (TokenKind.LPAREN, "("),
        (TokenKind.IDENT, "A1"),
        (TokenKind.COLON, ":"),
        (TokenKind.IDENT, "A5"),
        (TokenKind.RPAREN, ")"),
        (TokenKind.EOF, ""),
    ]


def test_arithmetic_expression():
    assert toks("A1 + B1 * 2") == [
        (TokenKind.IDENT, "A1"),
        (TokenKind.OP, "+"),
        (TokenKind.IDENT, "B1"),
        (TokenKind.OP, "*"),
        (TokenKind.NUMBER, 2),
        (TokenKind.EOF, ""),
    ]


def test_negative_number_is_two_tokens():
    """Unary minus is the parser's job; lexer emits OP then NUMBER."""
    assert toks("-5") == [
        (TokenKind.OP, "-"),
        (TokenKind.NUMBER, 5),
        (TokenKind.EOF, ""),
    ]


def test_leading_equals_is_an_op():
    """Lexer doesn't know about formula leading-=; parser strips it."""
    assert toks("=A1") == [
        (TokenKind.OP, "="),
        (TokenKind.IDENT, "A1"),
        (TokenKind.EOF, ""),
    ]


# --- Position tracking -----------------------------------------------


def test_positions_are_recorded():
    result = list(tokenize("SUM(A1)"))
    assert result[0].pos == 0   # S in SUM
    assert result[1].pos == 3   # (
    assert result[2].pos == 4   # A in A1
    assert result[3].pos == 6   # )
    assert result[4].pos == 7   # EOF at end


def test_position_skips_leading_whitespace():
    result = list(tokenize("   42"))
    assert result[0].pos == 3


# --- Error cases -----------------------------------------------------


def test_unexpected_char_raises():
    with pytest.raises(ParseError, match="Unexpected character"):
        list(tokenize("a @ b"))


def test_unexpected_char_position_in_error():
    try:
        list(tokenize("a # b"))
    except ParseError as e:
        assert e.pos == 2  # '#' is at position 2


# --- Token repr ------------------------------------------------------


def test_token_repr():
    t = Token(TokenKind.NUMBER, 42, 0)
    r = repr(t)
    assert "NUMBER" in r
    assert "42" in r
    assert "pos=0" in r


# --- $ in identifiers (absolute-reference pins, design.md Part 6) ------


def test_pinned_ref_is_one_ident_lexeme():
    assert toks("$A$1") == [
        (TokenKind.IDENT, "$A$1"),
        (TokenKind.EOF, ""),
    ]


def test_pinned_ref_in_expression_keeps_stream_shape():
    assert toks("$A1+1") == [
        (TokenKind.IDENT, "$A1"),
        (TokenKind.OP, "+"),
        (TokenKind.NUMBER, 1),
        (TokenKind.EOF, ""),
    ]


def test_bare_dollar_lexes_as_ident_for_the_parser_to_reject():
    # Pin placement is the PARSER's job — the lexer just carries the lexeme.
    assert toks("$") == [(TokenKind.IDENT, "$"), (TokenKind.EOF, "")]
