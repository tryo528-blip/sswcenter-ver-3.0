param(
    [int]$Port = 55432
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PostgresBin = "C:\Program Files\PostgreSQL\17\bin"
$InitDbExe = Join-Path $PostgresBin "initdb.exe"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl.exe"
$PgIsReadyExe = Join-Path $PostgresBin "pg_isready.exe"
$CreateDbExe = Join-Path $PostgresBin "createdb.exe"
$PsqlExe = Join-Path $PostgresBin "psql.exe"

foreach ($Executable in @($InitDbExe, $PgCtlExe, $PgIsReadyExe, $CreateDbExe, $PsqlExe)) {
    if (-not (Test-Path -LiteralPath $Executable)) {
        throw "Required PostgreSQL executable is missing: $Executable"
    }
}

$ExistingListener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($ExistingListener) {
    throw "Port $Port is already in use"
}

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA is required for the ephemeral cluster"
}
$AllowedTempRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $env:LOCALAPPDATA "Temp")
).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
)
if (-not (Test-Path -LiteralPath $AllowedTempRoot -PathType Container)) {
    throw "User temporary directory is unavailable: $AllowedTempRoot"
}
$env:TEMP = $AllowedTempRoot
$env:TMP = $AllowedTempRoot
$env:TMPDIR = $AllowedTempRoot
$AllowedTempPrefix = $AllowedTempRoot + [System.IO.Path]::DirectorySeparatorChar
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $AllowedTempRoot ("sswcenter-wave0-pg-" + [Guid]::NewGuid().ToString("N")))
)
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (-not $ClusterRoot.StartsWith($AllowedTempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Ephemeral cluster path escaped the temporary directory"
}
if (-not $ClusterLeaf.StartsWith("sswcenter-wave0-pg-", [StringComparison]::Ordinal)) {
    throw "Unexpected ephemeral cluster directory name"
}

$DataDirectory = Join-Path $ClusterRoot "data"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$DatabaseName = "sswcenter_wave0_test"
$RuntimeDatabaseName = "sswcenter_wave0_runtime_test"
$SeedDatabaseName = "sswcenter_wave0_seed_test"
$OfflineDatabaseName = "sswcenter_wave0_offline_test"
$OfflineSqlFile = Join-Path $ClusterRoot "wave0-offline.sql"
$OfflineErrorFile = Join-Path $ClusterRoot "wave0-offline.stderr.log"
$ClusterStarted = $false

New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null

try {
    & $InitDbExe `
        --pgdata=$DataDirectory `
        --username=postgres `
        --auth=trust `
        --encoding=UTF8 `
        --locale=C
    if ($LASTEXITCODE -ne 0) {
        throw "initdb failed"
    }

    & $PgCtlExe `
        --pgdata=$DataDirectory `
        --log=$LogFile `
        --options="-h 127.0.0.1 -p $Port" `
        start
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to start the ephemeral PostgreSQL cluster"
    }
    $ClusterStarted = $true

    & $PgIsReadyExe -h 127.0.0.1 -p $Port -U postgres -d postgres -t 10
    if ($LASTEXITCODE -ne 0) {
        throw "Ephemeral PostgreSQL did not become ready"
    }

    & $CreateDbExe -h 127.0.0.1 -p $Port -U postgres $DatabaseName
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the isolated Wave 0 database"
    }

    $WorkspaceRoot = Split-Path -Parent $PSScriptRoot
    $BackendRoot = Join-Path $WorkspaceRoot "backend"
    $PythonExe = Join-Path $BackendRoot ".venv\Scripts\python.exe"
    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_DATABASE_URL = (
        "postgresql+psycopg://postgres@127.0.0.1:{0}/{1}" -f $Port, $DatabaseName
    )
    $env:SSWCENTER_POSTGRES_TEST = "1"
    $env:SSWCENTER_PIN_PEPPER = "ephemeral-test-pepper"
    $env:SSWCENTER_PIN_LOOKUP_KEY = "ephemeral-test-lookup-key"
    $env:SSWCENTER_CSRF_SIGNING_KEY = "ephemeral-test-csrf-key"
    $env:SSWCENTER_DATA_ROOT = Join-Path $ClusterRoot "sswcenter-test-files"
    New-Item -ItemType Directory -Path $env:SSWCENTER_DATA_ROOT -Force | Out-Null
    $OnlineDatabaseUrl = $env:SSWCENTER_DATABASE_URL

    Push-Location $BackendRoot
    try {
        & $PythonExe -m alembic -c alembic.ini upgrade 20260724_0002
        if ($LASTEXITCODE -ne 0) { throw "Initial Alembic upgrade failed" }

        & $PythonExe -m alembic -c alembic.ini downgrade base
        if ($LASTEXITCODE -ne 0) { throw "Alembic downgrade round trip failed" }

        & $PythonExe -m alembic -c alembic.ini upgrade 20260724_0002
        if ($LASTEXITCODE -ne 0) { throw "Second Alembic upgrade failed" }

    }
    finally {
        Pop-Location
    }

    & (Join-Path $PSScriptRoot "verify-wave0-db.ps1") `
        -DatabaseUrl $OnlineDatabaseUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Wave 0 PostgreSQL postcheck failed"
    }

    & $CreateDbExe -h 127.0.0.1 -p $Port -U postgres $RuntimeDatabaseName
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the current-head Wave 0 runtime database"
    }
    $RuntimeDatabaseUrl = (
        "postgresql+psycopg://postgres@127.0.0.1:{0}/{1}" -f
        $Port,
        $RuntimeDatabaseName
    )
    $env:SSWCENTER_DATABASE_URL = $RuntimeDatabaseUrl
    Push-Location $BackendRoot
    try {
        & $PythonExe -m alembic -c alembic.ini upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw "Current-head Wave 0 runtime upgrade failed"
        }
        & $PythonExe -m pytest -q tests/test_auth_postgres.py
        if ($LASTEXITCODE -ne 0) {
            throw "Current-head Wave 0 authentication regression test failed"
        }
    }
    finally {
        Pop-Location
    }

    & $CreateDbExe -h 127.0.0.1 -p $Port -U postgres $SeedDatabaseName
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the isolated synthetic-seed database"
    }
    $SeedDatabaseUrl = (
        "postgresql+psycopg://postgres@127.0.0.1:{0}/{1}" -f $Port, $SeedDatabaseName
    )
    $env:SSWCENTER_DATABASE_URL = $SeedDatabaseUrl
    Push-Location $BackendRoot
    try {
        & $PythonExe -m alembic -c alembic.ini upgrade 20260724_0002
        if ($LASTEXITCODE -ne 0) { throw "Synthetic-seed Alembic upgrade failed" }
    }
    finally {
        Pop-Location
    }
    $Wave0SeedSql = @'
