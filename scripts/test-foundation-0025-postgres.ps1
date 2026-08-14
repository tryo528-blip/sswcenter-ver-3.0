param(
    [Parameter(Mandatory = $true)]
    [string]$ExpectedSha,

    [int]$Port = 55433,

    [string]$PythonExe
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "PostgresTools.psm1") -Force

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$ResolvedPythonExe = if ($PSBoundParameters.ContainsKey("PythonExe")) {
    [System.IO.Path]::GetFullPath($PythonExe)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $BackendRoot "\.venv\Scripts\python.exe"))
}
$CurrentRevision = "20260813_0025_w1_relationship_lock_contract_correction"
$CurrentMarker = "SSWCENTER_CURRENT_0025_DB_POSTCHECK_OK"
$CurrentHeadMarker = "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK"
$ExpectedPrefix = "FOUNDATION_0025_"

if ($ExpectedSha -notmatch "^[0-9a-fA-F]{40}$") {
    throw "FOUNDATION_0025_EXPECTED_SHA_INVALID"
}
if (-not (Test-Path -LiteralPath $ResolvedPythonExe -PathType Leaf)) {
    throw "FOUNDATION_0025_PYTHON_MISSING"
}

$Head = ((& git -C $WorkspaceRoot rev-parse HEAD 2>$null) -join "").Trim()
if ($LASTEXITCODE -ne 0 -or $Head -ne $ExpectedSha) {
    throw "FOUNDATION_0025_EXPECTED_SHA_MISMATCH"
}
$InitialGitStatus = ((& git -C $WorkspaceRoot status --porcelain --untracked-files=all 2>$null) -join "").Trim()
if ($LASTEXITCODE -ne 0 -or $InitialGitStatus) {
    throw "FOUNDATION_0025_WORKTREE_NOT_CLEAN"
}

$PostgresBin = "C:\Program Files\PostgreSQL\17\bin"
$InitDbExe = Join-Path $PostgresBin "initdb.exe"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl.exe"
$PgIsReadyExe = Join-Path $PostgresBin "pg_isready.exe"
$CreateDbExe = Join-Path $PostgresBin "createdb.exe"
$DropDbExe = Join-Path $PostgresBin "dropdb.exe"
$PsqlExe = Join-Path $PostgresBin "psql.exe"
foreach ($Executable in @(
        $InitDbExe,
        $PgCtlExe,
        $PgIsReadyExe,
        $CreateDbExe,
        $DropDbExe,
        $PsqlExe
    )) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "FOUNDATION_0025_POSTGRES_EXECUTABLE_MISSING"
    }
}
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "FOUNDATION_0025_PORT_IN_USE"
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "FOUNDATION_0025_LOCALAPPDATA_MISSING"
}

$TempParent = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Temp")).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
)
if (-not (Test-Path -LiteralPath $TempParent -PathType Container)) {
    throw "FOUNDATION_0025_TEMP_PARENT_MISSING"
}
$TempPrefix = $TempParent + [System.IO.Path]::DirectorySeparatorChar
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $TempParent ("sswcenter-foundation-0025-pg-" + [Guid]::NewGuid().ToString("N")))
)
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (
    -not $ClusterRoot.StartsWith($TempPrefix, [StringComparison]::OrdinalIgnoreCase) -or
    $ClusterLeaf -cnotmatch '^sswcenter-foundation-0025-pg-[0-9a-f]{32}$'
) {
    throw "FOUNDATION_0025_UNSAFE_CLUSTER_PATH"
}

$DataDirectory = Join-Path $ClusterRoot "data"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$BackendCopy = Join-Path $ClusterRoot "backend-copy"
$DataRoot = Join-Path $ClusterRoot "sswcenter-foundation-0025-data"
$BackupRoot = Join-Path $ClusterRoot "sswcenter-foundation-0025-backups"
$ReviewDataRoot = Join-Path $ClusterRoot (
    "sswcenter-restore-review-" + [Guid]::NewGuid().ToString("N")
)
$TargetDatabaseName = "sswcenter_dev"
$ReviewDatabaseName = "sswcenter_foundation_0025_review"
$SourceDatabaseUrl = "postgresql+psycopg://postgres@127.0.0.1:$Port/postgres"
$TargetDatabaseUrl = "postgresql+psycopg://postgres@127.0.0.1:$Port/$TargetDatabaseName"
$RevisionQuery = "SELECT version_num FROM erp.alembic_version"
$CenterCode = "FOUNDATION_0025_SYNTHETIC"
$DataFileRelative = "blobs/foundation-0025.txt"
$DataFileContent = "foundation-0025-deterministic-payload`n"

