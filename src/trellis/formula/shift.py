"""shift_formula — rewrite the cell references in formula text by an offset.

The public helper behind copy-paste (design.md Part 6): when a formula moves
``rows`` down and ``cols`` right, every *unpinned* reference axis moves with
it — ``=A1*2`` copied one row down becomes ``=A2*2``, while ``$`` pins hold
(``=$A$1*2`` is unchanged, ``=A$1+$B2`` shifts only its free axes).

This is a token-level splice, not an AST round-trip: only the reference
lexemes are rewritten, at their exact source positions, so spacing, case of
function names, argument commas — everything else — survives byte-for-byte.

Excel-shaped edges:

- A reference shifted off the sheet (row or column below zero) becomes the
  literal ``#REF!`` — which the engine parses and evaluates as the real
  error value, so the pasted formula computes to ``#REF!`` like Excel's.
- A *range* with either corner off the sheet collapses whole: ``=SUM(A1:B2)``
  shifted up a row becomes ``=SUM(#REF!)``, not ``SUM(#REF!:B1)``.
- Text that doesn't tokenize is returned unchanged — a rewriter must never
  blow up on text the engine itself happily stores (broken formulas are
  values here). Tokenizable-but-unparseable text (``=SUM(A1`` mid-edit) has
  its references shifted anyway, which is exactly what you want when moving
  a broken formula around.

``shift_formula(text, 0, 0)`` is the identity, byte-for-byte.
"""

from __future__ import annotations

import re

from trellis.core.address import to_a1

from .errors import ParseError
from .lexer import Token, TokenKind, tokenize
from .parser import _ref_parts

__all__ = ["shift_formula", "rename_sheet_in_formula"]


def _try_ref(text: str) -> tuple[int, int, bool, bool] | None:
    """``_ref_parts`` as a predicate: parts tuple, or None if not a ref."""
    try:
        return _ref_parts(text)
    except ValueError:
        return None


def _is_call(tokens: list[Token], i: int) -> bool:
    """True if the IDENT at ``i`` is a function name (next token is ``(``)."""
    return i + 1 < len(tokens) and tokens[i + 1].kind == TokenKind.LPAREN


def _shift_one(
    parts: tuple[int, int, bool, bool], rows: int, cols: int, original: str
) -> str | None:
    """Shift one reference; None means it fell off the sheet edge.

    A reference that does not actually move (pinned axes, zero offsets)
    returns ``original`` untouched — so unmoved text keeps its spelling
    and the zero-shift is the byte-for-byte identity. Moved references
    re-emit in canonical uppercase (Excel normalises on rewrite too).
    """
    row, col, col_abs, row_abs = parts
    new_row = row if row_abs else row + rows
    new_col = col if col_abs else col + cols
    if new_row < 0 or new_col < 0:
        return None
    if (new_row, new_col) == (row, col):
        return original
    a1 = to_a1(new_row, new_col)
    split = 0
    while split < len(a1) and a1[split].isalpha():
        split += 1
    return (
        ("$" if col_abs else "")
        + a1[:split]
        + ("$" if row_abs else "")
        + a1[split:]
    )


def shift_formula(text: str, rows: int = 0, cols: int = 0) -> str:
    """Return ``text`` with every unpinned reference shifted by the offset.

    Parameters
    ----------
    text
        Formula source, with or without its leading ``=``. Anything the
        lexer can't tokenize is returned unchanged.
    rows, cols
        How far the formula is moving: positive = down / right. ``$`` pins
        exempt their axis (``$A1``: column pinned; ``A$1``: row pinned).

    Returns
    -------
    str
        The rewritten source. References shifted off the sheet edge become
        the literal ``#REF!`` (a range collapses whole). Everything that is
        not a shifted reference is preserved byte-for-byte.
    """
    try:
        tokens = list(tokenize(text))
    except ParseError:
        return text

    # (start, end, replacement) splice spans, in source order.
    splices: list[tuple[int, int, str]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.kind != TokenKind.IDENT or _is_call(tokens, i):
            i += 1
            continue
        parts = _try_ref(tok.value)
        if parts is None:
            i += 1
            continue

        # Range unit (ref COLON ref): shift per-corner; if either corner
        # dies, the WHOLE range span collapses to #REF! (Excel-shaped).
        if (
            i + 2 < len(tokens)
            and tokens[i + 1].kind == TokenKind.COLON
            and tokens[i + 2].kind == TokenKind.IDENT
            and not _is_call(tokens, i + 2)
            and (end_parts := _try_ref(tokens[i + 2].value)) is not None
        ):
            end_tok = tokens[i + 2]
            new_start = _shift_one(parts, rows, cols, tok.value)
            new_end = _shift_one(end_parts, rows, cols, end_tok.value)
            if new_start is None or new_end is None:
                span_end = end_tok.pos + len(end_tok.value)
                splices.append((tok.pos, span_end, "#REF!"))
            else:
                splices.append((tok.pos, tok.pos + len(tok.value), new_start))
                splices.append(
                    (end_tok.pos, end_tok.pos + len(end_tok.value), new_end)
                )
            i += 3
            continue

        new = _shift_one(parts, rows, cols, tok.value)
        splices.append(
            (tok.pos, tok.pos + len(tok.value), new if new is not None else "#REF!")
        )
        i += 1

    out: list[str] = []
    last = 0
    for start, end, replacement in splices:
        out.append(text[last:start])
        out.append(replacement)
        last = end
    out.append(text[last:])
    return "".join(out)


_BARE_SHEET_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _render_sheet_name(name: str) -> str:
    """Render a sheet name for a formula qualifier: bare when it is a plain
    identifier, else single-quoted with ``'`` doubled (Excel-style)."""
    if _BARE_SHEET_NAME.match(name):
        return name
    return "'" + name.replace("'", "''") + "'"


def rename_sheet_in_formula(text: str, old: str, new: str) -> str:
    """Return ``text`` with every sheet qualifier naming ``old`` rewritten to
    ``new``, preserving everything else byte-for-byte (a token splice, like
    :func:`shift_formula`).

    A qualifier is an ``IDENT`` or a ``'quoted name'`` immediately followed by
    ``!``. The new name is emitted bare when it is a plain identifier, else
    quoted. Same-spelled tokens that are NOT sheet qualifiers (a string literal
    ``"Old"``, a plain cell ``Old``) are left untouched. Text the lexer can't
    tokenize is returned unchanged.
    """
    try:
        tokens = list(tokenize(text))
    except ParseError:
        return text
    rendered = _render_sheet_name(new)
    splices: list[tuple[int, int, str]] = []
    for i, tok in enumerate(tokens):
        if tok.kind not in (TokenKind.IDENT, TokenKind.QUOTED_NAME):
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is None or nxt.kind != TokenKind.BANG:
            continue
        if tok.value != old:
            continue
        if tok.kind == TokenKind.IDENT:
            end = tok.pos + len(tok.value)
        else:
            # QUOTED_NAME source span = the two quotes + the (doubled) inner
            # quotes around the unescaped value.
            end = tok.pos + 2 + len(tok.value) + tok.value.count("'")
        splices.append((tok.pos, end, rendered))

    out: list[str] = []
    last = 0
    for start, end, replacement in splices:
        out.append(text[last:start])
        out.append(replacement)
        last = end
    out.append(text[last:])
    return "".join(out)
