param(
    [int]$Port = 55439,
    [int]$CommandTimeoutSeconds = 120,
    [switch]$ExpectGreen
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$PythonExe = if (-not [string]::IsNullOrWhiteSpace($env:SSWCENTER_PYTHON_EXE)) {
    [System.IO.Path]::GetFullPath($env:SSWCENTER_PYTHON_EXE)
}
else {
    Join-Path $BackendRoot ".venv\Scripts\python.exe"
}
$PostgresBin = "C:\Program Files\PostgreSQL\17\bin"
$InitDbExe = Join-Path $PostgresBin "initdb.exe"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl.exe"
$CreateDbExe = Join-Path $PostgresBin "createdb.exe"
$DropDbExe = Join-Path $PostgresBin "dropdb.exe"
$PgDumpExe = Join-Path $PostgresBin "pg_dump.exe"
$PgRestoreExe = Join-Path $PostgresBin "pg_restore.exe"
$PsqlExe = Join-Path $PostgresBin "psql.exe"
$PowerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
$PostcheckPath = Join-Path $BackendRoot "app\db\postcheck_w1a_vs1.py"
$LeakGateScript = Join-Path $WorkspaceRoot "scripts\verify-w1a-vs1-leak-gate.ps1"
$Revision = "20260728_0008_w1a_staff_legacy_mapping"
$BaseRevision = "20260728_0007_w1a_staff_quarterly_consultation"
$PreviousRevision = "20260728_0006_w1a_staff_health_check"
$MigrationPath = Join-Path $BackendRoot "alembic\versions\20260728_0008_w1a_staff_legacy_mapping.py"
$RestoreScriptRevision = $BaseRevision
$TempParent = if ([string]::IsNullOrWhiteSpace($env:SSWCENTER_VS6_TEMP_ROOT)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is required for the W1A-VS6 harness"
    }
    [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Temp"))
}
else {
    [System.IO.Path]::GetFullPath($env:SSWCENTER_VS6_TEMP_ROOT)
}
$env:TEMP = $TempParent
$env:TMP = $TempParent
$env:TMPDIR = $TempParent
$TempRoot = Join-Path $TempParent ("sswcenter-w1a-vs6-pg-" + [Guid]::NewGuid().ToString("N"))
$ArtifactRoot = Join-Path $TempParent ("sswcenter-w1a-vs6-artifacts-" + [Guid]::NewGuid().ToString("N"))
$ArtifactPsqlRoot = Join-Path $ArtifactRoot "psql"
$MainRuntimeRoot = Join-Path $ArtifactRoot "sswcenter-runtime"
$RestoreRuntimeRoot = Join-Path $ArtifactRoot "sswcenter-w1a-vs6-restore-runtime"
$DataRoot = Join-Path $TempRoot "data"
$LogFile = Join-Path $ArtifactRoot "postgres.log"
$OfflineSqlPath = Join-Path $ArtifactRoot "offline.sql"
$BackupRoot = Join-Path $TempRoot "backup"
$DumpPath = Join-Path $BackupRoot "data.dump"
$DatabaseName = "w1a_vs6_review"
$OfflineDatabaseName = "w1a_vs6_offline_review"
$RestoreDatabaseName = "w1a_vs6_restore_review"
$OwnerPassword = "w1a_vs6_owner_only"
$AppPassword = "w1a_vs6_app_only"
$BackupPassword = "w1a_vs6_backup_only"
$ServerStarted = $false
$OfflineDatabaseCreated = $false
$RestoreDatabaseCreated = $false
$HarnessFailure = $false
$ProductMarkers = [System.Collections.Generic.List[string]]::new()
$Collected = $null
$Passed = 0
$Failed = 0
$Skipped = 0
$Errors = 0
$RunExitCode = $null
$LifecycleSuccessful = $false
$OfflineSuccessful = $false
$PostcheckSuccessful = $false
$RestoreSuccessful = $false
$ArtifactRemaining = 0
$MediaRemaining = 0
$RuntimeArtifactRemaining = 0
$RuntimeArtifactLeakExit = 125
$RuntimeArtifactScanned = 0
$RuntimeArtifactLeakSuccessful = $false
$PsqlArtifactCountBeforeLeakScan = 0
$PsqlArtifactAssertionPassed = $false
$ArtifactRootCreated = $false
$ExpectedCollectedTests = 39
$ExpectedRunExitCode = 1
$ExpectedPassed = 23
$ExpectedFailed = 16
$ExpectedSkipped = 0
$ExpectedErrors = 0
$ExpectedGreenRunExitCode = 0
$ExpectedGreenPassed = 39
$ExpectedGreenFailed = 0
$ExpectedGreenSkipped = 0
$ExpectedGreenErrors = 0
$RequiredRedMarkers = @(
    "W1A_VS6_ALLOWLIST_MISSING",
    "W1A_VS6_PII_EXCEPTION_CAUSE_LINKED",
    "W1A_VS6_LICENSE_CANONICAL_PREPARE_ONE_MISSING",
    "W1A_VS6_LICENSE_CANONICAL_PREPARE_TWO_MISSING",
    "W1A_VS6_LICENSE_LEGACY_ALIAS_ACCEPTED",
    "W1A_VS6_PII_DATABASE_SESSION_EXCEPTION_CAUSE_LINKED",
    "W1A_VS6_PII_SESSION_FACTORY_EXCEPTION_CAUSE_LINKED",
    "W1A_VS6_LICENSE_CANONICAL_APPLY_ONE_MISSING",
    "W1A_VS6_LICENSE_CANONICAL_APPLY_TWO_MISSING",
    "W1A_VS6_REHIRE_EMPLOYMENT_MISSING",
    "W1A_VS6_REHIRE_LICENSE_ROLLBACK_EXACT_MISSING",
    "W1A_VS6_MAPPING_REPLACEMENT_MISSING",
    "W1A_VS6_MAPPING_EXPECTED_VERSION_REQUIRED",
    "W1A_VS6_MAPPING_STALE_VERSION_REJECTED",
    "W1A_VS6_MAPPING_CONCURRENT_VERSIONING_MISSING",
    "W1A_VS6_MAPPING_ACTIVE_LOCK_MISSING"
)

function Remove-W1aVs6Tree {
    param(
        [Parameter(Mandatory = $true)] [string]$Path,
        [Parameter(Mandatory = $true)] [string]$ExpectedLeafPrefix
    )
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $resolved = [System.IO.Path]::GetFullPath($Path)
    $parentPrefix = [System.IO.Path]::GetFullPath($TempParent).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    ) + [System.IO.Path]::DirectorySeparatorChar
    $leaf = Split-Path -Leaf $resolved
    if (
        -not $resolved.StartsWith($parentPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not $leaf.StartsWith($ExpectedLeafPrefix, [StringComparison]::Ordinal)
    ) {
        throw "unsafe W1A-VS6 cleanup target"
    }
    $removed = $false
    for ($attempt = 1; $attempt -le 3 -and -not $removed; $attempt++) {
        try {
            [System.IO.Directory]::Delete($resolved, $true)
            $removed = $true
        }
        catch {
            if ($attempt -eq 3) { throw }
            Start-Sleep -Seconds $attempt
        }
    }
    if (-not $removed -or (Test-Path -LiteralPath $resolved)) {
        throw "W1A-VS6 cleanup target remains"
    }
}

function Invoke-Captured {
    param(
        [Parameter(Mandatory = $true)] [string]$FilePath,
        [Parameter(Mandatory = $true)] [string[]]$Arguments,
        [Parameter(Mandatory = $true)] [string]$WorkingDirectory
    )
    $process = [System.Diagnostics.Process]::new()
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    try {
        $isPgCtl = [System.IO.Path]::GetFileName($FilePath) -ieq "pg_ctl.exe"
        $startInfo.FileName = $FilePath
        $startInfo.Arguments = ($Arguments | ForEach-Object {
                '"' + ([string]$_).Replace('"', '\"') + '"'
            }) -join " "
        $startInfo.WorkingDirectory = $WorkingDirectory
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = -not $isPgCtl
        $startInfo.RedirectStandardError = -not $isPgCtl
        if (-not $isPgCtl) {
            $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
            $startInfo.StandardOutputEncoding = $utf8NoBom
            $startInfo.StandardErrorEncoding = $utf8NoBom
        }
        $process.StartInfo = $startInfo
        if (-not $process.Start()) {
            return [pscustomobject]@{ ExitCode = 125; Output = @(); Stdout = @(); Stderr = @(); TimedOut = $false }
        }
        $stdoutTask = if (-not $isPgCtl) { $process.StandardOutput.ReadToEndAsync() } else { $null }
        $stderrTask = if (-not $isPgCtl) { $process.StandardError.ReadToEndAsync() } else { $null }
        if (-not $process.WaitForExit($CommandTimeoutSeconds * 1000)) {
            $process.Kill()
            $process.WaitForExit()
            return [pscustomobject]@{ ExitCode = 124; Output = @(); Stdout = @(); Stderr = @(); TimedOut = $true }
        }
        $process.WaitForExit()
        $stdout = if ($isPgCtl -or [string]::IsNullOrEmpty($stdoutTask.Result)) { @() } else { $stdoutTask.Result -split "`r?`n" }
        $stderr = if ($isPgCtl -or [string]::IsNullOrEmpty($stderrTask.Result)) { @() } else { $stderrTask.Result -split "`r?`n" }
        return [pscustomobject]@{
            ExitCode = [int]$process.ExitCode
            Output = @($stdout + $stderr)
            Stdout = @($stdout)
            Stderr = @($stderr)
            TimedOut = $false
        }
    }
    catch {
        return [pscustomobject]@{ ExitCode = 125; Output = @(); Stdout = @(); Stderr = @(); TimedOut = $false }
    }
    finally { $process.Dispose() }
}

function Invoke-Psql {
    param(
        [Parameter(Mandatory = $true)] [string]$Database,
        [Parameter(Mandatory = $true)] [string]$Sql,
        [string]$Role = "postgres"
    )
    $sqlPath = Join-Path $ArtifactPsqlRoot ("vs6-" + [Guid]::NewGuid().ToString("N") + ".sql")
    [System.IO.File]::WriteAllText($sqlPath, $Sql, [System.Text.UTF8Encoding]::new($false))
    return Invoke-Captured -FilePath $PsqlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
        "-h", "127.0.0.1", "-p", [string]$Port, "-U", $Role, "-d", $Database,
        "-v", "ON_ERROR_STOP=1", "-f", $sqlPath
    )
}

