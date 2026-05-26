"""Tests for trellis.core.address — A1 ↔ (row, col) conversion."""

import pytest

from trellis.core.address import parse, to_a1


class TestParse:
    @pytest.mark.parametrize(
        "addr,expected",
        [
            ("A1", (0, 0)),
            ("B3", (2, 1)),
            ("Z1", (0, 25)),
            ("AA1", (0, 26)),
            ("AA10", (9, 26)),
            ("AZ1", (0, 51)),
            ("BA1", (0, 52)),
            ("ZZ999", (998, 701)),
            ("AAA1", (0, 702)),
        ],
    )
    def test_known_addresses(self, addr, expected):
        assert parse(addr) == expected

    def test_lowercase_is_accepted(self):
        assert parse("aa10") == (9, 26)

    def test_whitespace_is_stripped(self):
        assert parse("  B3 \n") == (2, 1)

    @pytest.mark.parametrize("bad", ["", "1", "A", "A0", "1A", "A 1", "$A$1", "A1.5"])
    def test_invalid_raises_value_error(self, bad):
        with pytest.raises(ValueError):
            parse(bad)

    def test_non_string_raises_type_error(self):
        with pytest.raises(TypeError):
            parse(123)  # type: ignore[arg-type]


class TestToA1:
    @pytest.mark.parametrize(
        "row,col,expected",
        [
            (0, 0, "A1"),
            (2, 1, "B3"),
            (0, 25, "Z1"),
            (0, 26, "AA1"),
            (9, 26, "AA10"),
            (0, 51, "AZ1"),
            (0, 52, "BA1"),
            (998, 701, "ZZ999"),
            (0, 702, "AAA1"),
        ],
    )
    def test_known_coords(self, row, col, expected):
        assert to_a1(row, col) == expected

    @pytest.mark.parametrize("row,col", [(-1, 0), (0, -1), (-5, -5)])
    def test_negative_raises(self, row, col):
        with pytest.raises(ValueError):
            to_a1(row, col)


class TestRoundTrip:
    @pytest.mark.parametrize(
        "addr",
        ["A1", "Z1", "AA1", "AZ27", "BA100", "ZZ999", "AAA1", "AAB42"],
    )
    def test_parse_then_format(self, addr):
        row, col = parse(addr)
        assert to_a1(row, col) == addr