DO $$
DECLARE
    seed_staff_id bigint;
    seed_account_id bigint;
BEGIN
    INSERT INTO erp.center (center_code, center_name)
    VALUES ('SYNTHETIC', 'Synthetic Wave 0 Center');

    INSERT INTO erp.staff (
        name,
        birth_date,
        sex_code,
        display_name,
        memo
    )
    VALUES (
        'Synthetic Wave 0 Admin',
        DATE '1990-01-01',
        'TEST',
        'Synthetic Admin',
        'Wave 0 backup fixture'
    )
    RETURNING id INTO seed_staff_id;

    INSERT INTO erp.user_account (
        staff_id,
        account_code,
        display_name,
        role_code,
        pin_hash,
        pin_lookup_hmac,
        pin_key_version
    )
    VALUES (
        seed_staff_id,
        'ADMIN',
        'Synthetic Admin',
        'ADMIN',
        'synthetic-hash-not-for-login',
        decode(repeat('02', 32), 'hex'),
        1
    )
    RETURNING id INTO seed_account_id;

    UPDATE erp.installation_state
    SET bootstrap_completed = true,
        bootstrap_completed_at_utc = now(),
        first_admin_account_id = seed_account_id,
        installed_app_version = 'wave0-exact-seed';
END
$$;
'@
    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -d $SeedDatabaseName `
        -c $Wave0SeedSql | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Exact Wave 0 synthetic seed failed"
    }
    $SeedCheck = & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -d $SeedDatabaseName `
        -tAc (
            "SELECT count(*) FROM erp.installation_state s " +
            "JOIN erp.user_account a ON a.id = s.first_admin_account_id " +
            "WHERE s.bootstrap_completed AND a.role_code = 'ADMIN'"
        )
    if ($LASTEXITCODE -ne 0 -or ($SeedCheck -join "").Trim() -ne "1") {
        throw "Synthetic seed verification failed"
    }

    $BlobDirectory = Join-Path $env:SSWCENTER_DATA_ROOT "blobs"
    $OfficialDirectory = Join-Path $env:SSWCENTER_DATA_ROOT "official-documents"
    New-Item -ItemType Directory -Path $BlobDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $OfficialDirectory -Force | Out-Null
    [System.IO.File]::WriteAllText(
        (Join-Path $BlobDirectory "synthetic-blob.txt"),
        "synthetic blob payload",
        [System.Text.UTF8Encoding]::new($false)
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $OfficialDirectory "synthetic-output.txt"),
        "synthetic official output",
        [System.Text.UTF8Encoding]::new($false)
    )
    $BackupRoot = Join-Path $ClusterRoot "sswcenter-backups"
    $BackupOutput = & (Join-Path $PSScriptRoot "backup-postgres.ps1") `
        -DatabaseUrl $SeedDatabaseUrl `
        -DestinationRoot $BackupRoot `
        -DataRoot $env:SSWCENTER_DATA_ROOT `
        -AppVersion "wave0-test"
    if ($LASTEXITCODE -ne 0) {
        throw "Wave 0 backup test failed"
    }
    $BackupDirectory = (
        Get-ChildItem -LiteralPath $BackupRoot -Directory |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    ).FullName
    $AdminDatabaseUrl = "postgresql+psycopg://postgres@127.0.0.1:$Port/postgres"
    & (Join-Path $PSScriptRoot "restore-drill.ps1") `
        -BackupDirectory $BackupDirectory `
        -AdminDatabaseUrl $AdminDatabaseUrl `
        -ReviewDatabaseName "sswcenter_restore_review" `
        -ReviewDataRoot (Join-Path $ClusterRoot "sswcenter-restore-review-files")
    if ($LASTEXITCODE -ne 0) {
        throw "Wave 0 restore drill failed: $BackupOutput"
    }

    & $CreateDbExe -h 127.0.0.1 -p $Port -U postgres $OfflineDatabaseName
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the isolated offline migration database"
    }

    $OfflineDatabaseUrl = (
        "postgresql+psycopg://postgres@127.0.0.1:{0}/{1}" -f $Port, $OfflineDatabaseName
    )
    $env:SSWCENTER_DATABASE_URL = $OfflineDatabaseUrl

    Push-Location $BackendRoot
    try {
        $PreviousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $OfflineSqlLines = & $PythonExe `
            -m alembic `
            -c alembic.ini `
            upgrade 20260724_0002 `
            --sql 2> $OfflineErrorFile
        $AlembicExitCode = $LASTEXITCODE
        $ErrorActionPreference = $PreviousErrorActionPreference
        if ($AlembicExitCode -ne 0) {
            $OfflineSqlErrors = Get-Content -LiteralPath $OfflineErrorFile -Raw
            throw "Offline Alembic SQL generation failed: $OfflineSqlErrors"
        }

        $OfflineSql = ($OfflineSqlLines -join [Environment]::NewLine) + [Environment]::NewLine
        [System.IO.File]::WriteAllText(
            $OfflineSqlFile,
            $OfflineSql,
            [System.Text.UTF8Encoding]::new($false)
        )
    }
    finally {
        Pop-Location
    }

    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -d $OfflineDatabaseName `
        -f $OfflineSqlFile
    if ($LASTEXITCODE -ne 0) {
        throw "Offline Alembic SQL application failed"
    }

    & (Join-Path $PSScriptRoot "verify-wave0-db.ps1") `
        -DatabaseUrl $OfflineDatabaseUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Offline Wave 0 PostgreSQL postcheck failed"
    }

    Write-Output "EPHEMERAL_POSTGRES_WAVE0_OK"
}
finally {
    if ($ClusterStarted) {
        & $PgCtlExe --pgdata=$DataDirectory stop --mode=fast --wait
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to stop the ephemeral PostgreSQL cluster"
        }
        $ClusterStarted = $false
        Start-Sleep -Seconds 1
    }

    $ResolvedClusterRoot = [System.IO.Path]::GetFullPath($ClusterRoot)
    if (
        $ResolvedClusterRoot.StartsWith(
            $AllowedTempPrefix,
            [StringComparison]::OrdinalIgnoreCase
        ) -and
        (Split-Path -Leaf $ResolvedClusterRoot).StartsWith(
            "sswcenter-wave0-pg-",
            [StringComparison]::Ordinal
        ) -and
        (Test-Path -LiteralPath $ResolvedClusterRoot)
    ) {
        $Removed = $false
        for ($Attempt = 1; $Attempt -le 3 -and -not $Removed; $Attempt++) {
            try {
                [System.IO.Directory]::Delete($ResolvedClusterRoot, $true)
                $Removed = $true
            }
            catch {
                if ($Attempt -eq 3) {
                    throw
                }
                Start-Sleep -Seconds $Attempt
            }
        }
        if (-not $Removed -or (Test-Path -LiteralPath $ResolvedClusterRoot)) {
            throw "Unable to remove the ephemeral PostgreSQL cluster"
        }
    }
}
