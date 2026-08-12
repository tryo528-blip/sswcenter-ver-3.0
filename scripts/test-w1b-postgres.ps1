param(
    [int]$Port = 55440,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 4173,
    [int]$CommandTimeoutSeconds = 600,
    [string]$RecoveryTempRoot = ""
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
$PgIsReadyExe = Join-Path $PostgresBin "pg_isready.exe"
$CreateDbExe = Join-Path $PostgresBin "createdb.exe"
$PsqlExe = Join-Path $PostgresBin "psql.exe"
$PowerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
$NpmExeCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
$NpmExe = if ($NpmExeCommand) { $NpmExeCommand.Source } else { $null }
$PostcheckPath = Join-Path $BackendRoot "app\db\postcheck_w1a_vs1.py"
$LeakGatePath = Join-Path $WorkspaceRoot "scripts\verify-w1a-vs1-leak-gate.ps1"
$SpecPath = Join-Path $FrontendRoot "e2e\w1b-recipients-real-pg.spec.ts"
$PlaywrightConfigPath = Join-Path $FrontendRoot "playwright.config.ts"
$ExpectedRevision = "20260730_0009_w1b_recipient"
$CurrentHead = "20260808_0017_recipient_guardian_email"

function Resolve-W1BTempParent {
    param(
        [AllowNull()][string]$Override,
        [AllowNull()][string]$LocalAppData
    )

    $candidate = if (-not [string]::IsNullOrWhiteSpace($Override)) {
        $Override
    }
    else {
        if ([string]::IsNullOrWhiteSpace($LocalAppData)) {
            throw "W1B_HARNESS_FAILURE: LOCALAPPDATA is unavailable"
        }
        Join-Path $LocalAppData "Temp"
    }
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        throw "W1B_HARNESS_FAILURE: temp parent must be absolute"
    }
    try {
        $resolved = [System.IO.Path]::GetFullPath($candidate).TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
    }
    catch {
        throw "W1B_HARNESS_FAILURE: temp parent path is invalid"
    }
    if ([string]::IsNullOrWhiteSpace($resolved) -or -not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "W1B_HARNESS_FAILURE: temp parent is not an accessible directory"
    }
    try {
        Get-ChildItem -LiteralPath $resolved -Force -ErrorAction Stop | Out-Null
    }
    catch {
        throw "W1B_HARNESS_FAILURE: temp parent cannot be enumerated"
    }

    $cursor = $resolved
    while ($true) {
        $item = Get-Item -LiteralPath $cursor -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "W1B_HARNESS_FAILURE: temp parent contains a reparse point"
        }
        $root = [System.IO.Path]::GetPathRoot($cursor)
        if ([string]::IsNullOrWhiteSpace($root)) {
            throw "W1B_HARNESS_FAILURE: temp parent root resolution failed"
        }
        if ($cursor.TrimEnd(
                [System.IO.Path]::DirectorySeparatorChar,
                [System.IO.Path]::AltDirectorySeparatorChar
            ) -ieq $root.TrimEnd(
                [System.IO.Path]::DirectorySeparatorChar,
                [System.IO.Path]::AltDirectorySeparatorChar
            )) {
            break
        }
        $next = Split-Path -Parent $cursor
        if ([string]::IsNullOrWhiteSpace($next) -or $next -eq $cursor) {
            throw "W1B_HARNESS_FAILURE: temp parent boundary resolution failed"
        }
        $cursor = $next
    }
    return $resolved
}

$TempParentResolutionFailure = $null
try {
    $TempParent = Resolve-W1BTempParent `
        -Override ([Environment]::GetEnvironmentVariable("SSWCENTER_W1B_TEMP_ROOT", "Process")) `
        -LocalAppData ([Environment]::GetEnvironmentVariable("LOCALAPPDATA", "Process"))
}
catch {
    $TempParentResolutionFailure = $_.Exception.Message
    $TempParent = $WorkspaceRoot
}
$TempRoot = Join-Path $TempParent ("sswcenter-w1b-pg-" + [Guid]::NewGuid().ToString("N"))
$ArtifactRoot = Join-Path $TempRoot "artifacts"
$RuntimeRoot = Join-Path $ArtifactRoot "sswcenter-w1b-runtime"
$DataRoot = Join-Path $TempRoot "data"
$LogFile = Join-Path $ArtifactRoot "postgres.log"
$DatabaseName = "w1b_recipients_review"
$PgStarted = $false
$BackendProcess = $null
$BackendStdoutTask = $null
$BackendStderrTask = $null
$PortCleanupAuthorized = $false
$PgStartAttempted = $false
$E2EStarted = $false
$E2EExitCode = 125
$E2EOutput = @()
$E2EPassed = 0
$E2EFailed = 0
$E2ESkipped = 0
$E2EErrors = 0
$ProductMarkers = [System.Collections.Generic.List[string]]::new()
$HarnessFailure = $false
$PostcheckBefore = $false
$PostcheckAfter = $false
$LeakAttempted = $false
$LeakSuccessful = $false
$LeakScannedFiles = 0
$ArtifactRootCreated = $false
$PlaywrightArtifactsCopied = $false
$FrontendArtifactCleanupReady = $false
$PreexistingFrontendArtifactFiles = 0
$RecoveryTempRemoved = $false
$SyntheticPin = if ([string]::IsNullOrWhiteSpace($env:SSWCENTER_W1B_SYNTHETIC_PIN)) {
    "123456"
}
else {
    [string]$env:SSWCENTER_W1B_SYNTHETIC_PIN
}
$OwnerPassword = "w1b-owner-" + [Guid]::NewGuid().ToString("N")
$AppPassword = "w1b-app-" + [Guid]::NewGuid().ToString("N")
$BackupPassword = "w1b-backup-" + [Guid]::NewGuid().ToString("N")
$PinPepper = "w1b-pin-pepper-" + [Guid]::NewGuid().ToString("N")
$PinLookupKey = "w1b-pin-lookup-" + [Guid]::NewGuid().ToString("N")
$CsrfSigningKey = "w1b-csrf-" + [Guid]::NewGuid().ToString("N")
$OwnerDatabaseUrl = "postgresql+psycopg://erp_owner:$OwnerPassword@127.0.0.1:$Port/$DatabaseName"
$AppDatabaseUrl = "postgresql+psycopg://erp_app:$AppPassword@127.0.0.1:$Port/$DatabaseName"
$BackupDatabaseUrl = "postgresql+psycopg://erp_backup:$BackupPassword@127.0.0.1:$Port/$DatabaseName"
$EnvironmentNames = @(
    "SSWCENTER_ENVIRONMENT",
    "SSWCENTER_POSTGRES_TEST",
    "SSWCENTER_DATABASE_URL",
    "SSWCENTER_APP_DATABASE_URL",
    "SSWCENTER_BACKUP_DATABASE_URL",
    "SSWCENTER_DATA_ROOT",
    "SSWCENTER_PIN_PEPPER",
    "SSWCENTER_PIN_LOOKUP_KEY",
    "SSWCENTER_CSRF_SIGNING_KEY",
    "SSWCENTER_RESIDENT_NUMBER_KEY_V1",
    "SSWCENTER_RESIDENT_NUMBER_LOOKUP_KEY",
    "SSWCENTER_RESIDENT_NUMBER_ACTIVE_KEY_VERSION",
    "SSWCENTER_W1B_REAL_PG",
    "SSWCENTER_W1B_SYNTHETIC_PIN",
    "TEMP",
    "TMP",
    "PYTHONDONTWRITEBYTECODE",
    "PLAYWRIGHT_NO_COPY_PROMPT"
)
$OriginalEnvironment = @{}
foreach ($name in $EnvironmentNames) {
    $value = [Environment]::GetEnvironmentVariable($name, "Process")
    $OriginalEnvironment[$name] = [pscustomobject]@{
        present = $null -ne $value
        value = $value
    }
}

function Redact-Text {
    param([AllowNull()][string]$Text)

    if ($null -eq $Text) { return "" }
    $safe = $Text
    foreach ($secret in @(
            $OwnerPassword,
            $AppPassword,
            $BackupPassword,
            $PinPepper,
            $PinLookupKey,
            $CsrfSigningKey,
            $SyntheticPin,
            $OwnerDatabaseUrl,
            $AppDatabaseUrl,
            $BackupDatabaseUrl
        )) {
        if (-not [string]::IsNullOrWhiteSpace($secret)) {
            $safe = $safe.Replace([string]$secret, "<REDACTED>")
        }
    }
    return [regex]::Replace(
        $safe,
        "(?i)postgresql(?:\+psycopg)?://[^\s]+",
        "<REDACTED_DSN>"
    )
}

