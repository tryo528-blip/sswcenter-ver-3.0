param(
    [int]$Port = 55437,
    [int]$CommandTimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$PythonExe = Join-Path $BackendRoot ".venv\Scripts\python.exe"
$PostgresBin = "C:\Program Files\PostgreSQL\17\bin"
$InitDbExe = Join-Path $PostgresBin "initdb.exe"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl.exe"
$CreateDbExe = Join-Path $PostgresBin "createdb.exe"
$DropDbExe = Join-Path $PostgresBin "dropdb.exe"
$PgDumpExe = Join-Path $PostgresBin "pg_dump.exe"
$PsqlExe = Join-Path $PostgresBin "psql.exe"
$PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$RequiredExecutables = @(
    $PythonExe,
    $InitDbExe,
    $PgCtlExe,
    $CreateDbExe,
    $DropDbExe,
    $PgDumpExe,
    $PsqlExe,
    $PowerShellExe
)
if (@($RequiredExecutables | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }).Count -gt 0) {
    Write-Output "W1A_VS4_PG_PREREQ_MISSING: runtime executable"
    exit 2
}
if (@(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).Count -gt 0) {
    Write-Output "W1A_VS4_PG_PREREQ_MISSING: isolated port is occupied"
    exit 2
}

$Revision = "20260728_0006_w1a_staff_health_check"
$MigrationPath = Join-Path $BackendRoot "alembic\versions\20260728_0006_w1a_staff_health_check.py"
$PostcheckPath = Join-Path $BackendRoot "app\db\postcheck_w1a_vs1.py"
$RestorePath = Join-Path $PSScriptRoot "restore-drill.ps1"
$TempRoot = [System.IO.Path]::GetFullPath(
    (Join-Path ([System.IO.Path]::GetTempPath()) ("sswcenter-w1a-vs4-pg-" + [Guid]::NewGuid().ToString("N")))
)
$DataRoot = Join-Path $TempRoot "data"
$LogFile = Join-Path $TempRoot "postgres.log"
$DatabaseName = "w1a_vs4_review"
$OfflineDatabaseName = "w1a_vs4_offline_review"
$RestoreDatabaseName = "w1a_vs4_restore_review"
$OwnerPassword = "w1a_vs4_owner_only"
$AppPassword = "w1a_vs4_app_only"
$BackupPassword = "w1a_vs4_backup_only"
$ServerStarted = $false
$OfflineDatabaseCreated = $false
$RestoreDatabaseCreated = $false
$RestoreDataRoot = $null
$HarnessFailure = $false
$ProductMarkers = [System.Collections.Generic.List[string]]::new()

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
        $startInfo.Arguments = ($Arguments | ForEach-Object { '"' + ([string]$_).Replace('"', '\"') + '"' }) -join " "
        $startInfo.WorkingDirectory = $WorkingDirectory
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = -not $isPgCtl
        $startInfo.RedirectStandardError = -not $isPgCtl
        $process.StartInfo = $startInfo
        if (-not $process.Start()) {
            return [pscustomobject]@{
                ExitCode = 125
                Output = @()
                Stdout = @()
                Stderr = @()
                TimedOut = $false
            }
        }
        $stdoutTask = if (-not $isPgCtl) { $process.StandardOutput.ReadToEndAsync() } else { $null }
        $stderrTask = if (-not $isPgCtl) { $process.StandardError.ReadToEndAsync() } else { $null }
        if (-not $process.WaitForExit($CommandTimeoutSeconds * 1000)) {
            $process.Kill(); $process.WaitForExit()
            return [pscustomobject]@{
                ExitCode = 124
                Output = @()
                Stdout = @()
                Stderr = @()
                TimedOut = $true
            }
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
        return [pscustomobject]@{
            ExitCode = 125
            Output = @()
            Stdout = @()
            Stderr = @()
            TimedOut = $false
        }
    }
    finally { $process.Dispose() }
}

