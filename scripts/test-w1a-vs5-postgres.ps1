param(
    [int]$Port = 55438,
    [int]$CommandTimeoutSeconds = 90,
    [switch]$E2ERedOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$FrontendRoot = Join-Path $WorkspaceRoot "frontend"
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
$PsqlExe = Join-Path $PostgresBin "psql.exe"
$PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$NpmExe = "C:\Program Files\nodejs\npm.cmd"
$BackendPort = 8000
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
if ($E2ERedOnly) { $RequiredExecutables += $NpmExe }
if (@($RequiredExecutables | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }).Count -gt 0) {
    Write-Output "W1A_VS5_HARNESS_FAILURE: required runtime executable is missing"
    exit 2
}
if (@(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).Count -gt 0) {
    Write-Output "W1A_VS5_HARNESS_FAILURE: isolated port is occupied"
    exit 2
}
if ($E2ERedOnly -and @(Get-NetTCPConnection -State Listen -LocalPort $BackendPort -ErrorAction SilentlyContinue).Count -gt 0) {
    Write-Output "W1A_VS5_HARNESS_FAILURE: backend port 8000 is occupied"
    exit 2
}
if ($E2ERedOnly -and @(Get-NetTCPConnection -State Listen -LocalPort 4173 -ErrorAction SilentlyContinue).Count -gt 0) {
    Write-Output "W1A_VS5_HARNESS_FAILURE: frontend port 4173 is occupied"
    exit 2
}

$Revision = "20260728_0007_w1a_staff_quarterly_consultation"
$BaseRevision = "20260728_0006_w1a_staff_health_check"
$PreviousRevision = "20260728_0005_w1a_staff_training"
$MigrationPath = Join-Path $BackendRoot "alembic\versions\20260728_0007_w1a_staff_quarterly_consultation.py"
$PostcheckPath = Join-Path $BackendRoot "app\db\postcheck_w1a_vs1.py"
$RestorePath = Join-Path $PSScriptRoot "restore-drill.ps1"
$TempParent = if ([string]::IsNullOrWhiteSpace($env:SSWCENTER_VS5_TEMP_ROOT)) {
    [System.IO.Path]::GetTempPath()
}
else {
    [System.IO.Path]::GetFullPath($env:SSWCENTER_VS5_TEMP_ROOT)
}
$TempRoot = Join-Path $TempParent ("sswcenter-w1a-vs5-pg-" + [Guid]::NewGuid().ToString("N"))
$DataRoot = Join-Path $TempRoot "data"
$LogFile = Join-Path $TempRoot "postgres.log"
$DatabaseName = "w1a_vs5_review"
$OfflineDatabaseName = "w1a_vs5_offline_review"
$RestoreDatabaseName = "w1a_vs5_restore_review"
$OwnerPassword = "w1a_vs5_owner_only"
$AppPassword = "w1a_vs5_app_only"
$BackupPassword = "w1a_vs5_backup_only"
$ServerStarted = $false
$OfflineDatabaseCreated = $false
$RestoreDatabaseCreated = $false
$RestoreDataRoot = $null
$BackendProcess = $null
$BackendPidsBefore = @()
$FrontendPidsBefore = @()
$E2EExitCode = $null
$E2EPassed = 0
$E2EFailed = 0
$E2ESkipped = 0
$E2EErrors = 0
$E2EProductMarkerFound = $false
$E2ELocationPushed = $false
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
            return [pscustomobject]@{ ExitCode = 125; Output = @(); Stdout = @(); Stderr = @(); TimedOut = $false }
        }
        $stdoutTask = if (-not $isPgCtl) { $process.StandardOutput.ReadToEndAsync() } else { $null }
        $stderrTask = if (-not $isPgCtl) { $process.StandardError.ReadToEndAsync() } else { $null }
        if (-not $process.WaitForExit($CommandTimeoutSeconds * 1000)) {
            $process.Kill(); $process.WaitForExit()
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
    param([Parameter(Mandatory = $true)][string]$Database, [Parameter(Mandatory = $true)][string]$Sql)
    $sqlPath = Join-Path $TempRoot ("vs5-" + [Guid]::NewGuid().ToString("N") + ".sql")
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
        foreach ($match in [regex]::Matches([string]$line, "W1A_VS5_[A-Z0-9_]+")) {
            if ($match.Value.EndsWith("_OK") -or $match.Value.EndsWith("_GREEN")) { continue }
            if (-not $ProductMarkers.Contains($match.Value)) { $ProductMarkers.Add($match.Value) }
        }
    }
}

