param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,

    [int]$Port = 55448
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# 3.0 R0-A port baseline (TASK_PACKET BASELINE_SHA); not a hard-coded 2.2 historical HEAD.
$ExpectedHead = "a5367f212acc6c70efeedb202e7999e90d9f7fc5"
$Source0018Database = "sswcenter_r0_0018_test"
$Source0019Database = "sswcenter_r0_0019_test"
$Review0018Database = "sswcenter_r0_0018_restore_review"
$Review0019Database = "sswcenter_r0_0019_restore_review"
$DatabaseNames = @(
    $Source0018Database,
    $Source0019Database,
    $Review0018Database,
    $Review0019Database
)
# Byte-identical product seals. postcheck is 3.0-merged and presence-sealed only.
$ExpectedProductHashes = [ordered]@{
    "backend/alembic/versions/20260809_0018_w2_service_plan_notice.py" =
        "AB1A7FB77498CAB7EBD1163084CA98FDF9FD350F5D32A0682F81DC17EE37D716"
    "backend/alembic/versions/20260812_0019_r0_w2_read_only.py" =
        "EF7FC4917015A265D4633EFAE372314B760F193C4CFC2C98240C158CFDFB21AA"
    "scripts/restore-drill.ps1" =
        "B37B9C26C27CED5794580BA00E0CAE808C94A783B1ECA0BAA0E7A1471829C5AB"
    "scripts/verify-w1a-vs1-db.ps1" =
        "5EB67C21F12F2DAA69E791AA6AB38D64195DF7C59A52A4F85EE63D307E8EB06C"
}
$RequiredProductFiles = @(
    "backend/app/db/postcheck_w1a_vs1.py"
)
$RequiredTrackedPaths = @(
    "backend/tests/test_r0_w2_read_only_lifecycle.py",
    "scripts/test-r0-w2-read-only-lifecycle.ps1"
)
# Optional dirty: HOME WIP + other R0-A allowlisted product paths before commit.
$OptionalDirtyPaths = @(
    "00-먼저읽기-작업환경안내.md",
    "00-오케스트레이션-작업지침.md",
    ".agents/skills/location-operator-writer/SKILL.md",
    ".agents/skills/location-operator-writer/references/runtime-contracts.md",
    "warpper/README.md",
    "warpper/wrapper-config.json",
    "warpper/ai-wrapper-core.ps1",
    "warpper/invoke-grok.ps1",
    "warpper/test-ai-wrappers-offline.ps1",
    "backend/alembic/versions/20260812_0019_r0_w2_read_only.py",
    "backend/app/db/postcheck_w1a_vs1.py",
    "backend/tests/test_r0_w2_read_only_contract.py",
    "backend/tests/test_r0_w2_read_only_postgres.py",
    "scripts/test-r0-w2-read-only-postgres.ps1",
    "scripts/restore-drill.ps1",
    "scripts/verify-w1a-vs1-db.ps1",
    "trouble/",
    "troubleshooting/"
)
$RequiredStatusLines = @($RequiredTrackedPaths | ForEach-Object { " M $_" })

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$ResolvedPythonExe = [System.IO.Path]::GetFullPath($PythonExe)
$PowerShellExe = (Get-Process -Id $PID -ErrorAction Stop).Path
$PostgresBin = "C:\Program Files\PostgreSQL\17\bin"
$InitDbExe = Join-Path $PostgresBin "initdb.exe"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl.exe"
$PgIsReadyExe = Join-Path $PostgresBin "pg_isready.exe"
$PsqlExe = Join-Path $PostgresBin "psql.exe"
$CreateDbExe = Join-Path $PostgresBin "createdb.exe"
$DropDbExe = Join-Path $PostgresBin "dropdb.exe"
$GitExe = (Get-Command git.exe -ErrorAction Stop).Source

$TempRoot = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::GetTempPath()
).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
)
$TempPrefix = $TempRoot + [System.IO.Path]::DirectorySeparatorChar

