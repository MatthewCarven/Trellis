"""Pratt parser for formula source.

Public entry point:

    parse_formula(src) -> Node

A small top-down operator-precedence parser. Source may optionally begin
with ``=`` (the spreadsheet convention); it is stripped before lexing.

Precedence (lowest -> highest left-binding power):

    10   = <> < > <= >=        comparisons
    20   &                      string concatenation
    30   + -                    additive
    40   * /                    multiplicative
    50   ^                      exponentiation (right-associative)
    60   %                      postfix percent (``5%`` -> ``UnaryOp('%', 5)``)
    70   prefix + / -           unary sign (binds tighter than any infix)

Cell-reference ranges (``A1:B5``) are not part of the precedence ladder —
they are recognised when an IDENT that parses as a cell address is followed
by a colon and another such IDENT.
"""

from __future__ import annotations

from trellis.core.address import parse as parse_addr

from .ast import (
    BinaryOp,
    Bool,
    CellRef,
    FunctionCall,
    Number,
    RangeRef,
    String,
    UnaryOp,
)
from .errors import ParseError
from .lexer import Token, TokenKind, tokenize

# Left-binding power for each infix/postfix operator.
_INFIX_BP = {
    "=": 10, "<>": 10, "<": 10, ">": 10, "<=": 10, ">=": 10,
    "&": 20,
    "+": 30, "-": 30,
    "*": 40, "/": 40,
    "^": 50,
    "%": 60,  # postfix — parse_infix handles specially
}

# Binding power used when parsing the operand of a unary +/-. Higher than any
# infix lbp, so unary binds tighter than every binary operator.
_PREFIX_BP = 70


class Parser:
    """Single-use token-stream consumer."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def peek_at(self, offset: int) -> Token | None:
        idx = self.pos + offset
        if 0 <= idx < len(self.tokens):
            return self.tokens[idx]
        return None

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind: TokenKind) -> Token:
        tok = self.advance()
        if tok.kind != kind:
            raise ParseError(
                f"Expected {kind.name}, got {tok.kind.name} ({tok.value!r})",
                pos=tok.pos,
            )
        return tok

    # --- Pratt core ---------------------------------------------------------

    def parse_expression(self, min_bp: int = 0):
        left = self.parse_prefix()
        while True:
            tok = self.peek()
            lbp = self._infix_lbp(tok)
            if lbp <= min_bp:
                break
            self.advance()
            left = self.parse_infix(left, tok)
        return left

    def _infix_lbp(self, tok: Token) -> int:
        if tok.kind == TokenKind.OP:
            return _INFIX_BP.get(tok.value, 0)
        return 0

    def parse_prefix(self):
        tok = self.advance()

        if tok.kind == TokenKind.NUMBER:
            return Number(tok.value)

        if tok.kind == TokenKind.STRING:
            return String(tok.value)

        if tok.kind == TokenKind.LPAREN:
            expr = self.parse_expression()
            self.expect(TokenKind.RPAREN)
            return expr

        if tok.kind == TokenKind.OP and tok.value in ("-", "+"):
            operand = self.parse_expression(min_bp=_PREFIX_BP)
            return UnaryOp(tok.value, operand)

        if tok.kind == TokenKind.IDENT:
            return self._parse_ident(tok)

        raise ParseError(
            f"Unexpected token {tok.kind.name} ({tok.value!r})",
            pos=tok.pos,
        )

    def parse_infix(self, left, tok: Token):
        op = tok.value

        # Postfix %
        if op == "%":
            return UnaryOp("%", left)

        # Right-associative ^
        if op == "^":
            right = self.parse_expression(min_bp=_INFIX_BP["^"] - 1)
            return BinaryOp("^", left, right)

        # Standard left-associative infix
        bp = _INFIX_BP[op]
        right = self.parse_expression(min_bp=bp)
        return BinaryOp(op, left, right)

    # --- Identifier handling -----------------------------------------------

    def _parse_ident(self, ident_tok: Token):
        text = ident_tok.value
        upper = text.upper()

        # Function call: IDENT(...)
        if self.peek().kind == TokenKind.LPAREN:
            self.advance()  # consume (
            args: list = []
            if self.peek().kind != TokenKind.RPAREN:
                args.append(self.parse_expression())
                while self.peek().kind == TokenKind.COMMA:
                    self.advance()
                    args.append(self.parse_expression())
            self.expect(TokenKind.RPAREN)
            return FunctionCall(upper, tuple(args))

        # Boolean literal
        if upper == "TRUE":
            return Bool(True)
        if upper == "FALSE":
            return Bool(False)

        # Cell reference (A1-style); may be the start of a range.
        try:
            row, col = parse_addr(text)
        except ValueError:
            raise ParseError(f"Unknown identifier {text!r}", pos=ident_tok.pos)

        start = CellRef(row, col)

        # Range? A1:B5 — only if next is COLON followed by another A1-ish IDENT.
        if self.peek().kind == TokenKind.COLON:
            next_tok = self.peek_at(1)
            if next_tok is None or next_tok.kind != TokenKind.IDENT:
                raise ParseError(
                    "Expected cell reference after ':'",
                    pos=self.peek().pos,
                )
            self.advance()  # consume :
            end_tok = self.advance()
            try:
                end_row, end_col = parse_addr(end_tok.value)
            except ValueError:
                raise ParseError(
                    f"Invalid cell reference {end_tok.value!r} in range",
                    pos=end_tok.pos,
                )
            end = CellRef(end_row, end_col)
            # Corner-normalise so start is top-left, end is bottom-right.
            top = CellRef(min(start.row, end.row), min(start.col, end.col))
            bot = CellRef(max(start.row, end.row), max(start.col, end.col))
            return RangeRef(top, bot)

        return start


def parse_formula(src: str):
    """Parse a formula source string into an AST.

    A leading ``=`` is stripped (it is the spreadsheet's "this is a formula"
    marker, not part of the expression language). Whitespace at the boundaries
    is also stripped.

    Raises :class:`ParseError` on malformed input.
    """
    if not isinstance(src, str):
        raise ParseError(
            f"Formula source must be a string, got {type(src).__name__}"
        )
    body = src.strip()
    if body.startswith("="):
        body = body[1:].lstrip()
    tokens = list(tokenize(body))
    parser = Parser(tokens)
    expr = parser.parse_expression()
    tail = parser.peek()
    if tail.kind != TokenKind.EOF:
        raise ParseError(
            f"Unexpected trailing token {tail.kind.name} ({tail.value!r})",
            pos=tail.pos,
        )
    return expr
