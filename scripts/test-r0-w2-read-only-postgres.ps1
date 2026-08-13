param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,

    [Parameter(Mandatory = $false)]
    [int]$Port = 55447
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$TestFile = Join-Path $BackendRoot "tests\test_r0_w2_read_only_postgres.py"
$VerifyScript = Join-Path $PSScriptRoot "verify-w1a-vs1-db.ps1"
# 3.0 R0-A port baseline (TASK_PACKET BASELINE_SHA); not a hard-coded 2.2 historical HEAD.
$ExpectedHead = "a5367f212acc6c70efeedb202e7999e90d9f7fc5"
$CurrentDatabase = "sswcenter_r0_current_test"
$FreshDatabase = "sswcenter_r0_fresh_test"
$ClusterPrefix = "sswcenter-r0-room2-"
$OwnerPassword = "r0_room2_owner_pw"
$AppPassword = "r0_room2_app_pw"
$BackupPassword = "r0_room2_backup_pw"
$GitCommand = Get-Command git.exe -ErrorAction Stop
$GitExe = $GitCommand.Source
$PostgresBin = "C:\Program Files\PostgreSQL\17\bin"
$InitDbExe = Join-Path $PostgresBin "initdb.exe"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl.exe"
$PgIsReadyExe = Join-Path $PostgresBin "pg_isready.exe"
$CreateDbExe = Join-Path $PostgresBin "createdb.exe"
$PsqlExe = Join-Path $PostgresBin "psql.exe"
$ResolvedPythonExe = [System.IO.Path]::GetFullPath($PythonExe)
$EnvironmentKeys = @(
    "SSWCENTER_ENVIRONMENT",
    "SSWCENTER_DATABASE_URL",
    "SSWCENTER_DATA_ROOT",
    "SSWCENTER_POSTGRES_TEST",
    "SSWCENTER_PIN_PEPPER",
    "SSWCENTER_PIN_LOOKUP_KEY",
    "SSWCENTER_CSRF_SIGNING_KEY",
    "SSWCENTER_R0_W2_REAL_PG",
    "SSWCENTER_R0_W2_CURRENT_OWNER_URL",
    "SSWCENTER_R0_W2_CURRENT_APP_URL",
    "SSWCENTER_R0_W2_CURRENT_BACKUP_URL",
    "SSWCENTER_R0_W2_FRESH_OWNER_URL",
    "SSWCENTER_R0_W2_FRESH_APP_URL",
    "SSWCENTER_R0_W2_FRESH_BACKUP_URL",
    "PYTHONDONTWRITEBYTECODE",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD"
)
$OldEnvironment = @{}
foreach ($EnvironmentKey in $EnvironmentKeys) {
    $OldEnvironment[$EnvironmentKey] = [Environment]::GetEnvironmentVariable(
        $EnvironmentKey,
        [EnvironmentVariableTarget]::Process
    )
}

function Get-R0RawSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.IO.File]::ReadAllBytes($Path)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "")
    }
    finally {
        $sha.Dispose()
    }
}

function Get-R0LfNormalizedSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $strictUtf8 = [System.Text.UTF8Encoding]::new($false, $true)
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $content = [System.IO.File]::ReadAllText($Path, $strictUtf8)
        $normalized = $content.Replace("`r`n", "`n").Replace("`r", "`n")
        return ([System.BitConverter]::ToString(
                $sha.ComputeHash($utf8.GetBytes($normalized))
            )).Replace("-", "")
    }
    finally {
        $sha.Dispose()
    }
}

function Get-R0GitStatus {
    $rows = @(& $GitExe -C $WorkspaceRoot status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) {
        throw "R0_ROOM2_GIT_STATUS_FAILED"
    }
    return @($rows | ForEach-Object { [string]$_ })
}

function Get-R0GitIndexStatus {
    $rows = @(& $GitExe -C $WorkspaceRoot diff --cached --name-status)
    if ($LASTEXITCODE -ne 0) {
        throw "R0_ROOM2_GIT_INDEX_STATUS_FAILED"
    }
    return @($rows | ForEach-Object { [string]$_ })
}

function Get-R0GitHead {
    $head = (& $GitExe -C $WorkspaceRoot rev-parse HEAD | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "R0_ROOM2_GIT_HEAD_FAILED"
    }
    return $head
}

