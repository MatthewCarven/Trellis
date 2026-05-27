"""File I/O for Trellis.

The core engine has no file format opinions; this subpackage adds them in
plugin-shaped layers. CSV lives in :mod:`trellis.io.csv` and ships in core
(stdlib only, zero dependencies). Other formats (xlsx, parquet, ...) are
expected to land as optional extras behind their own optional-dependency
groups.

The common entry points are re-exported here for convenience::

    from trellis.io import read_csv

The same names are also re-exported from the top-level ``trellis`` package.
"""

from .csv import read_csv, write_csv

__all__ = ["read_csv", "write_csv"]
