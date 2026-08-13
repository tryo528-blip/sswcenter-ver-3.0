param(
    [switch]$Check,
    [string]$PythonExecutable = "",
    [string]$NpmExecutable = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$WorkspaceRoot = Split-Path -Parent $PSScriptRoot
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$FrontendRoot = Join-Path $WorkspaceRoot "frontend"
$IsWindowsHost = [System.IO.Path]::DirectorySeparatorChar -eq '\'
$PythonExe = if ($IsWindowsHost) { Join-Path $BackendRoot ".venv\Scripts\python.exe" } else { Join-Path $BackendRoot ".venv/bin/python" }
$NpmExe = if ($IsWindowsHost) { "C:\Program Files\nodejs\npm.cmd" } else { "/usr/bin/npm" }
$GeneratedFile = Join-Path $FrontendRoot "src\generated\sswcenter-api.ts"

if (-not [string]::IsNullOrWhiteSpace($PythonExecutable)) {
    if (-not [System.IO.Path]::IsPathRooted($PythonExecutable)) { throw "PythonExecutable must be an absolute path" }
    $PythonExe = [System.IO.Path]::GetFullPath($PythonExecutable)
}
if (-not [string]::IsNullOrWhiteSpace($NpmExecutable)) {
    if (-not [System.IO.Path]::IsPathRooted($NpmExecutable)) { throw "NpmExecutable must be an absolute path" }
    $NpmExe = [System.IO.Path]::GetFullPath($NpmExecutable)
}

foreach ($tool in @($PythonExe, $NpmExe)) {
    if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) {
        throw "Required executable missing: $tool"
    }
}

# 1. Extract OpenAPI JSON from FastAPI app.  The desktop host can expose
# C:\Windows\Temp through TEMP/TMP without granting delete rights to the
# interactive user, so keep generated scratch files in the user's local temp.
$TempRoot = if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    [System.IO.Path]::GetTempPath()
} else {
    Join-Path $env:LOCALAPPDATA "Temp"
}
$TempRoot = [System.IO.Path]::GetFullPath($TempRoot)
if (-not (Test-Path -LiteralPath $TempRoot -PathType Container)) {
    throw "OpenAPI temp directory missing: $TempRoot"
}
$TempOpenApiJson = Join-Path $TempRoot ("openapi-" + [Guid]::NewGuid().ToString("N") + ".json")
$TempGeneratedTs = $null

try {
    $GetSpecScript = @"
import json
import sys
from pathlib import Path
from app.main import app

spec = app.openapi()
Path(sys.argv[1]).write_text(
    json.dumps(spec, ensure_ascii=False, indent=2),
    encoding='utf-8',
)
"@
    Push-Location $BackendRoot
    try {
        & $PythonExe -c $GetSpecScript $TempOpenApiJson
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to extract OpenAPI JSON from FastAPI app"
        }
    }
    finally {
        Pop-Location
    }

    # Verify W1A staff routes and schemas exist in OpenAPI spec
    $SpecJson = Get-Content -LiteralPath $TempOpenApiJson -Raw | ConvertFrom-Json
    $HasW1APath = $SpecJson.paths.PSObject.Properties.Name -contains "/api/v1/staff"
    $HasW1ASchema = $SpecJson.components.schemas.PSObject.Properties.Name -contains "StaffResponse"

    if (-not ($HasW1APath -and $HasW1ASchema)) {
        if ($Check) {
            Write-Host "W1A_OPENAPI_CONTRACT_FAILURE: Checked-in W1A schema missing or drifted: OpenAPI spec lacks /api/v1/staff routes or StaffResponse schema."
            exit 1
        } else {
            throw "OpenAPI spec lacks /api/v1/staff routes or StaffResponse schema."
        }
    }

    # 2. Generate TypeScript using openapi-typescript
    $TempGeneratedTs = Join-Path $TempRoot ("generated-ts-" + [Guid]::NewGuid().ToString("N") + ".ts")
    Push-Location $FrontendRoot
    try {
        & $NpmExe exec openapi-typescript -- $TempOpenApiJson --output $TempGeneratedTs
        if ($LASTEXITCODE -ne 0) {
            throw "openapi-typescript generation failed"
        }
    }
    finally {
        Pop-Location
    }

    $NewTsContent = (
        Get-Content -LiteralPath $TempGeneratedTs -Raw -Encoding UTF8
    ).Replace("`r`n", "`n")

    if ($Check) {
        if (-not (Test-Path -LiteralPath $GeneratedFile)) {
            Write-Host "W1A_OPENAPI_CONTRACT_FAILURE: Checked-in W1A schema missing or drifted: $GeneratedFile does not exist."
            exit 1
        }
        $ExistingTsContent = (
            Get-Content -LiteralPath $GeneratedFile -Raw -Encoding UTF8
        ).Replace("`r`n", "`n")
        if ($NewTsContent -ne $ExistingTsContent) {
            Write-Host "W1A_OPENAPI_CONTRACT_FAILURE: Checked-in W1A schema missing or drifted: $GeneratedFile differs from generated output."
            exit 1
        }
        Write-Output "OPENAPI_TYPES_UP_TO_DATE"
        exit 0
    } else {
        $TargetDir = Split-Path -Parent $GeneratedFile
        if (-not (Test-Path -LiteralPath $TargetDir)) {
            New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
        }
        [System.IO.File]::WriteAllText($GeneratedFile, $NewTsContent, $Utf8NoBom)
        Write-Output "OPENAPI_TYPES_GENERATED"
    }
}
finally {
    if (Test-Path -LiteralPath $TempOpenApiJson) {
        Remove-Item -LiteralPath $TempOpenApiJson -Force -ErrorAction SilentlyContinue
    }
    if ($TempGeneratedTs -and (Test-Path -LiteralPath $TempGeneratedTs)) {
        Remove-Item -LiteralPath $TempGeneratedTs -Force -ErrorAction SilentlyContinue
    }
}
