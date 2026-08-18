param(
    [string]$PythonExecutable = "",
    [string]$NpmExecutable = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$IsWindowsHost = [System.IO.Path]::DirectorySeparatorChar -eq '\'

if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    if ($IsWindowsHost) {
        $PythonExecutable = Join-Path $BackendRoot ".venv\Scripts\python.exe"
    } else {
        $PythonExecutable = Join-Path $BackendRoot ".venv/bin/python"
    }
}

if (-not [System.IO.Path]::IsPathRooted($PythonExecutable)) {
    throw "SSWCENTER_RUNTIME_PYTHON_NOT_ABSOLUTE"
}
$PythonExecutable = [System.IO.Path]::GetFullPath($PythonExecutable)
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "SSWCENTER_RUNTIME_PYTHON_MISSING: $PythonExecutable"
}

function Resolve-Application {
    param(
        [string]$Candidate,
        [string]$CommandName
    )
    if (-not [string]::IsNullOrWhiteSpace($Candidate)) {
        if (-not [System.IO.Path]::IsPathRooted($Candidate)) {
            throw "SSWCENTER_RUNTIME_TOOL_NOT_ABSOLUTE: $CommandName"
        }
        $Resolved = [System.IO.Path]::GetFullPath($Candidate)
        if (-not (Test-Path -LiteralPath $Resolved -PathType Leaf)) {
            throw "SSWCENTER_RUNTIME_TOOL_MISSING: $Resolved"
        }
        return $Resolved
    }
    $Command = @(Get-Command $CommandName -CommandType Application -ErrorAction Stop)[0]
    return [string]$Command.Source
}

$PythonBin = Split-Path -Parent $PythonExecutable
$RuffName = if ($IsWindowsHost) { "ruff.exe" } else { "ruff" }
$MypyName = if ($IsWindowsHost) { "mypy.exe" } else { "mypy" }
$RuffExecutable = Join-Path $PythonBin $RuffName
$MypyExecutable = Join-Path $PythonBin $MypyName
foreach ($Tool in @($RuffExecutable, $MypyExecutable)) {
    if (-not (Test-Path -LiteralPath $Tool -PathType Leaf)) {
        throw "SSWCENTER_RUNTIME_TOOL_MISSING: $Tool"
    }
}

$NodeExecutable = Resolve-Application -Candidate "" -CommandName "node"
$NodeDirectory = Split-Path -Parent $NodeExecutable
if ([string]::IsNullOrWhiteSpace($NpmExecutable)) {
    $SiblingNames = if ($IsWindowsHost) { @("npm.cmd", "npm.exe", "npm") } else { @("npm") }
    $SiblingNpm = $null
    foreach ($SiblingName in $SiblingNames) {
        $Candidate = Join-Path $NodeDirectory $SiblingName
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            $SiblingNpm = [System.IO.Path]::GetFullPath($Candidate)
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($SiblingNpm)) {
        throw "SSWCENTER_RUNTIME_NPM_NOT_SIBLING_OF_NODE: $NodeDirectory"
    }
    $NpmExecutable = $SiblingNpm
} else {
    $NpmExecutable = Resolve-Application -Candidate $NpmExecutable -CommandName "npm"
}
$NpmExecutableName = [System.IO.Path]::GetFileName($NpmExecutable)
if ($IsWindowsHost) {
    if (@("npm", "npm.cmd", "npm.exe") -inotcontains $NpmExecutableName) {
        throw "SSWCENTER_RUNTIME_NPM_EXECUTABLE_BASENAME_INVALID: $NpmExecutable"
    }
} else {
    if ($NpmExecutableName -cne "npm") {
        throw "SSWCENTER_RUNTIME_NPM_EXECUTABLE_BASENAME_INVALID: $NpmExecutable"
    }
}
$NpmDirectory = Split-Path -Parent $NpmExecutable
$NodeDirectoryComparable = if ($IsWindowsHost) { $NodeDirectory.ToLowerInvariant() } else { $NodeDirectory }
$NpmDirectoryComparable = if ($IsWindowsHost) { $NpmDirectory.ToLowerInvariant() } else { $NpmDirectory }
if ($NpmDirectoryComparable -cne $NodeDirectoryComparable) {
    throw "SSWCENTER_RUNTIME_NPM_NOT_SIBLING_OF_NODE: npm=$NpmExecutable node=$NodeExecutable"
}
$PwshExecutable = Resolve-Application -Candidate "" -CommandName "pwsh"
$PostgresModule = Join-Path $PSScriptRoot "PostgresTools.psm1"
Import-Module $PostgresModule -Force
$PsqlExecutable = Get-SswPostgresExecutable -Name "psql.exe"
$PgRestoreExecutable = Get-SswPostgresExecutable -Name "pg_restore.exe"

foreach ($Tool in @($PsqlExecutable, $PgRestoreExecutable)) {
    if (-not (Test-Path -LiteralPath $Tool -PathType Leaf)) {
        throw "SSWCENTER_RUNTIME_POSTGRES_TOOL_MISSING: $Tool"
    }
}

$RuntimeVersionModule = Join-Path $PSScriptRoot "RuntimeVersion.psm1"
if (-not (Test-Path -LiteralPath $RuntimeVersionModule -PathType Leaf)) {
    throw "SSWCENTER_RUNTIME_SEMVER_MODULE_MISSING: $RuntimeVersionModule"
}
Import-Module $RuntimeVersionModule -Force

function Invoke-Version {
    param([string]$Executable)
    $Output = (& $Executable --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Output)) {
        throw "SSWCENTER_RUNTIME_VERSION_FAILED: $Executable"
    }
    return $Output
}

$PythonVersion = Invoke-Version -Executable $PythonExecutable
$PytestVersion = (& $PythonExecutable -m pytest --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "SSWCENTER_RUNTIME_PYTEST_FAILED" }
$RuffVersion = Invoke-Version -Executable $RuffExecutable
$MypyVersion = Invoke-Version -Executable $MypyExecutable
$NodeVersion = Invoke-Version -Executable $NodeExecutable
$NpmVersion = Invoke-Version -Executable $NpmExecutable
if (-not (Test-SswcenterStrictSemVer -Value $NpmVersion)) {
    throw "SSWCENTER_RUNTIME_NPM_VERSION_INVALID: $NpmVersion"
}
$PwshVersion = (& $PwshExecutable --version 2>&1 | Out-String).Trim()
$PsqlVersion = Invoke-Version -Executable $PsqlExecutable
$PgRestoreVersion = Invoke-Version -Executable $PgRestoreExecutable

& $PythonExecutable -B -c "import alembic, fastapi, psycopg, pytest, sqlalchemy"
if ($LASTEXITCODE -ne 0) { throw "SSWCENTER_RUNTIME_PYTHON_IMPORTS_FAILED" }

$RequirementsLock = Join-Path $BackendRoot "requirements.lock"
if (-not (Test-Path -LiteralPath $RequirementsLock -PathType Leaf)) {
    throw "SSWCENTER_RUNTIME_LOCK_MISSING: $RequirementsLock"
}

Write-Output ("SSWCENTER_RUNTIME_GREEN " +
    "python=$PythonVersion; pytest=$PytestVersion; ruff=$RuffVersion; " +
    "mypy=$MypyVersion; node=$NodeVersion; npm=$NpmVersion; " +
    "pwsh=$PwshVersion; psql=$PsqlVersion; pg_restore=$PgRestoreVersion")
