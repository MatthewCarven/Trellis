# Recreate the Trellis dev venv (.venv at repo root) — Windows / PowerShell.
#   Usage:  powershell -ExecutionPolicy Bypass -File scripts\setup-venv.ps1
# Installs: core (editable) + trellis-mathpack (editable) + pytest, then runs the suite.
# Requires Python 3.11+ (the declared baseline in pyproject.toml).

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    if (Test-Path .venv) {
        Write-Host "Removing existing .venv ..."
        Remove-Item -Recurse -Force .venv
    }

    # Prefer the py launcher pinned to 3.11+, fall back to python on PATH.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 -m venv .venv
    } else {
        python -m venv .venv
    }

    $VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
    & $VenvPy -m pip install --upgrade pip --quiet
    & $VenvPy -m pip install -e . -e .\packages\trellis-mathpack pytest

    Write-Host ""
    Write-Host "Verifying: running the core suite (+doctests) ..."
    & $VenvPy -m pytest --doctest-modules src/trellis tests
    # NB: mathpack's Tier-1 tests are NOT run here -- they need the hermetic
    # (uninstalled) context; in this venv discovery auto-registers at import,
    # which their contract tests reject by design. See scripts/setup-venv.sh
    # notes and packages/trellis-mathpack/scripts/tier2_discovery_check.sh.

    Write-Host ""
    Write-Host "Done. Activate with:  .venv\Scripts\Activate.ps1"
} finally {
    Pop-Location
}
