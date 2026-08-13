param(
    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrl,

    [Parameter(Mandatory = $false)]
    [string]$PythonExe
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($DatabaseUrl -notmatch '(_test|_review)(\?|$)') {
    throw "Verification target must end with _test or _review"
}

$WorkspaceRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $ResolvedPythonExe = Join-Path $WorkspaceRoot "backend\.venv\Scripts\python.exe"
}
else {
    $ResolvedPythonExe = [System.IO.Path]::GetFullPath($PythonExe)
    if (-not (Test-Path -LiteralPath $ResolvedPythonExe -PathType Leaf)) {
        throw "Python executable is missing: $ResolvedPythonExe"
    }
}

$env:SSWCENTER_ENVIRONMENT = "test"
$env:SSWCENTER_DATABASE_URL = $DatabaseUrl

Push-Location (Join-Path $WorkspaceRoot "backend")
try {
    & $ResolvedPythonExe -m alembic -c alembic.ini current
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic current failed"
    }
    & $ResolvedPythonExe -m app.db.postcheck_w1a_vs1
    if ($LASTEXITCODE -ne 0) {
        throw "W1A-VS1 database postcheck failed"
    }
}
finally {
    Pop-Location
}