function Invoke-ScalarPsql {
    param(
        [Parameter(Mandatory = $true)] [string]$Database,
        [Parameter(Mandatory = $true)] [string]$Sql,
        [string]$Role = "postgres"
    )
    return Invoke-Captured -FilePath $PsqlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
        "-h", "127.0.0.1", "-p", [string]$Port, "-U", $Role, "-d", $Database,
        "-v", "ON_ERROR_STOP=1", "-q", "-At", "-c", $Sql
    )
}

function Add-ProductMarkers([object[]]$Lines) {
    foreach ($line in $Lines) {
        foreach ($match in [regex]::Matches([string]$line, "W1A_VS6_[A-Z0-9_]+")) {
            if ($match.Value.EndsWith("_OK") -or $match.Value.EndsWith("_GREEN")) { continue }
            if ($match.Value -match "HARNESS_FAILURE$") { continue }
            if (-not $ProductMarkers.Contains($match.Value)) { $ProductMarkers.Add($match.Value) }
        }
    }
}

function Test-HarnessOutput([object[]]$Lines) {
    $items = @($Lines)
    $text = $items -join "`n"
    if ($text -match "INTERNALERROR|W1A_VS6_[A-Z0-9_]*HARNESS_FAILURE") {
        return $true
    }

    $summaryIndex = -1
    for ($index = 0; $index -lt $items.Count; $index++) {
        $line = [string]$items[$index]
        if (
            $line -match "(?i)short test summary info" -or
            $line -match "(?i)^\s*\d+\s+(?:passed|failed|skipped|errors?)(?:,|\s|$)"
        ) {
            $summaryIndex = $index
        }
    }

    $infrastructurePattern = "(?i)Exception ignored in atexit callback|PytestUnhandledThreadExceptionWarning|Exception in thread|Fatal Python error|sys\.excepthook|unraisable"
    if ($text -match $infrastructurePattern) {
        return $true
    }
    $threadWarningPattern = "(?i)PytestUnhandledThreadExceptionWarning\s*:\s*Exception in thread"
    for ($index = 0; $index -lt $items.Count; $index++) {
        if ([string]$items[$index] -notmatch $threadWarningPattern) { continue }
        $threadWarningEnd = if ($summaryIndex -ge 0) { $summaryIndex } else { $items.Count }
        for ($threadIndex = $index + 1; $threadIndex -lt $threadWarningEnd; $threadIndex++) {
            if ([string]$items[$threadIndex] -match "(?i)Traceback") {
                return $true
            }
        }
    }
    if ($summaryIndex -ge 0) {
        for ($index = $summaryIndex + 1; $index -lt $items.Count; $index++) {
            if ([string]$items[$index] -match "(?i)Traceback") {
                return $true
            }
        }
    }
    return $false
}

