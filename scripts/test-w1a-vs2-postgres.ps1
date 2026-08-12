param(
    [int]$Port = 55434,
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
$required = @($PythonExe, $InitDbExe, $PgCtlExe, $CreateDbExe, $PsqlExe)
$missing = @($required | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
if ($missing.Count -gt 0) {
    Write-Output "W1A_VS2_PG_PREREQ_MISSING: runtime executable"
    exit 2
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($null -ne $listener) {
    Write-Output "W1A_VS2_PG_PREREQ_MISSING: isolated port is occupied"
    exit 2
}

$tag = [Guid]::NewGuid().ToString("N")
$TempRoot = [System.IO.Path]::GetFullPath(
    (Join-Path ([System.IO.Path]::GetTempPath()) ("sswcenter-w1a-vs2-pg-" + $tag))
)
$DataRoot = Join-Path $TempRoot "data"
$LogFile = Join-Path $TempRoot "postgres.log"
$DatabaseName = "w1a_vs2_review"
$OwnerPassword = "w1a_vs2_owner_only"
$AppPassword = "w1a_vs2_app_only"
$BackupPassword = "w1a_vs2_backup_only"
$serverStarted = $false
$finalCode = 2
$pythonOutput = @()
$collectOutput = @()
$contractRedValid = $false
$greenValid = $false
$phaseRejected = $false
$Vs2MigrationPath = Join-Path $BackendRoot "alembic\versions\20260727_0004_w1a_staff_qualifications.py"

function Invoke-Captured {
    param(
        [Parameter(Mandatory = $true)] [string]$FilePath,
    [Parameter(Mandatory = $true)] [string[]]$Arguments,
    [Parameter(Mandatory = $true)] [string]$WorkingDirectory
    )

    $process = New-Object System.Diagnostics.Process
    $processStartInfo = New-Object System.Diagnostics.ProcessStartInfo
    try {
        $argumentString = ($Arguments | ForEach-Object {
                $escaped = ([string]$_).Replace('"', '\"')
                '"' + $escaped + '"'
            }) -join " "
        $processStartInfo.FileName = $FilePath
        $processStartInfo.Arguments = $argumentString
        $processStartInfo.WorkingDirectory = $WorkingDirectory
        $processStartInfo.UseShellExecute = $false
        $processStartInfo.CreateNoWindow = $true
        $processStartInfo.RedirectStandardOutput = $true
        $processStartInfo.RedirectStandardError = $true
        $process.StartInfo = $processStartInfo
        if (-not $process.Start()) {
            return [PSCustomObject]@{
                ExitCode = 125
                Output = @("W1A_VS2_HARNESS_FAILURE: command launch failed")
                Stdout = @()
                Stderr = @()
                TimedOut = $false
            }
        }
        $isPgCtl = [System.IO.Path]::GetFileName($FilePath) -ieq "pg_ctl.exe"
        if (-not $isPgCtl) {
            $stdoutTask = $process.StandardOutput.ReadToEndAsync()
            $stderrTask = $process.StandardError.ReadToEndAsync()
        }
        if (-not $process.WaitForExit($CommandTimeoutSeconds * 1000)) {
            $process.Kill()
            $process.WaitForExit()
            return [PSCustomObject]@{
                ExitCode = 124
                Output = @("W1A_VS2_HARNESS_FAILURE: command timeout")
                Stdout = @()
                Stderr = @()
                TimedOut = $true
            }
        }
        $process.WaitForExit()
        $stdoutLines = @()
        $stderrLines = @()
        if (-not $isPgCtl) {
            if (-not [string]::IsNullOrEmpty($stdoutTask.Result)) {
                $stdoutLines = @($stdoutTask.Result -split "`r?`n")
            }
            if (-not [string]::IsNullOrEmpty($stderrTask.Result)) {
                $stderrLines = @($stderrTask.Result -split "`r?`n")
            }
        }
        return [PSCustomObject]@{
            ExitCode = [int]$process.ExitCode
            Output = @($stdoutLines + $stderrLines)
            Stdout = $stdoutLines
            Stderr = $stderrLines
            TimedOut = $false
        }
    }
    catch {
        return [PSCustomObject]@{
            ExitCode = 125
            Output = @("W1A_VS2_HARNESS_FAILURE: command launch failed")
            Stdout = @()
            Stderr = @()
            TimedOut = $false
        }
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

    $sqlFile = Join-Path $TempRoot ("w1a-vs2-sql-" + [Guid]::NewGuid().ToString("N") + ".sql")
    [System.IO.File]::WriteAllText($sqlFile, $Sql, [System.Text.UTF8Encoding]::new($false))
    try {
        return Invoke-Captured `
            -FilePath $PsqlExe `
            -WorkingDirectory $WorkspaceRoot `
            -Arguments @(
                "-h", "127.0.0.1", "-p", [string]$Port, "-U", $User, "-d", $Database,
                "-v", "ON_ERROR_STOP=1", "-f", $sqlFile
            )
    }
    finally {
        if (Test-Path -LiteralPath $sqlFile) {
            [System.IO.File]::Delete($sqlFile)
        }
    }
}

try {
    [System.IO.Directory]::CreateDirectory($TempRoot) | Out-Null
    Write-Output "W1A_VS2_STAGE=initdb"
    $init = Invoke-Captured -FilePath $InitDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
        "-D", $DataRoot, "-U", "postgres", "--auth=trust", "--no-locale", "--encoding=UTF8"
    )
    if ($init.ExitCode -ne 0) {
        Write-Output "W1A_VS2_HARNESS_FAILURE: initdb"
        $finalCode = 2
    }
    else {
        Write-Output "W1A_VS2_STAGE=pg_start"
        $start = Invoke-Captured -FilePath $PgCtlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-D", $DataRoot, "-l", $LogFile, "-o", "-p $Port -h 127.0.0.1", "start", "-w"
        )
        if ($start.ExitCode -ne 0) {
            Write-Output "W1A_VS2_HARNESS_FAILURE: pg_ctl start"
            $finalCode = 2
        }
        else {
            $serverStarted = $true
            Write-Output "W1A_VS2_STAGE=database_bootstrap"
            $bootstrapSql = @"
CREATE ROLE erp_owner LOGIN PASSWORD '$OwnerPassword';
CREATE ROLE erp_app LOGIN PASSWORD '$AppPassword';
CREATE ROLE erp_backup LOGIN PASSWORD '$BackupPassword';
"@
            $roles = Invoke-Psql -Database "postgres" -Sql $bootstrapSql
            $database = Invoke-Captured -FilePath $CreateDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-O", "erp_owner", $DatabaseName
            )
            Write-Output ("W1A_VS2_BOOTSTRAP_CODES=roles:$($roles.ExitCode) database:$($database.ExitCode)")
            if ($roles.ExitCode -ne 0 -or $database.ExitCode -ne 0) {
                Write-Output "W1A_VS2_HARNESS_FAILURE: isolated database bootstrap"
                $finalCode = 2
            }
            else {
                $env:SSWCENTER_ENVIRONMENT = "test"
                $env:SSWCENTER_POSTGRES_TEST = "1"
                $env:SSWCENTER_DATA_ROOT = Join-Path $TempRoot "sswcenter-runtime"
                $env:SSWCENTER_DATABASE_URL =
                    "postgresql+psycopg://erp_owner:$OwnerPassword@127.0.0.1:$Port/$DatabaseName"
                $env:SSWCENTER_APP_DATABASE_URL =
                    "postgresql+psycopg://erp_app:$AppPassword@127.0.0.1:$Port/$DatabaseName"
                $env:SSWCENTER_BACKUP_DATABASE_URL =
                    "postgresql+psycopg://erp_backup:$BackupPassword@127.0.0.1:$Port/$DatabaseName"
                [System.IO.Directory]::CreateDirectory($env:SSWCENTER_DATA_ROOT) | Out-Null

                Write-Output "W1A_VS2_STAGE=python_quality_gate"
                $formatCheck = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                    "-m", "ruff", "format", "--check", "backend"
                )
                $ruffCheck = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                    "-m", "ruff", "check", "backend"
                )
                $compileCheck = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                    "-m", "compileall", "-q", "backend"
                )
                $qualityFailure = (
                    $formatCheck.ExitCode -ne 0 -or
                    $ruffCheck.ExitCode -ne 0 -or
                    $compileCheck.ExitCode -ne 0
                )
                Write-Output ("W1A_VS2_QUALITY_CODES=format:$($formatCheck.ExitCode) ruff:$($ruffCheck.ExitCode) compile:$($compileCheck.ExitCode)")
                if ($qualityFailure) {
                    Write-Output "W1A_VS2_HARNESS_FAILURE: Python quality gate"
                    $phaseRejected = $true
                    $finalCode = 2
                }

                Write-Output "W1A_VS2_STAGE=fresh_base_to_head"
                $migration = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @(
                    "-m", "alembic", "upgrade", "head"
                )
                Write-Output ("W1A_VS2_MIGRATION_CODE=" + $migration.ExitCode)
                if ($migration.ExitCode -ne 0) {
                    Write-Output "W1A_VS2_HARNESS_FAILURE: migration command"
                    $finalCode = 2
                }
                else {
                    $lifecycleFailure = $false
                    if (Test-Path -LiteralPath $Vs2MigrationPath -PathType Leaf) {
                        Write-Output "W1A_VS2_STAGE=0004_to_0003"
                        $down = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @(
                            "-m", "alembic", "downgrade", "20260726_0003_w1a_staff"
                        )
                        if ($down.ExitCode -ne 0) {
                            $lifecycleFailure = $true
                        }
                        Write-Output "W1A_VS2_STAGE=0003_to_0004"
                        $up = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @(
                            "-m", "alembic", "upgrade", "20260727_0004_w1a_staff_qualifications"
                        )
                        if ($up.ExitCode -ne 0) {
                            $lifecycleFailure = $true
                        }
                        Write-Output "W1A_VS2_STAGE=0004_to_0003_to_0004"
                        $downAgain = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @(
                            "-m", "alembic", "downgrade", "20260726_0003_w1a_staff"
                        )
                        $upAgain = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @(
                            "-m", "alembic", "upgrade", "20260727_0004_w1a_staff_qualifications"
                        )
                        if ($downAgain.ExitCode -ne 0 -or $upAgain.ExitCode -ne 0) {
                            $lifecycleFailure = $true
                        }
                        Write-Output ("W1A_VS2_LIFECYCLE_CODES=down:$($down.ExitCode) up:$($up.ExitCode) down_again:$($downAgain.ExitCode) up_again:$($upAgain.ExitCode)")
                    }
                    else {
                        Write-Output "W1A_VS2_STAGE=0004_missing_named_red"
                    }

                    Write-Output "W1A_VS2_STAGE=offline_sql_generate"
                    $offlineSqlFile = Join-Path $TempRoot "offline-upgrade.sql"
                    $offline = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments @(
                        "-m", "alembic", "upgrade", "head", "--sql"
                    )
                    Write-Output ("W1A_VS2_OFFLINE_GENERATE_CODE=" + $offline.ExitCode)
                    if ($offline.ExitCode -ne 0) {
                        $lifecycleFailure = $true
                    }
                    else {
                        $offlineLines = @($offline.Stdout | ForEach-Object { [string]$_ })
                        [System.IO.File]::WriteAllLines($offlineSqlFile, [string[]]$offlineLines)
                        $offlineDatabaseName = "w1a_vs2_offline"
                        Write-Output "W1A_VS2_STAGE=offline_sql_empty_db_apply"
                        $offlineDatabase = Invoke-Captured -FilePath $CreateDbExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                            "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-O", "erp_owner", $offlineDatabaseName
                        )
                        $offlineApply = Invoke-Captured -FilePath $PsqlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
                            "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-d", $offlineDatabaseName,
                            "-v", "ON_ERROR_STOP=1", "-f", $offlineSqlFile
                        )
                        Write-Output ("W1A_VS2_OFFLINE_APPLY_CODES=database:$($offlineDatabase.ExitCode) apply:$($offlineApply.ExitCode)")
                        if ($offlineDatabase.ExitCode -ne 0 -or $offlineApply.ExitCode -ne 0) {
                            $lifecycleFailure = $true
                        }
                    }

                    if ($lifecycleFailure) {
                        Write-Output "W1A_VS2_HARNESS_FAILURE: migration lifecycle or offline SQL"
                        $finalCode = 2
                    }
                    else {
                        $pytestArgs = @(
                            "-m", "pytest", "-q",
                            "tests/test_w1a_vs2_semantics.py",
                            "tests/test_w1a_vs2_openapi_contract.py",
                            "tests/test_w1a_vs2_api.py",
                            "tests/test_w1a_vs2_postgres.py"
                        )
                        Write-Output "W1A_VS2_STAGE=pytest_collect"
                        $collectArgs = @("-m", "pytest", "--collect-only", "-q") + $pytestArgs[3..($pytestArgs.Count - 1)]
                        $collect = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments $collectArgs
                        Write-Output ("W1A_VS2_COLLECT_CODE=" + $collect.ExitCode)
                        $collectOutput = @($collect.Output | ForEach-Object { [string]$_ })
                        $collectText = [string]::Join("`n", $collectOutput)
                        $collectTestLines = @($collectOutput | Where-Object { $_ -match "tests[\\/].*::test_" })
                        $collectedCount = 0
                        $collectionMatch = [regex]::Match($collectText, "(?m)(\d+)\s+tests?\s+collected\b")
                        if ($collectionMatch.Success) {
                            $collectedCount = [int]$collectionMatch.Groups[1].Value
                        }
                        elseif ($collectTestLines.Count -gt 0) {
                            $collectedCount = $collectTestLines.Count
                        }
                    Write-Output ("W1A_VS2_COLLECTED_TESTS=" + $collectedCount)
                    $collectionFailure = $collect.ExitCode -ne 0 -or $collectedCount -le 0
                    foreach ($pattern in @(
                            "(?i)ERROR collecting",
                            "(?i)SyntaxError",
                            "(?i)Traceback \(most recent call last\)",
                            "(?i)ImportError",
                            "(?i)ModuleNotFoundError",
                            "(?i)INTERNALERROR",
                            "(?i)error during collection"
                        )) {
                        if ($collectText -match $pattern) {
                            $collectionFailure = $true
                        }
                    }
                    if ($collectionFailure) {
                        $phaseRejected = $true
                        $finalCode = 2
                    }
                    else {
                        Write-Output "W1A_VS2_STAGE=pytest_run"
                        $pytest = Invoke-Captured -FilePath $PythonExe -WorkingDirectory $BackendRoot -Arguments $pytestArgs
                        $pythonOutput = @($pytest.Output | ForEach-Object { [string]$_ })
                        $pytestText = [string]::Join("`n", $pythonOutput)
                        $passed = 0
                        $failed = 0
                        $skipped = 0
                        $errors = 0
                        $summaryLines = @(
                            $pythonOutput | Where-Object { $_ -match "(?i)\bin\s+\d+(?:\.\d+)?s\s*$" }
                        )
                        $summaryText = [string]($summaryLines | Select-Object -Last 1)
                        $countMatch = [regex]::Match($summaryText, "(?m)(\d+)\s+passed\b")
                        if ($countMatch.Success) { $passed = [int]$countMatch.Groups[1].Value }
                        $countMatch = [regex]::Match($summaryText, "(?m)(\d+)\s+failed\b")
                        if ($countMatch.Success) { $failed = [int]$countMatch.Groups[1].Value }
                        $countMatch = [regex]::Match($summaryText, "(?m)(\d+)\s+skipped\b")
                        if ($countMatch.Success) { $skipped = [int]$countMatch.Groups[1].Value }
                        $countMatch = [regex]::Match($summaryText, "(?m)(\d+)\s+errors?\b")
                        if ($countMatch.Success) { $errors = [int]$countMatch.Groups[1].Value }
                        Write-Output ("W1A_VS2_TEST_COUNTS=passed:$passed failed:$failed skipped:$skipped errors:$errors")

                        $hardFailure = $summaryLines.Count -eq 0
                        foreach ($pattern in @(
                                "(?i)ERROR collecting",
                                "(?i)SyntaxError",
                                "(?i)Traceback \(most recent call last\)",
                                "(?i)ImportError",
                                "(?i)ModuleNotFoundError",
                                "(?i)INTERNALERROR",
                                "(?i)error during collection"
                            )) {
                            if ($pytestText -match $pattern) {
                                $hardFailure = $true
                            }
                        }
                        if ($errors -gt 0) {
                            $hardFailure = $true
                        }
                        $markerMatches = [regex]::Matches(
                            $pytestText,
                            "W1A_VS2_(?:SEMANTICS|OPENAPI|API|POSTGRES)_MISSING:\s*[^\r\n]*"
                        )
                        $firstMarkerCode = ""
                        if ($markerMatches.Count -gt 0) {
                            $firstMarkerCode = [regex]::Match(
                                $markerMatches[0].Value,
                                "W1A_VS2_(?:SEMANTICS|OPENAPI|API|POSTGRES)_MISSING"
                            ).Value
                        }
                        if ($firstMarkerCode.Length -gt 0) {
                            Write-Output ("W1A_VS2_FIRST_NAMED_MARKER=" + $firstMarkerCode)
                        }
                        $greenValid = (
                            $collect.ExitCode -eq 0 -and
                            $collectedCount -gt 0 -and
                            $pytest.ExitCode -eq 0 -and
                            $passed -eq $collectedCount -and
                            $failed -eq 0 -and
                            $errors -eq 0 -and
                            -not $hardFailure
                        )
                        if ($greenValid) {
                            $finalCode = 0
                        }
                        elseif ($pytest.ExitCode -eq 1 -and $firstMarkerCode.Length -gt 0 -and -not $hardFailure) {
                            $contractRedValid = $true
                            $finalCode = 1
                        }
                        else {
                            $phaseRejected = $true
                            $finalCode = 2
                        }
                    }
                }
            }
        }
    }
}
}
finally {
    if ($serverStarted) {
        Write-Output "W1A_VS2_STAGE=pg_stop"
        $stop = Invoke-Captured -FilePath $PgCtlExe -WorkingDirectory $WorkspaceRoot -Arguments @(
            "-D", $DataRoot, "-m", "fast", "stop", "-w"
        )
        if ($stop.ExitCode -ne 0) {
            Write-Output "W1A_VS2_HARNESS_FAILURE: pg_ctl stop"
            $contractRedValid = $false
            $greenValid = $false
            $phaseRejected = $true
            $finalCode = 2
        }
    }
    Write-Output "W1A_VS2_STAGE=cleanup"
    if (Test-Path -LiteralPath $TempRoot) {
        try {
            [System.IO.Directory]::Delete($TempRoot, $true)
        }
        catch {
            Write-Output "W1A_VS2_HARNESS_FAILURE: isolated temp cleanup"
            $contractRedValid = $false
            $greenValid = $false
            $phaseRejected = $true
            $finalCode = 2
        }
    }
    if ($greenValid -and -not $phaseRejected) {
        Write-Output "W1A_VS2_POSTGRES_GREEN"
    }
    elseif ($contractRedValid -and -not $phaseRejected) {
        Write-Output "W1A_VS2_RED_CONTRACT_VALID"
    }
    else {
        Write-Output "W1A_VS2_RED_PHASE_REJECTED"
    }
}

exit $finalCode
