param(
    [switch]$RequirePostgres,
    [switch]$FoundationOnly,
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
$NpmExe = if ($IsWindowsHost) {
    "C:\Program Files\nodejs\npm.cmd"
} else {
    (Get-Command npm -CommandType Application -ErrorAction Stop).Source
}
$PowerShellExe = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
$HistoricalBackendTests = @(
    "tests/test_r0_w2_read_only_contract.py",
    "tests/test_w1b_red.py",
    "tests/test_w1d_contract.py",
    "tests/test_w1e_contract.py",
    "tests/test_w1f_contract.py"
)

if (-not $IsWindowsHost) {
    $UserProfilePath = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::UserProfile
    )
    $LocalPlaywrightLibraryPath = Join-Path $UserProfilePath ".local/share/sswcenter-playwright-libs/ubuntu-24.04/usr/lib/x86_64-linux-gnu"
    if (Test-Path -LiteralPath $LocalPlaywrightLibraryPath -PathType Container) {
        $env:LD_LIBRARY_PATH = if ([string]::IsNullOrWhiteSpace($env:LD_LIBRARY_PATH)) {
            $LocalPlaywrightLibraryPath
        } else {
            "$LocalPlaywrightLibraryPath$([System.IO.Path]::PathSeparator)$env:LD_LIBRARY_PATH"
        }
    }
}

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

    & $PythonExe -B -m pytest -q tests/test_w0_release_gate.py
    if ($LASTEXITCODE -ne 0) { throw "W0 release-gate contract failed" }

    $OpenApiScript = Join-Path $WorkspaceRoot "scripts\generate-openapi-types.ps1"
    & $PowerShellExe -NoProfile -File $OpenApiScript -Check -PythonExecutable $PythonExe -NpmExecutable $NpmExe
    if ($LASTEXITCODE -ne 0) { throw "OpenAPI drift check failed" }

    $PackageLockPath = Join-Path $WorkspaceRoot "frontend\package-lock.json"
    $RequirementsPath = Join-Path $WorkspaceRoot "backend\requirements.txt"
    $RequirementsLockPath = Join-Path $WorkspaceRoot "backend\requirements.lock"
    if (-not (Test-Path -LiteralPath $PackageLockPath -PathType Leaf)) {
        throw "frontend package-lock.json is missing"
    }
    if (-not (Test-Path -LiteralPath $RequirementsPath -PathType Leaf)) {
        throw "backend requirements.txt is missing"
    }
    if (-not (Test-Path -LiteralPath $RequirementsLockPath -PathType Leaf)) {
        throw "backend requirements.lock is missing"
    }
    if ($FoundationOnly) {
        $RuffTargets = @(
            "app/api/dependencies.py",
            "app/api/health.py",
            "app/api/w1a_errors.py",
            "app/core/logging.py",
            "app/core/readiness.py",
            "app/db/session.py",
            "tests/test_health.py",
            "tests/test_logging.py",
            "tests/test_security.py",
            "tests/test_settings.py",
            "tests/test_w0_auth_validation_safety.py",
            "tests/test_w0_postgres_live.py",
            "tests/test_w0_readiness_write_gate.py",
            "tests/test_w0_release_gate.py"
        )
        & $PythonExe -m ruff check @RuffTargets
        if ($LASTEXITCODE -ne 0) { throw "W0 Ruff failed" }

        $MypyTargets = @(
            "app/api/dependencies.py",
            "app/api/health.py",
            "app/api/w1a_errors.py",
            "app/core/logging.py",
            "app/core/readiness.py",
            "app/db/session.py"
        )
        & $PythonExe -m mypy --follow-imports=silent @MypyTargets
        if ($LASTEXITCODE -ne 0) { throw "W0 mypy failed" }

        $PytestArguments = @(
            "-B", "-m", "pytest", "-q",
            "tests/test_foundation_0025_contract.py",
            "tests/test_health.py",
            "tests/test_logging.py",
            "tests/test_schema_contract.py",
            "tests/test_security.py",
            "tests/test_settings.py",
            "tests/test_w0_auth_validation_safety.py",
            "tests/test_w0_postgres_live.py",
            "tests/test_w0_readiness_write_gate.py",
            "tests/test_w0_release_gate.py",
            "tests/test_wave0_postcheck_catalog.py"
        )
        $BackendProfile = "foundation"
    } else {
        & $PythonExe -m ruff check app tests alembic
        if ($LASTEXITCODE -ne 0) { throw "Ruff failed" }
        & $PythonExe -m mypy app
        if ($LASTEXITCODE -ne 0) { throw "mypy failed" }

        $PytestArguments = @("-B", "-m", "pytest", "-q")
        if (-not $RequirePostgres) {
            $PytestArguments += "--ignore=tests/test_w1a_vs6_postgres.py"
        }
        if (-not $IncludeHistoricalContracts) {
            foreach ($HistoricalBackendTest in $HistoricalBackendTests) {
                $PytestArguments += "--ignore=$HistoricalBackendTest"
            }
        }
        $BackendProfile = if ($IncludeHistoricalContracts) {
            "supported+historical"
        } else {
            "supported"
        }
    }
    $E2eProfile = if ($FoundationOnly) { "w0" } else { "smoke" }
    Write-Output (
        "SSWCENTER_TEST_PROFILE backend={0} frontend={1} e2e={2} postgres={3} historical={4}" -f
        $BackendProfile,
        $(if ($IncludeHistoricalContracts) { "supported+historical" } else { "supported" }),
        $E2eProfile,
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
    if ($FoundationOnly) {
        & $NpmExe run test:e2e:w0
    } else {
        & $NpmExe run test:e2e:smoke
    }
    if ($LASTEXITCODE -ne 0) { throw "Frontend Playwright smoke tests failed" }
}
finally {
    Pop-Location
}