function Get-LeakGateMarkers {
    param([Parameter(Mandatory = $true)][string]$ChildOutput)

    $knownMarkers = @(
        "LEAK_GATE_FAILURE",
        "LEAK_GATE_GIT_DISCOVERY_FAILURE",
        "LEAK_GATE_GIT_PATH_FAILURE",
        "LEAK_GATE_PATH_FAILURE",
        "LEAK_GATE_READ_FAILURE",
        "LEAK_GATE_SELF_TEST_FAILURE",
        "W1A_LEAK_GATE_GREEN",
        "W1A_LEAK_GATE_SCANNED_FILES",
        "W1A_LEAK_GATE_SELF_TEST_OK"
    )
    return @($knownMarkers | Where-Object { $ChildOutput.Contains($_) })
}

function Get-LeakGateReasonCodes {
    param(
        [Parameter(Mandatory = $true)][string]$ChildOutput,
        [Parameter(Mandatory = $true)][int]$ExitCode
    )

    $reasonMappings = @(
        [pscustomobject]@{ Code = "PATH_NORMALIZE"; Phrase = "LEAK_GATE_PATH_FAILURE: path could not be normalized" },
        [pscustomobject]@{ Code = "ARTIFACT_ROOT_INSPECT"; Phrase = "LEAK_GATE_PATH_FAILURE: artifact root could not be inspected" },
        [pscustomobject]@{ Code = "ARTIFACT_ROOT_REPARSE"; Phrase = "LEAK_GATE_PATH_FAILURE: artifact root is a reparse point" },
        [pscustomobject]@{ Code = "BOUNDARY_NORMALIZE"; Phrase = "LEAK_GATE_PATH_FAILURE: artifact boundary could not be normalized" },
        [pscustomobject]@{ Code = "REPARSE_ARTIFACT"; Phrase = "LEAK_GATE_PATH_FAILURE: reparse-point artifact could not be scanned" },
        [pscustomobject]@{ Code = "FILE_NORMALIZE"; Phrase = "LEAK_GATE_PATH_FAILURE: artifact file path could not be normalized" },
        [pscustomobject]@{ Code = "FILE_ESCAPE"; Phrase = "LEAK_GATE_PATH_FAILURE: artifact file escaped its root" },
        [pscustomobject]@{ Code = "EXPLICIT_ROOT_EMPTY"; Phrase = "LEAK_GATE_PATH_FAILURE: explicit artifact root is empty" },
        [pscustomobject]@{ Code = "EXPLICIT_ROOT_NORMALIZE"; Phrase = "LEAK_GATE_PATH_FAILURE: explicit artifact root could not be normalized" },
        [pscustomobject]@{ Code = "EXPLICIT_ROOT_MISSING"; Phrase = "LEAK_GATE_PATH_FAILURE: explicit artifact root does not exist" },
        [pscustomobject]@{ Code = "EXPLICIT_ROOT_EXCLUDED"; Phrase = "LEAK_GATE_PATH_FAILURE: explicit artifact root is excluded" },
        [pscustomobject]@{ Code = "EXPLICIT_ROOT_INSPECT"; Phrase = "LEAK_GATE_PATH_FAILURE: explicit artifact root could not be inspected" },
        [pscustomobject]@{ Code = "EXPLICIT_ROOT_REPARSE"; Phrase = "LEAK_GATE_PATH_FAILURE: explicit artifact root is a reparse point" },
        [pscustomobject]@{ Code = "DATA_ROOT_NORMALIZE"; Phrase = "LEAK_GATE_PATH_FAILURE: data root could not be normalized" },
        [pscustomobject]@{ Code = "TEMPORARY_RUNTIME_ENUMERATION"; Phrase = "LEAK_GATE_PATH_FAILURE: temporary runtime surface could not be enumerated" }
    )
    $reasonCodes = @(
        foreach ($mapping in $reasonMappings) {
            if ($ChildOutput.Contains($mapping.Phrase)) { $mapping.Code }
        }
    )
    if ($ExitCode -ne 0 -and $reasonCodes.Count -eq 0) {
        return @("UNKNOWN")
    }
    return @($reasonCodes)
}

function New-LeakGateEncodedArguments {
    param([switch]$IncludeArtifactRoot)

    $escapedLeakGatePath = ([string]$LeakGatePath).Replace("'", "''")
    $scriptText = '$utf8 = New-Object System.Text.UTF8Encoding($false); [Console]::InputEncoding=$utf8; [Console]::OutputEncoding=$utf8; $OutputEncoding=$utf8; & ' +
        [char]39 +
        $escapedLeakGatePath +
        [char]39
    if ($IncludeArtifactRoot) {
        $escapedArtifactRoot = ([string]$ArtifactRoot).Replace("'", "''")
        $scriptText += ' -ArtifactRoot ' + [char]39 + $escapedArtifactRoot + [char]39
    }
    $scriptText += '; exit $LASTEXITCODE'
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($scriptText))
    return @(
        "-NoProfile",
        "-ExecutionPolicy", "RemoteSigned",
        "-EncodedCommand", $encodedCommand
    )
}

function Restore-Environment {
    foreach ($name in $EnvironmentNames) {
        $saved = $OriginalEnvironment[$name]
        if ($saved.present) {
            [Environment]::SetEnvironmentVariable($name, [string]$saved.value, "Process")
        }
        else {
            Remove-Item -LiteralPath ("Env:" + $name) -ErrorAction SilentlyContinue
        }
    }
}

function Test-PathUnderRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $resolvedCandidate = [System.IO.Path]::GetFullPath($Candidate).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $resolvedRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    return $resolvedCandidate.StartsWith(
        $resolvedRoot + [System.IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Assert-SafePath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent,
        [Parameter(Mandatory = $true)][string]$LeafPrefix
    )

    $resolved = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-PathUnderRoot -Candidate $resolved -Root $Parent)) {
        throw "W1B_HARNESS_FAILURE: unsafe path boundary"
    }
    if (-not (Split-Path -Leaf $resolved).StartsWith($LeafPrefix, [StringComparison]::Ordinal)) {
        throw "W1B_HARNESS_FAILURE: unsafe path prefix"
    }
    $cursor = $resolved
    while ($true) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "W1B_HARNESS_FAILURE: reparse-point path"
            }
        }
        if ($cursor -eq [System.IO.Path]::GetFullPath($Parent).TrimEnd(
                [System.IO.Path]::DirectorySeparatorChar,
                [System.IO.Path]::AltDirectorySeparatorChar
            )) {
            break
        }
        $next = Split-Path -Parent $cursor
        if ([string]::IsNullOrWhiteSpace($next) -or $next -eq $cursor) {
            throw "W1B_HARNESS_FAILURE: path boundary resolution failed"
        }
        $cursor = $next
    }
}