function Test-HarnessOutput([object[]]$Lines) {
    $text = $Lines -join "`n"
    return $text -match "Traceback|INTERNALERROR|W1A_VS5_HARNESS_FAILURE"
}

function Get-ListeningProcessIds {
    param([Parameter(Mandatory = $true)][int]$ListenPort)
    @(
        Get-NetTCPConnection -State Listen -LocalPort $ListenPort -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess |
            ForEach-Object { [int]$_ } |
            Sort-Object -Unique
    )
}

try {
    [System.IO.Directory]::CreateDirectory($TempParent) | Out-Null
    [System.IO.Directory]::CreateDirectory($TempRoot) | Out-Null
    Write-Output "W1A_VS5_STAGE=initdb"
    $init = Invoke-Captured -FilePath $InitDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
        "-D", $DataRoot, "-U", "postgres", "--auth=trust", "--no-locale", "--encoding=UTF8"
    )
    Write-Output ("W1A_VS5_INITDB_CODE=" + $init.ExitCode)
    if ($init.ExitCode -ne 0) { $HarnessFailure = $true; Write-Output "W1A_VS5_HARNESS_FAILURE: initdb" }
    else {
        Write-Output "W1A_VS5_STAGE=pg_start"
        $start = Invoke-Captured -FilePath $PgCtlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-D", $DataRoot, "-l", $LogFile, "-o", "-p $Port -h 127.0.0.1", "start", "-w"
        )
        Write-Output ("W1A_VS5_PG_START_CODE=" + $start.ExitCode)
        if ($start.ExitCode -ne 0) { $HarnessFailure = $true; Write-Output "W1A_VS5_HARNESS_FAILURE: pg_ctl start" }
        else {
            $ServerStarted = $true
            Write-Output "W1A_VS5_STAGE=database_bootstrap"
            $roles = Invoke-Psql -Database "postgres" -Sql @"
CREATE ROLE erp_owner LOGIN PASSWORD '$OwnerPassword';
CREATE ROLE erp_app LOGIN PASSWORD '$AppPassword';
CREATE ROLE erp_backup LOGIN PASSWORD '$BackupPassword';
"@
            $database = Invoke-Captured -FilePath $CreateDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-O", "erp_owner", $DatabaseName
            )
            Write-Output ("W1A_VS5_BOOTSTRAP_CODES=roles:{0} database:{1}" -f $roles.ExitCode, $database.ExitCode)
            if ($roles.ExitCode -ne 0 -or $database.ExitCode -ne 0) { $HarnessFailure = $true; Write-Output "W1A_VS5_HARNESS_FAILURE: bootstrap" }
            else {
                $env:SSWCENTER_ENVIRONMENT = "test"
                $env:SSWCENTER_POSTGRES_TEST = "1"
                $env:SSWCENTER_DATA_ROOT = Join-Path $TempRoot "sswcenter-runtime"
                $env:SSWCENTER_DATABASE_URL = "postgresql+psycopg://erp_owner:$OwnerPassword@127.0.0.1:$Port/$DatabaseName"
                $env:SSWCENTER_APP_DATABASE_URL = "postgresql+psycopg://erp_app:$AppPassword@127.0.0.1:$Port/$DatabaseName"
                $env:SSWCENTER_BACKUP_DATABASE_URL = "postgresql+psycopg://erp_backup:$BackupPassword@127.0.0.1:$Port/$DatabaseName"
                [System.IO.Directory]::CreateDirectory($env:SSWCENTER_DATA_ROOT) | Out-Null
                $testFiles = @(
                    "tests/test_w1a_vs5_semantics.py",
                    "tests/test_w1a_vs5_api.py",
                    "tests/test_w1a_vs5_postgres.py",
                    "tests/test_w1a_vs5_openapi_contract.py",
                    "tests/test_w1a_vs5_absence_contract.py"
                )
                $qualityFiles = $testFiles | ForEach-Object { Join-Path $BackendRoot $_ }

                Write-Output "W1A_VS5_STAGE=quality"
                $format = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments (@("-m", "ruff", "format", "--check") + $qualityFiles)
                $ruff = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments (@("-m", "ruff", "check") + $qualityFiles)
                $compile = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments (@("-m", "compileall", "-q") + $qualityFiles)
                Write-Output ("W1A_VS5_QUALITY_CODES=format:{0} ruff:{1} compile:{2}" -f $format.ExitCode, $ruff.ExitCode, $compile.ExitCode)
                if ($format.ExitCode -ne 0 -or $ruff.ExitCode -ne 0 -or $compile.ExitCode -ne 0) { $HarnessFailure = $true; Write-Output "W1A_VS5_HARNESS_FAILURE: quality" }

                Write-Output "W1A_VS5_STAGE=migration"
                $migration = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "upgrade", "head")
                Write-Output ("W1A_VS5_MIGRATION_UPGRADE_CODE=" + $migration.ExitCode)
                $hasVs5Migration = Test-Path -LiteralPath $MigrationPath -PathType Leaf
                if (-not $hasVs5Migration -and -not $E2ERedOnly) { Add-ProductMarkers @("W1A_VS5_MIGRATION_MISSING") }
                if ($migration.ExitCode -ne 0) { $HarnessFailure = $true; Write-Output "W1A_VS5_HARNESS_FAILURE: baseline migration" }
                $appliedRevision = if ($hasVs5Migration) { $Revision } else { $BaseRevision }

                if (-not $E2ERedOnly) {
                Write-Output "W1A_VS5_STAGE=lifecycle"
                $downTarget = if ($hasVs5Migration) { $BaseRevision } else { $PreviousRevision }
                $lifecycle = @(
                    (Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "downgrade", $downTarget)),
                    (Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "upgrade", $appliedRevision)),
                    (Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "downgrade", $downTarget)),
                    (Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "upgrade", $appliedRevision))
                )
                Write-Output ("W1A_VS5_LIFECYCLE_CODES=down:{0} up:{1} down_again:{2} up_again:{3}" -f $lifecycle[0].ExitCode, $lifecycle[1].ExitCode, $lifecycle[2].ExitCode, $lifecycle[3].ExitCode)
                if (@($lifecycle | Where-Object { $_.ExitCode -ne 0 }).Count -gt 0) { $HarnessFailure = $true; Write-Output "W1A_VS5_HARNESS_FAILURE: migration lifecycle" }

                Write-Output "W1A_VS5_STAGE=offline"
                $offline = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "alembic", "upgrade", $appliedRevision, "--sql")
                Write-Output ("W1A_VS5_OFFLINE_CODE=" + $offline.ExitCode)
                if ($offline.ExitCode -ne 0) {
                    $HarnessFailure = $true
                    Write-Output "W1A_VS5_HARNESS_FAILURE: offline generation"
                }
                else {
                    $offlineSqlPath = Join-Path $TempRoot "vs5-offline.sql"
                    [System.IO.File]::WriteAllLines($offlineSqlPath, [string[]]$offline.Stdout, [System.Text.UTF8Encoding]::new($false))
                    $offlineDatabase = Invoke-Captured -FilePath $CreateDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                        "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-O", "erp_owner", $OfflineDatabaseName
                    )
                    if ($offlineDatabase.ExitCode -eq 0) { $OfflineDatabaseCreated = $true }
                    $offlineApply = if ($offlineDatabase.ExitCode -eq 0) {
                        Invoke-Captured -FilePath $PsqlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                            "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-d", $OfflineDatabaseName,
                            "-v", "ON_ERROR_STOP=1", "-f", $offlineSqlPath
                        )
                    }
                    else { [pscustomobject]@{ ExitCode = 125; Output = @(); Stdout = @(); Stderr = @(); TimedOut = $false } }
                    $verificationSql = if ($hasVs5Migration) {
                        "SELECT CASE WHEN EXISTS (SELECT 1 FROM erp.alembic_version WHERE version_num = '$Revision') AND EXISTS (SELECT 1 FROM pg_class WHERE relnamespace = 'erp'::regnamespace AND relname = 'staff_quarterly_consultation') THEN 0 ELSE 1 END"
                    }
                    else {
                        "SELECT CASE WHEN EXISTS (SELECT 1 FROM erp.alembic_version WHERE version_num = '$BaseRevision') AND EXISTS (SELECT 1 FROM pg_class WHERE relnamespace = 'erp'::regnamespace AND relname = 'staff_health_check') THEN 0 ELSE 1 END"
                    }
                    $offlineVerify = if ($offlineApply.ExitCode -eq 0) {
                        Invoke-Captured -FilePath $PsqlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                            "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-d", $OfflineDatabaseName,
                            "-v", "ON_ERROR_STOP=1", "-At", "-c", $verificationSql
                        )
                    }
                    else { [pscustomobject]@{ ExitCode = 125; Output = @(); Stdout = @(); Stderr = @(); TimedOut = $false } }
                    Write-Output ("W1A_VS5_OFFLINE_APPLY_CODES=database:{0} apply:{1} verify:{2}" -f $offlineDatabase.ExitCode, $offlineApply.ExitCode, $offlineVerify.ExitCode)
                    if ($offlineDatabase.ExitCode -ne 0 -or $offlineApply.ExitCode -ne 0 -or $offlineVerify.ExitCode -ne 0 -or ($offlineVerify.Stdout -join "`n") -notmatch "0") {
                        $HarnessFailure = $true
                        Write-Output "W1A_VS5_HARNESS_FAILURE: offline empty-db apply"
                    }
                }
                if (-not $hasVs5Migration) { Add-ProductMarkers @("W1A_VS5_OFFLINE_MISSING") }

                Write-Output "W1A_VS5_STAGE=pytest_collect"
                $collect = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments (@("-m", "pytest", "--collect-only", "-q") + $testFiles)
                $collectText = $collect.Output -join "`n"
                $collectMatch = [regex]::Match($collectText, "(\d+) tests? collected")
                if ($collectMatch.Success) { Write-Output ("W1A_VS5_COLLECTED_TESTS=" + $collectMatch.Groups[1].Value) }
                if ($collect.ExitCode -ne 0 -or -not $collectMatch.Success) { $HarnessFailure = $true; Write-Output "W1A_VS5_HARNESS_FAILURE: collection" }

                Write-Output "W1A_VS5_STAGE=pytest_run"
                $run = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments (@("-m", "pytest", "-q") + $testFiles)
                Add-ProductMarkers @($collect.Output + $run.Output)
                $summary = $run.Output -join "`n"
                $passed = 0; $failed = 0; $skipped = 0; $errors = 0
                foreach ($match in [regex]::Matches($summary, "(?i)(\d+)\s+(passed|failed|skipped|errors?)")) {
                    $value = [int]$match.Groups[1].Value
                    switch ($match.Groups[2].Value.ToLowerInvariant()) {
                        "passed" { $passed += $value }
                        "failed" { $failed += $value }
                        "skipped" { $skipped += $value }
                        "error" { $errors += $value }
                        "errors" { $errors += $value }
                    }
                }
                Write-Output ("W1A_VS5_TEST_COUNTS=passed:{0} failed:{1} skipped:{2} errors:{3}" -f $passed, $failed, $skipped, $errors)
                if (Test-HarnessOutput @($run.Output)) { $HarnessFailure = $true }
                if ($run.ExitCode -ne 0 -and -not (($run.Output -join "`n") -match "W1A_VS5_[A-Z0-9_]+")) { $HarnessFailure = $true; Write-Output "W1A_VS5_HARNESS_FAILURE: pytest returned without product marker" }

                Write-Output "W1A_VS5_STAGE=postcheck_restore"
                if (-not (Test-Path -LiteralPath $PostcheckPath -PathType Leaf)) {
                    Add-ProductMarkers @("W1A_VS5_POSTCHECK_MISSING")
                }
                else {
                    $postcheck = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @("-m", "app.db.postcheck_w1a_vs1")
                    $postcheckText = $postcheck.Output -join "`n"
                    if ($postcheck.ExitCode -eq 0) {
                        Write-Output "W1A_VS5_BASELINE_DB_POSTCHECK_OK"
                        if (-not $postcheckText.Contains("W1A_VS5_DB_POSTCHECK_OK")) { Add-ProductMarkers @("W1A_VS5_POSTCHECK_MISSING") }
                    }
                    elseif ($postcheckText -match "W1A_VS5_[A-Z0-9_]+") {
                        Add-ProductMarkers $postcheck.Output
                    }
                    else {
                        $HarnessFailure = $true
                        Write-Output "W1A_VS5_HARNESS_FAILURE: postcheck"
                    }
                }

                if (-not (Test-Path -LiteralPath $RestorePath -PathType Leaf)) {
                    Add-ProductMarkers @("W1A_VS5_RESTORE_MISSING")
                }
                else {
                    $backupRoot = Join-Path $TempRoot "backup"
                    [System.IO.Directory]::CreateDirectory($backupRoot) | Out-Null
                    $dumpPath = Join-Path $backupRoot "data.dump"
                    $dump = Invoke-Captured -FilePath $PgDumpExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                        "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-d", $DatabaseName,
                        "--format=custom", "--file", $dumpPath
                    )
                    if ($dump.ExitCode -ne 0) {
                        $HarnessFailure = $true
                        Write-Output "W1A_VS5_HARNESS_FAILURE: restore backup"
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
                        [System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Compress), [System.Text.UTF8Encoding]::new($false))
                        [System.IO.File]::WriteAllText((Join-Path $backupRoot "bundle.sha256"), ($dumpHash + " *data.dump"), [System.Text.UTF8Encoding]::new($false))
                        $RestoreDataRoot = Join-Path $TempParent ("sswcenter-restore-review-" + [Guid]::NewGuid().ToString("N"))
                        $RestoreDatabaseCreated = $true
                        $restore = Invoke-Captured -FilePath $PowerShellExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $RestorePath,
                            "-BackupDirectory", $backupRoot,
                            "-AdminDatabaseUrl", ("postgresql://postgres@127.0.0.1:{0}/postgres" -f $Port),
                            "-ReviewDatabaseName", $RestoreDatabaseName,
                            "-ReviewDataRoot", $RestoreDataRoot
                        )
                        $restoreText = $restore.Output -join "`n"
                        if ($restore.ExitCode -eq 0 -and $restoreText.Contains("RESTORE_DRILL_OK")) {
                            Write-Output ("W1A_VS5_BASELINE_RESTORE_OK=revision:{0}" -f $appliedRevision)
                            if (-not $hasVs5Migration) { Add-ProductMarkers @("W1A_VS5_RESTORE_MISSING") }
                        }
                        elseif ($restoreText -match "Unsupported backup Alembic revision|W1A_VS5_[A-Z0-9_]+") {
                            Add-ProductMarkers @("W1A_VS5_RESTORE_MISSING")
                        }
                        else {
                            $HarnessFailure = $true
                            Write-Output "W1A_VS5_HARNESS_FAILURE: restore drill"
                        }
                    }
                }
                }
                else {
                    Write-Output "W1A_VS5_STAGE=e2e_backend"
                    $env:SSWCENTER_W1A_VS5_REAL_PG = "1"
                    $env:SSWCENTER_PSQL_EXE = $PsqlExe
                    $BackendPidsBefore = @(Get-ListeningProcessIds -ListenPort $BackendPort)
                    $FrontendPidsBefore = @(Get-ListeningProcessIds -ListenPort 4173)

                    $backendStartInfo = [System.Diagnostics.ProcessStartInfo]::new()
                    $backendStartInfo.FileName = $PythonExe
                    $backendStartInfo.Arguments = "-m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort"
                    $backendStartInfo.WorkingDirectory = $BackendRoot
                    $backendStartInfo.UseShellExecute = $false
                    $backendStartInfo.CreateNoWindow = $true
                    $backendStartInfo.EnvironmentVariables["SSWCENTER_DATABASE_URL"] = [string]$env:SSWCENTER_APP_DATABASE_URL
                    $BackendProcess = [System.Diagnostics.Process]::Start($backendStartInfo)
                    if ($null -eq $BackendProcess) { throw "FastAPI process could not start" }

                    $backendReady = $false
                    for ($i = 0; $i -lt 30; $i++) {
                        if ($BackendProcess.HasExited) { break }
                        try {
                            $healthResponse = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/health/ready" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
                            if ($healthResponse.StatusCode -eq 200) {
                                $backendReady = $true
                                break
                            }
                        }
                        catch { }
                        Start-Sleep -Milliseconds 500
                    }
                    if (-not $backendReady) { throw "FastAPI health/ready did not become ready" }
                    Write-Output "W1A_VS5_BACKEND_READY=1"

                    Write-Output "W1A_VS5_STAGE=e2e_playwright"
                    Push-Location $FrontendRoot
                    $E2ELocationPushed = $true
                    try {
                        $previousErrorActionPreference = $ErrorActionPreference
                        try {
                            $ErrorActionPreference = "Continue"
                            $e2eOutput = @(& $NpmExe exec playwright -- test e2e/w1a-staff-quarterly-consultation-real-pg.spec.ts --workers=1 2>&1)
                            $E2EExitCode = $LASTEXITCODE
                        }
                        finally {
                            $ErrorActionPreference = $previousErrorActionPreference
                        }
                    }
                    finally {
                        if ($E2ELocationPushed) {
                            Pop-Location
                            $E2ELocationPushed = $false
                        }
                    }

                    $e2eText = $e2eOutput -join "`n"
                    $e2eSummaryText = [regex]::Replace(
                        $e2eText,
                        "\x1B\[[0-?]*[ -/]*[@-~]",
                        ""
                    )
                    $e2eOutput | ForEach-Object { Write-Output $_ }
                    $e2eProductMatches = [regex]::Matches($e2eText, "W1A_VS5_E2E_[A-Z0-9_]+")
                    foreach ($productMatch in $e2eProductMatches) {
                        if (-not $ProductMarkers.Contains($productMatch.Value)) {
                            $ProductMarkers.Add($productMatch.Value)
                        }
                    }
                    $E2EProductMarkerFound = $e2eProductMatches.Count -gt 0
                    foreach ($match in [regex]::Matches(
                        $e2eSummaryText,
                        "(?im)^\s*(\d+)\s+(passed|failed|skipped|errors?)(?:\s+\([^\r\n]*\))?\s*$"
                    )) {
                        $value = [int]$match.Groups[1].Value
                        switch ($match.Groups[2].Value.ToLowerInvariant()) {
                            "passed" { $E2EPassed += $value }
                            "failed" { $E2EFailed += $value }
                            "skipped" { $E2ESkipped += $value }
                            "error" { $E2EErrors += $value }
                            "errors" { $E2EErrors += $value }
                        }
                    }
                    Write-Output ("W1A_VS5_E2E_TEST_COUNTS=passed:{0} failed:{1} skipped:{2} errors:{3}" -f $E2EPassed, $E2EFailed, $E2ESkipped, $E2EErrors)
                    if (Test-HarnessOutput @($e2eOutput)) {
                        $HarnessFailure = $true
                        Write-Output "W1A_VS5_HARNESS_FAILURE: Playwright emitted a harness error"
                    }
                    if ($E2EExitCode -eq 0) {
                        if ($E2EPassed -ne 3 -or $E2EFailed -ne 0 -or $E2ESkipped -ne 0 -or $E2EErrors -ne 0) {
                            $HarnessFailure = $true
                            Write-Output "W1A_VS5_HARNESS_FAILURE: E2E did not run all three projects green"
                        }
                    }
                    elseif ($E2EExitCode -ne 1 -or -not $E2EProductMarkerFound -or $E2EPassed -ne 0 -or $E2EFailed -ne 3 -or $E2ESkipped -ne 0 -or $E2EErrors -ne 0) {
                        $HarnessFailure = $true
                        Write-Output "W1A_VS5_HARNESS_FAILURE: E2E import/collection/setup failure"
                    }
                }
            }
        }
    }
}
catch {
    $HarnessFailure = $true
    Write-Output "W1A_VS5_HARNESS_FAILURE: unhandled harness condition"
}
finally {
    if ($E2ERedOnly) {
        if ($null -ne $BackendProcess) {
            try {
                if (-not $BackendProcess.HasExited) {
                    $BackendProcess.Kill()
                    if (-not $BackendProcess.WaitForExit(5000)) {
                        Stop-Process -Id $BackendProcess.Id -Force -ErrorAction Stop
                    }
                }
            }
            catch {
                $HarnessFailure = $true
                Write-Output "W1A_VS5_HARNESS_FAILURE: FastAPI cleanup"
            }
        }

        $backendPidsAfter = @(Get-ListeningProcessIds -ListenPort $BackendPort)
        foreach ($pidValue in $backendPidsAfter) {
            if ($BackendPidsBefore -notcontains [int]$pidValue) {
                try { Stop-Process -Id ([int]$pidValue) -Force -ErrorAction Stop }
                catch { $HarnessFailure = $true; Write-Output "W1A_VS5_HARNESS_FAILURE: backend listener cleanup" }
            }
        }
        $frontendPidsAfter = @(Get-ListeningProcessIds -ListenPort 4173)
        foreach ($pidValue in $frontendPidsAfter) {
            if ($FrontendPidsBefore -notcontains [int]$pidValue) {
                try { Stop-Process -Id ([int]$pidValue) -Force -ErrorAction Stop }
                catch { $HarnessFailure = $true; Write-Output "W1A_VS5_HARNESS_FAILURE: frontend listener cleanup" }
            }
        }
        Start-Sleep -Milliseconds 250
        $backendListenerRemaining = @(Get-ListeningProcessIds -ListenPort $BackendPort)
        $frontendListenerRemaining = @(Get-ListeningProcessIds -ListenPort 4173)
        Write-Output ("W1A_VS5_BACKEND_LISTENER_REMAINING=" + $backendListenerRemaining.Count)
        Write-Output ("W1A_VS5_FRONTEND_LISTENER_REMAINING=" + $frontendListenerRemaining.Count)
        if ($backendListenerRemaining.Count -ne 0 -or $frontendListenerRemaining.Count -ne 0) {
            $HarnessFailure = $true
        }

        $frontendRootFull = [System.IO.Path]::GetFullPath($FrontendRoot)
        $frontendRootPrefix = $frontendRootFull.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
        $playwrightArtifactPaths = @(
            (Join-Path $FrontendRoot "test-results"),
            (Join-Path $FrontendRoot "playwright-report")
        )
        foreach ($artifactPath in $playwrightArtifactPaths) {
            $artifactFull = [System.IO.Path]::GetFullPath($artifactPath)
            if (-not $artifactFull.StartsWith($frontendRootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                $HarnessFailure = $true
                Write-Output "W1A_VS5_HARNESS_FAILURE: unsafe Playwright artifact cleanup target"
                continue
            }
            if (Test-Path -LiteralPath $artifactFull) {
                try { Remove-Item -LiteralPath $artifactFull -Recurse -Force }
                catch { $HarnessFailure = $true; Write-Output "W1A_VS5_HARNESS_FAILURE: Playwright artifact cleanup" }
            }
        }
        $playwrightArtifactRemaining = @($playwrightArtifactPaths | Where-Object { Test-Path -LiteralPath $_ }).Count
        Write-Output ("W1A_VS5_PLAYWRIGHT_ARTIFACT_REMAINING=" + $playwrightArtifactRemaining)
        if ($playwrightArtifactRemaining -ne 0) { $HarnessFailure = $true }
    }
    if ($ServerStarted -and $OfflineDatabaseCreated) {
        $dropOffline = Invoke-Captured -FilePath $DropDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "--if-exists", $OfflineDatabaseName
        )
        Write-Output ("W1A_VS5_OFFLINE_DROP_CODE=" + $dropOffline.ExitCode)
        if ($dropOffline.ExitCode -ne 0) { $HarnessFailure = $true }
    }
    if ($ServerStarted -and $RestoreDatabaseCreated) {
        $dropRestore = Invoke-Captured -FilePath $DropDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "--if-exists", $RestoreDatabaseName
        )
        Write-Output ("W1A_VS5_RESTORE_DROP_CODE=" + $dropRestore.ExitCode)
        if ($dropRestore.ExitCode -ne 0) { $HarnessFailure = $true }
    }
    if ($null -ne $RestoreDataRoot -and (Test-Path -LiteralPath $RestoreDataRoot)) {
        $restoreLeaf = Split-Path -Leaf ([System.IO.Path]::GetFullPath($RestoreDataRoot))
        if ($restoreLeaf.StartsWith("sswcenter-restore-review-", [StringComparison]::Ordinal)) {
            try { Remove-Item -LiteralPath $RestoreDataRoot -Recurse -Force }
            catch { $HarnessFailure = $true; Write-Output "W1A_VS5_HARNESS_FAILURE: restore artifact cleanup" }
        }
    }
    if ($ServerStarted) {
        $stop = Invoke-Captured -FilePath $PgCtlExe -WorkingDirectory $WorkspaceRoot -Arguments @("-D", $DataRoot, "stop", "-m", "fast", "-w")
        Write-Output ("W1A_VS5_PG_STOP_CODE=" + $stop.ExitCode)
        if ($stop.ExitCode -ne 0) { $HarnessFailure = $true }
    }
    if (Test-Path -LiteralPath $TempRoot) {
        try { Remove-Item -LiteralPath $TempRoot -Recurse -Force }
        catch { $HarnessFailure = $true; Write-Output "W1A_VS5_HARNESS_FAILURE: temp cleanup" }
    }
}

