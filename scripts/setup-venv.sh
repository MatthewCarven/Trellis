#!/usr/bin/env bash
# Recreate the Trellis dev venv — Linux / macOS.
#   Usage:  bash scripts/setup-venv.sh
# Installs: core + trellis-mathpack + trellis-undo + trellis-tui + trellis-tui-vim (all editable) + pytest, then runs the suite.
#
# Notes:
#  - VENV_DIR overrides the venv location (default: .venv at repo root).
#    In Claude's sandbox the venv MUST live off-mount, e.g.:
#      VENV_DIR=$(mktemp -d)/venv bash scripts/setup-venv.sh
#  - The sandbox is Python 3.10 vs the declared 3.11+ baseline; pass
#    PIP_FLAGS=--ignore-requires-python there (the suite runs fine on 3.10).
#    On a real 3.11+ machine both knobs are no-ops you never touch.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT/.venv}"
PIP_FLAGS="${PIP_FLAGS:-}"

if [ -d "$VENV_DIR" ]; then
    echo "Removing existing venv at $VENV_DIR ..."
    rm -rf "$VENV_DIR"
fi

python3 -m venv "$VENV_DIR"
VENV_PY="$VENV_DIR/bin/python"
"$VENV_PY" -m pip install --upgrade pip --quiet
# shellcheck disable=SC2086
"$VENV_PY" -m pip install $PIP_FLAGS -e "$ROOT" -e "$ROOT/packages/trellis-mathpack" -e "$ROOT/packages/trellis-undo" -e "$ROOT/packages/trellis-tui" -e "$ROOT/packages/trellis-tui-vim" pytest pytest-asyncio

echo
echo "Verifying: running the core suite (+doctests) ..."
cd "$ROOT" && "$VENV_PY" -m pytest --doctest-modules src/trellis tests
# NB: mathpack's Tier-1 tests are NOT run here — they require the hermetic
# (uninstalled) context: discovery auto-registers in this venv, which their
# import-alone/registry contract tests reject by design. Run them with:
#   PYTHONPATH=src:packages/trellis-mathpack/src python3 -m pytest packages/trellis-mathpack/tests
# (using a python WITHOUT trellis installed). The installed-context proof is
#   packages/trellis-mathpack/scripts/tier2_discovery_check.sh

echo
echo "Done. Activate with:  source $VENV_DIR/bin/activate"