function Invoke-R0Psql {
    param(
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Sql,
        [string]$User = "postgres"
    )
    $output = @(
        & $PsqlExe -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -p $Port `
            -U $User -d $Database -At -c $Sql 2>&1
    )
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $detail = ($output -join "`n").Trim()
        throw "R0_ROOM2_PSQL_FAILED database=$Database user=$User exit=$exitCode detail=$detail"
    }
    return @($output | ForEach-Object { [string]$_ })
}

function Get-R0OwnedPostgresProcesses {
    param([Parameter(Mandatory = $true)][string]$OwnedRoot)
    $rows = @(Get-CimInstance Win32_Process -OperationTimeoutSec 15 -ErrorAction Stop)
    $escapedRoot = [Regex]::Escape($OwnedRoot)
    return @(
        $rows | Where-Object {
            $_.Name -in @("postgres.exe", "pg_ctl.exe") -and
            [string]$_.CommandLine -match $escapedRoot
        }
    )
}

function Get-R0OwnedListeners {
    return @(
        Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    )
}

function Restore-R0Environment {
    foreach ($EnvironmentKey in $EnvironmentKeys) {
        $oldValue = $OldEnvironment[$EnvironmentKey]
        if ($null -eq $oldValue) {
            [Environment]::SetEnvironmentVariable(
                $EnvironmentKey,
                $null,
                [EnvironmentVariableTarget]::Process
            )
        }
        else {
            [Environment]::SetEnvironmentVariable(
                $EnvironmentKey,
                [string]$oldValue,
                [EnvironmentVariableTarget]::Process
            )
        }
    }
}

if ($Port -ne 55447) {
    throw "R0_ROOM2_PORT_FORBIDDEN: only port 55447 is allowed"
}
if (-not (Test-Path -LiteralPath $ResolvedPythonExe -PathType Leaf)) {
    throw "R0_ROOM2_PYTHON_MISSING: $ResolvedPythonExe"
}
if (-not (Test-Path -LiteralPath $TestFile -PathType Leaf)) {
    throw "R0_ROOM2_TEST_FILE_MISSING: $TestFile"
}
if (-not (Test-Path -LiteralPath $VerifyScript -PathType Leaf)) {
    throw "R0_ROOM2_VERIFY_SCRIPT_MISSING: $VerifyScript"
}
foreach ($Executable in @($InitDbExe, $PgCtlExe, $PgIsReadyExe, $CreateDbExe, $PsqlExe)) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "R0_ROOM2_POSTGRES_EXECUTABLE_MISSING: $Executable"
    }
}

# Byte-identical product seals. postcheck is 3.0-merged and presence-sealed only.
$ExpectedProductHashes = [ordered]@{
    "backend\alembic\versions\20260809_0018_w2_service_plan_notice.py" =
        "AB1A7FB77498CAB7EBD1163084CA98FDF9FD350F5D32A0682F81DC17EE37D716"
    "backend\alembic\versions\20260812_0019_r0_w2_read_only.py" =
        "EF7FC4917015A265D4633EFAE372314B760F193C4CFC2C98240C158CFDFB21AA"
    "scripts\restore-drill.ps1" =
        "B37B9C26C27CED5794580BA00E0CAE808C94A783B1ECA0BAA0E7A1471829C5AB"
    "scripts\verify-w1a-vs1-db.ps1" =
        "5EB67C21F12F2DAA69E791AA6AB38D64195DF7C59A52A4F85EE63D307E8EB06C"
}
$RequiredProductFiles = @(
    "backend\app\db\postcheck_w1a_vs1.py"
)
foreach ($RelativePath in $ExpectedProductHashes.Keys) {
    $ProductPath = Join-Path $WorkspaceRoot $RelativePath
    if (-not (Test-Path -LiteralPath $ProductPath -PathType Leaf)) {
        throw "R0_ROOM2_PRODUCT_FILE_MISSING: $RelativePath"
    }
    $ObservedHash = Get-R0LfNormalizedSha256 -Path $ProductPath
    if ($ObservedHash -ne $ExpectedProductHashes[$RelativePath]) {
        throw (
            "R0_ROOM2_PRODUCT_SHA_MISMATCH path={0} expected={1} actual={2}" -f
            $RelativePath, $ExpectedProductHashes[$RelativePath], $ObservedHash
        )
    }
}
foreach ($RelativePath in $RequiredProductFiles) {
    $ProductPath = Join-Path $WorkspaceRoot $RelativePath
    if (-not (Test-Path -LiteralPath $ProductPath -PathType Leaf)) {
        throw "R0_ROOM2_PRODUCT_FILE_MISSING: $RelativePath"
    }
    $ObservedHash = Get-R0LfNormalizedSha256 -Path $ProductPath
    if ($ObservedHash.Length -ne 64) {
        throw "R0_ROOM2_PRODUCT_HASH_SHAPE: $RelativePath"
    }
}