function Get-R0LfSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $normalized = New-Object System.IO.MemoryStream
    try {
        for ($index = 0; $index -lt $bytes.Length; $index++) {
            if (
                $bytes[$index] -eq 13 -and
                ($index + 1) -lt $bytes.Length -and
                $bytes[$index + 1] -eq 10
            ) {
                continue
            }
            $normalized.WriteByte($bytes[$index])
        }
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            return (($sha.ComputeHash($normalized.ToArray()) |
                ForEach-Object { $_.ToString("x2") }) -join "").ToUpperInvariant()
        }
        finally {
            $sha.Dispose()
        }
    }
    finally {
        $normalized.Dispose()
    }
}

function Assert-R0ProductHashes {
    foreach ($entry in $ExpectedProductHashes.GetEnumerator()) {
        $path = Join-Path $WorkspaceRoot $entry.Key
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "R0_ROOM3_PRODUCT_FILE_MISSING: $($entry.Key)"
        }
        $actual = Get-R0LfSha256 -Path $path
        if ($actual -ne $entry.Value) {
            throw (
                "R0_ROOM3_PRODUCT_HASH_MISMATCH: {0};expected={1};actual={2}" -f
                $entry.Key, $entry.Value, $actual
            )
        }
    }
    foreach ($relative in $RequiredProductFiles) {
        $path = Join-Path $WorkspaceRoot $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "R0_ROOM3_PRODUCT_FILE_MISSING: $relative"
        }
        $actual = Get-R0LfSha256 -Path $path
        if ($actual.Length -ne 64) {
            throw "R0_ROOM3_PRODUCT_HASH_SHAPE: $relative"
        }
    }
}

function Test-R0AllowedStatusLine {
    param([Parameter(Mandatory = $true)][string]$Line)

    if ($RequiredStatusLines -contains $Line) {
        return $true
    }
    $allOptional = $RequiredTrackedPaths + $OptionalDirtyPaths
    foreach ($path in $allOptional) {
        if ($Line -match [Regex]::Escape($path)) {
            return $true
        }
    }
    return $false
}

