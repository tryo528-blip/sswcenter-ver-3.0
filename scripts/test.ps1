param(
    [switch]$RequirePostgres,
    [switch]$IncludeHistoricalContracts,
    [string]$PythonExecutable = "",
    [string]$NpmExecutable = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WorkspaceRoot = Split-Path -Parent $PSScriptRoot
$IsWindowsHost = [System.IO.Path]::DirectorySeparatorChar -eq '\'
$PythonExe = if ($IsWindowsHost) {
    Join-Path $WorkspaceRoot "backend\.venv\Scripts\python.exe"
} else {
    Join-Path $WorkspaceRoot "backend/.venv/bin/python"
}
$NpmExe = if ($IsWindowsHost) { "C:\Program Files\nodejs\npm.cmd" } else { "/usr/bin/npm" }

if (-not [string]::IsNullOrWhiteSpace($PythonExecutable)) {
    if (-not [System.IO.Path]::IsPathRooted($PythonExecutable)) {
        throw "PythonExecutable must be an absolute path"
    }
    $PythonExe = [System.IO.Path]::GetFullPath($PythonExecutable)
}

if (-not [string]::IsNullOrWhiteSpace($NpmExecutable)) {
    if (-not [System.IO.Path]::IsPathRooted($NpmExecutable)) {
        throw "NpmExecutable must be an absolute path"
    }
    $NpmExe = [System.IO.Path]::GetFullPath($NpmExecutable)
}

foreach ($tool in @($PythonExe, $NpmExe)) {
    if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) {
        throw "Required executable missing: $tool"
    }
}
$env:Path = "$(Split-Path -Parent $NpmExe)$([System.IO.Path]::PathSeparator)$env:Path"

Push-Location (Join-Path $WorkspaceRoot "backend")
try {
    if ($RequirePostgres) {
        if (-not $env:SSWCENTER_DATABASE_URL) {
            throw "SSWCENTER_DATABASE_URL is required for PostgreSQL integration tests"
        }
        & $PythonExe -B -c "import os; from app.core.settings import assert_safe_test_database_url; assert_safe_test_database_url(os.environ['SSWCENTER_DATABASE_URL'])"
        if ($LASTEXITCODE -ne 0) {
            throw "Safe test-target validation failed"
        }
    }

    & $PythonExe -m ruff check app tests alembic
    if ($LASTEXITCODE -ne 0) { throw "Ruff failed" }
    & $PythonExe -m mypy app
    if ($LASTEXITCODE -ne 0) { throw "mypy failed" }

    $PytestArguments = @("-m", "pytest", "-q")
    if (-not $RequirePostgres) {
        $PytestArguments += "--ignore=tests/test_w1a_vs6_postgres.py"
    }
    if (-not $IncludeHistoricalContracts) {
        $PytestArguments += "--ignore=tests/test_w1b_red.py"
        $PytestArguments += "--ignore=tests/test_w1d_contract.py"
        $PytestArguments += "--ignore=tests/test_w1e_contract.py"
    }
    Write-Output (
        "SSWCENTER_TEST_PROFILE backend={0} frontend={1} e2e=smoke postgres={2} historical={3}" -f
        $(if ($IncludeHistoricalContracts) { "supported+historical" } else { "supported" }),
        $(if ($IncludeHistoricalContracts) { "supported+historical" } else { "supported" }),
        [int][bool]$RequirePostgres,
        [int][bool]$IncludeHistoricalContracts
    )
    & $PythonExe @PytestArguments
    if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

    if ($RequirePostgres) {
        & $PythonExe -m alembic -c alembic.ini upgrade head
        if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed" }
        & $PythonExe -m alembic -c alembic.ini current
        if ($LASTEXITCODE -ne 0) { throw "Alembic current failed" }
    }
}
finally {
    Pop-Location
}

Push-Location (Join-Path $WorkspaceRoot "frontend")
try {
    & $NpmExe run lint
    if ($LASTEXITCODE -ne 0) { throw "Frontend lint failed" }
    & $NpmExe run test:supported
    if ($LASTEXITCODE -ne 0) { throw "Frontend unit tests failed" }
    if ($IncludeHistoricalContracts) {
        & $NpmExe run test:historical
        if ($LASTEXITCODE -ne 0) { throw "Frontend historical contract tests failed" }
    }
    & $NpmExe run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
    & $NpmExe run test:e2e:smoke
    if ($LASTEXITCODE -ne 0) { throw "Frontend Playwright smoke tests failed" }
}
finally {
    Pop-Location
}
