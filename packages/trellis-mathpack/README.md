# trellis-mathpack

A reference math-function plugin for the [Trellis](../../README.md) spreadsheet
framework. It adds ~20 spreadsheet math functions through Trellis's public
extension surface — and serves as the worked example to copy when writing your
own Trellis plugin package.

> **Status: feature-complete, wiring proven (Part 4 #5).** All 20 functions, the
> `NUM` error value, and the `_num` / `_collect_numerics` helpers are implemented
> and tested (32 tests, incl. hermetic entry-point discovery). `setup()` is the
> single registration point; import alone registers nothing. What remains is the
> Tier-2 editable-install discovery proof (#7) and gate sign-off (#8). See
> `../../design.md` → *Part 4: trellis-mathpack*.

## Why this package exists

- **It proves the plugin API from the outside.** mathpack is a *separate
  installable distribution* that touches only `from trellis import ...`. When
  it installs, auto-loads on `import trellis`, and its formulas evaluate, the
  Trellis publication gate is cleared.
- **It is the reference plugin.** Idiomatic conventions, real tests, real
  packaging — the thing to copy.

## Install (local, pre-publication)

The core (`trellis`) is not on PyPI yet, so install both editable from the repo:

```bash
pip install -e .            # the core, from the repo root
pip install -e packages/trellis-mathpack
```

After that, discovery is automatic:

```python
import trellis                       # mathpack.setup() runs here, via entry point
wb = trellis.Workbook()
sh = wb.add_sheet("S")
sh["A1"] = "=COSH(0)"
sh["A1"].value                       # -> 1.0   (no manual setup call)
```

## Functions

| Group | Functions |
|-------|-----------|
| Trig (6) | `SIN COS TAN ASIN ACOS ATAN` |
| Hyperbolic (3) | `SINH COSH TANH` |
| Powers / logs (5) | `SQRT POWER EXP LN LOG` |
| Misc (3) | `MOD SIGN PI` |
| Range stats (3) | `STDEV VAR MEDIAN` |

Angles are in radians. `LOG(x, [base=10])` takes an optional base.

### Error behaviour

mathpack mints its own `#NUM!` error value for domain errors — Trellis core
does not define one, and constructing it here is the point:

- `SQRT(x)` with `x < 0` → `#NUM!`
- `ASIN(x)` / `ACOS(x)` with `x` outside `[-1, 1]` → `#NUM!`
- `LN(x)` / `LOG(x)` with `x <= 0` → `#NUM!`
- `MOD(x, 0)` → `#DIV/0!` (Excel-faithful — this one is *not* `#NUM!`)
- `STDEV` / `VAR` with fewer than 2 values → `#DIV/0!`

Non-numeric scalar args return `#VALUE!`; a `FormulaError` found inside a range
argument propagates. Booleans are not treated as numbers. mathpack never
overrides a core built-in.

## Develop / test

Two tiers — the second is the publication-gate proof.

```bash
# Tier 1 — hermetic unit + discovery tests, no install needed:
PYTHONPATH=../../src:src python -m pytest tests/

# Tier 2 — real auto-discovery: builds a throwaway venv, editable-installs the
# core + this package, then a fresh `import trellis` proves =COSH(0) works with
# no manual setup() call (plus a negative control with discovery disabled).
scripts/tier2_discovery_check.sh
```

> The script passes `--ignore-requires-python` to `pip` because the core
> declares `requires-python >= 3.11` while some dev sandboxes run 3.10; the code
> itself is compatible. On a 3.11+ machine the flag is a no-op.

## License

MIT — see the repository root `LICENSE`.
