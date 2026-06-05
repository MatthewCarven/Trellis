#!/usr/bin/env bash
#
# Tier-2 discovery proof for trellis-mathpack — the publication gate.
#
# Builds a throwaway venv, editable-installs the core (`trellis`) and this
# package, then launches a *fresh* interpreter that does only `import trellis`
# and confirms a mathpack formula already works. That proves end-to-end that
# the `trellis.plugins` entry point is auto-discovered at import time, with no
# manual setup() call — which is exactly what a real `pip install` user gets.
#
# Also runs a negative control: with TRELLIS_DISABLE_PLUGIN_DISCOVERY set, the
# functions must be ABSENT — so we know it's genuinely the entry point doing
# the work, not some import side effect.
#
# Usage:
#   packages/trellis-mathpack/scripts/tier2_discovery_check.sh [VENV_DIR]
#
# VENV_DIR defaults to a fresh mktemp dir. On Matthew's mount, keep it OFF the
# mount (the default /tmp-based mktemp does this): editable installs and venvs
# hit "Operation not permitted" quirks on the mounted filesystem.
#
# Exits non-zero (via the embedded asserts) if discovery is broken.

set -euo pipefail

# Resolve repo root from this script's location (.../packages/trellis-mathpack/scripts).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(cd "$PKG_DIR/../.." && pwd)"

VENV="${1:-$(mktemp -d -t trellis-gate-XXXXXX)/venv}"
PY="${PYTHON:-python3}"

echo ">>> repo root:   $REPO_ROOT"
echo ">>> package dir: $PKG_DIR"
echo ">>> venv:        $VENV"
echo

# The sandbox baseline can be older than the project's declared requires-python
# (>=3.11). The code is compatible; only the declared floor differs. Pass
# --ignore-requires-python so the install isn't blocked by the version gate.
# On a 3.11+ machine this flag is a harmless no-op.
PIP_FLAGS="--ignore-requires-python"

"$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip

echo ">>> editable-installing core + mathpack ..."
"$VENV/bin/pip" install --quiet -e "$REPO_ROOT"  $PIP_FLAGS
"$VENV/bin/pip" install --quiet -e "$PKG_DIR"     $PIP_FLAGS
echo

echo ">>> [1/2] auto-discovery proof: import trellis only, NO setup()"
# cd to the venv dir so nothing is imported from the source tree's cwd.
( cd "$VENV" && "$VENV/bin/python" - <<'PY'
import trellis  # load_plugins() runs here, scanning the trellis.plugins group

wb = trellis.Workbook(); sh = wb.add_sheet("S")
sh["A1"] = "=COSH(0)"
sh["A2"] = "=SQRT(-1)"
sh["A3"] = "=STDEV(1,2,3,4,5)"
print("   =COSH(0)     ->", sh["A1"].value)
print("   =SQRT(-1)    ->", sh["A2"].value)
print("   =STDEV(1..5) ->", sh["A3"].value)

names = set(trellis.registered_function_names())
expected = {"SIN","COS","TAN","ASIN","ACOS","ATAN","SINH","COSH","TANH",
            "SQRT","POWER","EXP","LN","LOG","MOD","SIGN","PI","STDEV","VAR","MEDIAN"}
missing = expected - names
assert sh["A1"].value == 1.0, f"COSH(0) should be 1.0, got {sh['A1'].value!r}"
assert str(sh["A2"].value) == "#NUM!", f"SQRT(-1) should be #NUM!, got {sh['A2'].value!r}"
assert not missing, f"functions not auto-registered: {sorted(missing)}"
print("   OK: all 20 functions auto-registered via the entry point.")
PY
)
echo

echo ">>> [2/2] negative control: TRELLIS_DISABLE_PLUGIN_DISCOVERY=1"
( cd "$VENV" && TRELLIS_DISABLE_PLUGIN_DISCOVERY=1 "$VENV/bin/python" - <<'PY'
import trellis
names = set(trellis.registered_function_names())
wb = trellis.Workbook(); sh = wb.add_sheet("S"); sh["A1"] = "=COSH(0)"
assert "COSH" not in names, "COSH should be absent when discovery is disabled"
assert str(sh["A1"].value) == "#NAME?", f"expected #NAME?, got {sh['A1'].value!r}"
print("   OK: with discovery disabled, mathpack functions are absent (=COSH(0) -> #NAME?).")
PY
)
echo
echo ">>> GATE PROOF PASSED."