function Write-CapturedDiagnostic {
    param(
        [Parameter(Mandatory = $true)] [string]$Label,
        [Parameter(Mandatory = $true)] [object]$Result
    )
    $lines = @($Result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })
    if ($lines.Count -gt 40) {
        Write-Output ("W1A_VS6_DIAGNOSTIC[{0}]=...{1} earlier lines omitted" -f $Label, ($lines.Count - 40))
        $lines = @($lines | Select-Object -Last 40)
    }
    foreach ($line in $lines) {
        $safe = [string]$line
        foreach ($secret in @($OwnerPassword, $AppPassword, $BackupPassword)) {
            $safe = $safe.Replace($secret, "<redacted>")
        }
        $safe = [regex]::Replace(
            $safe,
            "postgresql(?:\+psycopg)?://[^\s`"']+",
            "postgresql://<redacted>"
        )
        if ($safe.Length -gt 1000) { $safe = $safe.Substring(0, 1000) + "...<truncated>" }
        if (-not [string]::IsNullOrWhiteSpace($safe)) {
            Write-Output ("W1A_VS6_DIAGNOSTIC[{0}]={1}" -f $Label, $safe)
        }
    }
}

function Get-ListenerCount {
    return @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).Count
}

$required = @(
    $PythonExe,
    $InitDbExe,
    $PgCtlExe,
    $CreateDbExe,
    $DropDbExe,
    $PgDumpExe,
    $PgRestoreExe,
    $PsqlExe,
    $PowerShellExe,
    $LeakGateScript
)
if (@($required | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }).Count -gt 0) {
    Write-Output "W1A_VS6_HARNESS_FAILURE: required runtime executable is missing"
    exit 2
}
if ((Get-ListenerCount) -ne 0) {
    Write-Output "W1A_VS6_HARNESS_FAILURE: isolated PostgreSQL port is occupied"
    exit 2
}