function Invoke-Psql {
    param([Parameter(Mandatory = $true)][string]$Database, [Parameter(Mandatory = $true)][string]$Sql)
    $sqlPath = Join-Path $TempRoot ("vs4-" + [Guid]::NewGuid().ToString("N") + ".sql")
    [System.IO.File]::WriteAllText($sqlPath, $Sql, [System.Text.UTF8Encoding]::new($false))
    try {
        return Invoke-Captured -FilePath $PsqlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-d", $Database,
            "-v", "ON_ERROR_STOP=1", "-f", $sqlPath
        )
    }
    finally { if (Test-Path -LiteralPath $sqlPath) { Remove-Item -LiteralPath $sqlPath -Force } }
}

function Add-ProductMarkers([object[]]$Lines) {
    foreach ($line in $Lines) {
        foreach ($match in [regex]::Matches([string]$line, "W1A_VS4_[A-Z0-9_]+")) {
            if ($match.Value.EndsWith("_OK") -or $match.Value.EndsWith("_GREEN")) { continue }
            if (-not $ProductMarkers.Contains($match.Value)) { $ProductMarkers.Add($match.Value) }
        }
    }
}

function Get-FailureKind([object[]]$Lines) {
    $text = ($Lines -join "`n")
    if ($text -match "(?i)password|authentication") { return "authentication" }
    if ($text -match "(?i)permission denied|must be owner|not permitted") { return "permission" }
    if ($text -match "(?i)does not exist|undefined|relation .* missing|role .* missing") { return "missing_object" }
    if ($text -match "(?i)syntax|parse|invalid") { return "syntax" }
    return "external_command"
}