function Remove-RecoveryTempRoot {
    if ([string]::IsNullOrWhiteSpace($RecoveryTempRoot)) { return }
    if (-not [System.IO.Path]::IsPathRooted($RecoveryTempRoot)) {
        throw "W1B_HARNESS_FAILURE: recovery temp root must be absolute"
    }
    try {
        $resolved = [System.IO.Path]::GetFullPath($RecoveryTempRoot).TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
    }
    catch {
        throw "W1B_HARNESS_FAILURE: recovery temp root path is invalid"
    }
    if ([string]::Equals($resolved, $TempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "W1B_HARNESS_FAILURE: recovery temp root equals current temp root"
    }
    if ((Split-Path -Leaf $resolved) -cnotmatch "^sswcenter-w1b-pg-[0-9a-f]{32}$") {
        throw "W1B_HARNESS_FAILURE: recovery temp root prefix is invalid"
    }
    $parent = [System.IO.Path]::GetFullPath((Split-Path -Parent $resolved)).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    if (-not [string]::Equals($parent, $TempParent, [StringComparison]::OrdinalIgnoreCase)) {
        throw "W1B_HARNESS_FAILURE: recovery temp root is not an immediate child"
    }
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "W1B_HARNESS_FAILURE: recovery temp root is missing"
    }
    $rootItem = Get-Item -LiteralPath $resolved -Force
    if (($rootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "W1B_HARNESS_FAILURE: recovery temp root is a reparse point"
    }
    try {
        $descendants = @(Get-ChildItem -LiteralPath $resolved -Recurse -Force -ErrorAction Stop)
    }
    catch {
        throw "W1B_HARNESS_FAILURE: recovery temp root cannot be enumerated"
    }
    foreach ($entry in $descendants) {
        if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "W1B_HARNESS_FAILURE: recovery temp root contains a reparse point"
        }
    }
    foreach ($port in @($Port, $BackendPort, $FrontendPort)) {
        if ((Get-ListenerCount -ListenPort $port) -ne 0) {
            throw "W1B_HARNESS_FAILURE: recovery requires clear listeners"
        }
    }
    try {
        Remove-Item -LiteralPath $resolved -Recurse -Force
        if (Test-Path -LiteralPath $resolved) {
            throw "recovery temp root remained"
        }
    }
    catch {
        throw "W1B_HARNESS_FAILURE: recovery temp root cleanup failed"
    }
    $script:RecoveryTempRemoved = $true
    Write-Output "W1B_RECOVERY_TEMP_REMOVED=1"
}

function Write-ArtifactText {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [AllowNull()][string]$Text
    )

    if (-not $ArtifactRootCreated) { return }
    $destination = [System.IO.Path]::GetFullPath((Join-Path $ArtifactRoot $RelativePath))
    if (-not (Test-PathUnderRoot -Candidate $destination -Root $ArtifactRoot)) {
        throw "W1B_HARNESS_FAILURE: artifact escaped root"
    }
    $directory = Split-Path -Parent $destination
    [System.IO.Directory]::CreateDirectory($directory) | Out-Null
    [System.IO.File]::WriteAllText(
        $destination,
        (Redact-Text $Text),
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Join-ProcessArguments {
    param([string[]]$Arguments)

    return (($Arguments | ForEach-Object {
            '"' + ([string]$_).Replace('"', '\"') + '"'
        }) -join " ")
}

function Invoke-Captured {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [hashtable]$Environment = @{}
    )

    $process = [System.Diagnostics.Process]::new()
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $isPgCtl = [System.IO.Path]::GetFileName($FilePath) -ieq "pg_ctl.exe"
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = Join-ProcessArguments -Arguments $Arguments
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = -not $isPgCtl
    $startInfo.RedirectStandardError = -not $isPgCtl
    if (-not $isPgCtl) {
        $utf8 = [System.Text.UTF8Encoding]::new($false)
        $startInfo.StandardOutputEncoding = $utf8
        $startInfo.StandardErrorEncoding = $utf8
    }
    foreach ($key in $Environment.Keys) {
        $startInfo.EnvironmentVariables[[string]$key] = [string]$Environment[$key]
    }
    $process.StartInfo = $startInfo
    try {
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
            try { $process.Kill() } catch {}
            $process.WaitForExit()
            return [pscustomobject]@{
                ExitCode = 124
                Output = @()
                Stdout = @()
                Stderr = @()
                TimedOut = $true
            }
        }
        $process.WaitForExit()
        $stdoutText = if ($null -eq $stdoutTask) { "" } else { $stdoutTask.GetAwaiter().GetResult() }
        $stderrText = if ($null -eq $stderrTask) { "" } else { $stderrTask.GetAwaiter().GetResult() }
        $stdout = if ([string]::IsNullOrEmpty($stdoutText)) { @() } else { @($stdoutText -split "`r?`n") }
        $stderr = if ([string]::IsNullOrEmpty($stderrText)) { @() } else { @($stderrText -split "`r?`n") }
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
    finally {
        $process.Dispose()
    }
}

function Write-CommandCapture {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Result
    )

    $safeName = [regex]::Replace($Name, "[^A-Za-z0-9_.-]", "_")
    Write-ArtifactText -RelativePath ("commands\" + $safeName + ".log") -Text (($Result.Output -join "`n"))
}

function Assert-CommandSuccess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Result
    )

    Write-CommandCapture -Name $Name -Result $Result
    if ($Result.TimedOut -or $Result.ExitCode -ne 0) {
        throw ("W1B_HARNESS_FAILURE: {0} command failed" -f $Name)
    }
}

function Invoke-PsqlSql {
    param(
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Sql,
        [string]$Role = "postgres"
    )

    Write-ArtifactText -RelativePath ("w1b-" + [Guid]::NewGuid().ToString("N") + ".sql") -Text $Sql
    $password = ""
    if ($Role -eq "erp_owner") { $password = $OwnerPassword }
    elseif ($Role -eq "erp_app") { $password = $AppPassword }
    elseif ($Role -eq "erp_backup") { $password = $BackupPassword }
    return Invoke-Captured `
        -FilePath $PsqlExe `
        -WorkingDirectory $WorkspaceRoot `
        -Environment @{ PGPASSWORD = $password } `
        -Arguments @(
            "-h", "127.0.0.1", "-p", [string]$Port, "-U", $Role, "-d", $Database,
            "-v", "ON_ERROR_STOP=1", "-c", $Sql
        )
}

function Invoke-ScalarPsql {
    param(
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Sql,
        [string]$Role = "postgres"
    )

    Write-ArtifactText -RelativePath ("w1b-query-" + [Guid]::NewGuid().ToString("N") + ".sql") -Text $Sql
    $password = ""
    if ($Role -eq "erp_owner") { $password = $OwnerPassword }
    elseif ($Role -eq "erp_app") { $password = $AppPassword }
    elseif ($Role -eq "erp_backup") { $password = $BackupPassword }
    return Invoke-Captured `
        -FilePath $PsqlExe `
        -WorkingDirectory $WorkspaceRoot `
        -Environment @{ PGPASSWORD = $password } `
        -Arguments @(
            "-h", "127.0.0.1", "-p", [string]$Port, "-U", $Role, "-d", $Database,
            "-v", "ON_ERROR_STOP=1", "-q", "-At", "-c", $Sql
        )
}

function Get-ListenerPids {
    param([Parameter(Mandatory = $true)][int]$ListenPort)

    return @(
        Get-NetTCPConnection -State Listen -LocalPort $ListenPort -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess |
            ForEach-Object { [int]$_ } |
            Sort-Object -Unique
    )
}

function Get-ListenerCount {
    param([Parameter(Mandatory = $true)][int]$ListenPort)

    return @(Get-ListenerPids -ListenPort $ListenPort).Count
}

function Stop-NewPortListeners {
    param(
        [Parameter(Mandatory = $true)][int]$ListenPort,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][int[]]$BaselinePids,
        [Parameter(Mandatory = $true)][string]$Label
    )

    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        $currentPids = @(Get-ListenerPids -ListenPort $ListenPort)
        foreach ($pidValue in $currentPids) {
            if ($BaselinePids -notcontains [int]$pidValue) {
                try {
                    Stop-Process -Id ([int]$pidValue) -Force -ErrorAction Stop
                }
                catch {
                    $script:HarnessFailure = $true
                    Write-Output ("W1B_HARNESS_FAILURE: {0} listener cleanup" -f $Label)
                }
            }
        }
        Start-Sleep -Milliseconds 250
        if (@(Get-ListenerPids -ListenPort $ListenPort).Count -eq 0) { break }
    }
}

function Invoke-PortCleanup {
    param(
        [Parameter(Mandatory = $true)][int]$ListenPort,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][int[]]$BaselinePids,
        [Parameter(Mandatory = $true)][string]$Label
    )

    try {
        Stop-NewPortListeners -ListenPort $ListenPort -BaselinePids $BaselinePids -Label $Label
    }
    catch {
        $script:HarnessFailure = $true
        Write-Output ("W1B_HARNESS_FAILURE: {0} listener cleanup" -f $Label)
    }
}

function Start-Backend {
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $PythonExe
    $startInfo.Arguments = Join-ProcessArguments -Arguments @(
        "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", [string]$BackendPort
    )
    $startInfo.WorkingDirectory = $BackendRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $startInfo.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
    $startInfo.EnvironmentVariables["SSWCENTER_DATABASE_URL"] = $AppDatabaseUrl
    $startInfo.EnvironmentVariables["SSWCENTER_APP_DATABASE_URL"] = $AppDatabaseUrl
    $startInfo.EnvironmentVariables["SSWCENTER_BACKUP_DATABASE_URL"] = $BackupDatabaseUrl
    $startInfo.EnvironmentVariables["SSWCENTER_W1B_REAL_PG"] = "1"
    $script:BackendProcess = [System.Diagnostics.Process]::Start($startInfo)
    if ($null -eq $script:BackendProcess) {
        throw "W1B_HARNESS_FAILURE: FastAPI process could not start"
    }
    $script:BackendStdoutTask = $script:BackendProcess.StandardOutput.ReadToEndAsync()
    $script:BackendStderrTask = $script:BackendProcess.StandardError.ReadToEndAsync()
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        if ($script:BackendProcess.HasExited) { break }
        try {
            $health = Invoke-WebRequest `
                -Uri ("http://127.0.0.1:{0}/health/ready" -f $BackendPort) `
                -UseBasicParsing `
                -TimeoutSec 2 `
                -ErrorAction SilentlyContinue
            if ($health.StatusCode -eq 200) {
                $ready = $true
                break
            }
        }
        catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
        throw "W1B_HARNESS_FAILURE: FastAPI readiness timeout"
    }
    Write-Output "W1B_BACKEND_READY=1"
}

function Stop-Backend {
    if ($null -eq $script:BackendProcess) { return }
    try {
        if (-not $script:BackendProcess.HasExited) {
            Stop-Process -Id $script:BackendProcess.Id -Force -ErrorAction Stop
            if (-not $script:BackendProcess.WaitForExit(10000)) {
                throw "backend process did not exit"
            }
        }
        if (-not $script:BackendProcess.HasExited) {
            throw "backend process remained running"
        }
    }
    catch {
        $script:HarnessFailure = $true
        Write-Output "W1B_HARNESS_FAILURE: backend stop"
    }
    try {
        $stdout = if ($null -eq $script:BackendStdoutTask) { "" } else { $script:BackendStdoutTask.GetAwaiter().GetResult() }
        $stderr = if ($null -eq $script:BackendStderrTask) { "" } else { $script:BackendStderrTask.GetAwaiter().GetResult() }
        Write-ArtifactText -RelativePath "backend\stdout.log" -Text $stdout
        Write-ArtifactText -RelativePath "backend\stderr.log" -Text $stderr
        $redactedBackendOutput = Redact-Text ($stdout + "`n" + $stderr)
        $backendHarnessPattern = "Traceback|INTERNALERROR|Exception ignored in atexit callback|PytestUnhandledThreadExceptionWarning|Exception in thread|UnhandledPromiseRejection"
        $backendHarnessMarkers = @(
            [regex]::Matches($redactedBackendOutput, $backendHarnessPattern) |
                ForEach-Object { $_.Value } |
                Sort-Object -Unique
        )
        if ($backendHarnessMarkers.Count -gt 0) {
            $backendExceptionTypes = @(
                [regex]::Matches(
                    $redactedBackendOutput,
                    "(?m)^(?:[A-Za-z_][A-Za-z0-9_]*\.)*([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Interrupt))(?=:|$)"
                ) |
                    ForEach-Object { $_.Groups[1].Value } |
                    Sort-Object -Unique
            )
            $script:HarnessFailure = $true
            Write-Output ("W1B_BACKEND_HARNESS_MARKERS=" + ($backendHarnessMarkers -join ","))
            Write-Output ("W1B_BACKEND_EXCEPTION_TYPES=" + ($backendExceptionTypes -join ","))
            Write-Output "W1B_HARNESS_FAILURE: backend output harness marker"
        }
    }
    catch {
        $script:HarnessFailure = $true
        Write-Output "W1B_HARNESS_FAILURE: backend output drain"
    }
    $script:BackendProcess.Dispose()
    $script:BackendProcess = $null
}