try {
    [System.IO.Directory]::CreateDirectory($TempParent) | Out-Null
    [System.IO.Directory]::CreateDirectory($TempRoot) | Out-Null
    [System.IO.Directory]::CreateDirectory($ArtifactRoot) | Out-Null
    [System.IO.Directory]::CreateDirectory($ArtifactPsqlRoot) | Out-Null
    $ArtifactRootCreated = $true
    [System.IO.Directory]::CreateDirectory($BackupRoot) | Out-Null
    $hasMigration = Test-Path -LiteralPath $MigrationPath -PathType Leaf
    if (-not $hasMigration) { Add-ProductMarkers @("W1A_VS6_MIGRATION_MISSING") }
    $RestoreScriptRevision = if ($hasMigration) { $Revision } else { $BaseRevision }

    Write-Output "W1A_VS6_STAGE=initdb"
    $init = Invoke-Captured -FilePath $InitDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
        "-D", $DataRoot, "-U", "postgres", "--auth=trust", "--no-locale", "--encoding=UTF8"
    )
    Write-Output ("W1A_VS6_INITDB_CODE=" + $init.ExitCode)
    if ($init.ExitCode -ne 0) {
        $HarnessFailure = $true
        Write-Output "W1A_VS6_HARNESS_FAILURE: initdb"
    }
    else {
        $start = Invoke-Captured -FilePath $PgCtlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-D", $DataRoot, "-l", $LogFile, "-o", "-p $Port -h 127.0.0.1", "start", "-w"
        )
        Write-Output ("W1A_VS6_PG_START_CODE=" + $start.ExitCode)
        if ($start.ExitCode -ne 0) {
            if (Test-Path -LiteralPath $LogFile -PathType Leaf) {
                $pgLogLines = @(Get-Content -LiteralPath $LogFile -ErrorAction SilentlyContinue)
                if ($pgLogLines.Count -gt 20) { $pgLogLines = @($pgLogLines | Select-Object -Last 20) }
                foreach ($pgLogLine in $pgLogLines) {
                    if (-not [string]::IsNullOrWhiteSpace([string]$pgLogLine)) {
                        Write-Output ("W1A_VS6_PG_DIAGNOSTIC=" + [string]$pgLogLine)
                    }
                }
            }
            $HarnessFailure = $true
            Write-Output "W1A_VS6_HARNESS_FAILURE: pg_ctl start"
        }
        else {
            $ServerStarted = $true
            $roles = Invoke-Psql -Database "postgres" -Sql @"
CREATE ROLE erp_owner LOGIN PASSWORD '$OwnerPassword';
CREATE ROLE erp_app LOGIN PASSWORD '$AppPassword';
CREATE ROLE erp_backup LOGIN PASSWORD '$BackupPassword';
"@
            $database = Invoke-Captured -FilePath $CreateDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-O", "erp_owner", $DatabaseName
            )
            Write-Output ("W1A_VS6_BOOTSTRAP_CODES=roles:{0} database:{1}" -f $roles.ExitCode, $database.ExitCode)
            if ($roles.ExitCode -ne 0 -or $database.ExitCode -ne 0) {
                $HarnessFailure = $true
                Write-Output "W1A_VS6_HARNESS_FAILURE: bootstrap"
            }
            else {
                $env:SSWCENTER_ENVIRONMENT = "test"
                $env:SSWCENTER_POSTGRES_TEST = "1"
                $env:PYTHONDONTWRITEBYTECODE = "1"
                $env:SSWCENTER_DATA_ROOT = $MainRuntimeRoot
                $env:SSWCENTER_DATABASE_URL = "postgresql+psycopg://erp_owner:$OwnerPassword@127.0.0.1:$Port/$DatabaseName"
                $env:SSWCENTER_APP_DATABASE_URL = "postgresql+psycopg://erp_app:$AppPassword@127.0.0.1:$Port/$DatabaseName"
                $env:SSWCENTER_BACKUP_DATABASE_URL = "postgresql+psycopg://erp_backup:$BackupPassword@127.0.0.1:$Port/$DatabaseName"
                [System.IO.Directory]::CreateDirectory($env:SSWCENTER_DATA_ROOT) | Out-Null
                $testFiles = @(
                    "tests/test_w1a_vs6_semantics.py",
                    "tests/test_w1a_vs6_import_contract.py",
                    "tests/test_w1a_vs6_postgres.py",
                    "tests/test_w1a_vs6_absence_contract.py"
                )
                $qualityFiles = $testFiles | ForEach-Object { Join-Path $BackendRoot $_ }

                Write-Output "W1A_VS6_STAGE=quality"
                $format = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments (@("-m", "ruff", "format", "--check") + $qualityFiles)
                $ruff = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments (@("-m", "ruff", "check") + $qualityFiles)
                $compile = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments (@("-m", "compileall", "-q") + $qualityFiles)
                Write-Output ("W1A_VS6_QUALITY_CODES=format:{0} ruff:{1} compile:{2}" -f $format.ExitCode, $ruff.ExitCode, $compile.ExitCode)
                if ($format.ExitCode -ne 0 -or $ruff.ExitCode -ne 0 -or $compile.ExitCode -ne 0) {
                    $HarnessFailure = $true
                    Write-Output "W1A_VS6_HARNESS_FAILURE: quality"
                }

                Write-Output "W1A_VS6_STAGE=migration"
                $upgrade = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "upgrade", $RestoreScriptRevision)
                Write-Output ("W1A_VS6_MIGRATION_UPGRADE_CODE=" + $upgrade.ExitCode)
                if ($upgrade.ExitCode -ne 0) {
                    Write-CapturedDiagnostic -Label "migration-upgrade" -Result $upgrade
                    $HarnessFailure = $true
                    Write-Output "W1A_VS6_HARNESS_FAILURE: baseline migration"
                }
                elseif ($hasMigration) {
                    $applied = Invoke-ScalarPsql -Database $DatabaseName -Sql "SELECT version_num FROM erp.alembic_version" -Role "postgres"
                    if (($applied.Stdout -join "`n").Trim() -ne $Revision) {
                        $HarnessFailure = $true
                        Write-Output "W1A_VS6_HARNESS_FAILURE: 0008 revision was not applied"
                    }
                }
                else {
                    $applied = Invoke-ScalarPsql -Database $DatabaseName -Sql "SELECT version_num FROM erp.alembic_version" -Role "postgres"
                    if (($applied.Stdout -join "`n").Trim() -ne $BaseRevision) {
                        $HarnessFailure = $true
                        Write-Output "W1A_VS6_HARNESS_FAILURE: baseline 0007 revision was not applied"
                    }
                }

                Write-Output "W1A_VS6_STAGE=lifecycle"
                $downTarget = if ($hasMigration) { $BaseRevision } else { $PreviousRevision }
                $down = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "downgrade", $downTarget)
                $up = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "upgrade", $RestoreScriptRevision)
                $downAgain = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "downgrade", $downTarget)
                $upAgain = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "upgrade", $RestoreScriptRevision)
                Write-Output ("W1A_VS6_LIFECYCLE_CODES=down:{0} up:{1} down_again:{2} up_again:{3}" -f $down.ExitCode, $up.ExitCode, $downAgain.ExitCode, $upAgain.ExitCode)
                $lifecycle = @($down, $up, $downAgain, $upAgain)
                if (@($lifecycle | Where-Object { $_.ExitCode -ne 0 }).Count -gt 0) {
                    foreach ($item in $lifecycle) {
                        if ($item.ExitCode -ne 0) {
                            Write-CapturedDiagnostic -Label "migration-lifecycle" -Result $item
                        }
                    }
                    $HarnessFailure = $true
                    Write-Output "W1A_VS6_HARNESS_FAILURE: migration lifecycle"
                }
                else { $LifecycleSuccessful = $true }
                if (-not $hasMigration) { Add-ProductMarkers @("W1A_VS6_MIGRATION_MISSING") }

                Write-Output "W1A_VS6_STAGE=offline_apply"
                $offlineTarget = if ($hasMigration) { $Revision } else { $BaseRevision }
                $offline = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "upgrade", $offlineTarget, "--sql")
                if ($offline.ExitCode -eq 0) {
                    [System.IO.File]::WriteAllLines($OfflineSqlPath, [string[]]$offline.Stdout, [System.Text.UTF8Encoding]::new($false))
                }
                $offlineDb = Invoke-Captured -FilePath $CreateDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                    "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-O", "erp_owner", $OfflineDatabaseName
                )
                if ($offlineDb.ExitCode -eq 0) { $OfflineDatabaseCreated = $true }
                $offlineApply = if ($offline.ExitCode -eq 0 -and $offlineDb.ExitCode -eq 0) {
                    Invoke-Captured -FilePath $PsqlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                        "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-d", $OfflineDatabaseName,
                        "-v", "ON_ERROR_STOP=1", "-f", $OfflineSqlPath
                    )
                }
                else { [pscustomobject]@{ ExitCode = 125; Output = @(); Stdout = @(); Stderr = @(); TimedOut = $false } }
                $offlineVerifySql = if ($hasMigration) {
                    "SELECT CASE WHEN EXISTS (SELECT 1 FROM erp.alembic_version WHERE version_num = '$Revision') AND to_regclass('erp.staff_legacy_mapping') IS NOT NULL THEN 0 ELSE 1 END"
                }
                else {
                    "SELECT CASE WHEN EXISTS (SELECT 1 FROM erp.alembic_version WHERE version_num = '$BaseRevision') AND to_regclass('erp.staff_quarterly_consultation') IS NOT NULL THEN 0 ELSE 1 END"
                }
                $offlineVerify = if ($offlineApply.ExitCode -eq 0) {
                    Invoke-ScalarPsql -Database $OfflineDatabaseName -Sql $offlineVerifySql
                }
                else { [pscustomobject]@{ ExitCode = 125; Output = @(); Stdout = @(); Stderr = @(); TimedOut = $false } }
                Write-Output ("W1A_VS6_OFFLINE_APPLY_CODES=database:{0} apply:{1} verify:{2}" -f $offlineDb.ExitCode, $offlineApply.ExitCode, $offlineVerify.ExitCode)
                if ($offline.ExitCode -ne 0 -or $offlineDb.ExitCode -ne 0 -or $offlineApply.ExitCode -ne 0 -or $offlineVerify.ExitCode -ne 0 -or ($offlineVerify.Stdout -join "`n") -notmatch "0") {
                    foreach ($item in @($offline, $offlineDb, $offlineApply, $offlineVerify)) {
                        if ($item.ExitCode -ne 0) {
                            Write-CapturedDiagnostic -Label "offline-apply" -Result $item
                        }
                    }
                    $HarnessFailure = $true
                    Write-Output "W1A_VS6_HARNESS_FAILURE: offline empty-db apply"
                }
                else { $OfflineSuccessful = $true }
                if (-not $hasMigration) { Add-ProductMarkers @("W1A_VS6_OFFLINE_MISSING") }

                Write-Output "W1A_VS6_STAGE=pytest_collect"
                $collect = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments (@("-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider") + $testFiles)
                $collectText = $collect.Output -join "`n"
                $collectMatch = [regex]::Match($collectText, "(\d+) tests? collected")
                if ($collectMatch.Success) {
                    $Collected = [int]$collectMatch.Groups[1].Value
                    Write-Output ("W1A_VS6_COLLECTED_TESTS=" + $Collected)
                }
                if ($collect.ExitCode -ne 0 -or -not $collectMatch.Success) {
                    Write-CapturedDiagnostic -Label "pytest-collect" -Result $collect
                    $HarnessFailure = $true
                    Write-Output "W1A_VS6_HARNESS_FAILURE: collection"
                }

                Write-Output "W1A_VS6_STAGE=pytest_run"
                $run = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments (@("-m", "pytest", "-q", "-p", "no:cacheprovider") + $testFiles)
                $RunExitCode = $run.ExitCode
                Add-ProductMarkers @($collect.Output + $run.Output)
                $runText = $run.Output -join "`n"
                foreach ($match in [regex]::Matches($runText, "(?i)(\d+)\s+(passed|failed|skipped|errors?)")) {
                    $value = [int]$match.Groups[1].Value
                    switch ($match.Groups[2].Value.ToLowerInvariant()) {
                        "passed" { $Passed += $value }
                        "failed" { $Failed += $value }
                        "skipped" { $Skipped += $value }
                        "error" { $Errors += $value }
                        "errors" { $Errors += $value }
                    }
                }
                Write-Output ("W1A_VS6_TEST_COUNTS=passed:{0} failed:{1} skipped:{2} errors:{3}" -f $Passed, $Failed, $Skipped, $Errors)
                if (Test-HarnessOutput @($run.Output)) {
                    $HarnessFailure = $true
                    Write-Output "W1A_VS6_HARNESS_FAILURE: pytest output"
                }
                if ($run.ExitCode -ne 0 -and -not ($runText -match "W1A_VS6_[A-Z0-9_]+")) {
                    $HarnessFailure = $true
                    Write-Output "W1A_VS6_HARNESS_FAILURE: pytest returned without product marker"
                }

                Write-Output "W1A_VS6_STAGE=postcheck"
                if (-not (Test-Path -LiteralPath $PostcheckPath -PathType Leaf)) {
                    $HarnessFailure = $true
                    Write-Output "W1A_VS6_HARNESS_FAILURE: postcheck module is missing"
                }
                else {
                    $postcheck = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "app.db.postcheck_w1a_vs1")
                    Write-Output ("W1A_VS6_POSTCHECK_CODE=" + $postcheck.ExitCode)
                    if ($postcheck.ExitCode -ne 0) {
                        Write-CapturedDiagnostic -Label "postcheck" -Result $postcheck
                        $HarnessFailure = $true
                        Write-Output "W1A_VS6_HARNESS_FAILURE: postcheck"
                    }
                    else {
                        $PostcheckSuccessful = $true
                        Write-Output "W1A_VS6_POSTCHECK_OK=1"
                    }
                }

                Write-Output "W1A_VS6_STAGE=backup_restore"
                $dump = Invoke-Captured -FilePath $PgDumpExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                    "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-d", $DatabaseName,
                    "--format=custom", "--file", $DumpPath
                )
                $restoreDb = Invoke-Captured -FilePath $CreateDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                    "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-O", "erp_owner", $RestoreDatabaseName
                )
                if ($restoreDb.ExitCode -eq 0) { $RestoreDatabaseCreated = $true }
                $restore = if ($dump.ExitCode -eq 0 -and $restoreDb.ExitCode -eq 0) {
                    Invoke-Captured -FilePath $PgRestoreExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                        "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-d", $RestoreDatabaseName,
                        "--no-owner", "--role=erp_owner", "--exit-on-error", $DumpPath
                    )
                }
                else { [pscustomobject]@{ ExitCode = 125; Output = @(); Stdout = @(); Stderr = @(); TimedOut = $false } }
                $restoreVerifySql = if ($hasMigration) {
                    @"
SELECT CASE WHEN EXISTS (
    SELECT 1 FROM erp.alembic_version WHERE version_num = '$RestoreScriptRevision'
) AND to_regclass('erp.staff_legacy_mapping') IS NOT NULL AND EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname = 'erp'
      AND tablename = 'staff_legacy_mapping'
      AND indexdef ILIKE '%UNIQUE%'
      AND indexdef ILIKE '%source_system_code%'
      AND indexdef ILIKE '%legacy_staff_key%'
      AND indexdef ILIKE '%invalidated_at_utc IS NULL%'
) THEN 0 ELSE 1 END
"@
                }
                else {
                    @"
SELECT CASE WHEN EXISTS (
    SELECT 1 FROM erp.alembic_version WHERE version_num = '$RestoreScriptRevision'
) AND to_regclass('erp.staff_quarterly_consultation') IS NOT NULL
THEN 0 ELSE 1 END
"@
                }
                $restoreVerify = if ($restore.ExitCode -eq 0) {
                    Invoke-ScalarPsql -Database $RestoreDatabaseName -Sql $restoreVerifySql
                }
                else { [pscustomobject]@{ ExitCode = 125; Output = @(); Stdout = @(); Stderr = @(); TimedOut = $false } }
                $restorePostcheck = [pscustomobject]@{ ExitCode = 125; Output = @(); Stdout = @(); Stderr = @(); TimedOut = $false }
                if ($restore.ExitCode -eq 0 -and $restoreVerify.ExitCode -eq 0 -and ($restoreVerify.Stdout -join "`n").Trim() -eq "0") {
                    $savedDatabaseUrl = $env:SSWCENTER_DATABASE_URL
                    $savedDataRoot = $env:SSWCENTER_DATA_ROOT
                    try {
                        $env:SSWCENTER_DATABASE_URL = "postgresql+psycopg://erp_owner:$OwnerPassword@127.0.0.1:$Port/$RestoreDatabaseName"
                        $env:SSWCENTER_DATA_ROOT = $RestoreRuntimeRoot
                        [System.IO.Directory]::CreateDirectory($env:SSWCENTER_DATA_ROOT) | Out-Null
                        $restorePostcheck = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "app.db.postcheck_w1a_vs1")
                    }
                    finally {
                        $env:SSWCENTER_DATABASE_URL = $savedDatabaseUrl
                        $env:SSWCENTER_DATA_ROOT = $savedDataRoot
                    }
                }
                Write-Output ("W1A_VS6_RESTORE_CODES=dump:{0} database:{1} restore:{2} verify:{3} postcheck:{4}" -f $dump.ExitCode, $restoreDb.ExitCode, $restore.ExitCode, $restoreVerify.ExitCode, $restorePostcheck.ExitCode)
                if ($dump.ExitCode -ne 0 -or $restoreDb.ExitCode -ne 0 -or $restore.ExitCode -ne 0 -or $restoreVerify.ExitCode -ne 0 -or ($restoreVerify.Stdout -join "`n").Trim() -ne "0") {
                    foreach ($item in @($dump, $restoreDb, $restore, $restoreVerify)) {
                        if ($item.ExitCode -ne 0) {
                            Write-CapturedDiagnostic -Label "backup-restore" -Result $item
                        }
                    }
                    $HarnessFailure = $true
                    Write-Output "W1A_VS6_HARNESS_FAILURE: backup restore"
                }
                elseif ($restorePostcheck.ExitCode -ne 0) {
                    Write-CapturedDiagnostic -Label "restore-postcheck" -Result $restorePostcheck
                    $HarnessFailure = $true
                    Write-Output "W1A_VS6_HARNESS_FAILURE: restore postcheck"
                }
                else {
                    $RestoreSuccessful = $true
                    Write-Output ("W1A_VS6_RESTORE_OK=revision:{0} postcheck=0" -f $RestoreScriptRevision)
                }
            }
        }
    }
}
catch {
    $HarnessFailure = $true
    $safeHarnessMessage = [string]$_.Exception.Message
    foreach ($secret in @($OwnerPassword, $AppPassword, $BackupPassword)) {
        $safeHarnessMessage = $safeHarnessMessage.Replace($secret, "<redacted>")
    }
    Write-Output ("W1A_VS6_HARNESS_EXCEPTION_TYPE=" + $_.Exception.GetType().Name)
    Write-Output ("W1A_VS6_HARNESS_EXCEPTION_MESSAGE=" + $safeHarnessMessage)
    Write-Output "W1A_VS6_HARNESS_FAILURE: unhandled harness condition"
}
finally {
    if ($ServerStarted -and $OfflineDatabaseCreated) {
        $dropOffline = Invoke-Captured -FilePath $DropDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "--if-exists", $OfflineDatabaseName
        )
        Write-Output ("W1A_VS6_OFFLINE_DROP_CODE=" + $dropOffline.ExitCode)
        if ($dropOffline.ExitCode -ne 0) { $HarnessFailure = $true }
    }
    if ($ServerStarted -and $RestoreDatabaseCreated) {
        $dropRestore = Invoke-Captured -FilePath $DropDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "--if-exists", $RestoreDatabaseName
        )
        Write-Output ("W1A_VS6_RESTORE_DROP_CODE=" + $dropRestore.ExitCode)
        if ($dropRestore.ExitCode -ne 0) { $HarnessFailure = $true }
    }
    if ($ServerStarted) {
        $stop = Invoke-Captured -FilePath $PgCtlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-D", $DataRoot, "stop", "-m", "fast", "-w"
        )
        Write-Output ("W1A_VS6_PG_STOP_CODE=" + $stop.ExitCode)
        if ($stop.ExitCode -ne 0) { $HarnessFailure = $true }
    }
    Write-Output "W1A_VS6_STAGE=runtime_artifact_leak"
    if (-not $ArtifactRootCreated -or -not (Test-Path -LiteralPath $ArtifactRoot -PathType Container)) {
        $HarnessFailure = $true
        Write-Output "W1A_VS6_HARNESS_FAILURE: runtime artifact root is missing"
    }
    else {
        $resolvedArtifactRoot = [System.IO.Path]::GetFullPath($ArtifactRoot)
        Write-Output ("W1A_VS6_RUNTIME_ARTIFACT_ROOT=" + $resolvedArtifactRoot)
        try {
            $resolvedArtifactPsqlRoot = [System.IO.Path]::GetFullPath($ArtifactPsqlRoot)
            $artifactBoundaryPrefix = $resolvedArtifactRoot.TrimEnd(
                [System.IO.Path]::DirectorySeparatorChar,
                [System.IO.Path]::AltDirectorySeparatorChar
            ) + [System.IO.Path]::DirectorySeparatorChar
            $psqlArtifacts = @(
                Get-ChildItem -LiteralPath $resolvedArtifactPsqlRoot -File -Filter "vs6-*.sql" -Force -ErrorAction Stop
            )
            $PsqlArtifactCountBeforeLeakScan = $psqlArtifacts.Count
            $outsideArtifactRootCount = @($psqlArtifacts | Where-Object {
                    try {
                        $resolvedPsqlArtifact = [System.IO.Path]::GetFullPath($_.FullName)
                        return -not $resolvedPsqlArtifact.StartsWith(
                            $artifactBoundaryPrefix,
                            [StringComparison]::OrdinalIgnoreCase
                        )
                    }
                    catch {
                        return $true
                    }
                }).Count
            $PsqlArtifactAssertionPassed = (
                $PsqlArtifactCountBeforeLeakScan -gt 0 -and
                $outsideArtifactRootCount -eq 0
            )
        }
        catch {
            $PsqlArtifactCountBeforeLeakScan = 0
            $PsqlArtifactAssertionPassed = $false
        }
        Write-Output ("W1A_VS6_PSQL_ARTIFACT_COUNT_BEFORE_LEAK_SCAN=" + $PsqlArtifactCountBeforeLeakScan)
        Write-Output ("W1A_VS6_PSQL_ARTIFACT_ASSERTION=" + [int]$PsqlArtifactAssertionPassed)
        if (-not $PsqlArtifactAssertionPassed) {
            $HarnessFailure = $true
            Write-Output "W1A_VS6_HARNESS_FAILURE: expected psql artifact is missing before leak scan"
        }
        $escapedLeakGatePath = ([string]$LeakGateScript).Replace("'", "''")
        $runtimeLeakCommand = `
            '$utf8 = New-Object System.Text.UTF8Encoding($false); ' +
            '[Console]::InputEncoding=$utf8; [Console]::OutputEncoding=$utf8; ' +
            '$OutputEncoding=$utf8; $ProgressPreference="SilentlyContinue"; & ' +
            [char]39 + $escapedLeakGatePath + [char]39 +
            ' -ArtifactRoot ([Environment]::GetEnvironmentVariable(' +
            "'SSWCENTER_VS6_RUNTIME_ARTIFACT_ROOT')); exit `$LASTEXITCODE"
        $runtimeLeakEncodedCommand = [Convert]::ToBase64String(
            [Text.Encoding]::Unicode.GetBytes($runtimeLeakCommand)
        )
        $savedDataRootForLeak = $env:SSWCENTER_DATA_ROOT
        $env:SSWCENTER_VS6_RUNTIME_ARTIFACT_ROOT = $resolvedArtifactRoot
        try {
            Remove-Item -LiteralPath Env:SSWCENTER_DATA_ROOT -ErrorAction SilentlyContinue
            $runtimeLeak = Invoke-Captured `
                -FilePath $PowerShellExe `
                -WorkingDirectory $WorkspaceRoot `
                -Arguments @(
                    "-NoProfile", "-NonInteractive", "-EncodedCommand",
                    $runtimeLeakEncodedCommand
                )
        }
        finally {
            if ($null -eq $savedDataRootForLeak) {
                Remove-Item -LiteralPath Env:SSWCENTER_DATA_ROOT -ErrorAction SilentlyContinue
            }
            else {
                $env:SSWCENTER_DATA_ROOT = $savedDataRootForLeak
            }
            Remove-Item -LiteralPath Env:SSWCENTER_VS6_RUNTIME_ARTIFACT_ROOT -ErrorAction SilentlyContinue
        }
        $RuntimeArtifactLeakExit = $runtimeLeak.ExitCode
        $runtimeLeakText = $runtimeLeak.Output -join "`n"
        $runtimeScanMatch = [regex]::Match($runtimeLeakText, "W1A_LEAK_GATE_SCANNED_FILES=(\d+)")
        if ($runtimeScanMatch.Success) {
            $RuntimeArtifactScanned = [int]$runtimeScanMatch.Groups[1].Value
        }
        Write-Output ("W1A_VS6_RUNTIME_ARTIFACT_LEAK_CODE=" + $RuntimeArtifactLeakExit)
        Write-Output ("W1A_VS6_RUNTIME_ARTIFACT_LEAK_SCANNED_FILES=" + $RuntimeArtifactScanned)
        if (
            $RuntimeArtifactLeakExit -eq 0 -and
            $runtimeScanMatch.Success -and
            $runtimeLeakText -match "W1A_LEAK_GATE_GREEN"
        ) {
            $RuntimeArtifactLeakSuccessful = $true
            Write-Output "W1A_VS6_RUNTIME_ARTIFACT_LEAK_GREEN=1"
        }
        else {
            Write-CapturedDiagnostic -Label "runtime-artifact-leak" -Result $runtimeLeak
            $HarnessFailure = $true
            Write-Output "W1A_VS6_HARNESS_FAILURE: runtime artifact leak gate"
        }
    }
    if (Test-Path -LiteralPath $TempRoot) {
        try {
            $resolvedTemp = [System.IO.Path]::GetFullPath($TempRoot)
            $resolvedParent = [System.IO.Path]::GetFullPath($TempParent).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
            if (-not $resolvedTemp.StartsWith($resolvedParent, [StringComparison]::OrdinalIgnoreCase)) {
                throw "unsafe temp cleanup target"
            }
            Remove-W1aVs6Tree `
                -Path $resolvedTemp `
                -ExpectedLeafPrefix "sswcenter-w1a-vs6-pg-"
        }
        catch {
            $HarnessFailure = $true
            Write-Output "W1A_VS6_HARNESS_FAILURE: temp cleanup"
        }
    }
    if (Test-Path -LiteralPath $ArtifactRoot) {
        try {
            $resolvedArtifact = [System.IO.Path]::GetFullPath($ArtifactRoot)
            $resolvedParent = [System.IO.Path]::GetFullPath($TempParent).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
            if (-not $resolvedArtifact.StartsWith($resolvedParent, [StringComparison]::OrdinalIgnoreCase)) {
                throw "unsafe runtime artifact cleanup target"
            }
            Remove-W1aVs6Tree `
                -Path $resolvedArtifact `
                -ExpectedLeafPrefix "sswcenter-w1a-vs6-artifacts-"
        }
        catch {
            $HarnessFailure = $true
            Write-Output "W1A_VS6_HARNESS_FAILURE: runtime artifact cleanup"
        }
    }
}