function Get-R0UnexpectedGitCount {
    $head = (& $GitExe -C $WorkspaceRoot rev-parse HEAD 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne $ExpectedHead) {
        return 1
    }
    $tracked = @(& $GitExe -C $WorkspaceRoot -c core.quotepath=false diff --name-only)
    if ($LASTEXITCODE -ne 0) {
        return 1
    }
    $allowedTracked = $RequiredTrackedPaths + $OptionalDirtyPaths
    $unexpectedTracked = @($tracked | Where-Object { $allowedTracked -notcontains $_ })
    # Required lifecycle paths may be committed clean; only fail on unexpected dirt.
    if ($unexpectedTracked.Count -ne 0) {
        return $unexpectedTracked.Count
    }
    $staged = @(& $GitExe -C $WorkspaceRoot -c core.quotepath=false diff --cached --name-only)
    if ($LASTEXITCODE -ne 0 -or $staged.Count -ne 0) {
        return [Math]::Max(1, $staged.Count)
    }
    $status = @(
        & $GitExe -C $WorkspaceRoot -c core.quotepath=false `
            status --porcelain=v1 --untracked-files=all
    )
    if ($LASTEXITCODE -ne 0) {
        return 1
    }
    $unexpected = @($status | Where-Object { -not (Test-R0AllowedStatusLine -Line $_) })
    return $unexpected.Count
}

function New-R0OwnedTempPath {
    param([Parameter(Mandatory = $true)][string]$Prefix)

    $leaf = $Prefix + [Guid]::NewGuid().ToString("N")
    $path = [System.IO.Path]::GetFullPath((Join-Path $TempRoot $leaf))
    if (
        -not $path.StartsWith($TempPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Parent $path) -ne $TempRoot -or
        (Split-Path -Leaf $path) -notmatch '^[a-z0-9-]+[0-9a-f]{32}$' -or
        (Test-Path -LiteralPath $path)
    ) {
        throw "R0_ROOM3_TEMP_PATH_PREFLIGHT_FAILED: $path"
    }
    return $path
}

function Test-R0SafeOwnedTempPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $resolved = [System.IO.Path]::GetFullPath($Path)
    return (
        $resolved.StartsWith($TempPrefix, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Parent $resolved) -eq $TempRoot -and
        (Split-Path -Leaf $resolved) -match
            '^sswcenter-(r0-room3|restore-review-room3)-[a-z0-9-]*[0-9a-f]{32}$'
    )
}

function Get-R0OwnedProcesses {
    param([string]$OwnedClusterRoot = "")

    $portPattern = "(?:^|\s)-p(?:\s+|=)$Port(?:\s|$)"
    return @(
        Get-CimInstance Win32_Process -ErrorAction Stop |
            Where-Object {
                $_.Name -match '^(postgres|pg_ctl)\.exe$' -and
                $_.CommandLine -and
                (
                    $_.CommandLine -match $portPattern -or
                    (
                        -not [string]::IsNullOrWhiteSpace($OwnedClusterRoot) -and
                        $_.CommandLine.IndexOf(
                            $OwnedClusterRoot,
                            [StringComparison]::OrdinalIgnoreCase
                        ) -ge 0
                    )
                )
            }
    )
}

function Invoke-R0Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$FailureMarker
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMarker exit=$LASTEXITCODE"
    }
}

if ($Port -ne 55448) {
    throw "R0_ROOM3_PORT_MUST_BE_55448"
}
if (-not (Test-Path -LiteralPath $TempRoot -PathType Container)) {
    throw "R0_ROOM3_TEMP_ROOT_MISSING: $TempRoot"
}
foreach (
    $executable in @(
        $ResolvedPythonExe,
        $PowerShellExe,
        $InitDbExe,
        $PgCtlExe,
        $PgIsReadyExe,
        $PsqlExe,
        $CreateDbExe,
        $DropDbExe,
        $GitExe
    )
) {
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "R0_ROOM3_EXECUTABLE_MISSING: $executable"
    }
}

$ClusterRoot = New-R0OwnedTempPath -Prefix "sswcenter-r0-room3-cluster-"
$Source0018Root = New-R0OwnedTempPath -Prefix "sswcenter-r0-room3-source-0018-"
$Source0019Root = New-R0OwnedTempPath -Prefix "sswcenter-r0-room3-source-0019-"
$Backup0018Root = New-R0OwnedTempPath -Prefix "sswcenter-r0-room3-backup-0018-"
$Backup0019Root = New-R0OwnedTempPath -Prefix "sswcenter-r0-room3-backup-0019-"
$Review0018Root = New-R0OwnedTempPath -Prefix "sswcenter-restore-review-room3-0018-"
$Review0019Root = New-R0OwnedTempPath -Prefix "sswcenter-restore-review-room3-0019-"
$OwnedRoots = @(
    $ClusterRoot,
    $Source0018Root,
    $Source0019Root,
    $Backup0018Root,
    $Backup0019Root,
    $Review0018Root,
    $Review0019Root
)
if (@($OwnedRoots | Select-Object -Unique).Count -ne 7) {
    throw "R0_ROOM3_TEMP_PATHS_NOT_DISTINCT"
}
foreach ($root in $OwnedRoots) {
    if (-not (Test-R0SafeOwnedTempPath -Path $root)) {
        throw "R0_ROOM3_TEMP_PATH_NOT_OWNED: $root"
    }
}

$DataDirectory = Join-Path $ClusterRoot "data"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$AdminUrl = "postgresql+psycopg://postgres@127.0.0.1:$Port/postgres"
$Source0018Url = "postgresql+psycopg://erp_owner@127.0.0.1:$Port/$Source0018Database"
$Source0019Url = "postgresql+psycopg://erp_owner@127.0.0.1:$Port/$Source0019Database"
$Review0018Url = "postgresql+psycopg://erp_owner@127.0.0.1:$Port/$Review0018Database"
$Review0019Url = "postgresql+psycopg://erp_owner@127.0.0.1:$Port/$Review0019Database"
$ClusterStarted = $false
$PrimaryFailure = $null
$CleanupFailures = New-Object System.Collections.Generic.List[string]
$ArtifactCount = 0
$ListenerCount = 0
$ProcessCount = 0
$TempCount = 0
$GitCount = 0

try {
    Assert-R0ProductHashes
    $initialGitCount = Get-R0UnexpectedGitCount
    if ($initialGitCount -ne 0) {
        throw "R0_ROOM3_GIT_PREFLIGHT_FAILED: unexpected=$initialGitCount"
    }
    $initialListeners = @(
        Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    )
    $initialProcesses = @(Get-R0OwnedProcesses)
    if ($initialListeners.Count -ne 0 -or $initialProcesses.Count -ne 0) {
        throw (
            "R0_ROOM3_PORT_PREFLIGHT_FAILED: listener={0};process={1}" -f
            $initialListeners.Count, $initialProcesses.Count
        )
    }
    Write-Output "R0_ROOM3_PREFLIGHT head=$ExpectedHead port=$Port roots_absent=7 roots_distinct=7"

    New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
    Invoke-R0Native `
        -FilePath $InitDbExe `
        -ArgumentList @(
            "--pgdata=$DataDirectory",
            "--username=postgres",
            "--auth=trust",
            "--encoding=UTF8",
            "--locale=C",
            "--no-sync"
        ) `
        -FailureMarker "R0_ROOM3_INITDB_FAILED"
    Invoke-R0Native `
        -FilePath $PgCtlExe `
        -ArgumentList @(
            "--pgdata=$DataDirectory",
            "--log=$LogFile",
            "--options=-h 127.0.0.1 -p $Port",
            "start",
            "--wait"
        ) `
        -FailureMarker "R0_ROOM3_PG_START_FAILED"
    $ClusterStarted = $true
    Invoke-R0Native `
        -FilePath $PgIsReadyExe `
        -ArgumentList @(
            "--host=127.0.0.1",
            "--port=$Port",
            "--username=postgres",
            "--dbname=postgres",
            "--timeout=10"
        ) `
        -FailureMarker "R0_ROOM3_PG_NOT_READY"

    $artifactSql = (
        "SELECT count(*) FROM pg_database WHERE datname IN (" +
        (($DatabaseNames | ForEach-Object { "'$_'" }) -join ",") +
        ")"
    )
    $preexistingArtifacts = @(
        & $PsqlExe -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -p $Port `
            -U postgres -d postgres -tAc $artifactSql
    )
    if ($LASTEXITCODE -ne 0 -or ($preexistingArtifacts -join "").Trim() -ne "0") {
        throw "R0_ROOM3_DATABASE_PREFLIGHT_FAILED"
    }

    Invoke-R0Native `
        -FilePath $PsqlExe `
        -ArgumentList @(
            "-X",
            "-v", "ON_ERROR_STOP=1",
            "-h", "127.0.0.1",
            "-p", [string]$Port,
            "-U", "postgres",
            "-d", "postgres",
            "-c",
            (
                "CREATE ROLE erp_owner LOGIN; " +
                "CREATE ROLE erp_app LOGIN; " +
                "CREATE ROLE erp_backup LOGIN;"
            )
        ) `
        -FailureMarker "R0_ROOM3_ROLE_CREATE_FAILED"
    foreach ($database in @($Source0018Database, $Source0019Database)) {
        Invoke-R0Native `
            -FilePath $CreateDbExe `
            -ArgumentList @(
                "-h", "127.0.0.1",
                "-p", [string]$Port,
                "-U", "postgres",
                "-O", "erp_owner",
                $database
            ) `
            -FailureMarker "R0_ROOM3_SOURCE_DATABASE_CREATE_FAILED"
    }

    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_R0_ROOM3_LIFECYCLE = "1"
    $env:SSWCENTER_R0_ROOM3_PYTHON_EXE = $ResolvedPythonExe
    $env:SSWCENTER_R0_ROOM3_POWERSHELL_EXE = $PowerShellExe
    $env:SSWCENTER_R0_ROOM3_ADMIN_URL = $AdminUrl
    $env:SSWCENTER_R0_ROOM3_0018_SOURCE_URL = $Source0018Url
    $env:SSWCENTER_R0_ROOM3_0019_SOURCE_URL = $Source0019Url
    $env:SSWCENTER_R0_ROOM3_0018_REVIEW_URL = $Review0018Url
    $env:SSWCENTER_R0_ROOM3_0019_REVIEW_URL = $Review0019Url
    $env:SSWCENTER_R0_ROOM3_TEMP_ROOT = $TempRoot
    $env:SSWCENTER_R0_ROOM3_0018_SOURCE_ROOT = $Source0018Root
    $env:SSWCENTER_R0_ROOM3_0019_SOURCE_ROOT = $Source0019Root
    $env:SSWCENTER_R0_ROOM3_0018_BACKUP_ROOT = $Backup0018Root
    $env:SSWCENTER_R0_ROOM3_0019_BACKUP_ROOT = $Backup0019Root
    $env:SSWCENTER_R0_ROOM3_0018_REVIEW_ROOT = $Review0018Root
    $env:SSWCENTER_R0_ROOM3_0019_REVIEW_ROOT = $Review0019Root
    $env:SSWCENTER_PIN_PEPPER = "r0-room3-pin-pepper"
    $env:SSWCENTER_PIN_LOOKUP_KEY = "r0-room3-pin-lookup"
    $env:SSWCENTER_CSRF_SIGNING_KEY = "r0-room3-csrf"
    $env:SSWCENTER_RESIDENT_NUMBER_KEY_V1 =
        "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    $env:SSWCENTER_RESIDENT_NUMBER_LOOKUP_KEY =
        "YWJjZGVmMDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODk="
    $env:SSWCENTER_RESIDENT_NUMBER_ACTIVE_KEY_VERSION = "1"
    $env:SSWCENTER_DATA_ROOT = Join-Path $ClusterRoot "sswcenter-r0-room3-settings-data"
    New-Item -ItemType Directory -Path $env:SSWCENTER_DATA_ROOT -Force | Out-Null
    Remove-Item Env:SSWCENTER_DATABASE_URL -ErrorAction SilentlyContinue

    Push-Location $BackendRoot
    try {
        & $ResolvedPythonExe -B -m pytest -q -s -p no:cacheprovider `
            "tests/test_r0_w2_read_only_lifecycle.py"
        $pytestExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    Write-Output "R0_ROOM3_PYTEST_EXIT=$pytestExitCode"
    if ($pytestExitCode -ne 0) {
        throw "R0_ROOM3_PYTEST_FAILED exit=$pytestExitCode"
    }

    Assert-R0ProductHashes
    $postTestGitCount = Get-R0UnexpectedGitCount
    if ($postTestGitCount -ne 0) {
        throw "R0_ROOM3_GIT_POSTTEST_FAILED: unexpected=$postTestGitCount"
    }
}
catch {
    $PrimaryFailure = $_
    Write-Output ("R0_ROOM3_FAILURE {0}" -f $_.Exception.Message)
}
finally {
    if ($ClusterStarted) {
        foreach ($database in $DatabaseNames) {
            & $DropDbExe -h 127.0.0.1 -p $Port -U postgres --if-exists $database 2>$null |
                Out-Null
            if ($LASTEXITCODE -ne 0) {
                $CleanupFailures.Add("dropdb:$database")
            }
        }
        $artifactSql = (
            "SELECT count(*) FROM pg_database WHERE datname IN (" +
            (($DatabaseNames | ForEach-Object { "'$_'" }) -join ",") +
            ")"
        )
        $artifactResult = @(
            & $PsqlExe -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -p $Port `
                -U postgres -d postgres -tAc $artifactSql 2>$null
        )
        if ($LASTEXITCODE -eq 0 -and ($artifactResult -join "").Trim() -match '^\d+$') {
            $ArtifactCount = [int](($artifactResult -join "").Trim())
        }
        else {
            $ArtifactCount = -1
            $CleanupFailures.Add("artifact-query")
        }

        & $PgCtlExe --pgdata=$DataDirectory stop --mode=fast --wait 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            $CleanupFailures.Add("pg-ctl-stop")
        }
        $ClusterStarted = $false
    }

    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $ownedProcesses = @(Get-R0OwnedProcesses -OwnedClusterRoot $ClusterRoot)
        if ($ownedProcesses.Count -eq 0) {
            break
        }
        Start-Sleep -Milliseconds 250
    }
    $ownedProcesses = @(Get-R0OwnedProcesses -OwnedClusterRoot $ClusterRoot)
    if ($ownedProcesses.Count -gt 0) {
        foreach ($process in $ownedProcesses) {
            try {
                Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction Stop
            }
            catch {
                $CleanupFailures.Add("stop-process:$($process.ProcessId)")
            }
        }
        Start-Sleep -Milliseconds 500
    }

    $CleanupRoots = @(
        $Source0018Root,
        $Source0019Root,
        $Backup0018Root,
        $Backup0019Root,
        $Review0018Root,
        $Review0019Root,
        $ClusterRoot
    )
    foreach ($root in $CleanupRoots) {
        if (-not (Test-R0SafeOwnedTempPath -Path $root)) {
            $CleanupFailures.Add("unsafe-root:$root")
            continue
        }
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if (-not (Test-Path -LiteralPath $root)) {
                break
            }
            try {
                Remove-Item -LiteralPath $root -Recurse -Force
            }
            catch {
                if ($attempt -lt 19) {
                    Start-Sleep -Milliseconds 250
                }
            }
        }
        if (Test-Path -LiteralPath $root) {
            try {
                [System.IO.Directory]::Delete($root, $true)
            }
            catch {
                $CleanupFailures.Add("remove-root:$root")
            }
        }
    }

    $ListenerCount = @(
        Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    ).Count
    $ProcessCount = @(Get-R0OwnedProcesses -OwnedClusterRoot $ClusterRoot).Count
    $TempCount = @($OwnedRoots | Where-Object { Test-Path -LiteralPath $_ }).Count
    try {
        Assert-R0ProductHashes
        $GitCount = Get-R0UnexpectedGitCount
    }
    catch {
        $GitCount = 1
        $CleanupFailures.Add("product-hash-or-git")
    }
}

Write-Output (
    "R0_ROOM3_CLEANUP listener={0} process={1} temp={2} artifact={3} git={4}" -f
    $ListenerCount, $ProcessCount, $TempCount, $ArtifactCount, $GitCount
)

$CleanupFailed = (
    $ListenerCount -ne 0 -or
    $ProcessCount -ne 0 -or
    $TempCount -ne 0 -or
    $ArtifactCount -ne 0 -or
    $GitCount -ne 0 -or
    $CleanupFailures.Count -ne 0
)
if ($null -ne $PrimaryFailure -or $CleanupFailed) {
    if ($CleanupFailures.Count -gt 0) {
        Write-Output ("R0_ROOM3_CLEANUP_FAILURES {0}" -f ($CleanupFailures -join ","))
    }
    if ($null -ne $PrimaryFailure) {
        throw $PrimaryFailure
    }
    throw "R0_ROOM3_CLEANUP_FAILED"
}

Write-Output "R0_ROOM3_POSTGRES_GREEN"
