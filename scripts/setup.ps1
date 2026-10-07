param(
  [string]$Python = "python",
  [string]$HoardLink = $env:HOARD_LINK_ROOT,
  [string]$DesignCraftCli = $env:GUTENBERG_DESIGNCRAFT_CLI
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $HoardLink) { $HoardLink = Join-Path (Split-Path -Parent $root) "HoardLink" }
if (-not (Test-Path (Join-Path $HoardLink "hoard_link\appconfig.py"))) {
  throw "Set HOARD_LINK_ROOT to the shared HoardLink checkout."
}
Push-Location $root
try {
  $venvPython = Join-Path $root ".venv\Scripts\python.exe"
  if (-not (Test-Path $venvPython)) {
    & $Python -m venv (Join-Path $root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create Gutenberg's dedicated .venv." }
  }
  & $venvPython -m pip install -e $HoardLink
  if ($LASTEXITCODE -ne 0) { throw "Could not install the shared hoard-link package." }
  & $venvPython -m pip install -e ".[dev]"
  if ($LASTEXITCODE -ne 0) { throw "Could not install Gutenberg's Hoard dependencies." }
  if ($DesignCraftCli) {
    & $venvPython (Join-Path $root "scripts\configure.py") $DesignCraftCli
    if ($LASTEXITCODE -ne 0) { throw "Could not save the local DesignCraft executable path." }
  }
} finally { Pop-Location }