$InitialHead = Get-R0GitHead
$InitialStatus = Get-R0GitStatus
$InitialIndexStatus = Get-R0GitIndexStatus
if ($InitialHead -ne $ExpectedHead) {
    throw "R0_ROOM2_HEAD_MISMATCH expected=$ExpectedHead actual=$InitialHead"
}
$AllowedTempRoot = [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
)
if (-not (Test-Path -LiteralPath $AllowedTempRoot -PathType Container)) {
    throw "R0_ROOM2_TEMP_ROOT_MISSING: $AllowedTempRoot"
}
$AllowedTempPrefix = $AllowedTempRoot + [System.IO.Path]::DirectorySeparatorChar
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $AllowedTempRoot ($ClusterPrefix + [Guid]::NewGuid().ToString("N")))
)
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (-not $ClusterRoot.StartsWith($AllowedTempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "R0_ROOM2_TEMP_PATH_ESCAPE"
}
if (-not $ClusterLeaf.StartsWith($ClusterPrefix, [StringComparison]::Ordinal)) {
    throw "R0_ROOM2_TEMP_LEAF_INVALID"
}

$ExistingListener = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
if ($ExistingListener.Count -gt 0) {
    throw "R0_ROOM2_PORT_ALREADY_LISTENING: $Port"
}
$AmbientUrlValues = @(
    $env:SSWCENTER_DATABASE_URL,
    $env:SSWCENTER_R0_W2_CURRENT_OWNER_URL,
    $env:SSWCENTER_R0_W2_CURRENT_APP_URL,
    $env:SSWCENTER_R0_W2_CURRENT_BACKUP_URL,
    $env:SSWCENTER_R0_W2_FRESH_OWNER_URL,
    $env:SSWCENTER_R0_W2_FRESH_APP_URL,
    $env:SSWCENTER_R0_W2_FRESH_BACKUP_URL
)
foreach ($AmbientUrl in $AmbientUrlValues) {
    if (-not [string]::IsNullOrWhiteSpace([string]$AmbientUrl)) {
        if (
            [string]$AmbientUrl -match [Regex]::Escape($CurrentDatabase) -or
            [string]$AmbientUrl -match [Regex]::Escape($FreshDatabase) -or
            [string]$AmbientUrl -match (":{0}/" -f $Port)
        ) {
            throw "R0_ROOM2_AMBIENT_DATABASE_COLLISION"
        }
    }
}

$DataDirectory = Join-Path $ClusterRoot "data"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$ArtifactRoot = Join-Path $ClusterRoot "artifacts"
$RuntimeDataRoot = Join-Path $ClusterRoot "sswcenter-r0-room2-data"
$ClusterStarted = $false
$RunFailed = $false
$RunFailureDetail = ""
$CleanupFailed = $false
$CleanupFailureDetail = ""
$PytestExitCode = -1

$CurrentOwnerUrl = "postgresql+psycopg://erp_owner:{0}@127.0.0.1:{1}/{2}" -f `
    $OwnerPassword, $Port, $CurrentDatabase
$CurrentAppUrl = "postgresql+psycopg://erp_app:{0}@127.0.0.1:{1}/{2}" -f `
    $AppPassword, $Port, $CurrentDatabase
$CurrentBackupUrl = "postgresql+psycopg://erp_backup:{0}@127.0.0.1:{1}/{2}" -f `
    $BackupPassword, $Port, $CurrentDatabase
$FreshOwnerUrl = "postgresql+psycopg://erp_owner:{0}@127.0.0.1:{1}/{2}" -f `
    $OwnerPassword, $Port, $FreshDatabase
$FreshAppUrl = "postgresql+psycopg://erp_app:{0}@127.0.0.1:{1}/{2}" -f `
    $AppPassword, $Port, $FreshDatabase
$FreshBackupUrl = "postgresql+psycopg://erp_backup:{0}@127.0.0.1:{1}/{2}" -f `
    $BackupPassword, $Port, $FreshDatabase

try {
    New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $RuntimeDataRoot -Force | Out-Null

    & $InitDbExe --pgdata=$DataDirectory --username=postgres --auth=trust --encoding=UTF8 --locale=C
    if ($LASTEXITCODE -ne 0) {
        throw "R0_ROOM2_INITDB_FAILED exit=$LASTEXITCODE"
    }
    & $PgCtlExe --pgdata=$DataDirectory --log=$LogFile --options="-h 127.0.0.1 -p $Port" start
    if ($LASTEXITCODE -ne 0) {
        throw "R0_ROOM2_PGCTL_START_FAILED exit=$LASTEXITCODE"
    }
    $ClusterStarted = $true

    $ready = $false
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        & $PgIsReadyExe -h 127.0.0.1 -p $Port -U postgres -d postgres -t 1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        throw "R0_ROOM2_POSTGRES_NOT_READY"
    }

    $RoleSql = @'
CREATE ROLE erp_owner LOGIN PASSWORD 'r0_room2_owner_pw';
CREATE ROLE erp_app LOGIN PASSWORD 'r0_room2_app_pw';
CREATE ROLE erp_backup LOGIN PASSWORD 'r0_room2_backup_pw';
'@
    Invoke-R0Psql -Database "postgres" -Sql $RoleSql | Out-Null
    $roleCount = (Invoke-R0Psql -Database "postgres" -Sql (
            "SELECT count(*) FROM pg_roles WHERE rolname IN " +
            "('erp_owner','erp_app','erp_backup') AND rolcanlogin AND NOT rolsuper"
        )).Trim()
    if ($roleCount -ne "3") {
        throw "R0_ROOM2_ROLE_BOOTSTRAP_MISMATCH observed=$roleCount"
    }

    $existingDatabases = @(
        Invoke-R0Psql -Database "postgres" -Sql (
            "SELECT datname FROM pg_database WHERE datname IN " +
            "('$CurrentDatabase','$FreshDatabase') ORDER BY datname"
        )
    ) | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ }
    if (@($existingDatabases).Count -ne 0) {
        throw "R0_ROOM2_DATABASE_COLLISION: $(@($existingDatabases) -join ',')"
    }
    & $CreateDbExe -h 127.0.0.1 -p $Port -U postgres -O erp_owner $CurrentDatabase
    if ($LASTEXITCODE -ne 0) {
        throw "R0_ROOM2_CURRENT_DATABASE_CREATE_FAILED exit=$LASTEXITCODE"
    }
    & $CreateDbExe -h 127.0.0.1 -p $Port -U postgres -O erp_owner $FreshDatabase
    if ($LASTEXITCODE -ne 0) {
        throw "R0_ROOM2_FRESH_DATABASE_CREATE_FAILED exit=$LASTEXITCODE"
    }

    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_POSTGRES_TEST = "1"
    $env:SSWCENTER_DATA_ROOT = $RuntimeDataRoot
    $env:SSWCENTER_PIN_PEPPER = "r0-room2-pin-pepper-20260812"
    $env:SSWCENTER_PIN_LOOKUP_KEY = "r0-room2-pin-lookup-key-20260812"
    $env:SSWCENTER_CSRF_SIGNING_KEY = "r0-room2-csrf-signing-key-20260812"
    $env:SSWCENTER_R0_W2_REAL_PG = "1"
    $env:SSWCENTER_R0_W2_CURRENT_OWNER_URL = $CurrentOwnerUrl
    $env:SSWCENTER_R0_W2_CURRENT_APP_URL = $CurrentAppUrl
    $env:SSWCENTER_R0_W2_CURRENT_BACKUP_URL = $CurrentBackupUrl
    $env:SSWCENTER_R0_W2_FRESH_OWNER_URL = $FreshOwnerUrl
    $env:SSWCENTER_R0_W2_FRESH_APP_URL = $FreshAppUrl
    $env:SSWCENTER_R0_W2_FRESH_BACKUP_URL = $FreshBackupUrl
    $env:SSWCENTER_DATABASE_URL = $CurrentOwnerUrl
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"

    Push-Location $BackendRoot
    try {
        & $ResolvedPythonExe -m pytest -q -s `
            "tests/test_r0_w2_read_only_postgres.py" `
            -o ("cache_dir={0}" -f (Join-Path $ArtifactRoot "pytest-cache"))
        $PytestExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    Write-Output ("R0_ROOM2_PYTEST_EXIT={0}" -f $PytestExitCode)
    if ($PytestExitCode -ne 0) {
        throw "R0_ROOM2_PYTEST_FAILED exit=$PytestExitCode"
    }

    $CurrentPostcheckOutput = @(
        & $VerifyScript -DatabaseUrl $CurrentOwnerUrl -PythonExe $ResolvedPythonExe 2>&1
    )
    $CurrentPostcheckExit = $LASTEXITCODE
    $CurrentPostcheckOutput | Write-Output
    if (
        $CurrentPostcheckExit -ne 0 -or
        (($CurrentPostcheckOutput -join "`n") -notmatch "R0_W2_READ_ONLY_DB_POSTCHECK_OK")
    ) {
        throw "R0_ROOM2_CURRENT_POSTCHECK_FAILED exit=$CurrentPostcheckExit"
    }
    $FreshPostcheckOutput = @(
        & $VerifyScript -DatabaseUrl $FreshOwnerUrl -PythonExe $ResolvedPythonExe 2>&1
    )
    $FreshPostcheckExit = $LASTEXITCODE
    $FreshPostcheckOutput | Write-Output
    if (
        $FreshPostcheckExit -ne 0 -or
        (($FreshPostcheckOutput -join "`n") -notmatch "R0_W2_READ_ONLY_DB_POSTCHECK_OK")
    ) {
        throw "R0_ROOM2_FRESH_POSTCHECK_FAILED exit=$FreshPostcheckExit"
    }
    Write-Output "R0_ROOM2_POSTCHECK_MARKERS=0018+0019+0019"
}
catch {
    $RunFailed = $true
    $RunFailureDetail = [string]$_.Exception.Message
    Write-Output ("R0_ROOM2_RUN_FAILED: {0}" -f $RunFailureDetail)
}
finally {
    if ($ClusterStarted) {
        try {
            & $PgCtlExe --pgdata=$DataDirectory stop --mode=fast --wait | Out-Null
            if ($LASTEXITCODE -ne 0) {
                $CleanupFailed = $true
                $CleanupFailureDetail = "R0_ROOM2_PGCTL_STOP_FAILED exit=$LASTEXITCODE"
            }
        }
        catch {
            $CleanupFailed = $true
            $CleanupFailureDetail = [string]$_.Exception.Message
        }
        $ClusterStarted = $false
        Start-Sleep -Milliseconds 750
    }

    $ownedProcesses = @()
    try {
        $ownedProcesses = @(Get-R0OwnedPostgresProcesses -OwnedRoot $ClusterRoot)
        foreach ($ownedProcess in $ownedProcesses) {
            try {
                Stop-Process -Id ([int]$ownedProcess.ProcessId) -Force -ErrorAction Stop
            }
            catch {
                $CleanupFailed = $true
                $CleanupFailureDetail = "R0_ROOM2_OWNED_PROCESS_STOP_FAILED pid=$($ownedProcess.ProcessId)"
            }
        }
        if ($ownedProcesses.Count -gt 0) {
            Start-Sleep -Milliseconds 500
        }
        $ownedProcesses = @(Get-R0OwnedPostgresProcesses -OwnedRoot $ClusterRoot)
    }
    catch {
        $CleanupFailed = $true
        $CleanupFailureDetail = [string]$_.Exception.Message
        $ownedProcesses = @([pscustomobject]@{ ProcessId = -1 })
    }
    $processResidual = $ownedProcesses.Count

    try {
        $listenerSnapshot = @(Get-R0OwnedListeners)
        $listenerResidual = $listenerSnapshot.Count
    }
    catch {
        $CleanupFailed = $true
        $CleanupFailureDetail = [string]$_.Exception.Message
        $listenerResidual = 1
    }

    if ($processResidual -eq 0 -and (Test-Path -LiteralPath $ClusterRoot)) {
        $resolvedClusterRoot = [System.IO.Path]::GetFullPath($ClusterRoot)
        if (
            $resolvedClusterRoot.StartsWith($AllowedTempPrefix, [StringComparison]::OrdinalIgnoreCase) -and
            (Split-Path -Leaf $resolvedClusterRoot).StartsWith($ClusterPrefix, [StringComparison]::Ordinal)
        ) {
            try {
                $deleteSucceeded = $false
                $deleteError = $null
                for ($attempt = 1; $attempt -le 5; $attempt++) {
                    try {
                        [System.IO.Directory]::Delete($resolvedClusterRoot, $true)
                        $deleteSucceeded = $true
                        break
                    }
                    catch {
                        $deleteError = [string]$_.Exception.Message
                        if ($attempt -lt 5) {
                            Start-Sleep -Milliseconds 250
                        }
                    }
                }
                if (-not $deleteSucceeded) {
                    throw "R0_ROOM2_CLUSTER_DELETE_FAILED path=$resolvedClusterRoot error=$deleteError"
                }
            }
            catch {
                $CleanupFailed = $true
                $CleanupFailureDetail = [string]$_.Exception.Message
            }
        }
        else {
            $CleanupFailed = $true
            $CleanupFailureDetail = "R0_ROOM2_CLUSTER_DELETE_PATH_REJECTED"
        }
    }
    $tempResidual = if (Test-Path -LiteralPath $ClusterRoot) { 1 } else { 0 }
    $artifactResidual = if (Test-Path -LiteralPath $ArtifactRoot) {
        @(Get-ChildItem -LiteralPath $ArtifactRoot -Recurse -Force -File -ErrorAction SilentlyContinue).Count
    }
    else {
        0
    }
    $remainingPaths = @()
    foreach ($candidatePath in @($ClusterRoot, $ArtifactRoot)) {
        if (Test-Path -LiteralPath $candidatePath) {
            $resolvedCandidatePath = [System.IO.Path]::GetFullPath($candidatePath)
            if ($remainingPaths -notcontains $resolvedCandidatePath) {
                $remainingPaths += $resolvedCandidatePath
            }
        }
    }
    $remainingPathText = $remainingPaths -join ';'

    $gitResidual = 0
    try {
        $finalHead = Get-R0GitHead
        $finalStatus = Get-R0GitStatus
        $finalIndexStatus = Get-R0GitIndexStatus
        if ($finalHead -ne $InitialHead) {
            $gitResidual = 1
        }
        if (($finalStatus -join "`n") -ne ($InitialStatus -join "`n")) {
            $gitResidual = 1
        }
        if (($finalIndexStatus -join "`n") -ne ($InitialIndexStatus -join "`n")) {
            $gitResidual = 1
        }
        foreach ($RelativePath in $ExpectedProductHashes.Keys) {
            $ProductPath = Join-Path $WorkspaceRoot $RelativePath
            if (
                -not (Test-Path -LiteralPath $ProductPath -PathType Leaf) -or
                (Get-R0LfNormalizedSha256 -Path $ProductPath) -ne $ExpectedProductHashes[$RelativePath]
            ) {
                $gitResidual = 1
            }
        }
        foreach ($RelativePath in $RequiredProductFiles) {
            $ProductPath = Join-Path $WorkspaceRoot $RelativePath
            if (-not (Test-Path -LiteralPath $ProductPath -PathType Leaf)) {
                $gitResidual = 1
            }
        }
        Write-Output ("R0_ROOM2_CHANGED_PATHS={0}" -f ($finalStatus -join ","))
    }
    catch {
        $gitResidual = 1
        $CleanupFailed = $true
        $CleanupFailureDetail = [string]$_.Exception.Message
    }

    Restore-R0Environment
    Write-Output ("R0_ROOM2_CLEANUP_LISTENER={0}" -f $listenerResidual)
    Write-Output ("R0_ROOM2_CLEANUP_PROCESS={0}" -f $processResidual)
    Write-Output ("R0_ROOM2_CLEANUP_TEMP={0}" -f $tempResidual)
    Write-Output ("R0_ROOM2_CLEANUP_ARTIFACT={0}" -f $artifactResidual)
    Write-Output ("R0_ROOM2_CLEANUP_GIT={0}" -f $gitResidual)
    Write-Output ("R0_ROOM2_CLEANUP_REMAINING_PATHS={0}" -f $remainingPathText)
    if ($CleanupFailed) {
        Write-Output ("R0_ROOM2_CLEANUP_FAILURE: {0}" -f $CleanupFailureDetail)
    }
}

if (
    $RunFailed -or
    $CleanupFailed -or
    $listenerResidual -ne 0 -or
    $processResidual -ne 0 -or
    $tempResidual -ne 0 -or
    $artifactResidual -ne 0 -or
    $gitResidual -ne 0
) {
    exit 1
}

Write-Output "R0_ROOM2_POSTGRES_GREEN"
exit 0
