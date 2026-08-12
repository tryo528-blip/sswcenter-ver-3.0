param(
    [Parameter(Mandatory = $true)]
    [string]$BackupDirectory,

    [Parameter(Mandatory = $true)]
    [string]$AdminDatabaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$ReviewDatabaseName,

    [Parameter(Mandatory = $true)]
    [string]$ReviewDataRoot,

    [switch]$KeepReviewArtifacts
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "PostgresTools.psm1") -Force

$Connection = ConvertFrom-SswPostgresUrl -DatabaseUrl $AdminDatabaseUrl
if ($Connection.Database -ne "postgres") {
    throw "Restore drill administration URL must target the postgres maintenance database"
}
if ($ReviewDatabaseName -notmatch '^[a-zA-Z][a-zA-Z0-9_]*_review$') {
    throw "Restore drill target name must be a simple identifier ending in _review"
}
if ($ReviewDatabaseName -in @("postgres", "template0", "template1")) {
    throw "Restore drill refuses PostgreSQL maintenance databases"
}
if (-not [System.IO.Path]::IsPathRooted($ReviewDataRoot)) {
    throw "Restore drill data root must be an absolute path"
}
$ResolvedReviewDataRoot = [System.IO.Path]::GetFullPath($ReviewDataRoot)
if (-not (Split-Path -Leaf $ResolvedReviewDataRoot).StartsWith(
    "sswcenter-restore-review-",
    [StringComparison]::Ordinal
)) {
    throw "Restore drill data root name must start with sswcenter-restore-review-"
}
if (Test-Path -LiteralPath $ResolvedReviewDataRoot) {
    throw "Restore drill data root already exists; refusing overwrite"
}