function Invoke-Postcheck {
    param([Parameter(Mandatory = $true)][string]$Stage)

    $previous = [Environment]::GetEnvironmentVariable("SSWCENTER_DATABASE_URL", "Process")
    [Environment]::SetEnvironmentVariable("SSWCENTER_DATABASE_URL", $OwnerDatabaseUrl, "Process")
    try {
        $result = Invoke-Captured `
            -FilePath $PythonExe `
            -WorkingDirectory $BackendRoot `
            -Environment @{ SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl } `
            -Arguments @("-m", "app.db.postcheck_w1a_vs1")
        Write-CommandCapture -Name ("postcheck-" + $Stage) -Result $result
        $text = Redact-Text ($result.Output -join "`n")
        # Before head upgrade: historical 0009 marker. After exact head: current-head marker.
        $requiredMarker = if ($Stage -eq "before") {
            "W1B_DB_POSTCHECK_OK"
        }
        else {
            "RECIPIENT_GUARDIAN_EMAIL_DB_POSTCHECK_OK"
        }
        if ($result.TimedOut -or $result.ExitCode -ne 0 -or $text -notmatch $requiredMarker) {
            throw ("W1B_HARNESS_FAILURE: {0} postcheck failed" -f $Stage)
        }
        if ($Stage -eq "before") { $script:PostcheckBefore = $true }
        else { $script:PostcheckAfter = $true }
        Write-Output ("{0}=1" -f $requiredMarker)
        Write-Output ("W1B_POSTCHECK_{0}=1" -f $Stage.ToUpperInvariant())
    }
    finally {
        if ($null -eq $previous) {
            Remove-Item Env:SSWCENTER_DATABASE_URL -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable("SSWCENTER_DATABASE_URL", $previous, "Process")
        }
    }
}

function Invoke-AppSessionSettingsProbe {
    $probeRelativePath = "sswcenter-w1b-runtime\session_settings_probe.py"
    $probePath = [System.IO.Path]::GetFullPath((Join-Path $ArtifactRoot $probeRelativePath))
    if (-not (Test-PathUnderRoot -Candidate $probePath -Root $ArtifactRoot)) {
        throw "W1B_HARNESS_FAILURE: session settings probe escaped artifact root"
    }
    $probeSource = @'
from __future__ import annotations

import os

from sqlalchemy import text

from app.db.session import create_postgres_engine


def read_settings(connection):
    return connection.execute(
        text(
            """
            SELECT
                pg_backend_pid() AS backend_pid,
                current_setting('TimeZone') AS timezone,
                current_setting('statement_timeout') AS statement_timeout,
                current_setting('lock_timeout') AS lock_timeout,
                current_setting('idle_in_transaction_session_timeout') AS idle_timeout,
                current_setting('search_path') AS search_path
            """
        )
    ).mappings().one()


def settings_are_expected(settings) -> bool:
    search_path = ",".join(part.strip() for part in str(settings["search_path"]).split(","))
    return (
        str(settings["timezone"]).strip().upper() == "UTC"
        and str(settings["statement_timeout"]).strip().lower() == "30s"
        and str(settings["lock_timeout"]).strip().lower() == "5s"
        and str(settings["idle_timeout"]).strip().lower() == "30s"
        and search_path == "erp,pg_catalog"
    )


def main() -> int:
    database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if not database_url:
        return 1
    engine = None
    try:
        engine = create_postgres_engine(database_url)
        with engine.connect() as connection:
            before = read_settings(connection)
            if not settings_are_expected(before):
                return 1
            first_backend_pid = before["backend_pid"]
            connection.execute(text("SELECT 1"))
            connection.rollback()
        with engine.connect() as connection:
            after = read_settings(connection)
            if not settings_are_expected(after):
                return 1
            if after["backend_pid"] != first_backend_pid:
                return 1
            connection.rollback()
    except Exception:
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'@
    Write-ArtifactText -RelativePath $probeRelativePath -Text $probeSource
    $result = Invoke-Captured `
        -FilePath $PythonExe `
        -WorkingDirectory $BackendRoot `
        -Environment @{
            PYTHONPATH = $BackendRoot
            SSWCENTER_DATABASE_URL = $AppDatabaseUrl
        } `
        -Arguments @("-B", $probePath)
    Write-CommandCapture -Name "app-session-settings-probe" -Result $result
    if ($result.TimedOut -or $result.ExitCode -ne 0) {
        throw "W1B_HARNESS_FAILURE: app session settings probe failed"
    }
    Write-Output "W1B_DB_SESSION_SETTINGS_BEFORE=1"
    Write-Output "W1B_DB_SESSION_SETTINGS_AFTER=1"
    Write-Output "W1B_DB_SESSION_SETTINGS_OK=1"
}

