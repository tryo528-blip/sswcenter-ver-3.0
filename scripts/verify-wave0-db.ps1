param(
    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrl
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($DatabaseUrl -notmatch '(_test|_review)(\?|$)') {
    throw "Verification target must end with _test or _review"
}

$WorkspaceRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $WorkspaceRoot "backend\.venv\Scripts\python.exe"
$env:SSWCENTER_ENVIRONMENT = "test"
$env:SSWCENTER_DATABASE_URL = $DatabaseUrl

Push-Location (Join-Path $WorkspaceRoot "backend")
try {
    & $PythonExe -m alembic -c alembic.ini current
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic current failed"
    }
    & $PythonExe -m app.db.postcheck
    if ($LASTEXITCODE -ne 0) {
        throw "Wave 0 database postcheck failed"
    }
}
finally {
    Pop-Location
}
