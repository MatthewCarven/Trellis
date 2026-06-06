---
name: trellis-test-command
description: "How to run the Trellis test suite in the cowork sandbox: PYTHONPATH=src python3 -m pytest, optionally with --doctest-modules."
metadata: 
  node_type: memory
  type: reference
  originSessionId: 119f8586-f304-4502-a589-72e52c8a98b2
---

Run the Trellis suite from the repo root (bash path `/sessions/<id>/mnt/Cross Tabulator Pro/`):

```
PYTHONPATH=src python3 -m pytest tests/ -q -p no:cacheprovider
```

Full run including the doctests in module docstrings (the canonical "all green" check):

```
PYTHONPATH=src python3 -m pytest tests/ --doctest-modules src/trellis -q -p no:cacheprovider
```

As of 2026-06-03 that's **748 passing** (741 tests + 7 doctest modules).

Notes:
- The sandbox ships **Python 3.10**, but the project baseline is **3.11+**. The code is `from __future__ import annotations`-safe so it runs fine on 3.10; if a real version-specific check is needed, re-confirm on 3.11. There is usually no 3.11 interpreter pre-installed.
- `PYTHONPATH=src` avoids the editable-install permission quirk on the mount (a plain `pip install -e .` has bitten past sessions). For the upcoming mathpack Tier-2 discovery test, an actual venv may be required since `entry_points` discovery needs the package truly installed.
- `pip install` needs `--break-system-packages` in this sandbox.
