param(
    [int]$Port = 55435,
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
$PsqlExe = Join-Path $PostgresBin "psql.exe"
$RequiredExecutables = @($PythonExe, $InitDbExe, $PgCtlExe, $CreateDbExe, $PsqlExe)
$MissingExecutables = @(
    $RequiredExecutables | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }
)
if ($MissingExecutables.Count -gt 0) {
    Write-Output "W1A_VS3_PG_PREREQ_MISSING: runtime executable"
    exit 2
}

$ExistingListener = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
if ($ExistingListener.Count -gt 0) {
    Write-Output "W1A_VS3_PG_PREREQ_MISSING: isolated port is occupied"
    exit 2
}

$Vs3Revision = "20260728_0005_w1a_staff_training"
$Vs3MigrationPath = Join-Path $BackendRoot "alembic\versions\20260728_0005_w1a_staff_training.py"
$PostcheckPath = Join-Path $BackendRoot "app\db\postcheck_w1a_vs1.py"
$RestorePath = Join-Path $PSScriptRoot "restore-drill.ps1"
$TempRoot = [System.IO.Path]::GetFullPath(
    (Join-Path ([System.IO.Path]::GetTempPath()) ("sswcenter-w1a-vs3-pg-" + [Guid]::NewGuid().ToString("N")))
)
$DataRoot = Join-Path $TempRoot "data"
$LogFile = Join-Path $TempRoot "postgres.log"
$DatabaseName = "w1a_vs3_review"
$OwnerPassword = "w1a_vs3_owner_only"
$AppPassword = "w1a_vs3_app_only"
$BackupPassword = "w1a_vs3_backup_only"
$ServerStarted = $false
$ProductMarkers = [System.Collections.Generic.List[string]]::new()
$HarnessFailure = $false
$PytestOutput = @()
$CollectOutput = @()

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
        $process.StartInfo = $startInfo
        if (-not $process.Start()) {
            return [pscustomobject]@{ ExitCode = 125; Output = @("launch failed"); TimedOut = $false }
        }
        $stdoutTask = if (-not $isPgCtl) { $process.StandardOutput.ReadToEndAsync() } else { $null }
        $stderrTask = if (-not $isPgCtl) { $process.StandardError.ReadToEndAsync() } else { $null }
        if (-not $process.WaitForExit($CommandTimeoutSeconds * 1000)) {
            $process.Kill()
            $process.WaitForExit()
            return [pscustomobject]@{ ExitCode = 124; Output = @("command timeout"); TimedOut = $true }
        }
        $process.WaitForExit()
        $stdout = if ($isPgCtl -or [string]::IsNullOrEmpty($stdoutTask.Result)) { @() } else { $stdoutTask.Result -split "`r?`n" }
        $stderr = if ($isPgCtl -or [string]::IsNullOrEmpty($stderrTask.Result)) { @() } else { $stderrTask.Result -split "`r?`n" }
        return [pscustomobject]@{
            ExitCode = [int]$process.ExitCode
            Output = @($stdout + $stderr)
            TimedOut = $false
        }
    }
    catch {
        return [pscustomobject]@{ ExitCode = 125; Output = @("command launch failed"); TimedOut = $false }
    }
    finally {
        $process.Dispose()
    }
}

function Invoke-Psql {
    param(
        [Parameter(Mandatory = $true)] [string]$Database,
        [Parameter(Mandatory = $true)] [string]$Sql,
        [string]$User = "postgres"
    )
    $sqlPath = Join-Path $TempRoot ("vs3-" + [Guid]::NewGuid().ToString("N") + ".sql")
    [System.IO.File]::WriteAllText($sqlPath, $Sql, [System.Text.UTF8Encoding]::new($false))
    try {
        return Invoke-Captured -FilePath $PsqlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-h", "127.0.0.1", "-p", [string]$Port, "-U", $User, "-d", $Database,
            "-v", "ON_ERROR_STOP=1", "-f", $sqlPath
        )
    }
    finally {
        if ([System.IO.File]::Exists($sqlPath)) { [System.IO.File]::Delete($sqlPath) }
    }
}

