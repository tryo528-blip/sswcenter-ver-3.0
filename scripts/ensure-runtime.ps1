param(
    [switch]$Online,
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$VenvRoot = Join-Path $BackendRoot ".venv"
$IsWindowsHost = [System.IO.Path]::DirectorySeparatorChar -eq '\'
if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    if ($IsWindowsHost) {
        $PythonExecutable = Join-Path $VenvRoot "Scripts\python.exe"
    } else {
        $PythonExecutable = Join-Path $VenvRoot "bin/python"
    }
}

$UvCommand = Get-Command uv -CommandType Application -ErrorAction Stop
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    & $UvCommand.Source venv $VenvRoot --python 3.12
    if ($LASTEXITCODE -ne 0) { throw "SSWCENTER_RUNTIME_VENV_CREATE_FAILED" }
}

$RequirementsLock = Join-Path $BackendRoot "requirements.lock"
$SyncArguments = @("pip", "sync", "--python", $PythonExecutable)
if (-not $Online) { $SyncArguments += "--offline" }
$SyncArguments += $RequirementsLock
& $UvCommand.Source @SyncArguments
if ($LASTEXITCODE -ne 0) {
    if ($Online) {
        throw "SSWCENTER_RUNTIME_SYNC_FAILED"
    }
    throw "SSWCENTER_RUNTIME_OFFLINE_SYNC_FAILED: rerun with -Online only when network access is approved"
}

& (Join-Path $PSScriptRoot "verify-runtime.ps1") -PythonExecutable $PythonExecutable
if ($LASTEXITCODE -ne 0) { throw "SSWCENTER_RUNTIME_PREFLIGHT_FAILED" }