$remaining = @(Get-ChildItem -LiteralPath $TempParent -Directory -Filter "sswcenter-w1a-vs5-pg-*" -ErrorAction SilentlyContinue).Count
$listenerRemaining = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).Count
Write-Output ("W1A_VS5_TEMP_CLUSTER_REMAINING=" + $remaining)
Write-Output ("W1A_VS5_LISTENER_REMAINING=" + $listenerRemaining)
if ($listenerRemaining -ne 0) { $HarnessFailure = $true }

if ($E2ERedOnly) {
    $backendListenerRemainingFinal = @(Get-ListeningProcessIds -ListenPort $BackendPort).Count
    $frontendListenerRemainingFinal = @(Get-ListeningProcessIds -ListenPort 4173).Count
    Write-Output ("W1A_VS5_BACKEND_LISTENER_REMAINING_FINAL=" + $backendListenerRemainingFinal)
    Write-Output ("W1A_VS5_FRONTEND_LISTENER_REMAINING_FINAL=" + $frontendListenerRemainingFinal)
    if ($backendListenerRemainingFinal -ne 0 -or $frontendListenerRemainingFinal -ne 0) { $HarnessFailure = $true }
    if ($HarnessFailure -or $remaining -ne 0 -or $listenerRemaining -ne 0) { exit 2 }
    if ($E2EExitCode -eq 0 -and $E2EPassed -eq 3 -and $E2EFailed -eq 0 -and $E2ESkipped -eq 0 -and $E2EErrors -eq 0) {
        Write-Output "W1A_VS5_E2E_GREEN"
        exit 0
    }
    if ($E2EExitCode -eq 1 -and $E2EProductMarkerFound -and $E2EPassed -eq 0 -and $E2EFailed -eq 3 -and $E2ESkipped -eq 0 -and $E2EErrors -eq 0) {
        Write-Output ("W1A_VS5_FIRST_MARKER=" + ($ProductMarkers | Select-Object -First 1))
        Write-Output ("W1A_VS5_RED_MARKERS=" + ($ProductMarkers -join ","))
        Write-Output "W1A_VS5_E2E_RED_VALID"
        exit 1
    }
    Write-Output "W1A_VS5_E2E_RED_NOT_REPRODUCED"
    exit 2
}

if ($HarnessFailure -or $remaining -ne 0) { exit 2 }
if ($ProductMarkers.Count -eq 0) {
    Write-Output "W1A_VS5_RED_NOT_REPRODUCED"
    exit 2
}
Write-Output ("W1A_VS5_FIRST_MARKER=" + ($ProductMarkers | Select-Object -First 1))
Write-Output ("W1A_VS5_RED_MARKERS=" + ($ProductMarkers -join ","))
Write-Output "W1A_VS5_RED_VALID"
exit 1
