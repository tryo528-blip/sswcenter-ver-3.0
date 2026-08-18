param(
    [Parameter(Mandatory = $true)]
    [string]$BackupDirectory,

    [Parameter(Mandatory = $true)]
    [string]$AdminDatabaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$ReviewDatabaseName,

    [Parameter(Mandatory = $true)]
    [string]$ReviewDataRoot,

    [switch]$KeepReviewArtifacts,

    [Parameter(Mandatory = $false)]
    [string]$PythonExe
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "PostgresTools.psm1") -Force

$ActiveRevision = "20260818_0029_w3_persistent_apply_workspace"
$ActiveMarker = "SSWCENTER_CURRENT_0029_DB_POSTCHECK_OK"
$CurrentHeadMarker = "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK"
$Historical0025Revision = "20260813_0025_w1_relationship_lock_contract_correction"
$Historical0025DirectMarker = "SSWCENTER_CURRENT_0025_DB_POSTCHECK_OK"
$Historical0026Revision = "20260814_0026_w1e_care_assignment_family_relationship_lock"
$Historical0026DirectMarker = "SSWCENTER_CURRENT_0026_DB_POSTCHECK_OK"
$Historical0027Revision = "20260817_0027_w2_official_card_assignee_and_plan_replacement"
$Historical0027DirectMarker = "SSWCENTER_CURRENT_0027_DB_POSTCHECK_OK"
$Historical0028Revision = "20260817_0028_w3_source_intake_foundation"
$Historical0028DirectMarker = "SSWCENTER_CURRENT_0028_DB_POSTCHECK_OK"

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
    "20260808_0017_recipient_guardian_email",
    "20260809_0018_w2_service_plan_notice",
    "20260812_0019_r0_w2_read_only",
    $Historical0025Revision,
    $Historical0026Revision,
    $Historical0027Revision,
    $Historical0028Revision,
    $ActiveRevision
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
        $Historical0025Revision,
        $Historical0026Revision,
        $Historical0027Revision,
        $Historical0028Revision,
        $ActiveRevision
    )) {
        $ResolvedPythonExe = if ($PSBoundParameters.ContainsKey("PythonExe")) {
            [System.IO.Path]::GetFullPath($PythonExe)
        }
        else {
            $BackendRoot = [System.IO.Path]::GetFullPath(
                (Join-Path (Split-Path -Parent $PSScriptRoot) "backend")
            )
            if ([System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT) {
                [System.IO.Path]::GetFullPath(
                    (Join-Path $BackendRoot ".venv\Scripts\python.exe")
                )
            }
            else {
                [System.IO.Path]::GetFullPath(
                    (Join-Path $BackendRoot ".venv/bin/python")
                )
            }
        }
        if (-not (Test-Path -LiteralPath $ResolvedPythonExe -PathType Leaf)) {
            throw "Current restore requires an existing Python executable"
        }

        New-Item -ItemType Directory -Path $ResolvedReviewDataRoot | Out-Null
        $CreatedReviewDataRoot = $true
        $EnvironmentNames = @(
            "SSWCENTER_ENVIRONMENT",
            "SSWCENTER_DATABASE_URL",
            "SSWCENTER_DATA_ROOT",
            "PYTHONDONTWRITEBYTECODE"
        )
        $PreviousEnvironment = @{}
        foreach ($EnvironmentName in $EnvironmentNames) {
            $PreviousEnvironment[$EnvironmentName] = [Environment]::GetEnvironmentVariable(
                $EnvironmentName,
                "Process"
            )
        }
        $PostcheckOutput = @()
        $PostcheckExitCode = 1
        Push-Location (Join-Path (Split-Path -Parent $PSScriptRoot) "backend")
        try {
            $env:SSWCENTER_ENVIRONMENT = "test"
            $env:SSWCENTER_DATABASE_URL = $ReviewUrl
            $env:SSWCENTER_DATA_ROOT = $ResolvedReviewDataRoot
            $env:PYTHONDONTWRITEBYTECODE = "1"
            if ($ManifestRevision -eq $ActiveRevision) {
                # Dispatch is reserved for the active 0029 head; it is the
                # only restore branch allowed to emit the current-head marker.
                $PostcheckOutput = @(& $ResolvedPythonExe -B -m app.db.postcheck_dispatch)
            }
            elseif ($ManifestRevision -eq $Historical0028Revision) {
                # 0028 remains a direct historical verifier after 0029 becomes current.
                $PostcheckOutput = @(& $ResolvedPythonExe -B -m app.db.postcheck_current_0028)
            }
            elseif ($ManifestRevision -eq $Historical0027Revision) {
                # Keep the W2 pinned restore proof independent of active-head
                # dispatch so it cannot masquerade as a 0029 current check.
                $PostcheckOutput = @(& $ResolvedPythonExe -B -m app.db.postcheck_current_0027)
            }
            elseif ($ManifestRevision -eq $Historical0026Revision) {
                # Keep the W1E pinned restore proof independent of active-head
                # dispatch so it cannot masquerade as a 0029 current check.
                $PostcheckOutput = @(& $ResolvedPythonExe -B -m app.db.postcheck_current_0026)
            }
            else {
                # 0025 is likewise a direct historical verifier, never a
                # current-head dispatch path.
                $PostcheckOutput = @(& $ResolvedPythonExe -B -m app.db.postcheck_current_0025)
            }
            $PostcheckExitCode = $LASTEXITCODE
        }
        finally {
            Pop-Location
            foreach ($EnvironmentName in $EnvironmentNames) {
                $PreviousValue = $PreviousEnvironment[$EnvironmentName]
                if ($null -eq $PreviousValue) {
                    Remove-Item -LiteralPath "Env:$EnvironmentName" -ErrorAction SilentlyContinue
                }
                else {
                    Set-Item -Path "Env:$EnvironmentName" -Value $PreviousValue
                }
            }
        }
        if ($PostcheckExitCode -ne 0) {
            throw "Restored revision-specific postcheck failed"
        }
        if ($ManifestRevision -eq $ActiveRevision) {
            if ($PostcheckOutput -notcontains $ActiveMarker) {
                throw "Restored active 0029 postcheck marker is missing"
            }
            if ($PostcheckOutput -notcontains $CurrentHeadMarker) {
                throw "Restored active current-head postcheck marker is missing"
            }
        }
        elseif ($ManifestRevision -eq $Historical0028Revision) {
            if ($PostcheckOutput -notcontains $Historical0028DirectMarker) {
                throw "Restored historical 0028 direct postcheck marker is missing"
            }
            if ($PostcheckOutput -contains $CurrentHeadMarker) {
                throw "Historical 0028 restore emitted a current-head marker"
            }
        }
        elseif ($ManifestRevision -eq $Historical0027Revision) {
            if ($PostcheckOutput -notcontains $Historical0027DirectMarker) {
                throw "Restored historical 0027 direct postcheck marker is missing"
            }
            if ($PostcheckOutput -contains $CurrentHeadMarker) {
                throw "Historical 0027 restore emitted a current-head marker"
            }
        }
        elseif ($ManifestRevision -eq $Historical0026Revision) {
            if ($PostcheckOutput -notcontains $Historical0026DirectMarker) {
                throw "Restored historical 0026 direct postcheck marker is missing"
            }
            if ($PostcheckOutput -contains $CurrentHeadMarker) {
                throw "Historical 0026 restore emitted a current-head marker"
            }
        }
        else {
            if ($PostcheckOutput -notcontains $Historical0025DirectMarker) {
                throw "Restored historical 0025 direct postcheck marker is missing"
            }
            if ($PostcheckOutput -contains $CurrentHeadMarker) {
                throw "Historical 0025 restore emitted a current-head marker"
            }
        }
        # Expose the already-verified revision-specific marker to the caller.
        # The W2 harness must independently prove its restored 0027 catalog
        # stays historical rather than accepting only the generic final token.
        $PostcheckOutput | Write-Output
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
        "20260808_0017_recipient_guardian_email",
        "20260809_0018_w2_service_plan_notice",
        "20260812_0019_r0_w2_read_only"
    )) {
        $VerifyArgs = @{
            DatabaseUrl = $ReviewUrl
        }
        if ($PSBoundParameters.ContainsKey("PythonExe")) {
            $VerifyArgs["PythonExe"] = $PythonExe
        }
        $PostcheckOutput = @(
            & (Join-Path $PSScriptRoot "verify-w1a-vs1-db.ps1") @VerifyArgs
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
        if (
            $ManifestRevision -eq "20260809_0018_w2_service_plan_notice" -and
            $PostcheckOutput -notcontains "W2_SERVICE_PLAN_NOTICE_DB_POSTCHECK_OK"
        ) {
            throw "Restored W2 service-plan-notice database postcheck marker is missing"
        }
        if (
            $ManifestRevision -eq "20260812_0019_r0_w2_read_only" -and
            $PostcheckOutput -notcontains "R0_W2_READ_ONLY_DB_POSTCHECK_OK"
        ) {
            throw "Restored R0 W2 read-only database postcheck marker is missing"
        }
    }

    if (-not $CreatedReviewDataRoot) {
        New-Item -ItemType Directory -Path $ResolvedReviewDataRoot | Out-Null
        $CreatedReviewDataRoot = $true
    }
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
