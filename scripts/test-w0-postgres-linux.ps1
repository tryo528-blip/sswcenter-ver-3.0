param(
    [int]$Port = 55434,
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.IO.Path]::DirectorySeparatorChar -eq '\\') {
    throw "W0_POSTGRES_LINUX_ONLY"
}
if ($Port -lt 1024 -or $Port -gt 65535) {
    throw "W0_POSTGRES_PORT_INVALID"
}

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$PythonExe = if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    Join-Path $BackendRoot ".venv/bin/python"
} else {
    if (-not [System.IO.Path]::IsPathRooted($PythonExecutable)) {
        throw "W0_POSTGRES_PYTHON_MUST_BE_ABSOLUTE"
    }
    [System.IO.Path]::GetFullPath($PythonExecutable)
}

$PostgresBin = "/usr/lib/postgresql/16/bin"
$InitDbExe = Join-Path $PostgresBin "initdb"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl"
$PgIsReadyExe = Join-Path $PostgresBin "pg_isready"
$CreateDbExe = Join-Path $PostgresBin "createdb"
$PsqlExe = "/usr/bin/psql"
foreach ($Executable in @(
        $PythonExe,
        $InitDbExe,
        $PgCtlExe,
        $PgIsReadyExe,
        $CreateDbExe,
        $PsqlExe
    )) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "W0_POSTGRES_EXECUTABLE_MISSING: $Executable"
    }
}

$PortProbe = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    $Port
)
try {
    $PortProbe.Start()
}
catch {
    throw "W0_POSTGRES_PORT_IN_USE: $Port"
}
finally {
    $PortProbe.Stop()
}

$TempParent = [System.IO.Path]::GetFullPath("/tmp")
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $TempParent ("sswcenter-w0-pg-" + [Guid]::NewGuid().ToString("N")))
)
$TempPrefix = $TempParent.TrimEnd('/') + '/'
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (
    -not $ClusterRoot.StartsWith($TempPrefix, [StringComparison]::Ordinal) -or
    $ClusterLeaf -cnotmatch '^sswcenter-w0-pg-[0-9a-f]{32}$'
) {
    throw "W0_POSTGRES_UNSAFE_CLUSTER_PATH"
}

$DataDirectory = Join-Path $ClusterRoot "data"
$SocketDirectory = Join-Path $ClusterRoot "socket"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$DataRoot = Join-Path $ClusterRoot "sswcenter-w0-data"
$DatabaseName = "sswcenter_w0_test"
$OwnerDatabaseUrl = "postgresql+psycopg://erp_owner@127.0.0.1:$Port/$DatabaseName"
$AppDatabaseUrl = "postgresql+psycopg://erp_app@127.0.0.1:$Port/$DatabaseName"
$GrantScript = Join-Path $WorkspaceRoot "infra/postgres/grant-application-access.sql"
$InitialGitStatus = ((
        & git -C $WorkspaceRoot status --porcelain --untracked-files=all
    ) -join "`n")

$TrackedEnvironmentNames = @(
    "SSWCENTER_ENVIRONMENT",
    "SSWCENTER_DATABASE_URL",
    "SSWCENTER_APP_DATABASE_URL",
    "SSWCENTER_DATA_ROOT",
    "SSWCENTER_W0_POSTGRES_LIVE",
    "PYTHONDONTWRITEBYTECODE",
    "PGCLIENTENCODING"
)
$PreviousEnvironment = @{}
foreach ($EnvironmentName in $TrackedEnvironmentNames) {
    $PreviousEnvironment[$EnvironmentName] = [Environment]::GetEnvironmentVariable(
        $EnvironmentName,
        "Process"
    )
}

$BaselinePostgresIds = @(
    Get-Process -Name postgres -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Id
)
$StartedPostgresIds = @()
$ClusterStarted = $false
$RunSucceeded = $false
$PrimaryFailure = $null
$CleanupFailure = $null