try {
    [System.IO.Directory]::CreateDirectory($TempRoot) | Out-Null
    Write-Output "W1A_VS4_STAGE=initdb"
    $init = Invoke-Captured -FilePath $InitDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
        "-D", $DataRoot, "-U", "postgres", "--auth=trust", "--no-locale", "--encoding=UTF8"
    )
    if ($init.ExitCode -ne 0) { $HarnessFailure = $true; Write-Output "W1A_VS4_HARNESS_FAILURE: initdb" }
    else {
        Write-Output "W1A_VS4_STAGE=pg_start"
        $start = Invoke-Captured -FilePath $PgCtlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-D", $DataRoot, "-l", $LogFile, "-o", "-p $Port -h 127.0.0.1", "start", "-w"
        )
        if ($start.ExitCode -ne 0) { $HarnessFailure = $true; Write-Output "W1A_VS4_HARNESS_FAILURE: pg_ctl start" }
        else {
            $ServerStarted = $true
            Write-Output "W1A_VS4_STAGE=database_bootstrap"
            $roles = Invoke-Psql -Database "postgres" -Sql @"
CREATE ROLE erp_owner LOGIN PASSWORD '$OwnerPassword';
CREATE ROLE erp_app LOGIN PASSWORD '$AppPassword';
CREATE ROLE erp_backup LOGIN PASSWORD '$BackupPassword';
"@
            $database = Invoke-Captured -FilePath $CreateDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-O", "erp_owner", $DatabaseName
            )
            Write-Output ("W1A_VS4_BOOTSTRAP_CODES=roles:{0} database:{1}" -f $roles.ExitCode, $database.ExitCode)
            if ($roles.ExitCode -ne 0 -or $database.ExitCode -ne 0) { $HarnessFailure = $true; Write-Output "W1A_VS4_HARNESS_FAILURE: bootstrap" }
            else {
                $env:SSWCENTER_ENVIRONMENT = "test"
                $env:SSWCENTER_POSTGRES_TEST = "1"
                $env:SSWCENTER_DATA_ROOT = Join-Path $TempRoot "sswcenter-runtime"
                $env:SSWCENTER_DATABASE_URL = "postgresql+psycopg://erp_owner:$OwnerPassword@127.0.0.1:$Port/$DatabaseName"
                $env:SSWCENTER_APP_DATABASE_URL = "postgresql+psycopg://erp_app:$AppPassword@127.0.0.1:$Port/$DatabaseName"
                $env:SSWCENTER_BACKUP_DATABASE_URL = "postgresql+psycopg://erp_backup:$BackupPassword@127.0.0.1:$Port/$DatabaseName"
                [System.IO.Directory]::CreateDirectory($env:SSWCENTER_DATA_ROOT) | Out-Null
                $testFiles = @(
                    "tests/test_w1a_vs4_semantics.py",
                    "tests/test_w1a_vs4_api.py",
                    "tests/test_w1a_vs4_postgres.py",
                    "tests/test_w1a_vs4_openapi_contract.py",
                    "tests/test_w1a_vs4_absence_contract.py"
                )
                $qualityFiles = $testFiles | ForEach-Object { Join-Path "backend" $_ }
                Write-Output "W1A_VS4_STAGE=quality"
                $formatArguments = @("-m", "ruff", "format", "--check") + $qualityFiles
                $ruffArguments = @("-m", "ruff", "check") + $qualityFiles
                $compileArguments = @("-m", "compileall", "-q") + $qualityFiles
                $format = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments $formatArguments
                $ruff = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments $ruffArguments
                $compile = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments $compileArguments
                Write-Output ("W1A_VS4_QUALITY_CODES=format:{0} ruff:{1} compile:{2}" -f $format.ExitCode, $ruff.ExitCode, $compile.ExitCode)
                if ($format.ExitCode -ne 0 -or $ruff.ExitCode -ne 0 -or $compile.ExitCode -ne 0) { $HarnessFailure = $true; Write-Output "W1A_VS4_HARNESS_FAILURE: quality" }

                Write-Output "W1A_VS4_STAGE=migration"
                $migration = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "upgrade", "head")
                Write-Output ("W1A_VS4_MIGRATION_UPGRADE_CODE=" + $migration.ExitCode)
                if (-not (Test-Path -LiteralPath $MigrationPath -PathType Leaf)) { Add-ProductMarkers @("W1A_VS4_MIGRATION_MISSING") }
                if ($migration.ExitCode -ne 0) {
                    $HarnessFailure = $true
                    Write-Output ("W1A_VS4_HARNESS_FAILURE: migration kind=" + (Get-FailureKind $migration.Output))
                }

                Write-Output "W1A_VS4_STAGE=lifecycle"
                if (Test-Path -LiteralPath $MigrationPath -PathType Leaf) {
                    $down = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "downgrade", "20260728_0005_w1a_staff_training")
                    $up = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "upgrade", $Revision)
                    $down2 = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "downgrade", "20260728_0005_w1a_staff_training")
                    $up2 = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "upgrade", $Revision)
                    Write-Output ("W1A_VS4_LIFECYCLE_CODES=down:{0} up:{1} down_again:{2} up_again:{3}" -f $down.ExitCode, $up.ExitCode, $down2.ExitCode, $up2.ExitCode)
                    $lifecycleCodes = @($down.ExitCode, $up.ExitCode, $down2.ExitCode, $up2.ExitCode)
                    if (@($lifecycleCodes | Where-Object { $_ -ne 0 }).Count -gt 0) {
                        $HarnessFailure = $true
                        Write-Output "W1A_VS4_HARNESS_FAILURE: migration lifecycle"
                    }
                }
                else { Add-ProductMarkers @("W1A_VS4_LIFECYCLE_MISSING") }

                Write-Output "W1A_VS4_STAGE=offline"
                $offlineTargetRevision = if (Test-Path -LiteralPath $MigrationPath -PathType Leaf) {
                    $Revision
                }
                else { "20260728_0005_w1a_staff_training" }
                $offlineVerificationSql = if (Test-Path -LiteralPath $MigrationPath -PathType Leaf) {
                    "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_class WHERE relnamespace = 'erp'::regnamespace AND relname = 'staff_health_check') AND EXISTS (SELECT 1 FROM pg_class WHERE relnamespace = 'erp'::regnamespace AND relname = 'staff_health_check_requirement') AND EXISTS (SELECT 1 FROM erp.alembic_version WHERE version_num = '$Revision') AND EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'erp' AND tablename = 'staff_health_check_requirement' AND indexname = 'uq_staff_health_check_requirement_active') AND (SELECT count(*) FROM pg_constraint WHERE conrelid = 'erp.staff_health_check_requirement'::regclass AND contype IN ('c', 'f')) >= 3 THEN 0 ELSE 1 END"
                }
                else {
                    "SELECT CASE WHEN EXISTS (SELECT 1 FROM erp.alembic_version WHERE version_num = '20260728_0005_w1a_staff_training') AND EXISTS (SELECT 1 FROM pg_class WHERE relnamespace = 'erp'::regnamespace AND relname = 'staff_periodic_training_status') THEN 0 ELSE 1 END"
                }
                $offline = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "upgrade", $offlineTargetRevision, "--sql")
                Write-Output ("W1A_VS4_OFFLINE_CODE=" + $offline.ExitCode)
                if ($offline.ExitCode -ne 0) {
                    $HarnessFailure = $true
                    Write-Output "W1A_VS4_HARNESS_FAILURE: offline generation"
                }
                else {
                    $offlineSqlPath = Join-Path $TempRoot "vs4-offline.sql"
                    [System.IO.File]::WriteAllLines(
                        $offlineSqlPath,
                        [string[]]$offline.Stdout,
                        [System.Text.UTF8Encoding]::new($false)
                    )
                    $offlineDatabase = Invoke-Captured -FilePath $CreateDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                        "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres",
                        "-O", "erp_owner", $OfflineDatabaseName
                    )
                    if ($offlineDatabase.ExitCode -eq 0) { $OfflineDatabaseCreated = $true }
                    $offlineApply = if ($offlineDatabase.ExitCode -eq 0) {
                        Invoke-Captured -FilePath $PsqlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                            "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres",
                            "-d", $OfflineDatabaseName, "-v", "ON_ERROR_STOP=1", "-f", $offlineSqlPath
                        )
                    }
                    else { [pscustomobject]@{ ExitCode = 125; Output = @(); TimedOut = $false } }
                    $offlineVerify = if ($offlineApply.ExitCode -eq 0) {
                        Invoke-Captured -FilePath $PsqlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                            "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres",
                            "-d", $OfflineDatabaseName, "-v", "ON_ERROR_STOP=1", "-At", "-c",
                            $offlineVerificationSql
                        )
                    }
                    else { [pscustomobject]@{ ExitCode = 125; Output = @(); TimedOut = $false } }
                    Write-Output ("W1A_VS4_OFFLINE_APPLY_CODES=database:{0} apply:{1} verify:{2}" -f $offlineDatabase.ExitCode, $offlineApply.ExitCode, $offlineVerify.ExitCode)
                    if ($offlineDatabase.ExitCode -ne 0 -or $offlineApply.ExitCode -ne 0 -or $offlineVerify.ExitCode -ne 0) {
                        $HarnessFailure = $true
                        Write-Output "W1A_VS4_HARNESS_FAILURE: offline empty-db apply"
                    }
                }
                if (-not (Test-Path -LiteralPath $MigrationPath -PathType Leaf)) {
                    Add-ProductMarkers @("W1A_VS4_OFFLINE_MISSING")
                }

                Write-Output "W1A_VS4_STAGE=pytest_collect"
                $collectArguments = @("-m", "pytest", "--collect-only", "-q") + $testFiles
                $collect = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments $collectArguments
                $collectText = $collect.Output -join "`n"
                $collectMatch = [regex]::Match($collectText, "(\d+) tests? collected")
                if ($collectMatch.Success) { Write-Output ("W1A_VS4_COLLECTED_TESTS=" + $collectMatch.Groups[1].Value) }
                if ($collect.ExitCode -ne 0) { $HarnessFailure = $true; Write-Output "W1A_VS4_HARNESS_FAILURE: collection" }

                Write-Output "W1A_VS4_STAGE=pytest_run"
                $runArguments = @("-m", "pytest", "-q") + $testFiles
                $run = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments $runArguments
                $allOutput = @($collect.Output + $run.Output)
                Add-ProductMarkers $allOutput
                $summary = $run.Output -join "`n"
                $passed = 0; $failed = 0; $skipped = 0; $errors = 0
                foreach ($match in [regex]::Matches($summary, "(?i)(\d+)\s+(passed|failed|skipped|errors?)")) {
                    $value = [int]$match.Groups[1].Value
                    switch ($match.Groups[2].Value.ToLowerInvariant()) { "passed" {$passed += $value}; "failed" {$failed += $value}; "skipped" {$skipped += $value}; "error" {$errors += $value}; "errors" {$errors += $value} }
                }
                Write-Output ("W1A_VS4_TEST_COUNTS=passed:{0} failed:{1} skipped:{2} errors:{3}" -f $passed,$failed,$skipped,$errors)
                if ($run.Output -match "Traceback|INTERNALERROR|W1A_VS4_HARNESS_FAILURE") { $HarnessFailure = $true }

                Write-Output "W1A_VS4_STAGE=postcheck_restore_contract"
                if (-not (Test-Path -LiteralPath $PostcheckPath -PathType Leaf)) {
                    Add-ProductMarkers @("W1A_VS4_POSTCHECK_MISSING")
                }
                else {
                    $postcheck = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @(
                        "-m", "app.db.postcheck_w1a_vs1"
                    )
                    if ($postcheck.ExitCode -eq 0 -and ($postcheck.Output -join "`n").Contains("W1A_VS4_DB_POSTCHECK_OK")) {
                        Write-Output "W1A_VS4_DB_POSTCHECK_OK"
                    }
                    elseif ($postcheck.ExitCode -ne 0 -and ($postcheck.Output -join "`n") -match "W1A_VS4_[A-Z0-9_]+") {
                        Add-ProductMarkers $postcheck.Output
                    }
                    else {
                        Add-ProductMarkers @("W1A_VS4_POSTCHECK_MISSING")
                    }
                }

                if (-not (Test-Path -LiteralPath $RestorePath -PathType Leaf)) {
                    Add-ProductMarkers @("W1A_VS4_RESTORE_MISSING")
                }
                else {
                    $backupRoot = Join-Path $TempRoot "backup"
                    [System.IO.Directory]::CreateDirectory($backupRoot) | Out-Null
                    $dumpPath = Join-Path $backupRoot "data.dump"
                    $appliedRevision = if (Test-Path -LiteralPath $MigrationPath -PathType Leaf) {
                        $Revision
                    }
                    else { "20260728_0005_w1a_staff_training" }
                    $dump = Invoke-Captured -FilePath $PgDumpExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                        "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-d", $DatabaseName,
                        "--format=custom", "--file", $dumpPath
                    )
                    if ($dump.ExitCode -ne 0) {
                        $HarnessFailure = $true
                        Write-Output "W1A_VS4_HARNESS_FAILURE: restore backup"
                    }
                    else {
                        $dumpHash = (Get-FileHash -LiteralPath $dumpPath -Algorithm SHA256).Hash.ToLowerInvariant()
                        $manifest = [pscustomobject]@{
                            alembic_revision = $appliedRevision
                            dump_file = "data.dump"
                            dump_sha256 = $dumpHash
                            files = @()
                        }
                        $manifestPath = Join-Path $backupRoot "manifest.json"
                        [System.IO.File]::WriteAllText(
                            $manifestPath,
                            ($manifest | ConvertTo-Json -Compress),
                            [System.Text.UTF8Encoding]::new($false)
                        )
                        [System.IO.File]::WriteAllText(
                            (Join-Path $backupRoot "bundle.sha256"),
                            ($dumpHash + " *data.dump"),
                            [System.Text.UTF8Encoding]::new($false)
                        )
                        $restoreDataRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
                            "sswcenter-restore-review-" + [Guid]::NewGuid().ToString("N")
                        )
                        $RestoreDatabaseCreated = $true
                        $restore = Invoke-Captured -FilePath $PowerShellExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $RestorePath,
                            "-BackupDirectory", $backupRoot,
                            "-AdminDatabaseUrl", ("postgresql://postgres@127.0.0.1:{0}/postgres" -f $Port),
                            "-ReviewDatabaseName", $RestoreDatabaseName,
                            "-ReviewDataRoot", $restoreDataRoot
                        )
                        $restoreText = $restore.Output -join "`n"
                        if ($restore.ExitCode -eq 0 -and $restoreText.Contains("RESTORE_DRILL_OK")) {
                            Write-Output ("W1A_VS4_RESTORE_ACTUAL_OK=revision:{0}" -f $appliedRevision)
                            if ($appliedRevision -ne $Revision) {
                                Add-ProductMarkers @("W1A_VS4_RESTORE_MISSING")
                            }
                        }
                        elseif ($restoreText -match "Unsupported backup Alembic revision|W1A_VS4_DB_POSTCHECK_OK|W1A_VS4") {
                            Add-ProductMarkers @("W1A_VS4_RESTORE_MISSING")
                        }
                        else {
                            $HarnessFailure = $true
                            Write-Output "W1A_VS4_HARNESS_FAILURE: restore drill"
                        }
                    }
                }
            }
        }
    }
}
catch {
    $HarnessFailure = $true
    Write-Output "W1A_VS4_HARNESS_FAILURE: unhandled harness condition"
}
finally {
    if ($ServerStarted -and $OfflineDatabaseCreated) {
        $dropOffline = Invoke-Captured -FilePath $DropDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "--if-exists", $OfflineDatabaseName
        )
        Write-Output ("W1A_VS4_OFFLINE_DROP_CODE=" + $dropOffline.ExitCode)
        if ($dropOffline.ExitCode -ne 0) { $HarnessFailure = $true }
    }
    if ($ServerStarted -and $RestoreDatabaseCreated) {
        $dropRestore = Invoke-Captured -FilePath $DropDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "--if-exists", $RestoreDatabaseName
        )
        Write-Output ("W1A_VS4_RESTORE_DROP_CODE=" + $dropRestore.ExitCode)
        if ($dropRestore.ExitCode -ne 0) { $HarnessFailure = $true }
    }
    if ($null -ne $RestoreDataRoot -and (Test-Path -LiteralPath $RestoreDataRoot)) {
        $restoreLeaf = Split-Path -Leaf ([System.IO.Path]::GetFullPath($RestoreDataRoot))
        if ($restoreLeaf.StartsWith("sswcenter-restore-review-", [StringComparison]::Ordinal)) {
            try { Remove-Item -LiteralPath $RestoreDataRoot -Recurse -Force }
            catch { $HarnessFailure = $true; Write-Output "W1A_VS4_HARNESS_FAILURE: restore artifact cleanup" }
        }
    }
    if ($ServerStarted) {
        $stop = Invoke-Captured -FilePath $PgCtlExe -WorkingDirectory $WorkspaceRoot -Arguments @("-D", $DataRoot, "stop", "-m", "fast", "-w")
        Write-Output ("W1A_VS4_PG_STOP_CODE=" + $stop.ExitCode)
        if ($stop.ExitCode -ne 0) { $HarnessFailure = $true }
    }
    if (Test-Path -LiteralPath $TempRoot) {
        try { Remove-Item -LiteralPath $TempRoot -Recurse -Force }
        catch { $HarnessFailure = $true; Write-Output "W1A_VS4_HARNESS_FAILURE: cleanup" }
    }
}

$remaining = @(Get-ChildItem -LiteralPath ([System.IO.Path]::GetTempPath()) -Directory -Filter "sswcenter-w1a-vs4-pg-*" -ErrorAction SilentlyContinue).Count
Write-Output ("W1A_VS4_TEMP_CLUSTER_REMAINING=" + $remaining)
if ($HarnessFailure -or $remaining -ne 0) { exit 2 }
if ($ProductMarkers.Count -eq 0) { Write-Output "W1A_VS4_RED_NOT_REPRODUCED"; exit 2 }
Write-Output ("W1A_VS4_FIRST_MARKER=" + ($ProductMarkers | Select-Object -First 1))
Write-Output ("W1A_VS4_RED_MARKERS=" + ($ProductMarkers -join ","))
Write-Output "W1A_VS4_RED_VALID"
exit 1