function Add-ProductMarker {
    param([Parameter(Mandatory = $true)] [string]$Marker)
    if (-not $ProductMarkers.Contains($Marker)) { $ProductMarkers.Add($Marker) }
}

function Get-NamedMarkers {
    param([Parameter(Mandatory = $true)] [object[]]$Lines)
    @(
        $Lines |
            ForEach-Object { [regex]::Matches([string]$_, "W1A_VS3_[A-Z0-9_]+") } |
            ForEach-Object { $_.Value } |
            Sort-Object -Unique
    )
}

try {
    [System.IO.Directory]::CreateDirectory($TempRoot) | Out-Null
    Write-Output "W1A_VS3_STAGE=initdb"
    $init = Invoke-Captured -FilePath $InitDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
        "-D", $DataRoot, "-U", "postgres", "--auth=trust", "--no-locale", "--encoding=UTF8"
    )
    if ($init.ExitCode -ne 0) {
        $HarnessFailure = $true
        Write-Output "W1A_VS3_HARNESS_FAILURE: initdb"
    }
    else {
        Write-Output "W1A_VS3_STAGE=pg_start"
        $start = Invoke-Captured -FilePath $PgCtlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-D", $DataRoot, "-l", $LogFile, "-o", "-p $Port -h 127.0.0.1", "start", "-w"
        )
        if ($start.ExitCode -ne 0) {
            $HarnessFailure = $true
            Write-Output "W1A_VS3_HARNESS_FAILURE: pg_ctl start"
        }
        else {
            $ServerStarted = $true
            Write-Output "W1A_VS3_STAGE=database_bootstrap"
            $roles = Invoke-Psql -Database "postgres" -Sql @"
CREATE ROLE erp_owner LOGIN PASSWORD '$OwnerPassword';
CREATE ROLE erp_app LOGIN PASSWORD '$AppPassword';
CREATE ROLE erp_backup LOGIN PASSWORD '$BackupPassword';
"@
            $database = Invoke-Captured -FilePath $CreateDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-O", "erp_owner", $DatabaseName
            )
            Write-Output ("W1A_VS3_BOOTSTRAP_CODES=roles:{0} database:{1}" -f $roles.ExitCode, $database.ExitCode)
            if ($roles.ExitCode -ne 0 -or $database.ExitCode -ne 0) {
                $HarnessFailure = $true
                Write-Output "W1A_VS3_HARNESS_FAILURE: isolated database bootstrap"
            }
            else {
                $env:SSWCENTER_ENVIRONMENT = "test"
                $env:SSWCENTER_POSTGRES_TEST = "1"
                $env:SSWCENTER_DATA_ROOT = Join-Path $TempRoot "sswcenter-runtime"
                $env:SSWCENTER_DATABASE_URL = "postgresql+psycopg://erp_owner:$OwnerPassword@127.0.0.1:$Port/$DatabaseName"
                $env:SSWCENTER_APP_DATABASE_URL = "postgresql+psycopg://erp_app:$AppPassword@127.0.0.1:$Port/$DatabaseName"
                $env:SSWCENTER_BACKUP_DATABASE_URL = "postgresql+psycopg://erp_backup:$BackupPassword@127.0.0.1:$Port/$DatabaseName"
                [System.IO.Directory]::CreateDirectory($env:SSWCENTER_DATA_ROOT) | Out-Null

                Write-Output "W1A_VS3_STAGE=quality"
                $format = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                    "-m", "ruff", "format", "--check",
                    "backend/tests/test_w1a_vs3_semantics.py",
                    "backend/tests/test_w1a_vs3_api.py",
                    "backend/tests/test_w1a_vs3_postgres.py",
                    "backend/tests/test_w1a_vs3_openapi_contract.py",
                    "backend/tests/test_w1a_vs3_absence_contract.py"
                )
                $ruff = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                    "-m", "ruff", "check", "backend/tests/test_w1a_vs3_semantics.py",
                    "backend/tests/test_w1a_vs3_api.py", "backend/tests/test_w1a_vs3_postgres.py",
                    "backend/tests/test_w1a_vs3_openapi_contract.py",
                    "backend/tests/test_w1a_vs3_absence_contract.py"
                )
                $compile = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                    "-m", "compileall", "-q", "backend/tests/test_w1a_vs3_semantics.py",
                    "backend/tests/test_w1a_vs3_api.py", "backend/tests/test_w1a_vs3_postgres.py",
                    "backend/tests/test_w1a_vs3_openapi_contract.py",
                    "backend/tests/test_w1a_vs3_absence_contract.py"
                )
                Write-Output ("W1A_VS3_QUALITY_CODES=format:{0} ruff:{1} compile:{2}" -f $format.ExitCode, $ruff.ExitCode, $compile.ExitCode)
                if ($format.ExitCode -ne 0 -or $ruff.ExitCode -ne 0 -or $compile.ExitCode -ne 0) {
                    $HarnessFailure = $true
                    Write-Output "W1A_VS3_HARNESS_FAILURE: quality gate"
                }

                Write-Output "W1A_VS3_STAGE=migration"
                $upgrade = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @(
                    "-m", "alembic", "upgrade", "head"
                )
                Write-Output ("W1A_VS3_MIGRATION_UPGRADE_CODE=" + $upgrade.ExitCode)
                if (-not (Test-Path -LiteralPath $Vs3MigrationPath -PathType Leaf)) {
                    Add-ProductMarker "W1A_VS3_MIGRATION_MISSING"
                }
                elseif ($upgrade.ExitCode -ne 0) {
                    $HarnessFailure = $true
                    Write-Output "W1A_VS3_HARNESS_FAILURE: migration command"
                }

                if (Test-Path -LiteralPath $Vs3MigrationPath -PathType Leaf) {
                    Write-Output "W1A_VS3_STAGE=0005_lifecycle"
                    $down = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @(
                        "-m", "alembic", "downgrade", "20260727_0004_w1a_staff_qualifications"
                    )
                    $up = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @(
                        "-m", "alembic", "upgrade", $Vs3Revision
                    )
                    Write-Output ("W1A_VS3_LIFECYCLE_CODES=down:{0} up:{1}" -f $down.ExitCode, $up.ExitCode)
                    if ($down.ExitCode -ne 0 -or $up.ExitCode -ne 0) {
                        $HarnessFailure = $true
                        Write-Output "W1A_VS3_HARNESS_FAILURE: migration lifecycle"
                    }
                }
                else {
                    Write-Output "W1A_VS3_LIFECYCLE_CODES=skipped_missing_0005"
                }

                Write-Output "W1A_VS3_STAGE=offline"
                if (Test-Path -LiteralPath $Vs3MigrationPath -PathType Leaf) {
                    $offline = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @(
                        "-m", "alembic", "upgrade", $Vs3Revision, "--sql"
                    )
                    Write-Output ("W1A_VS3_OFFLINE_CODE=" + $offline.ExitCode)
                    if ($offline.ExitCode -ne 0) {
                        $HarnessFailure = $true
                        Write-Output "W1A_VS3_HARNESS_FAILURE: offline SQL"
                    }
                }
                else {
                    Add-ProductMarker "W1A_VS3_OFFLINE_MISSING"
                }

                Write-Output "W1A_VS3_STAGE=pytest_collect"
                $testFiles = @(
                    "tests/test_w1a_vs3_semantics.py",
                    "tests/test_w1a_vs3_api.py",
                    "tests/test_w1a_vs3_postgres.py",
                    "tests/test_w1a_vs3_openapi_contract.py",
                    "tests/test_w1a_vs3_absence_contract.py"
                )
                $collectArguments = @("-m", "pytest", "--collect-only", "-q") + $testFiles
                $CollectOutput = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments $collectArguments
                $collectLines = $CollectOutput.Output
                $collectMatch = $collectLines -join "`n" | Select-String -Pattern "(\d+) tests? collected"
                if ($null -ne $collectMatch) { Write-Output ("W1A_VS3_COLLECTED_TESTS=" + $collectMatch.Matches[0].Groups[1].Value) }
                if ($CollectOutput.ExitCode -ne 0) {
                    $HarnessFailure = $true
                    Write-Output "W1A_VS3_HARNESS_FAILURE: test collection"
                }

                Write-Output "W1A_VS3_STAGE=pytest_run"
                $pytestArguments = @("-m", "pytest", "-q") + $testFiles
                $PytestOutput = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments $pytestArguments
                $allOutput = @($CollectOutput.Output + $PytestOutput.Output)
                $namedMarkers = Get-NamedMarkers -Lines $allOutput
                $summaryText = $PytestOutput.Output -join "`n"
                $passed = 0; $failed = 0; $skipped = 0; $errors = 0
                foreach ($summaryMatch in [regex]::Matches($summaryText, "(?i)(\d+)\s+(passed|failed|skipped|errors?)")) {
                    $summaryCount = [int]$summaryMatch.Groups[1].Value
                    switch ($summaryMatch.Groups[2].Value.ToLowerInvariant()) {
                        "passed" { $passed += $summaryCount }
                        "failed" { $failed += $summaryCount }
                        "skipped" { $skipped += $summaryCount }
                        "error" { $errors += $summaryCount }
                        "errors" { $errors += $summaryCount }
                    }
                }
                Write-Output ("W1A_VS3_TEST_COUNTS=passed:{0} failed:{1} skipped:{2} errors:{3}" -f $passed, $failed, $skipped, $errors)
                if ($PytestOutput.Output -match "Traceback|INTERNALERROR|W1A_VS3_HARNESS_FAILURE") {
                    $HarnessFailure = $true
                }
                foreach ($marker in $namedMarkers) { Add-ProductMarker $marker }

                $postcheckSource = if (Test-Path -LiteralPath $PostcheckPath) { Get-Content -LiteralPath $PostcheckPath -Raw -Encoding UTF8 } else { "" }
                $restoreSource = if (Test-Path -LiteralPath $RestorePath) { Get-Content -LiteralPath $RestorePath -Raw -Encoding UTF8 } else { "" }
                if (-not $postcheckSource.Contains("W1A_VS3_DB_POSTCHECK_OK") -or -not $restoreSource.Contains($Vs3Revision)) {
                    Add-ProductMarker "W1A_VS3_RESTORE_MISSING"
                }
            }
        }
    }
}
catch {
    $HarnessFailure = $true
    Write-Output "W1A_VS3_HARNESS_FAILURE: unhandled harness condition"
}
finally {
    if ($ServerStarted) {
        $stop = Invoke-Captured -FilePath $PgCtlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-D", $DataRoot, "stop", "-m", "fast", "-w"
        )
        Write-Output ("W1A_VS3_PG_STOP_CODE=" + $stop.ExitCode)
        if ($stop.ExitCode -ne 0) { $HarnessFailure = $true }
    }
    if ([System.IO.Directory]::Exists($TempRoot)) {
        try { [System.IO.Directory]::Delete($TempRoot, $true) }
        catch { $HarnessFailure = $true; Write-Output "W1A_VS3_HARNESS_FAILURE: cleanup" }
    }
}

$remainingClusters = @(Get-ChildItem -LiteralPath ([System.IO.Path]::GetTempPath()) -Directory -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "sswcenter-w1a-vs3-pg-*" }).Count
Write-Output ("W1A_VS3_TEMP_CLUSTER_REMAINING=" + $remainingClusters)
if ($HarnessFailure -or $remainingClusters -ne 0) {
    exit 2
}
if ($ProductMarkers.Count -eq 0) {
    Write-Output "W1A_VS3_RED_NOT_REPRODUCED"
    exit 2
}
$firstMarker = $ProductMarkers | Select-Object -First 1
Write-Output ("W1A_VS3_FIRST_MARKER=" + $firstMarker)
Write-Output ("W1A_VS3_RED_MARKERS=" + ($ProductMarkers -join ","))
Write-Output "W1A_VS3_RED_VALID"
exit 1