$remaining = @(Get-ChildItem -LiteralPath $TempParent -Directory -Filter "sswcenter-w1a-vs6-pg-*" -ErrorAction SilentlyContinue).Count
$listenerRemaining = Get-ListenerCount
$ArtifactRemaining = if (Test-Path -LiteralPath $TempRoot) {
    @(Get-ChildItem -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue | Where-Object {
            $_.Name -match "(?i)artifact|test-results|playwright-report"
        }).Count
}
else { 0 }
$MediaRemaining = if (Test-Path -LiteralPath $TempRoot) {
    @(Get-ChildItem -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue | Where-Object {
            $_.Name -match "(?i)media"
        }).Count
}
else { 0 }
$RuntimeArtifactRemaining = if (Test-Path -LiteralPath $ArtifactRoot) { 1 } else { 0 }
Write-Output ("W1A_VS6_TEMP_CLUSTER_REMAINING=" + $remaining)
Write-Output ("W1A_VS6_LISTENER_REMAINING=" + $listenerRemaining)
Write-Output ("W1A_VS6_ARTIFACT_REMAINING=" + $ArtifactRemaining)
Write-Output ("W1A_VS6_MEDIA_REMAINING=" + $MediaRemaining)
Write-Output ("W1A_VS6_RUNTIME_ARTIFACT_REMAINING=" + $RuntimeArtifactRemaining)
if (
    $remaining -ne 0 -or
    $listenerRemaining -ne 0 -or
    $ArtifactRemaining -ne 0 -or
    $MediaRemaining -ne 0 -or
    $RuntimeArtifactRemaining -ne 0 -or
    -not $PsqlArtifactAssertionPassed -or
    -not $RuntimeArtifactLeakSuccessful
) { $HarnessFailure = $true }
$ActualRedMarkers = @($ProductMarkers | Sort-Object -Unique)
$ExpectedRedMarkers = @($RequiredRedMarkers | Sort-Object -Unique)
$MissingRedMarkers = @($ExpectedRedMarkers | Where-Object { $_ -notin $ActualRedMarkers })
$UnexpectedRedMarkers = @($ActualRedMarkers | Where-Object { $_ -notin $ExpectedRedMarkers })
$RunTotalsMatchCollection = $null -ne $Collected -and ($Passed + $Failed + $Skipped + $Errors -eq $Collected)
$RedCountsExact = (
    $Collected -eq $ExpectedCollectedTests -and
    $RunExitCode -eq $ExpectedRunExitCode -and
    $Passed -eq $ExpectedPassed -and
    $Failed -eq $ExpectedFailed -and
    $Skipped -eq $ExpectedSkipped -and
    $Errors -eq $ExpectedErrors -and
    $RunTotalsMatchCollection
)
$RedMarkersExact = ($MissingRedMarkers.Count -eq 0 -and $UnexpectedRedMarkers.Count -eq 0)
Write-Output ("W1A_VS6_EXPECTED_COUNTS=collected:{0} run_exit:{1} passed:{2} failed:{3} skipped:{4} errors:{5}" -f $ExpectedCollectedTests, $ExpectedRunExitCode, $ExpectedPassed, $ExpectedFailed, $ExpectedSkipped, $ExpectedErrors)
Write-Output ("W1A_VS6_EXPECTED_RED_MARKERS=" + ($ExpectedRedMarkers -join ","))
$SyntheticActualRedMarkers = @($ExpectedRedMarkers | Sort-Object -Unique)
$SyntheticMissingRedMarkers = @($ExpectedRedMarkers | Where-Object { $_ -notin $SyntheticActualRedMarkers })
$SyntheticUnexpectedRedMarkers = @($SyntheticActualRedMarkers | Where-Object { $_ -notin $ExpectedRedMarkers })
$SyntheticRunTotalsMatchCollection = (
    $ExpectedPassed + $ExpectedFailed + $ExpectedSkipped + $ExpectedErrors -eq $ExpectedCollectedTests
)
$SyntheticRedCountsExact = (
    $ExpectedCollectedTests -eq 39 -and
    $ExpectedRunExitCode -eq 1 -and
    $ExpectedPassed -eq 23 -and
    $ExpectedFailed -eq 16 -and
    $ExpectedSkipped -eq 0 -and
    $ExpectedErrors -eq 0 -and
    $SyntheticRunTotalsMatchCollection
)
$SyntheticRedMarkersExact = (
    $ExpectedRedMarkers.Count -eq 16 -and
    $SyntheticMissingRedMarkers.Count -eq 0 -and
    $SyntheticUnexpectedRedMarkers.Count -eq 0
)
$SyntheticHarnessLines = @(
    "============================= short test summary info =============================",
    "23 passed, 16 failed, 0 skipped, 0 errors in 1.0s",
    "Exception ignored in atexit callback:",
    "Traceback (most recent call last):",
    "  synthetic infrastructure traceback"
)
$SyntheticHarnessFailure = Test-HarnessOutput $SyntheticHarnessLines
$SyntheticWouldEmitRedValid = (
    $SyntheticRedCountsExact -and
    $SyntheticRedMarkersExact -and
    -not $SyntheticHarnessFailure
)
$SyntheticSelfCheckOk = $SyntheticHarnessFailure -and -not $SyntheticWouldEmitRedValid
Write-Output ("SYNTHETIC_ATEXIT_TRACEBACK_WOULD_EMIT_RED_VALID=" + $SyntheticWouldEmitRedValid)
Write-Output ("W1A_VS6_SYNTHETIC_ATEXIT_HARNESS_FAILURE=" + $SyntheticHarnessFailure)
Write-Output ("W1A_VS6_SYNTHETIC_ATEXIT_SELF_CHECK_OK=" + $SyntheticSelfCheckOk)
if (-not $SyntheticSelfCheckOk) {
    $HarnessFailure = $true
    Write-Output "W1A_VS6_HARNESS_FAILURE: synthetic atexit traceback self-check"
}
$SyntheticThreadWarningLines = @(
    "PytestUnhandledThreadExceptionWarning: Exception in thread synthetic-worker",
    "Traceback (most recent call last):",
    "  synthetic thread exception",
    "39 passed, 1 warning in 1.0s"
)
$SyntheticThreadWarningHarnessFailure = Test-HarnessOutput $SyntheticThreadWarningLines
$SyntheticThreadWarningWouldEmitGreen = (
    $SyntheticRedCountsExact -and
    $SyntheticRedMarkersExact -and
    -not $SyntheticThreadWarningHarnessFailure
)
$SyntheticThreadWarningSelfCheckOk = (
    $SyntheticThreadWarningHarnessFailure -and
    -not $SyntheticThreadWarningWouldEmitGreen
)
Write-Output ("SYNTHETIC_THREAD_WARNING_WOULD_EMIT_GREEN=" + $SyntheticThreadWarningWouldEmitGreen)
Write-Output ("W1A_VS6_SYNTHETIC_THREAD_WARNING_HARNESS_FAILURE=" + $SyntheticThreadWarningHarnessFailure)
Write-Output ("W1A_VS6_SYNTHETIC_THREAD_WARNING_SELF_CHECK_OK=" + $SyntheticThreadWarningSelfCheckOk)
if (-not $SyntheticThreadWarningSelfCheckOk) {
    $HarnessFailure = $true
    Write-Output "W1A_VS6_HARNESS_FAILURE: synthetic thread warning self-check"
}
if ($HarnessFailure) { exit 2 }
if ($ExpectGreen) {
    if (
        $RunExitCode -eq $ExpectedGreenRunExitCode -and
        $Collected -eq $ExpectedCollectedTests -and
        $Passed -eq $ExpectedGreenPassed -and
        $Failed -eq $ExpectedGreenFailed -and
        $Skipped -eq $ExpectedGreenSkipped -and
        $Errors -eq $ExpectedGreenErrors -and
        $RunTotalsMatchCollection -and
        $ActualRedMarkers.Count -eq 0 -and
        $LifecycleSuccessful -and
        $OfflineSuccessful -and
        $PostcheckSuccessful -and
        $RestoreSuccessful -and
        $RuntimeArtifactLeakSuccessful -and
        $remaining -eq 0 -and
        $listenerRemaining -eq 0 -and
        $ArtifactRemaining -eq 0 -and
        $MediaRemaining -eq 0 -and
        $RuntimeArtifactRemaining -eq 0 -and
        $PsqlArtifactAssertionPassed
    ) {
        Write-Output "W1A_VS6_GREEN"
        exit 0
    }
    Write-Output ("W1A_VS6_FIRST_MARKER=" + ($ActualRedMarkers | Select-Object -First 1))
    Write-Output ("W1A_VS6_RED_MARKERS=" + ($ActualRedMarkers -join ","))
    Write-Output "W1A_VS6_GREEN_NOT_REPRODUCED"
    exit 2
}
if (-not $RedCountsExact -or -not $RedMarkersExact) {
    Write-Output ("W1A_VS6_FIRST_MARKER=" + ($ActualRedMarkers | Select-Object -First 1))
    Write-Output ("W1A_VS6_RED_MARKERS=" + ($ActualRedMarkers -join ","))
    Write-Output ("W1A_VS6_MISSING_RED_MARKERS=" + ($MissingRedMarkers -join ","))
    Write-Output ("W1A_VS6_UNEXPECTED_RED_MARKERS=" + ($UnexpectedRedMarkers -join ","))
    Write-Output "W1A_VS6_RED_NOT_REPRODUCED"
    exit 2
}
Write-Output ("W1A_VS6_FIRST_MARKER=" + ($ActualRedMarkers | Select-Object -First 1))
Write-Output ("W1A_VS6_RED_MARKERS=" + ($ActualRedMarkers -join ","))
Write-Output "W1A_VS6_RED_VALID"
exit 1
