"""Tokenizer for formula source.

Tokenises input like ``"=SUM(A1:A5) + B2 * 2"`` into a stream of :class:`Token`
instances ending in an EOF token. A leading ``=`` is stripped by the parser
entry point, not here — the lexer treats every ``=`` as an OP token.

Tokens carry a character offset (``pos``) for error messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterator

from .errors import _BY_CODE, ParseError

# Error-literal codes, longest first so prefixes can't shadow (#N/A vs #NAME?).
_ERROR_CODES = sorted(_BY_CODE, key=len, reverse=True)


class TokenKind(Enum):
    NUMBER = "number"    # int or float in Token.value
    STRING = "string"    # str in Token.value (unquoted, escapes resolved)
    IDENT = "ident"      # cell ref, function name, or bool literal — parser decides
    OP = "op"            # arithmetic, comparison, %, &, =
    ERROR = "error"      # error literal: #REF!, #DIV/0!, ... (code str in value)
    LPAREN = "lparen"
    RPAREN = "rparen"
    COMMA = "comma"
    COLON = "colon"
    EOF = "eof"


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    value: object  # int / float / str depending on kind
    pos: int

    def __repr__(self) -> str:
        return f"Token({self.kind.name}, {self.value!r}, pos={self.pos})"


# Single-character punctuation -> (kind, value) pairs.
_PUNCT = {
    "(": (TokenKind.LPAREN, "("),
    ")": (TokenKind.RPAREN, ")"),
    ",": (TokenKind.COMMA, ","),
    ":": (TokenKind.COLON, ":"),
}

# Single-character operators that never combine with the next character.
_SIMPLE_OPS = set("+-*/^%&=")


def tokenize(src: str) -> Iterator[Token]:
    """Yield Tokens from ``src``, ending with an EOF token.

    Raises :class:`ParseError` on unterminated strings, bad numbers, or
    unexpected characters.
    """
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]

        # Whitespace
        if ch.isspace():
            i += 1
            continue

        # Single-char punctuation
        if ch in _PUNCT:
            kind, val = _PUNCT[ch]
            yield Token(kind, val, i)
            i += 1
            continue

        # String literal: "..." with "" as escaped quote.
        if ch == '"':
            start = i
            i += 1
            buf = []
            closed = False
            while i < n:
                if src[i] == '"':
                    if i + 1 < n and src[i + 1] == '"':
                        buf.append('"')
                        i += 2
                    else:
                        i += 1
                        closed = True
                        break
                else:
                    buf.append(src[i])
                    i += 1
            if not closed:
                raise ParseError("Unterminated string literal", pos=start)
            yield Token(TokenKind.STRING, "".join(buf), start)
            continue

        # Number: 42, 3.14, .5, 1e3, 1.5e-3
        if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            start = i
            saw_dot = False
            while i < n and (src[i].isdigit() or (src[i] == "." and not saw_dot)):
                if src[i] == ".":
                    saw_dot = True
                i += 1
            # Optional exponent: [eE][+-]?digits
            saw_exp = False
            if i < n and src[i] in "eE":
                saw_exp = True
                i += 1
                if i < n and src[i] in "+-":
                    i += 1
                exp_start = i
                while i < n and src[i].isdigit():
                    i += 1
                if i == exp_start:
                    raise ParseError("Bad exponent in number literal", pos=start)
            text = src[start:i]
            try:
                if saw_dot or saw_exp:
                    yield Token(TokenKind.NUMBER, float(text), start)
                else:
                    yield Token(TokenKind.NUMBER, int(text), start)
            except ValueError:
                raise ParseError(f"Bad number literal {text!r}", pos=start)
            continue

        # Identifier: starts with a letter, underscore, or ``$`` (absolute-
        # reference pin — ``$A$1`` arrives as ONE ident lexeme; the parser
        # validates pin placement). The parser decides whether it's a cell
        # ref, bool literal, or function name.
        if ch.isalpha() or ch == "_" or ch == "$":
            start = i
            while i < n and (src[i].isalnum() or src[i] in "_$"):
                i += 1
            yield Token(TokenKind.IDENT, src[start:i], start)
            continue

        # Multi-char comparison operators.
        if ch == "<":
            if i + 1 < n and src[i + 1] == "=":
                yield Token(TokenKind.OP, "<=", i)
                i += 2
                continue
            if i + 1 < n and src[i + 1] == ">":
                yield Token(TokenKind.OP, "<>", i)
                i += 2
                continue
            yield Token(TokenKind.OP, "<", i)
            i += 1
            continue
        if ch == ">":
            if i + 1 < n and src[i + 1] == "=":
                yield Token(TokenKind.OP, ">=", i)
                i += 2
                continue
            yield Token(TokenKind.OP, ">", i)
            i += 1
            continue

        # Single-char operators
        if ch in _SIMPLE_OPS:
            yield Token(TokenKind.OP, ch, i)
            i += 1
            continue

        # Error literal: one of the known codes, verbatim (uppercase).
        # ``=#REF!*2`` is real source — pasting a formula off the sheet
        # edge produces it (shift_formula, design.md Part 6).
        if ch == "#":
            for code in _ERROR_CODES:
                if src.startswith(code, i):
                    yield Token(TokenKind.ERROR, code, i)
                    i += len(code)
                    break
            else:
                raise ParseError(f"Unknown error literal at {ch!r}", pos=i)
            continue

        raise ParseError(f"Unexpected character {ch!r}", pos=i)

    yield Token(TokenKind.EOF, "", n)