function Copy-TreeToArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$RelativeDestination
    )

    if (-not (Test-Path -LiteralPath $Source -PathType Container)) { return }
    foreach ($entry in @(Get-ChildItem -LiteralPath $Source -Recurse -Force)) {
        if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "W1B_HARNESS_FAILURE: reparse-point artifact"
        }
    }
    $destination = Join-Path $ArtifactRoot $RelativeDestination
    if (-not (Test-PathUnderRoot -Candidate $destination -Root $ArtifactRoot)) {
        throw "W1B_HARNESS_FAILURE: artifact destination escaped root"
    }
    [System.IO.Directory]::CreateDirectory($destination) | Out-Null
    Copy-Item -LiteralPath $Source -Destination $destination -Recurse -Force
    $script:PlaywrightArtifactsCopied = $true
}

function Copy-FrontendArtifacts {
    Copy-TreeToArtifacts -Source (Join-Path $FrontendRoot "test-results") -RelativeDestination "frontend-test-results"
    Copy-TreeToArtifacts -Source (Join-Path $FrontendRoot "playwright-report") -RelativeDestination "frontend-playwright-report"
}

function Copy-BackendArtifacts {
    $backendLogs = Join-Path $BackendRoot "logs"
    if (Test-Path -LiteralPath $backendLogs -PathType Container) {
        Copy-TreeToArtifacts -Source $backendLogs -RelativeDestination "backend-repo-logs"
    }
}