$ResolvedBackupDirectory = [System.IO.Path]::GetFullPath($BackupDirectory)
$ManifestFile = Join-Path $ResolvedBackupDirectory "manifest.json"
if (-not (Test-Path -LiteralPath $ManifestFile -PathType Leaf)) {
    throw "Backup manifest is missing"
}
$Manifest = Get-Content -LiteralPath $ManifestFile -Raw | ConvertFrom-Json
$ManifestRevision = [string]$Manifest.alembic_revision
$SupportedRevisions = @(
    "20260724_0002",
    "20260726_0003_w1a_staff",
    "20260727_0004_w1a_staff_qualifications",
    "20260728_0005_w1a_staff_training",
    "20260728_0006_w1a_staff_health_check",
    "20260728_0007_w1a_staff_quarterly_consultation",
    "20260728_0008_w1a_staff_legacy_mapping",
    "20260730_0009_w1b_recipient",
    "20260730_0010_w1c_certification_ledgers",
    "20260730_0011_w1d_recipient_contract",
    "20260801_0012_w1e_care_assignment",
    "20260802_0013_staff_continuing_education",
    "20260803_0014_recipient_plan_notification",
    "20260806_0015_recipient_status_tag",
    "20260808_0016_recipient_payer_guardian",
    "20260808_0017_recipient_guardian_email"
)
if ($SupportedRevisions -notcontains $ManifestRevision) {
    throw "Unsupported backup Alembic revision: $ManifestRevision"
}
$DumpFile = [System.IO.Path]::GetFullPath(
    (Join-Path $ResolvedBackupDirectory $Manifest.dump_file)
)
if (-not $DumpFile.StartsWith(
    $ResolvedBackupDirectory + [System.IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Backup manifest dump path escaped the backup directory"
}
if (-not (Test-Path -LiteralPath $DumpFile -PathType Leaf)) {
    throw "Backup dump file is missing"
}
$ActualHash = (Get-FileHash -LiteralPath $DumpFile -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualHash -ne $Manifest.dump_sha256) {
    throw "Backup SHA256 verification failed"
}
$BundleHashFile = Join-Path $ResolvedBackupDirectory "bundle.sha256"
if (-not (Test-Path -LiteralPath $BundleHashFile -PathType Leaf)) {
    throw "Backup bundle SHA256 list is missing"
}
foreach ($HashLine in Get-Content -LiteralPath $BundleHashFile) {
    if ($HashLine -notmatch '^([0-9a-f]{64}) \*(.+)$') {
        throw "Backup bundle SHA256 list is malformed"
    }
    $ExpectedBundleHash = $Matches[1]
    $RelativeBundlePath = $Matches[2]
    $BundleFile = [System.IO.Path]::GetFullPath(
        (Join-Path $ResolvedBackupDirectory $RelativeBundlePath)
    )
    if (-not $BundleFile.StartsWith(
        $ResolvedBackupDirectory + [System.IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Backup bundle SHA256 path escaped the backup directory"
    }
    if (-not (Test-Path -LiteralPath $BundleFile -PathType Leaf)) {
        throw "Backup bundle file is missing: $RelativeBundlePath"
    }
    $ActualBundleHash = (
        Get-FileHash -LiteralPath $BundleFile -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($ActualBundleHash -ne $ExpectedBundleHash) {
        throw "Backup bundle SHA256 verification failed: $RelativeBundlePath"
    }
}

$PsqlExe = Get-SswPostgresExecutable -Name "psql.exe"
$CreateDbExe = Get-SswPostgresExecutable -Name "createdb.exe"
$DropDbExe = Get-SswPostgresExecutable -Name "dropdb.exe"
$PgRestoreExe = Get-SswPostgresExecutable -Name "pg_restore.exe"
$CreatedReviewDatabase = $false
$CreatedReviewDataRoot = $false

try {
    Invoke-WithPgPassword -Password $Connection.Password -Action {
        $Exists = & $PsqlExe `
            --host=$($Connection.Host) `
            --port=$($Connection.Port) `
            --username=$($Connection.User) `
            --dbname=postgres `
            --no-password `
            --tuples-only `
            --no-align `
            --command="SELECT 1 FROM pg_database WHERE datname = '$ReviewDatabaseName'"
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to inspect restore drill target"
        }
        if (($Exists -join "").Trim() -eq "1") {
            throw "Restore drill target already exists; refusing overwrite"
        }

        & $CreateDbExe `
            --host=$($Connection.Host) `
            --port=$($Connection.Port) `
            --username=$($Connection.User) `
            --no-password `
            $ReviewDatabaseName
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to create restore drill database"
        }
        $script:CreatedReviewDatabase = $true

        & $PgRestoreExe `
            --host=$($Connection.Host) `
            --port=$($Connection.Port) `
            --username=$($Connection.User) `
            --dbname=$ReviewDatabaseName `
            --no-password `
            --exit-on-error `
            $DumpFile
        if ($LASTEXITCODE -ne 0) {
            throw "pg_restore failed"
        }
    }

    $EscapedUser = [Uri]::EscapeDataString($Connection.User)
    $EscapedPassword = [Uri]::EscapeDataString($Connection.Password)
    $Credentials = if ($Connection.Password) {
        "${EscapedUser}:${EscapedPassword}"
    }
    else {
        $EscapedUser
    }
    $ReviewUrl = (
        "postgresql+psycopg://{0}@{1}:{2}/{3}" -f
        $Credentials,
        $Connection.Host,
        $Connection.Port,
        $ReviewDatabaseName
    )
    if ($ManifestRevision -eq "20260724_0002") {
        & (Join-Path $PSScriptRoot "verify-wave0-db.ps1") -DatabaseUrl $ReviewUrl
        if ($LASTEXITCODE -ne 0) {
            throw "Restored Wave 0 database postcheck failed"
        }
    }
    elseif ($ManifestRevision -in @(
        "20260726_0003_w1a_staff",
        "20260727_0004_w1a_staff_qualifications",
        "20260728_0005_w1a_staff_training",
        "20260728_0006_w1a_staff_health_check",
        "20260728_0007_w1a_staff_quarterly_consultation",
        "20260728_0008_w1a_staff_legacy_mapping",
        "20260730_0009_w1b_recipient",
        "20260730_0010_w1c_certification_ledgers",
        "20260730_0011_w1d_recipient_contract",
        "20260801_0012_w1e_care_assignment",
        "20260802_0013_staff_continuing_education",
        "20260803_0014_recipient_plan_notification",
        "20260806_0015_recipient_status_tag",
        "20260808_0016_recipient_payer_guardian",
        "20260808_0017_recipient_guardian_email"
    )) {
        $PostcheckOutput = @(
            & (Join-Path $PSScriptRoot "verify-w1a-vs1-db.ps1") -DatabaseUrl $ReviewUrl
        )
        $PostcheckExitCode = $LASTEXITCODE
        $PostcheckOutput | Write-Output
        if ($PostcheckExitCode -ne 0) {
            throw "Restored W1A database postcheck failed"
        }
        if (
            $ManifestRevision -eq "20260727_0004_w1a_staff_qualifications" -and
            $PostcheckOutput -notcontains "W1A_VS2_DB_POSTCHECK_OK"
        ) {
            throw "Restored W1A-VS2 database postcheck marker is missing"
        }
        if (
            $ManifestRevision -eq "20260728_0005_w1a_staff_training" -and
            $PostcheckOutput -notcontains "W1A_VS3_DB_POSTCHECK_OK"
        ) {
            throw "Restored W1A-VS3 database postcheck marker is missing"
        }
        if (
            $ManifestRevision -eq "20260728_0006_w1a_staff_health_check" -and
            $PostcheckOutput -notcontains "W1A_VS4_DB_POSTCHECK_OK"
        ) {
            throw "Restored W1A-VS4 database postcheck marker is missing"
        }
        if (
            $ManifestRevision -eq "20260728_0007_w1a_staff_quarterly_consultation" -and
            $PostcheckOutput -notcontains "W1A_VS5_DB_POSTCHECK_OK"
        ) {
            throw "Restored W1A-VS5 database postcheck marker is missing"
        }
        if (
            $ManifestRevision -eq "20260728_0008_w1a_staff_legacy_mapping" -and
            $PostcheckOutput -notcontains "W1A_VS6_DB_POSTCHECK_OK"
        ) {
            throw "Restored W1A-VS6 database postcheck marker is missing"
        }
        if (
            $ManifestRevision -eq "20260730_0009_w1b_recipient" -and
            $PostcheckOutput -notcontains "W1B_DB_POSTCHECK_OK"
        ) {
            throw "Restored W1B database postcheck marker is missing"
        }
        if (
            $ManifestRevision -eq "20260730_0010_w1c_certification_ledgers" -and
            $PostcheckOutput -notcontains "W1C_DB_POSTCHECK_OK"
        ) {
            throw "Restored W1C database postcheck marker is missing"
        }
        if (
            $ManifestRevision -eq "20260730_0011_w1d_recipient_contract" -and
            $PostcheckOutput -notcontains "W1D_DB_POSTCHECK_OK"
        ) {
            throw "Restored W1D database postcheck marker is missing"
        }
        if (
            $ManifestRevision -eq "20260801_0012_w1e_care_assignment" -and
            $PostcheckOutput -notcontains "W1E_DB_POSTCHECK_OK"
        ) {
            throw "Restored W1E database postcheck marker is missing"
        }
        if (
            $ManifestRevision -eq "20260802_0013_staff_continuing_education" -and
            $PostcheckOutput -notcontains "STAFF_CONTINUING_EDUCATION_DB_POSTCHECK_OK"
        ) {
            throw "Restored continuing-education database postcheck marker is missing"
        }
        if (
            $ManifestRevision -eq "20260803_0014_recipient_plan_notification" -and
            $PostcheckOutput -notcontains "RECIPIENT_PLAN_NOTIFICATION_DB_POSTCHECK_OK"
        ) {
            throw "Restored recipient-plan-notification database postcheck marker is missing"
        }
        if (
            $ManifestRevision -eq "20260806_0015_recipient_status_tag" -and
            $PostcheckOutput -notcontains "RECIPIENT_STATUS_TAG_DB_POSTCHECK_OK"
        ) {
            throw "Restored recipient-status-tag database postcheck marker is missing"
        }
        if (
            $ManifestRevision -eq "20260808_0016_recipient_payer_guardian" -and
            $PostcheckOutput -notcontains "RECIPIENT_PAYER_GUARDIAN_DB_POSTCHECK_OK"
        ) {
            throw "Restored recipient-payer-guardian database postcheck marker is missing"
        }
        if (
            $ManifestRevision -eq "20260808_0017_recipient_guardian_email" -and
            $PostcheckOutput -notcontains "RECIPIENT_GUARDIAN_EMAIL_DB_POSTCHECK_OK"
        ) {
            throw "Restored recipient-guardian-email database postcheck marker is missing"
        }
    }

    New-Item -ItemType Directory -Path $ResolvedReviewDataRoot | Out-Null
    $CreatedReviewDataRoot = $true
    foreach ($FileEntry in @($Manifest.files)) {
        $RelativeFilePath = [string]$FileEntry.relative_path
        $BackupDataFile = [System.IO.Path]::GetFullPath(
            (Join-Path (Join-Path $ResolvedBackupDirectory "data") $RelativeFilePath)
        )
        $ExpectedDataPrefix = (
            [System.IO.Path]::GetFullPath((Join-Path $ResolvedBackupDirectory "data")) +
            [System.IO.Path]::DirectorySeparatorChar
        )
        if (-not $BackupDataFile.StartsWith(
            $ExpectedDataPrefix,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Backup data path escaped the data directory"
        }
        $RestoredDataFile = [System.IO.Path]::GetFullPath(
            (Join-Path $ResolvedReviewDataRoot $RelativeFilePath)
        )
        if (-not $RestoredDataFile.StartsWith(
            $ResolvedReviewDataRoot + [System.IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Restore data path escaped the review data root"
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $RestoredDataFile) -Force |
            Out-Null
        Copy-Item -LiteralPath $BackupDataFile -Destination $RestoredDataFile
        $RestoredHash = (
            Get-FileHash -LiteralPath $RestoredDataFile -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        if ($RestoredHash -ne $FileEntry.sha256) {
            throw "Restored file SHA256 verification failed: $RelativeFilePath"
        }
    }

    Write-Output "RESTORE_DRILL_OK $ReviewDatabaseName"
}
finally {
    if ($CreatedReviewDatabase -and -not $KeepReviewArtifacts) {
        Invoke-WithPgPassword -Password $Connection.Password -Action {
            & $DropDbExe `
                --host=$($Connection.Host) `
                --port=$($Connection.Port) `
                --username=$($Connection.User) `
                --no-password `
                --if-exists `
                $ReviewDatabaseName
            if ($LASTEXITCODE -ne 0) {
                throw "Unable to remove restore drill database"
            }
        }
    }
    if ($CreatedReviewDataRoot -and -not $KeepReviewArtifacts) {
        $CheckedReviewDataRoot = [System.IO.Path]::GetFullPath($ResolvedReviewDataRoot)
        if (
            (Split-Path -Leaf $CheckedReviewDataRoot).StartsWith(
                "sswcenter-restore-review-",
                [StringComparison]::Ordinal
            ) -and
            (Test-Path -LiteralPath $CheckedReviewDataRoot)
        ) {
            Remove-Item -LiteralPath $CheckedReviewDataRoot -Recurse -Force
        }
    }
}