$ClusterStarted = $false
$RunSucceeded = $false
$PrimaryFailure = $null
$CleanupFailure = $null
$ReviewDatabaseCreated = $false
$ReviewDataRootCreated = $false
$TargetDatabaseCreated = $false
$BackupDirectory = $null
$MaintenanceBefore = $null
$MaintenanceAfter = $null
$RowShaBefore = $null
$FileShaBefore = $null
$BaselinePostgresIds = @(
    Get-Process -Name postgres -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Id
)
$StartedPostgresIds = @()

function Invoke-FoundationPsqlScalar {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DatabaseName,

        [Parameter(Mandatory = $true)]
        [string]$Query
    )

    $Output = & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -d $DatabaseName `
        -tAc $Query 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "FOUNDATION_0025_PSQL_FAILED"
    }
    return (($Output -join "").Trim())
}

function Invoke-FoundationPsql {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DatabaseName,

        [Parameter(Mandatory = $true)]
        [string]$Query
    )

    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -d $DatabaseName `
        -c $Query `
        | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "FOUNDATION_0025_PSQL_COMMAND_FAILED"
    }
}

function Get-FoundationSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Value
    )

    $Encoding = [System.Text.UTF8Encoding]::new($false)
    $Bytes = $Encoding.GetBytes($Value)
    $Hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        return (
            $Hasher.ComputeHash($Bytes) |
                ForEach-Object { $_.ToString("x2") }
        ) -join ""
    }
    finally {
        $Hasher.Dispose()
    }
}

function Copy-FoundationBackendTree {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,

        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    foreach ($Entry in Get-ChildItem -LiteralPath $Source -Force) {
        if ($Entry.Name -in @(".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache")) {
            continue
        }
        if ($Entry.Name -like ".env*") {
            continue
        }
        $Target = Join-Path $Destination $Entry.Name
        if ($Entry.PSIsContainer) {
            Copy-FoundationBackendTree -Source $Entry.FullName -Destination $Target
        }
        else {
            Copy-Item -LiteralPath $Entry.FullName -Destination $Target
        }
    }
}

function Get-FoundationGitStatus {
    return ((& git -C $WorkspaceRoot status --porcelain --untracked-files=all 2>$null) -join "").Trim()
}

try {
    $PreviousTemp = $env:TEMP
    $PreviousTmp = $env:TMP
    $PreviousTmpDir = $env:TMPDIR
    $env:TEMP = $TempParent
    $env:TMP = $TempParent
    $env:TMPDIR = $TempParent
    $env:PGCLIENTENCODING = "UTF8"

    New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
    & $InitDbExe `
        --pgdata=$DataDirectory `
        --username=postgres `
        --auth=trust `
        --encoding=UTF8 `
        --locale=C `
        | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "FOUNDATION_0025_INITDB_FAILED"
    }
    & $PgCtlExe `
        --pgdata=$DataDirectory `
        --log=$LogFile `
        --options="-h 127.0.0.1 -p $Port" `
        start
    if ($LASTEXITCODE -ne 0) {
        throw "FOUNDATION_0025_POSTGRES_START_FAILED"
    }
    $ClusterStarted = $true
    & $PgIsReadyExe -h 127.0.0.1 -p $Port -U postgres -d postgres -t 15 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "FOUNDATION_0025_POSTGRES_NOT_READY"
    }
    Write-Output "FOUNDATION_0025_STAGE=postgres_ready"
    $StartedPostgresIds = @(
        Get-Process -Name postgres -ErrorAction SilentlyContinue |
            Where-Object { $BaselinePostgresIds -notcontains $_.Id } |
            Select-Object -ExpandProperty Id
    )

    $MaintenanceBefore = Invoke-FoundationPsqlScalar -DatabaseName "postgres" -Query (
        "SELECT COALESCE(to_regnamespace('erp')::text, '') || '|' || " +
        "(SELECT count(*)::text FROM pg_tables WHERE schemaname = 'erp') || '|' || " +
        "COALESCE(to_regclass('erp.alembic_version')::text, '')"
    )
    Write-Output "FOUNDATION_0025_STAGE=maintenance_fingerprint"

    Copy-FoundationBackendTree -Source $BackendRoot -Destination $BackendCopy
    Write-Output "FOUNDATION_0025_STAGE=backend_copy"
    $TempEnv = @(
        "SSWCENTER_ENVIRONMENT=development",
        "SSWCENTER_DATABASE_URL=$SourceDatabaseUrl",
        "SSWCENTER_DATA_ROOT=$DataRoot"
    ) -join [Environment]::NewLine
    [System.IO.File]::WriteAllText(
        (Join-Path $BackendCopy ".env"),
        $TempEnv + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
    New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null

    $PreviousEnvironment = @{}
    foreach ($EnvironmentName in @(
            "SSWCENTER_ENVIRONMENT",
            "SSWCENTER_DATABASE_URL",
            "SSWCENTER_DATA_ROOT",
            "PYTHONDONTWRITEBYTECODE"
        )) {
        $PreviousEnvironment[$EnvironmentName] = [Environment]::GetEnvironmentVariable(
            $EnvironmentName,
            "Process"
        )
    }
    Push-Location $BackendCopy
    try {
        $env:SSWCENTER_ENVIRONMENT = "development"
        $env:SSWCENTER_DATABASE_URL = $SourceDatabaseUrl
        $env:SSWCENTER_DATA_ROOT = $DataRoot
        $env:PYTHONDONTWRITEBYTECODE = "1"
        $InitOutput = @(& $ResolvedPythonExe -m app.db.init_development)
        $InitExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
        foreach ($EnvironmentName in $PreviousEnvironment.Keys) {
            $PreviousValue = $PreviousEnvironment[$EnvironmentName]
            if ($null -eq $PreviousValue) {
                Remove-Item -LiteralPath "Env:$EnvironmentName" -ErrorAction SilentlyContinue
            }
            else {
                Set-Item -Path "Env:$EnvironmentName" -Value $PreviousValue
            }
        }
    }
    if ($InitExitCode -ne 0) {
        throw "FOUNDATION_0025_INIT_FAILED"
    }
    Write-Output "FOUNDATION_0025_STAGE=development_init"
    foreach ($Marker in @($CurrentMarker, $CurrentHeadMarker, "DEFAULT_POSTGRES_UNCHANGED")) {
        if ($InitOutput -notcontains $Marker) {
            throw "FOUNDATION_0025_INIT_MARKER_MISSING"
        }
    }
    $MaintenanceAfter = Invoke-FoundationPsqlScalar -DatabaseName "postgres" -Query (
        "SELECT COALESCE(to_regnamespace('erp')::text, '') || '|' || " +
        "(SELECT count(*)::text FROM pg_tables WHERE schemaname = 'erp') || '|' || " +
        "COALESCE(to_regclass('erp.alembic_version')::text, '')"
    )
    if ($MaintenanceAfter -ne $MaintenanceBefore) {
        throw "FOUNDATION_0025_MAINTENANCE_CHANGED"
    }
    Write-Output "FOUNDATION_0025_INIT_GREEN"

    Invoke-FoundationPsql -DatabaseName $TargetDatabaseName -Query (
        "INSERT INTO erp.center (center_code, center_name) VALUES " +
        "('$CenterCode', 'Foundation 0025 Synthetic')"
    )
    $RowJsonBefore = Invoke-FoundationPsqlScalar -DatabaseName $TargetDatabaseName -Query (
        "SELECT row_to_json(c)::text FROM erp.center AS c WHERE c.center_code = '$CenterCode'"
    )
    if ([string]::IsNullOrWhiteSpace($RowJsonBefore)) {
        throw "FOUNDATION_0025_SYNTHETIC_ROW_MISSING"
    }
    $RowShaBefore = Get-FoundationSha256 -Value $RowJsonBefore

    $DataFile = Join-Path $DataRoot $DataFileRelative
    New-Item -ItemType Directory -Path (Split-Path -Parent $DataFile) -Force | Out-Null
    [System.IO.File]::WriteAllText(
        $DataFile,
        $DataFileContent,
        [System.Text.UTF8Encoding]::new($false)
    )
    $FileShaBefore = (Get-FileHash -LiteralPath $DataFile -Algorithm SHA256).Hash.ToLowerInvariant()

    $BackupOutput = @(& (Join-Path $PSScriptRoot "backup-postgres.ps1") `
        -DatabaseUrl $TargetDatabaseUrl `
        -DestinationRoot $BackupRoot `
        -DataRoot $DataRoot `
        -AppVersion "foundation-0025-test")
    if ($LASTEXITCODE -ne 0) {
        throw "FOUNDATION_0025_BACKUP_FAILED"
    }
    Write-Output "FOUNDATION_0025_STAGE=backup"
    $BackupLine = @($BackupOutput | ForEach-Object { [string]$_ } | Where-Object {
        $_ -like "BACKUP_OK *"
    }) | Select-Object -Last 1
    if ($null -eq $BackupLine) {
        throw "FOUNDATION_0025_BACKUP_MARKER_MISSING"
    }
    $BackupDirectory = $BackupLine.Substring("BACKUP_OK ".Length).Trim()
    if (-not (Test-Path -LiteralPath $BackupDirectory -PathType Container)) {
        throw "FOUNDATION_0025_BACKUP_DIRECTORY_MISSING"
    }
    $Manifest = Get-Content -LiteralPath (Join-Path $BackupDirectory "manifest.json") -Raw |
        ConvertFrom-Json
    if ([string]$Manifest.alembic_revision -ne $CurrentRevision) {
        throw "FOUNDATION_0025_BACKUP_REVISION_MISMATCH"
    }
    Write-Output "FOUNDATION_0025_BACKUP_GREEN"

    $RestoreOutput = @(& (Join-Path $PSScriptRoot "restore-drill.ps1") `
        -BackupDirectory $BackupDirectory `
        -AdminDatabaseUrl $SourceDatabaseUrl `
        -ReviewDatabaseName $ReviewDatabaseName `
        -ReviewDataRoot $ReviewDataRoot `
        -KeepReviewArtifacts `
        -PythonExe $ResolvedPythonExe)
    if ($LASTEXITCODE -ne 0) {
        throw "FOUNDATION_0025_RESTORE_FAILED"
    }
    Write-Output "FOUNDATION_0025_STAGE=restore"
    $ReviewDatabaseCreated = $true
    $ReviewDataRootCreated = $true
    if (-not (@($RestoreOutput | ForEach-Object { [string]$_ }) -contains "RESTORE_DRILL_OK $ReviewDatabaseName")) {
        throw "FOUNDATION_0025_RESTORE_MARKER_MISSING"
    }

    $RestoredRevision = Invoke-FoundationPsqlScalar -DatabaseName $ReviewDatabaseName -Query $RevisionQuery
    if ($RestoredRevision -ne $CurrentRevision) {
        throw "FOUNDATION_0025_RESTORE_REVISION_MISMATCH"
    }
    $RowJsonAfter = Invoke-FoundationPsqlScalar -DatabaseName $ReviewDatabaseName -Query (
        "SELECT row_to_json(c)::text FROM erp.center AS c WHERE c.center_code = '$CenterCode'"
    )
    $RowShaAfter = Get-FoundationSha256 -Value $RowJsonAfter
    if ($RowShaAfter -ne $RowShaBefore) {
        throw "FOUNDATION_0025_RESTORE_ROW_HASH_MISMATCH"
    }
    $RestoredDataFile = Join-Path $ReviewDataRoot $DataFileRelative
    if (-not (Test-Path -LiteralPath $RestoredDataFile -PathType Leaf)) {
        throw "FOUNDATION_0025_RESTORE_FILE_MISSING"
    }
    $FileShaAfter = (Get-FileHash -LiteralPath $RestoredDataFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($FileShaAfter -ne $FileShaBefore) {
        throw "FOUNDATION_0025_RESTORE_FILE_HASH_MISMATCH"
    }
    $MaintenanceAfterRestore = Invoke-FoundationPsqlScalar -DatabaseName "postgres" -Query (
        "SELECT COALESCE(to_regnamespace('erp')::text, '') || '|' || " +
        "(SELECT count(*)::text FROM pg_tables WHERE schemaname = 'erp') || '|' || " +
        "COALESCE(to_regclass('erp.alembic_version')::text, '')"
    )
    if ($MaintenanceAfterRestore -ne $MaintenanceBefore) {
        throw "FOUNDATION_0025_RESTORE_MAINTENANCE_CHANGED"
    }
    Write-Output "FOUNDATION_0025_RESTORE_GREEN"
    $RunSucceeded = $true
}
catch {
    $PrimaryFailure = $_.Exception
}
finally {
    try {
        if ($ClusterStarted) {
            foreach ($DatabaseName in @($ReviewDatabaseName, $TargetDatabaseName)) {
                & $DropDbExe `
                    -h 127.0.0.1 `
                    -p $Port `
                    -U postgres `
                    --if-exists `
                    $DatabaseName `
                    | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    throw "FOUNDATION_0025_DATABASE_CLEANUP_FAILED"
                }
            }
            $ReviewDatabaseCreated = $false
            $TargetDatabaseCreated = $false
            if (Test-Path -LiteralPath $ReviewDataRoot) {
                Remove-Item -LiteralPath $ReviewDataRoot -Recurse -Force
            }
            $ReviewDataRootCreated = $false
            & $PgCtlExe --pgdata=$DataDirectory --mode=fast stop --wait
            if ($LASTEXITCODE -ne 0) {
                throw "FOUNDATION_0025_POSTGRES_STOP_FAILED"
            }
            $ClusterStarted = $false
        }
        if (Test-Path -LiteralPath $ClusterRoot) {
            [System.IO.Directory]::Delete($ClusterRoot, $true)
        }
        $ListenerCount = @(
            Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
        ).Count
        $RemainingStartedIds = @(
            Get-Process -Name postgres -ErrorAction SilentlyContinue |
                Where-Object { $StartedPostgresIds -contains $_.Id } |
                Select-Object -ExpandProperty Id
        )
        $ProcessCount = @($RemainingStartedIds).Count
        $TempCount = if (Test-Path -LiteralPath $ClusterRoot) { 1 } else { 0 }
        $ArtifactCount = @(
            @($BackendCopy, $DataRoot, $BackupRoot, $ReviewDataRoot) |
                Where-Object { Test-Path -LiteralPath $_ }
        ).Count
        $DatabaseCount = 0
        $GitStatus = Get-FoundationGitStatus
        $GitCount = if ($GitStatus) { 1 } else { 0 }
        if ($ListenerCount -ne 0 -or $ProcessCount -ne 0 -or $TempCount -ne 0 -or
            $ArtifactCount -ne 0 -or $DatabaseCount -ne 0 -or $GitCount -ne 0) {
            throw "FOUNDATION_0025_CLEANUP_NOT_ZERO"
        }
        Write-Output (
            "FOUNDATION_0025_CLEANUP listener={0} process={1} temp={2} database={3} artifact={4} git={5}" -f
            $ListenerCount,
            $ProcessCount,
            $TempCount,
            $DatabaseCount,
            $ArtifactCount,
            $GitCount
        )
    }
    catch {
        $CleanupFailure = $_.Exception
    }
    finally {
        if ($null -ne $PreviousTemp) { $env:TEMP = $PreviousTemp }
        else { Remove-Item Env:TEMP -ErrorAction SilentlyContinue }
        if ($null -ne $PreviousTmp) { $env:TMP = $PreviousTmp }
        else { Remove-Item Env:TMP -ErrorAction SilentlyContinue }
        if ($null -ne $PreviousTmpDir) { $env:TMPDIR = $PreviousTmpDir }
        else { Remove-Item Env:TMPDIR -ErrorAction SilentlyContinue }
    }
}

if ($null -ne $PrimaryFailure) {
    if ($null -ne $CleanupFailure) {
        throw "FOUNDATION_0025_FAILED_WITH_CLEANUP_FAILURE"
    }
    throw $PrimaryFailure
}
if ($null -ne $CleanupFailure) {
    throw $CleanupFailure
}
if (-not $RunSucceeded) {
    throw "FOUNDATION_0025_RUN_NOT_GREEN"
}

Write-Output "FOUNDATION_0025_POSTGRES_GREEN"