try {
    New-Item -ItemType Directory -Path $DataDirectory | Out-Null
    New-Item -ItemType Directory -Path $SocketDirectory | Out-Null
    New-Item -ItemType Directory -Path $DataRoot | Out-Null

    & $InitDbExe `
        "--pgdata=$DataDirectory" `
        "--username=postgres" `
        "--auth=trust" `
        "--encoding=UTF8" `
        "--locale=C.utf8" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W0_POSTGRES_INITDB_FAILED"
    }

    & $PgCtlExe `
        "--pgdata=$DataDirectory" `
        "--log=$LogFile" `
        "--options=-h 127.0.0.1 -p $Port -k $SocketDirectory" `
        start | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W0_POSTGRES_START_FAILED"
    }
    $ClusterStarted = $true

    & $PgIsReadyExe -h 127.0.0.1 -p $Port -U postgres -d postgres -t 15 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W0_POSTGRES_NOT_READY"
    }
    $StartedPostgresIds = @(
        Get-Process -Name postgres -ErrorAction SilentlyContinue |
            Where-Object { $BaselinePostgresIds -notcontains $_.Id } |
            Select-Object -ExpandProperty Id
    )
    Write-Output "W0_POSTGRES_STAGE=cluster_ready"

    $RoleSql = @'
CREATE ROLE erp_owner LOGIN;
CREATE ROLE erp_app LOGIN;
CREATE ROLE erp_backup LOGIN;
'@
    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -d postgres `
        -c $RoleSql | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W0_POSTGRES_ROLE_BOOTSTRAP_FAILED"
    }
    & $CreateDbExe `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -O erp_owner `
        $DatabaseName
    if ($LASTEXITCODE -ne 0) {
        throw "W0_POSTGRES_DATABASE_CREATE_FAILED"
    }

    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_APP_DATABASE_URL = $AppDatabaseUrl
    $env:SSWCENTER_DATA_ROOT = $DataRoot
    $env:SSWCENTER_W0_POSTGRES_LIVE = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PGCLIENTENCODING = "UTF8"

    Push-Location $BackendRoot
    try {
        & $PythonExe -B -m alembic -c alembic.ini upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw "W0_POSTGRES_ALEMBIC_FAILED"
        }
    }
    finally {
        Pop-Location
    }
    Write-Output "W0_POSTGRES_STAGE=migration_head"

    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U erp_owner `
        -d $DatabaseName `
        -f $GrantScript | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W0_POSTGRES_APPLICATION_GRANT_FAILED"
    }
    Write-Output "W0_POSTGRES_STAGE=application_acl"

    Push-Location $BackendRoot
    try {
        $env:SSWCENTER_DATABASE_URL = $AppDatabaseUrl
        & $PythonExe -B -m app.db.postcheck_dispatch
        if ($LASTEXITCODE -ne 0) {
            throw "W0_POSTGRES_CURRENT_POSTCHECK_FAILED"
        }
        $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
        & $PythonExe -B -m pytest -q -p no:cacheprovider tests/test_w0_postgres_live.py
        if ($LASTEXITCODE -ne 0) {
            throw "W0_POSTGRES_LIVE_TEST_FAILED"
        }
    }
    finally {
        Pop-Location
    }

    Write-Output "W0_POSTGRES_LIVE_GREEN"
    $RunSucceeded = $true
}
catch {
    $PrimaryFailure = $_.Exception
}
finally {
    try {
        if ($ClusterStarted) {
            & $PgCtlExe "--pgdata=$DataDirectory" --mode=fast stop --wait | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "W0_POSTGRES_STOP_FAILED"
            }
            $ClusterStarted = $false
        }

        if (Test-Path -LiteralPath $ClusterRoot -PathType Container) {
            $ResolvedCleanupRoot = [System.IO.Path]::GetFullPath($ClusterRoot)
            if (
                -not $ResolvedCleanupRoot.StartsWith($TempPrefix, [StringComparison]::Ordinal) -or
                (Split-Path -Leaf $ResolvedCleanupRoot) -cnotmatch '^sswcenter-w0-pg-[0-9a-f]{32}$'
            ) {
                throw "W0_POSTGRES_UNSAFE_CLEANUP_PATH"
            }
            [System.IO.Directory]::Delete($ResolvedCleanupRoot, $true)
        }

        $RemainingProcessCount = @(
            Get-Process -Name postgres -ErrorAction SilentlyContinue |
                Where-Object { $StartedPostgresIds -contains $_.Id }
        ).Count
        $TempCount = if (Test-Path -LiteralPath $ClusterRoot) { 1 } else { 0 }
        $FinalGitStatus = ((
                & git -C $WorkspaceRoot status --porcelain --untracked-files=all
            ) -join "`n")
        $GitDeltaCount = if ($FinalGitStatus -ceq $InitialGitStatus) { 0 } else { 1 }

        $CleanupPortProbe = [System.Net.Sockets.TcpListener]::new(
            [System.Net.IPAddress]::Loopback,
            $Port
        )
        $ListenerCount = 0
        try {
            $CleanupPortProbe.Start()
        }
        catch {
            $ListenerCount = 1
        }
        finally {
            $CleanupPortProbe.Stop()
        }

        if (
            $ListenerCount -ne 0 -or
            $RemainingProcessCount -ne 0 -or
            $TempCount -ne 0 -or
            $GitDeltaCount -ne 0
        ) {
            throw "W0_POSTGRES_CLEANUP_NOT_ZERO"
        }
        Write-Output (
            "W0_POSTGRES_CLEANUP listener={0} process={1} temp={2} git_delta={3}" -f
            $ListenerCount,
            $RemainingProcessCount,
            $TempCount,
            $GitDeltaCount
        )
    }
    catch {
        $CleanupFailure = $_.Exception
    }
    finally {
        foreach ($EnvironmentName in $TrackedEnvironmentNames) {
            $PreviousValue = $PreviousEnvironment[$EnvironmentName]
            if ($null -eq $PreviousValue) {
                Remove-Item -LiteralPath "Env:$EnvironmentName" -ErrorAction SilentlyContinue
            }
            else {
                Set-Item -Path "Env:$EnvironmentName" -Value $PreviousValue
            }
        }
    }
}

if ($null -ne $PrimaryFailure) {
    if ($null -ne $CleanupFailure) {
        throw "W0_POSTGRES_FAILED_WITH_CLEANUP_FAILURE"
    }
    throw $PrimaryFailure
}
if ($null -ne $CleanupFailure) {
    throw $CleanupFailure
}
if (-not $RunSucceeded) {
    throw "W0_POSTGRES_RUN_NOT_GREEN"
}

Write-Output "W0_POSTGRES_SEAL_GREEN"