function Write-ArtifactManifest {
    if (-not $ArtifactRootCreated) { return }
    $entries = @(
        Get-ChildItem -LiteralPath $ArtifactRoot -File -Recurse -Force |
            ForEach-Object {
                $relative = $_.FullName.Substring(
                    ([System.IO.Path]::GetFullPath($ArtifactRoot).TrimEnd("\") + "\").Length
                ).Replace("\", "/")
                [pscustomobject]@{
                    path = $relative
                    bytes = [int64]$_.Length
                    sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                }
            }
    )
    Write-ArtifactText -RelativePath "manifest.json" -Text (
        [pscustomobject]@{
            contract = "W1B_ARTIFACT_MANIFEST"
            files = $entries
        } | ConvertTo-Json -Depth 6
    )
}

function Get-ArtifactPathValidationFailureCount {
    if (-not $ArtifactRootCreated -or -not (Test-Path -LiteralPath $ArtifactRoot -PathType Container)) {
        return 1
    }
    try {
        $resolvedRoot = [System.IO.Path]::GetFullPath($ArtifactRoot)
        $rootItem = Get-Item -LiteralPath $resolvedRoot -Force
    }
    catch {
        return 1
    }
    if (($rootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        return 1
    }
    try {
        $entries = @(Get-ChildItem -LiteralPath $resolvedRoot -Recurse -Force -ErrorAction Stop)
    }
    catch {
        return 1
    }
    $failureCount = 0
    foreach ($entry in $entries) {
        $entryFailed = $false
        try {
            $resolvedEntry = [System.IO.Path]::GetFullPath($entry.FullName)
            if (-not (Test-PathUnderRoot -Candidate $resolvedEntry -Root $resolvedRoot)) {
                $entryFailed = $true
            }
            if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                $entryFailed = $true
            }
        }
        catch {
            $entryFailed = $true
        }
        if ($entryFailed) { $failureCount++ }
    }
    return $failureCount
}

function Invoke-LeakScan {
    if ($script:LeakAttempted) { return }
    $script:LeakAttempted = $true
    if (-not $ArtifactRootCreated -or -not (Test-Path -LiteralPath $ArtifactRoot -PathType Container)) {
        $script:HarnessFailure = $true
        Write-Output "W1B_HARNESS_FAILURE: artifact root missing before leak scan"
        return
    }
    $sqlArtifacts = @(Get-ChildItem -LiteralPath $ArtifactRoot -File -Filter "w1b-*.sql" -Force)
    Write-Output ("W1B_PSQL_ARTIFACT_COUNT=" + $sqlArtifacts.Count)
    if ($sqlArtifacts.Count -eq 0) {
        $script:HarnessFailure = $true
        Write-Output "W1B_HARNESS_FAILURE: psql artifact missing"
    }
    Write-ArtifactManifest
    $artifactPathFailures = Get-ArtifactPathValidationFailureCount
    Write-Output ("W1B_ARTIFACT_PATH_VALIDATION_FAILURES=" + $artifactPathFailures)
    if ($artifactPathFailures -gt 0) {
        $script:HarnessFailure = $true
        Write-Output "W1B_HARNESS_FAILURE: artifact path validation"
        return
    }
    $savedDataRoot = [Environment]::GetEnvironmentVariable("SSWCENTER_DATA_ROOT", "Process")
    Remove-Item Env:SSWCENTER_DATA_ROOT -ErrorAction SilentlyContinue
    try {
        $explicitLeakArguments = @(New-LeakGateEncodedArguments -IncludeArtifactRoot)
        $result = Invoke-Captured `
            -FilePath $PowerShellExe `
            -WorkingDirectory $WorkspaceRoot `
            -Arguments $explicitLeakArguments
        $childOutput = $result.Output -join "`n"
        $leakMarkers = @(Get-LeakGateMarkers -ChildOutput $childOutput)
        Write-Output ("W1B_LEAK_GATE_MARKERS=" + ($leakMarkers -join ","))
        $reasonCodes = @(Get-LeakGateReasonCodes -ChildOutput $childOutput -ExitCode ([int]$result.ExitCode))
        Write-Output ("W1B_LEAK_GATE_REASON_CODES=" + ($reasonCodes -join ","))
        $text = Redact-Text $childOutput
        $scanMatch = [regex]::Match($text, "W1A_LEAK_GATE_SCANNED_FILES=(\d+)")
        if ($scanMatch.Success) { $script:LeakScannedFiles = [int]$scanMatch.Groups[1].Value }
        Write-Output ("W1B_LEAK_GATE_EXIT=" + $result.ExitCode)
        Write-Output ("W1B_LEAK_GATE_SCANNED_FILES=" + $script:LeakScannedFiles)
        $explicitPassed = $result.ExitCode -eq 0 -and $text -match "W1A_LEAK_GATE_GREEN"
        if ($explicitPassed) {
            $script:LeakSuccessful = $true
            Write-Output "W1B_LEAK_GATE_GREEN=1"
        }
        else {
            $script:HarnessFailure = $true
            Write-Output "W1B_HARNESS_FAILURE: leak gate"
            $baselineLeakArguments = @(New-LeakGateEncodedArguments)
            $baseline = Invoke-Captured `
                -FilePath $PowerShellExe `
                -WorkingDirectory $WorkspaceRoot `
                -Arguments $baselineLeakArguments
            $baselineOutput = $baseline.Output -join "`n"
            $baselineMarkers = @(Get-LeakGateMarkers -ChildOutput $baselineOutput)
            Write-Output ("W1B_LEAK_GATE_BASELINE_MARKERS=" + ($baselineMarkers -join ","))
            $baselineText = Redact-Text $baselineOutput
            $baselineScanMatch = [regex]::Match($baselineText, "W1A_LEAK_GATE_SCANNED_FILES=(\d+)")
            $baselineScannedFiles = 0
            if ($baselineScanMatch.Success) { $baselineScannedFiles = [int]$baselineScanMatch.Groups[1].Value }
            Write-Output ("W1B_LEAK_GATE_BASELINE_EXIT=" + $baseline.ExitCode)
            Write-Output ("W1B_LEAK_GATE_BASELINE_SCANNED_FILES=" + $baselineScannedFiles)
            if ($baseline.ExitCode -eq 0 -and $baselineText -match "W1A_LEAK_GATE_GREEN") {
                Write-Output "W1B_LEAK_GATE_BASELINE_GREEN=1"
            }
            elseif ($baseline.ExitCode -ne 0) {
                $baselineReasons = @(Get-LeakGateReasonCodes -ChildOutput $baselineOutput -ExitCode ([int]$baseline.ExitCode))
                Write-Output ("W1B_LEAK_GATE_BASELINE_REASON_CODES=" + ($baselineReasons -join ","))
            }
        }
    }
    finally {
        if ($null -eq $savedDataRoot) {
            Remove-Item Env:SSWCENTER_DATA_ROOT -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable("SSWCENTER_DATA_ROOT", $savedDataRoot, "Process")
        }
    }
}

function Remove-FrontendArtifacts {
    param(
        [switch]$RecordInitial,
        [switch]$CopyEvidence
    )

    if (-not (Test-Path -LiteralPath $FrontendRoot -PathType Container)) {
        throw "W1B_HARNESS_FAILURE: frontend root missing"
    }
    $frontendItem = Get-Item -LiteralPath $FrontendRoot -Force
    if (($frontendItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "W1B_HARNESS_FAILURE: frontend root is a reparse point"
    }

    $targets = [System.Collections.Generic.List[object]]::new()
    $fileCount = 0
    foreach ($leaf in @("test-results", "playwright-report")) {
        $path = Join-Path $FrontendRoot $leaf
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $resolved = [System.IO.Path]::GetFullPath($path)
        if (-not (Test-PathUnderRoot -Candidate $resolved -Root $FrontendRoot)) {
            throw "W1B_HARNESS_FAILURE: unsafe frontend artifact target"
        }
        if ((Split-Path -Leaf $resolved) -cne $leaf) {
            throw "W1B_HARNESS_FAILURE: unexpected frontend artifact leaf"
        }
        if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
            throw "W1B_HARNESS_FAILURE: frontend artifact is not a directory"
        }
        $item = Get-Item -LiteralPath $resolved -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "W1B_HARNESS_FAILURE: frontend artifact target is a reparse point"
        }
        $entries = @(Get-ChildItem -LiteralPath $resolved -Recurse -Force)
        foreach ($entry in $entries) {
            if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "W1B_HARNESS_FAILURE: frontend artifact contains a reparse point"
            }
        }
        $fileCount += @($entries | Where-Object { -not $_.PSIsContainer }).Count
        $targets.Add([pscustomobject]@{ Path = $resolved; Leaf = $leaf }) | Out-Null
    }

    if ($RecordInitial) {
        $script:PreexistingFrontendArtifactFiles = $fileCount
        Write-Output ("W1B_PREEXISTING_ARTIFACT_FILES=" + $fileCount)
    }

    if ($CopyEvidence) {
        if (-not $ArtifactRootCreated) {
            throw "W1B_HARNESS_FAILURE: artifact root missing before preexisting evidence copy"
        }
        foreach ($target in $targets) {
            Copy-TreeToArtifacts `
                -Source $target.Path `
                -RelativeDestination ("preexisting-frontend-" + $target.Leaf)
        }
    }

    foreach ($target in $targets) {
        $resolved = $target.Path
        try {
            Remove-Item -LiteralPath $resolved -Recurse -Force
            if (Test-Path -LiteralPath $resolved) {
                throw "frontend artifact directory remained"
            }
        }
        catch {
            $script:HarnessFailure = $true
            throw "W1B_HARNESS_FAILURE: Playwright artifact cleanup"
        }
    }
}

function Parse-PlaywrightOutput {
    param([object[]]$Lines)

    $ansiFree = [regex]::Replace((Redact-Text ($Lines -join "`n")), "\x1B\[[0-?]*[ -/]*[@-~]", "")
    foreach ($match in [regex]::Matches(
            $ansiFree,
            "(?im)^\s*(\d+)\s+(passed|failed|skipped|errors?)(?:\s+\([^\r\n]*\))?\s*$"
        )) {
        $value = [int]$match.Groups[1].Value
        switch ($match.Groups[2].Value.ToLowerInvariant()) {
            "passed" { $script:E2EPassed += $value }
            "failed" { $script:E2EFailed += $value }
            "skipped" { $script:E2ESkipped += $value }
            "error" { $script:E2EErrors += $value }
            "errors" { $script:E2EErrors += $value }
        }
    }
    foreach ($match in [regex]::Matches($ansiFree, "(?m)^\s*Error:\s*(W1B_E2E_[A-Z0-9_]+)\s*$")) {
        $marker = $match.Groups[1].Value
        if (-not $script:ProductMarkers.Contains($marker)) {
            $script:ProductMarkers.Add($marker)
        }
    }
    return $ansiFree
}

function Get-PlaywrightDiagnosticReasonCodes {
    param([Parameter(Mandatory = $true)][string]$Text)

    $codes = [System.Collections.Generic.List[string]]::new()
    $patterns = [ordered]@{
        TEST_TIMEOUT = "Test timeout of \d+ms exceeded"
        WAIT_FOR_RESPONSE = "page\.waitForResponse"
        LOCATOR_ASSERTION = "expect\(locator\)"
        VALUE_ASSERTION = "expect\(received\)"
        STRICT_MODE = "strict mode violation"
        PAGE_CLOSED = "Target page, context or browser has been closed"
    }
    foreach ($entry in $patterns.GetEnumerator()) {
        if ($Text -match $entry.Value) {
            $codes.Add([string]$entry.Key) | Out-Null
        }
    }
    if ($codes.Count -eq 0) {
        $codes.Add("UNCLASSIFIED") | Out-Null
    }
    return @($codes)
}

function Get-PlaywrightDiagnosticSourceLines {
    param([Parameter(Mandatory = $true)][string]$Text)

    return @(
        [regex]::Matches(
            $Text,
            "(?i)w1b-recipients-real-pg\.spec\.ts:(\d+):\d+"
        ) |
            ForEach-Object { [int]$_.Groups[1].Value } |
            Sort-Object -Unique
    )
}

function Get-PlaywrightDiagnosticFailures {
    param([Parameter(Mandatory = $true)][string]$Text)

    $failures = [System.Collections.Generic.List[string]]::new()
    foreach ($match in [regex]::Matches(
            $Text,
            "(?ms)^\s*\d+\)\s+\[([^\]\r\n]+)\][^\r\n]*\r?\n(?<body>.*?)(?=^\s*\d+\)\s+\[|^\s*\d+\s+failed)"
        )) {
        $project = $match.Groups[1].Value.Trim()
        if ($project -cnotmatch "^chromium-\d+x\d+$") {
            continue
        }
        $lineMatch = [regex]::Match($match.Groups["body"].Value, "(?m)^\s*>\s*(\d+)\s*\|")
        $line = if ($lineMatch.Success) { [int]$lineMatch.Groups[1].Value } else { 0 }
        $failures.Add(("{0}:{1}" -f $project, $line)) | Out-Null
    }
    return @($failures)
}

function Test-HarnessOutput {
    param([object[]]$Lines)

    $text = Redact-Text ($Lines -join "`n")
    return $text -match (
        "Traceback|INTERNALERROR|Exception ignored in atexit callback|" +
        "PytestUnhandledThreadExceptionWarning|Exception in thread|" +
        "UnhandledPromiseRejection|Fatal Python error|unraisable"
    )
}

function Set-TestEnvironment {
    [Environment]::SetEnvironmentVariable("SSWCENTER_ENVIRONMENT", "test", "Process")
    [Environment]::SetEnvironmentVariable("SSWCENTER_POSTGRES_TEST", "1", "Process")
    [Environment]::SetEnvironmentVariable("SSWCENTER_DATABASE_URL", $OwnerDatabaseUrl, "Process")
    [Environment]::SetEnvironmentVariable("SSWCENTER_APP_DATABASE_URL", $AppDatabaseUrl, "Process")
    [Environment]::SetEnvironmentVariable("SSWCENTER_BACKUP_DATABASE_URL", $BackupDatabaseUrl, "Process")
    [Environment]::SetEnvironmentVariable("SSWCENTER_DATA_ROOT", $RuntimeRoot, "Process")
    [Environment]::SetEnvironmentVariable("SSWCENTER_PIN_PEPPER", $PinPepper, "Process")
    [Environment]::SetEnvironmentVariable("SSWCENTER_PIN_LOOKUP_KEY", $PinLookupKey, "Process")
    [Environment]::SetEnvironmentVariable("SSWCENTER_CSRF_SIGNING_KEY", $CsrfSigningKey, "Process")
    [Environment]::SetEnvironmentVariable(
        "SSWCENTER_RESIDENT_NUMBER_KEY_V1",
        "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "SSWCENTER_RESIDENT_NUMBER_LOOKUP_KEY",
        "YWJjZGVmMDEyMzQ1Njc4OWFiMjM0NTY3ODlhYmNkZWY=",
        "Process"
    )
    [Environment]::SetEnvironmentVariable("SSWCENTER_RESIDENT_NUMBER_ACTIVE_KEY_VERSION", "1", "Process")
    [Environment]::SetEnvironmentVariable("SSWCENTER_W1B_REAL_PG", "1", "Process")
    [Environment]::SetEnvironmentVariable("SSWCENTER_W1B_SYNTHETIC_PIN", $SyntheticPin, "Process")
    [Environment]::SetEnvironmentVariable("TEMP", $TempParent, "Process")
    [Environment]::SetEnvironmentVariable("TMP", $TempParent, "Process")
    [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1", "Process")
    [Environment]::SetEnvironmentVariable("PLAYWRIGHT_NO_COPY_PROMPT", "1", "Process")
    [System.IO.Directory]::CreateDirectory($RuntimeRoot) | Out-Null
}

function Assert-Prerequisites {
    if (-not [string]::IsNullOrWhiteSpace($TempParentResolutionFailure)) {
        throw "W1B_HARNESS_FAILURE: temp parent unavailable"
    }
    if ($SyntheticPin -notmatch "^[0-9]{6}$") {
        throw "W1B_HARNESS_FAILURE: synthetic PIN environment is invalid"
    }
    $required = @(
        $PythonExe,
        $InitDbExe,
        $PgCtlExe,
        $PgIsReadyExe,
        $CreateDbExe,
        $PsqlExe,
        $PowerShellExe,
        $NpmExe,
        $PostcheckPath,
        $LeakGatePath,
        $SpecPath,
        $PlaywrightConfigPath
    )
    $missing = @($required | Where-Object { [string]::IsNullOrWhiteSpace([string]$_) -or -not (Test-Path -LiteralPath $_ -PathType Leaf) })
    if ($missing.Count -gt 0) {
        throw "W1B_HARNESS_FAILURE: required executable or file missing"
    }
    foreach ($port in @($Port, $BackendPort, $FrontendPort)) {
        if ((Get-ListenerCount -ListenPort $port) -ne 0) {
            throw ("W1B_HARNESS_FAILURE: port {0} is occupied" -f $port)
        }
    }
    $script:PortCleanupAuthorized = $true
    Remove-RecoveryTempRoot
    Assert-SafePath -Path $TempRoot -Parent $TempParent -LeafPrefix "sswcenter-w1b-pg-"
    [System.IO.Directory]::CreateDirectory($TempRoot) | Out-Null
    [System.IO.Directory]::CreateDirectory($ArtifactRoot) | Out-Null
    [System.IO.Directory]::CreateDirectory($DataRoot) | Out-Null
    $script:ArtifactRootCreated = $true
    Remove-FrontendArtifacts -RecordInitial -CopyEvidence
    $script:FrontendArtifactCleanupReady = $true
    Write-Output "W1B_PREFLIGHT_OK=1"
}

try {
    Assert-Prerequisites
    Set-TestEnvironment

    $init = Invoke-Captured `
        -FilePath $InitDbExe `
        -WorkingDirectory $WorkspaceRoot `
        -Arguments @("-D", $DataRoot, "-U", "postgres", "--auth=trust", "--no-locale", "--encoding=UTF8")
    Assert-CommandSuccess -Name "initdb" -Result $init

    $PgStartAttempted = $true
    $start = Invoke-Captured `
        -FilePath $PgCtlExe `
        -WorkingDirectory $WorkspaceRoot `
        -Arguments @(
            "-D", $DataRoot,
            "-l", $LogFile,
            "-o", ("-h 127.0.0.1 -p {0}" -f $Port),
            "start", "-w"
        )
    Assert-CommandSuccess -Name "pg-start" -Result $start
    $PgStarted = $true
    if ((Get-ListenerCount -ListenPort $Port) -ne 1) {
        throw "W1B_HARNESS_FAILURE: PostgreSQL listener did not become ready"
    }

    $roles = Invoke-PsqlSql -Database "postgres" -Role "postgres" -Sql @"
CREATE ROLE erp_owner LOGIN PASSWORD '$OwnerPassword';
CREATE ROLE erp_app LOGIN PASSWORD '$AppPassword';
CREATE ROLE erp_backup LOGIN PASSWORD '$BackupPassword';
"@
    Assert-CommandSuccess -Name "roles" -Result $roles
    $database = Invoke-Captured `
        -FilePath $CreateDbExe `
        -WorkingDirectory $WorkspaceRoot `
        -Environment @{ PGPASSWORD = "" } `
        -Arguments @("-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres", "-O", "erp_owner", $DatabaseName)
    Assert-CommandSuccess -Name "database" -Result $database

    $upgrade = Invoke-Captured `
        -FilePath $PythonExe `
        -WorkingDirectory $BackendRoot `
        -Environment @{ SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl } `
        -Arguments @("-m", "alembic", "-c", "alembic.ini", "upgrade", $ExpectedRevision)
    Assert-CommandSuccess -Name "alembic-upgrade-w1b" -Result $upgrade
    $revisionResult = Invoke-ScalarPsql `
        -Database $DatabaseName `
        -Role "erp_owner" `
        -Sql "SELECT version_num FROM erp.alembic_version"
    Assert-CommandSuccess -Name "revision-check" -Result $revisionResult
    $revisionLines = @(
        $revisionResult.Stdout |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    $safeRevisions = @($revisionLines | Where-Object { $_ -cmatch "^[0-9]{8}_[A-Za-z0-9_]+$" })
    Write-Output ("W1B_ALEMBIC_REVISION_COUNT=" + $revisionLines.Count)
    Write-Output ("W1B_ALEMBIC_SAFE_REVISION_COUNT=" + $safeRevisions.Count)
    Write-Output ("W1B_ALEMBIC_SAFE_REVISIONS=" + ($safeRevisions -join ","))
    $revisionMatchesExpected = $false
    if ($revisionLines.Count -eq 1 -and $safeRevisions.Count -eq 1) {
        $revisionMatchesExpected = [string]::Compare(
            [string]$safeRevisions[0],
            [string]$ExpectedRevision,
            [System.StringComparison]::Ordinal
        ) -eq 0
    }
    if (-not $revisionMatchesExpected) {
        throw "W1B_HARNESS_FAILURE: migration revision mismatch"
    }
    Invoke-AppSessionSettingsProbe
    Invoke-Postcheck -Stage "before"

    # Historical 0009 revision + pre-postcheck are sealed above. Current backend
    # ORM/E2E require the live Alembic head (includes 0016 payer_guardian_id).
    $headUpgrade = Invoke-Captured `
        -FilePath $PythonExe `
        -WorkingDirectory $BackendRoot `
        -Environment @{ SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl } `
        -Arguments @("-m", "alembic", "-c", "alembic.ini", "upgrade", $CurrentHead)
    Write-CommandCapture -Name "alembic-upgrade-head" -Result $headUpgrade
    if ($headUpgrade.TimedOut -or $headUpgrade.ExitCode -ne 0) {
        throw "W1B_HARNESS_HEAD_UPGRADE_FAILED"
    }
    $headRevisionResult = Invoke-ScalarPsql `
        -Database $DatabaseName `
        -Role "erp_owner" `
        -Sql "SELECT version_num FROM erp.alembic_version"
    Write-CommandCapture -Name "head-revision-check" -Result $headRevisionResult
    if ($headRevisionResult.TimedOut -or $headRevisionResult.ExitCode -ne 0) {
        throw "W1B_HARNESS_HEAD_UPGRADE_FAILED"
    }
    $headRevisionLines = @(
        $headRevisionResult.Stdout |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    $headMatchesCurrent = $false
    if ($headRevisionLines.Count -eq 1) {
        $headMatchesCurrent = [string]::Compare(
            [string]$headRevisionLines[0],
            [string]$CurrentHead,
            [System.StringComparison]::Ordinal
        ) -eq 0
    }
    if (-not $headMatchesCurrent) {
        throw "W1B_HARNESS_HEAD_UPGRADE_FAILED"
    }
    Write-Output "W1B_HEAD_UPGRADE_OK"

    Start-Backend
    $E2EStarted = $true
    $e2e = Invoke-Captured `
        -FilePath $NpmExe `
        -WorkingDirectory $FrontendRoot `
        -Environment @{
            SSWCENTER_E2E_BACKEND_PORT = [string]$BackendPort
            SSWCENTER_E2E_FRONTEND_PORT = [string]$FrontendPort
        } `
        -Arguments @(
            "exec", "playwright", "--", "test",
            "e2e/w1b-recipients-real-pg.spec.ts",
            "--workers=1"
        )
    $E2EExitCode = [int]$e2e.ExitCode
    $E2EOutput = @($e2e.Output)
    Write-CommandCapture -Name "playwright" -Result $e2e
    if ($e2e.TimedOut) {
        $HarnessFailure = $true
        Write-Output "W1B_HARNESS_FAILURE: Playwright timeout"
    }
    $parsedE2EOutput = Parse-PlaywrightOutput -Lines $E2EOutput
    if ($E2EExitCode -ne 0 -and $ProductMarkers.Count -eq 0) {
        $diagnosticReasonCodes = @(Get-PlaywrightDiagnosticReasonCodes -Text $parsedE2EOutput)
        $diagnosticSourceLines = @(Get-PlaywrightDiagnosticSourceLines -Text $parsedE2EOutput)
        $diagnosticFailures = @(Get-PlaywrightDiagnosticFailures -Text $parsedE2EOutput)
        Write-Output ("W1B_E2E_DIAGNOSTIC_REASON_CODES=" + ($diagnosticReasonCodes -join ","))
        Write-Output ("W1B_E2E_DIAGNOSTIC_SOURCE_LINES=" + ($diagnosticSourceLines -join ","))
        Write-Output ("W1B_E2E_DIAGNOSTIC_FAILURES=" + ($diagnosticFailures -join ","))
    }
    if (Test-HarnessOutput -Lines $E2EOutput) {
        $HarnessFailure = $true
        Write-Output "W1B_HARNESS_FAILURE: Playwright harness output"
    }
    Write-Output ("W1B_E2E_EXIT_CODE=" + $E2EExitCode)
    Write-Output ("W1B_E2E_COUNTS=passed:{0} failed:{1} skipped:{2} errors:{3}" -f $E2EPassed, $E2EFailed, $E2ESkipped, $E2EErrors)
    if ($ProductMarkers.Count -gt 0) {
        Write-Output ("W1B_E2E_MARKERS=" + ($ProductMarkers -join ","))
    }

    Stop-Backend
    Invoke-Postcheck -Stage "after"
    $stop = Invoke-Captured `
        -FilePath $PgCtlExe `
        -WorkingDirectory $WorkspaceRoot `
        -Arguments @("-D", $DataRoot, "stop", "-m", "fast", "-w")
    Assert-CommandSuccess -Name "pg-stop" -Result $stop
    $PgStarted = $false
    Copy-FrontendArtifacts
    Copy-BackendArtifacts
    Invoke-LeakScan
}
catch {
    $HarnessFailure = $true
    $safeMessage = Redact-Text $_.Exception.Message
    Write-Output ("W1B_HARNESS_FAILURE: " + $safeMessage)
}
finally {
    try { Stop-Backend } catch { $HarnessFailure = $true; Write-Output "W1B_HARNESS_FAILURE: backend finally cleanup" }
    if ($PgStarted) {
        try {
            $stopFinally = Invoke-Captured `
                -FilePath $PgCtlExe `
                -WorkingDirectory $WorkspaceRoot `
                -Arguments @("-D", $DataRoot, "stop", "-m", "fast", "-w")
            Write-CommandCapture -Name "pg-stop-finally" -Result $stopFinally
            if ($stopFinally.TimedOut -or $stopFinally.ExitCode -ne 0) {
                $HarnessFailure = $true
                Write-Output "W1B_HARNESS_FAILURE: PostgreSQL finally cleanup"
            }
        }
        catch {
            $HarnessFailure = $true
            Write-Output "W1B_HARNESS_FAILURE: PostgreSQL finally cleanup"
        }
        $PgStarted = $false
    }
    if ($ArtifactRootCreated -and -not $LeakAttempted) {
        try { Copy-FrontendArtifacts } catch { $HarnessFailure = $true; Write-Output "W1B_HARNESS_FAILURE: artifact capture" }
        try { Copy-BackendArtifacts } catch { $HarnessFailure = $true; Write-Output "W1B_HARNESS_FAILURE: backend artifact capture" }
        try { Invoke-LeakScan } catch { $HarnessFailure = $true; Write-Output "W1B_HARNESS_FAILURE: leak finally cleanup" }
    }
    if ($FrontendArtifactCleanupReady) {
        try { Remove-FrontendArtifacts } catch { $HarnessFailure = $true; Write-Output "W1B_HARNESS_FAILURE: artifact cleanup" }
    }
    if ($PortCleanupAuthorized -and $PgStartAttempted) {
        Invoke-PortCleanup -ListenPort $Port -BaselinePids @() -Label "postgres"
    }
    if ($PortCleanupAuthorized) {
        Invoke-PortCleanup -ListenPort $BackendPort -BaselinePids @() -Label "backend"
        Invoke-PortCleanup -ListenPort $FrontendPort -BaselinePids @() -Label "frontend"
    }
    if (Test-Path -LiteralPath $TempRoot) {
        try {
            Assert-SafePath -Path $TempRoot -Parent $TempParent -LeafPrefix "sswcenter-w1b-pg-"
            Remove-Item -LiteralPath $TempRoot -Recurse -Force
        }
        catch {
            $HarnessFailure = $true
            Write-Output "W1B_HARNESS_FAILURE: temp root cleanup"
        }
    }
    try { Restore-Environment } catch { $HarnessFailure = $true; Write-Output "W1B_HARNESS_FAILURE: environment restore" }
}

$pgRemaining = Get-ListenerCount -ListenPort $Port
$backendRemaining = Get-ListenerCount -ListenPort $BackendPort
$frontendRemaining = Get-ListenerCount -ListenPort $FrontendPort
$artifactRemaining = @(
    (Join-Path $FrontendRoot "test-results"),
    (Join-Path $FrontendRoot "playwright-report")
) | Where-Object { Test-Path -LiteralPath $_ } | Measure-Object | Select-Object -ExpandProperty Count
$tempClusterRemaining = @(Get-ChildItem -LiteralPath $TempParent -Directory -Filter "sswcenter-w1b-pg-*" -Force -ErrorAction SilentlyContinue).Count
Write-Output ("W1B_PG_LISTENER_REMAINING=" + $pgRemaining)
Write-Output ("W1B_BACKEND_LISTENER_REMAINING=" + $backendRemaining)
Write-Output ("W1B_FRONTEND_LISTENER_REMAINING=" + $frontendRemaining)
Write-Output ("W1B_PLAYWRIGHT_ARTIFACT_REMAINING=" + $artifactRemaining)
Write-Output ("W1B_TEMP_CLUSTER_REMAINING=" + $tempClusterRemaining)

if (
    $HarnessFailure -or
    -not $PostcheckBefore -or
    -not $PostcheckAfter -or
    -not $LeakSuccessful -or
    $pgRemaining -ne 0 -or
    $backendRemaining -ne 0 -or
    $frontendRemaining -ne 0 -or
    $artifactRemaining -ne 0 -or
    $tempClusterRemaining -ne 0
) {
    Write-Output "W1B_HARNESS_FAILURE: final invariant"
    exit 2
}

if ($E2EExitCode -eq 0 -and $E2EPassed -eq 3 -and $E2EFailed -eq 0 -and $E2ESkipped -eq 0 -and $E2EErrors -eq 0) {
    Write-Output "W1B_E2E_GREEN"
    exit 0
}

if ($E2EExitCode -eq 1 -and $E2EPassed -eq 0 -and $E2EFailed -eq 3 -and $E2ESkipped -eq 0 -and $E2EErrors -eq 0 -and $ProductMarkers.Count -gt 0) {
    Write-Output "W1B_E2E_RED_VALID"
    exit 1
}

Write-Output "W1B_E2E_RED_NOT_REPRODUCED"
exit 2
