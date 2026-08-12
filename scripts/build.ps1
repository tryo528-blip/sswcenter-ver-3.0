param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WorkspaceRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $WorkspaceRoot "backend\.venv\Scripts\python.exe"
$NpmExe = "C:\Program Files\nodejs\npm.cmd"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Backend virtual environment is missing: $PythonExe"
}
if (-not (Test-Path -LiteralPath $NpmExe)) {
    throw "Node.js npm.cmd is missing: $NpmExe"
}
$env:Path = "$(Split-Path -Parent $NpmExe);$env:Path"

Push-Location (Join-Path $WorkspaceRoot "backend")
try {
    & $PythonExe -m compileall -q app
    if ($LASTEXITCODE -ne 0) { throw "Backend bytecode compilation failed" }
}
finally {
    Pop-Location
}

Push-Location (Join-Path $WorkspaceRoot "frontend")
try {
    & $NpmExe run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
    $ProductionFiles = Get-ChildItem -LiteralPath "dist" -File -Recurse
    $DevBypassText = $ProductionFiles | Select-String -SimpleMatch "data-bypass-enabled"
    if ($DevBypassText) {
        throw "Production frontend bundle contains the development login bypass UI"
    }
}
finally {
    Pop-Location
}
