param(
    [switch]$RedOnly,
    [switch]$E2ERedOnly,
    [int]$Port = 55433,
    [string]$ArtifactOutputPath = $null,
    [switch]$TestArtifactFailure,
    [switch]$TestStopFailure
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

# Verify fixed service ports
$ExistingListener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($ExistingListener) {
    throw "Port $Port is already in use"
}

$AllowedTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$ReviewArtifactRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $WorkspaceRoot "review\artifacts")
)
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$FrontendRoot = Join-Path $WorkspaceRoot "frontend"
$RuntimeDataRoot = $null
$ArtifactRoot = $null
$W1aArtifactEntries = @()

function Test-W1aPathUnderRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Candidate,
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $NormalizedRoot = $Root.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $Candidate.StartsWith(
        $NormalizedRoot + [System.IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Resolve-W1aArtifactOutputPath {
    param(
        [Parameter(Mandatory = $false)]
        [AllowNull()]
        [string]$RequestedPath
    )

    if ([string]::IsNullOrWhiteSpace($RequestedPath)) {
        return $null
    }
    if (-not [System.IO.Path]::IsPathRooted($RequestedPath)) {
        throw "W1A_ARTIFACT_PATH_REJECTED: ArtifactOutputPath must be an absolute path under a dedicated temp or review boundary"
    }

    try {
        $Candidate = [System.IO.Path]::GetFullPath($RequestedPath)
    }
    catch {
        throw "W1A_ARTIFACT_PATH_REJECTED: ArtifactOutputPath is not a valid path"
    }
    $Candidate = $Candidate.TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $NormalizedReviewRoot = $ReviewArtifactRoot.TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $NormalizedTempRoot = $AllowedTempRoot.TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $IsUnderReviewBoundary = Test-W1aPathUnderRoot -Candidate $Candidate -Root $NormalizedReviewRoot
    $IsUnderTempBoundary = Test-W1aPathUnderRoot -Candidate $Candidate -Root $NormalizedTempRoot

    # The repository root, HOME, the shared temp root, and review/artifacts itself
    # are broad boundaries. A caller must provide a dedicated child directory.
    $TempRelative = $null
    if ($IsUnderTempBoundary) {
        $TempRelative = $Candidate.Substring($NormalizedTempRoot.Length).TrimStart(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
        $TempBoundaryName = ($TempRelative -split '[\\/]')[0]
        $IsUnderTempBoundary = $TempBoundaryName.StartsWith(
            "sswcenter-w1a-artifacts-",
            [StringComparison]::OrdinalIgnoreCase
        )
    }
    $IsDedicatedReviewChild = $IsUnderReviewBoundary -and ($Candidate -ne $NormalizedReviewRoot)
    if (-not ($IsUnderTempBoundary -or $IsDedicatedReviewChild)) {
        throw "W1A_ARTIFACT_PATH_REJECTED: ArtifactOutputPath must be a dedicated temp child named sswcenter-w1a-artifacts-* or a child of repo review\artifacts"
    }

    # Refuse existing junctions/symlinks in the requested output path so a
    # permitted-looking path cannot redirect artifacts outside the boundary.
    $BoundaryRoot = if ($IsUnderTempBoundary) { $NormalizedTempRoot } else { $NormalizedReviewRoot }
    $PathToCheck = $Candidate
    while ($true) {
        if (Test-Path -LiteralPath $PathToCheck) {
            $ExistingItem = Get-Item -LiteralPath $PathToCheck -Force
            if (($ExistingItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "W1A_ARTIFACT_PATH_REJECTED: ArtifactOutputPath cannot contain a junction or symlink"
            }
        }
        if ($PathToCheck -eq $BoundaryRoot) {
            break
        }
        $ParentPath = Split-Path -Parent $PathToCheck
        if ([string]::IsNullOrWhiteSpace($ParentPath) -or ($ParentPath -eq $PathToCheck)) {
            throw "W1A_ARTIFACT_PATH_REJECTED: ArtifactOutputPath boundary could not be resolved"
        }
        $PathToCheck = $ParentPath
    }

    [System.IO.Directory]::CreateDirectory($Candidate) | Out-Null
    return $Candidate
}

function Add-W1aArtifactFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,
        [Parameter(Mandatory = $true)]
        [string]$DestinationRelativePath,
        [Parameter(Mandatory = $true)]
        [string]$ArtifactType
    )

    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        return
    }
    $DestinationPath = Join-Path $ArtifactRoot $DestinationRelativePath
    $DestinationDirectory = Split-Path -Parent $DestinationPath
    [System.IO.Directory]::CreateDirectory($DestinationDirectory) | Out-Null
    Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
    $DestinationItem = Get-Item -LiteralPath $DestinationPath -Force
    $script:W1aArtifactEntries += [pscustomobject]@{
        type = $ArtifactType
        path = $DestinationRelativePath.Replace([System.IO.Path]::DirectorySeparatorChar, '/')
        bytes = [int64]$DestinationItem.Length
        sha256 = (Get-FileHash -LiteralPath $DestinationPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Add-W1aArtifactTree {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot,
        [Parameter(Mandatory = $true)]
        [string]$DestinationRelativeRoot,
        [Parameter(Mandatory = $true)]
        [string]$ArtifactType
    )

    if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
        return
    }
    $SourceRootFull = [System.IO.Path]::GetFullPath($SourceRoot).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    foreach ($SourceItem in Get-ChildItem -LiteralPath $SourceRootFull -File -Recurse -Force) {
        $RelativePath = $SourceItem.FullName.Substring($SourceRootFull.Length).TrimStart(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
        $DestinationRelativePath = Join-Path $DestinationRelativeRoot $RelativePath
        $EntryType = $ArtifactType
        if ($SourceItem.Extension -ieq '.gz') {
            $EntryType = 'runtime-rotated-gzip'
        }
        Add-W1aArtifactFile `
            -SourcePath $SourceItem.FullName `
            -DestinationRelativePath $DestinationRelativePath `
            -ArtifactType $EntryType
    }
}

function Remove-W1aManifestState {
    if ($null -eq $ArtifactRoot) {
        return
    }
    $ManifestPath = Join-Path $ArtifactRoot "manifest.json"
    $ManifestTempPath = Join-Path $ArtifactRoot ".w1a-manifest.tmp.json"
    foreach ($ManifestArtifactPath in @($ManifestPath, $ManifestTempPath)) {
        if (Test-Path -LiteralPath $ManifestArtifactPath -PathType Leaf) {
            Remove-Item -LiteralPath $ManifestArtifactPath -Force -ErrorAction Stop
        }
    }
}

function Save-W1aArtifacts {
    if ($null -eq $ArtifactRoot) {
        return
    }

    $ManifestPath = Join-Path $ArtifactRoot "manifest.json"
    $ManifestTempPath = Join-Path $ArtifactRoot ".w1a-manifest.tmp.json"
    $ManifestPublished = $false
    try {
        # Invalidate only harness-owned manifest state before collecting a new
        # run, so a reused output root cannot retain a stale success marker.
        Remove-W1aManifestState

        # Copy only after child processes and PostgreSQL have stopped, while the
        # ephemeral cluster and its runtime data still exist.
        Add-W1aArtifactFile `
            -SourcePath $LogFile `
            -DestinationRelativePath "postgres\postgres.log" `
            -ArtifactType 'postgresql-log'
        if ($TestArtifactFailure) {
            throw "W1A_TEST_ARTIFACT_FAILURE"
        }
        if ($null -ne $RuntimeDataRoot) {
            Add-W1aArtifactTree `
                -SourceRoot (Join-Path $RuntimeDataRoot "logs") `
                -DestinationRelativeRoot "backend\logs" `
                -ArtifactType 'runtime-log'
        }
        Add-W1aArtifactTree `
            -SourceRoot (Join-Path $FrontendRoot "test-results") `
            -DestinationRelativeRoot "playwright\test-results" `
            -ArtifactType 'playwright-output'
        Add-W1aArtifactTree `
            -SourceRoot (Join-Path $FrontendRoot "playwright-report") `
            -DestinationRelativeRoot "playwright\playwright-report" `
            -ArtifactType 'playwright-output'

        $Manifest = [ordered]@{
            schema_version = 1
            artifact_contract = 'W1A_POSTGRES_ARTIFACTS_V1'
            files = @($script:W1aArtifactEntries)
            counts = [ordered]@{
                postgresql_log = @($script:W1aArtifactEntries | Where-Object { $_.type -eq 'postgresql-log' }).Count
                app_log = @($script:W1aArtifactEntries | Where-Object { $_.path -eq 'backend/logs/app.log' }).Count
                error_log = @($script:W1aArtifactEntries | Where-Object { $_.path -eq 'backend/logs/error.log' }).Count
                access_log = @($script:W1aArtifactEntries | Where-Object { $_.path -eq 'backend/logs/access.log' }).Count
                runtime_log = @($script:W1aArtifactEntries | Where-Object { $_.type -eq 'runtime-log' }).Count
                rotated_gzip = @($script:W1aArtifactEntries | Where-Object { $_.type -eq 'runtime-rotated-gzip' }).Count
                playwright_output = @($script:W1aArtifactEntries | Where-Object { $_.type -eq 'playwright-output' }).Count
            }
        }
        $Manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ManifestTempPath -Encoding UTF8
        [System.IO.File]::Move($ManifestTempPath, $ManifestPath)
        $ManifestPublished = $true
        Write-Output (
            "W1A_POSTGRES_ARTIFACTS_PRESERVED " +
            "files={0} postgresql_log={1} app_log={2} error_log={3} access_log={4} runtime_log={5} rotated_gzip={6} playwright_output={7}" -f
            ($Manifest.counts.postgresql_log +
            $Manifest.counts.runtime_log +
            $Manifest.counts.rotated_gzip +
            $Manifest.counts.playwright_output),
            $Manifest.counts.postgresql_log,
            $Manifest.counts.app_log,
            $Manifest.counts.error_log,
            $Manifest.counts.access_log,
            $Manifest.counts.runtime_log,
            $Manifest.counts.rotated_gzip,
            $Manifest.counts.playwright_output
        )
    }
    catch {
        $ManifestError = $_
        throw $ManifestError.Exception
    }
    finally {
        if (-not $ManifestPublished -and (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
            Remove-Item -LiteralPath $ManifestPath -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $ManifestTempPath -PathType Leaf) {
            Remove-Item -LiteralPath $ManifestTempPath -Force -ErrorAction SilentlyContinue
        }
    }
}

$ArtifactRoot = Resolve-W1aArtifactOutputPath -RequestedPath $ArtifactOutputPath
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $AllowedTempRoot ("sswcenter-w1a-pg-" + [Guid]::NewGuid().ToString("N")))
)
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (-not $ClusterRoot.StartsWith($AllowedTempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Ephemeral cluster path escaped the temporary directory"
}
if (-not $ClusterLeaf.StartsWith("sswcenter-w1a-pg-", [StringComparison]::Ordinal)) {
    throw "Unexpected ephemeral cluster directory name"
}
$DataDirectory = Join-Path $ClusterRoot "data"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$DatabaseName = "sswcenter_w1a_test"
$UpgradeDatabaseName = "sswcenter_w1a_upgrade_test"
$OfflineDatabaseName = "sswcenter_w1a_offline_test"
$OfflineSqlFile = Join-Path $ClusterRoot "w1a-offline.sql"
$OfflineErrorFile = Join-Path $ClusterRoot "w1a-offline.stderr.log"

$ClusterStarted = $false
$BackendProcess = $null

function New-W1aDatabase {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if ($Name -notmatch '^[a-z][a-z0-9_]*_test$') {
        throw "Ephemeral database name must be a simple identifier ending in _test"
    }
    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -d postgres `
        -c "CREATE DATABASE $Name OWNER erp_owner;" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create ephemeral database: $Name"
    }
}

function Set-W1aDatabaseContext {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $env:SSWCENTER_DATABASE_URL = (
        "postgresql+psycopg://erp_owner:test_owner_pw@127.0.0.1:{0}/{1}" -f
        $Port,
        $Name
    )
    $env:SSWCENTER_APP_DATABASE_URL = (
        "postgresql+psycopg://erp_app:test_app_pw@127.0.0.1:{0}/{1}" -f
        $Port,
        $Name
    )
    $env:SSWCENTER_BACKUP_DATABASE_URL = (
        "postgresql+psycopg://erp_backup:test_backup_pw@127.0.0.1:{0}/{1}" -f
        $Port,
        $Name
    )
}

function Get-Wave0StaffFingerprint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $FingerprintSql = @"
SELECT COALESCE(
    string_agg(
        id::text || ':' ||
        md5(
            CASE
                WHEN display_name IS NULL THEN '<NULL>'
                ELSE '<VALUE>' || display_name
            END ||
            chr(31) ||
            CASE
                WHEN memo IS NULL THEN '<NULL>'
                ELSE '<VALUE>' || memo
            END
        ),
        ',' ORDER BY id
    ),
    '<EMPTY>'
)
FROM erp.staff;
"@
    $Fingerprint = & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U erp_owner `
        -d $Name `
        -tAc $FingerprintSql
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to fingerprint Wave 0 staff values"
    }
    return ($Fingerprint -join "").Trim()
}

function Get-Wave0AclFingerprint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $AclSql = @"
WITH acl_objects AS (
    SELECT
        'schema:' || n.nspname AS object_key,
        CASE WHEN n.nspacl IS NULL THEN 'default' ELSE 'explicit' END AS acl_source,
        CASE
            WHEN n.nspacl IS NULL THEN acldefault('n', n.nspowner)
            ELSE n.nspacl
        END AS acl_value
    FROM pg_namespace n
    WHERE n.nspname = 'erp'
    UNION ALL
    SELECT
        'table:' || n.nspname || '.' || c.relname AS object_key,
        CASE WHEN c.relacl IS NULL THEN 'default' ELSE 'explicit' END AS acl_source,
        CASE
            WHEN c.relacl IS NULL THEN acldefault('r', c.relowner)
            ELSE c.relacl
        END AS acl_value
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'erp'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
    UNION ALL
    SELECT
        'sequence:' || n.nspname || '.' || c.relname AS object_key,
        CASE WHEN c.relacl IS NULL THEN 'default' ELSE 'explicit' END AS acl_source,
        CASE
            WHEN c.relacl IS NULL THEN acldefault('s', c.relowner)
            ELSE c.relacl
        END AS acl_value
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'erp'
      AND c.relkind = 'S'
    UNION ALL
    SELECT
        'column:' || n.nspname || '.' || c.relname || '.' || a.attname AS object_key,
        CASE WHEN a.attacl IS NULL THEN 'column-null' ELSE 'explicit' END AS acl_source,
        a.attacl AS acl_value
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'erp'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
      AND a.attnum > 0
      AND NOT a.attisdropped
), canonical_objects AS (
    SELECT
        object_key,
        CASE
            WHEN acl_source = 'column-null' THEN '<NULL>'
            ELSE COALESCE(
                (
                    SELECT string_agg(
                        grantee::text || ':' ||
                        privilege_type || ':' ||
                        is_grantable::text || ':' ||
                        grantor::text,
                        ',' ORDER BY grantee, privilege_type, is_grantable, grantor
                    )
                    FROM aclexplode(acl_value)
                ),
                '<EMPTY>'
            )
        END AS acl_text
    FROM acl_objects
)
SELECT md5(
    COALESCE(
        string_agg(object_key || '=' || acl_text, '|' ORDER BY object_key),
        '<EMPTY>'
    )
)
FROM canonical_objects;
"@
    $Fingerprint = & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U erp_owner `
        -d $Name `
        -tAc $AclSql
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to fingerprint Wave 0 schema/table/sequence ACLs"
    }
    return ($Fingerprint -join "").Trim()
}

function Invoke-Wave0AclProbeSql {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Sql
    )

    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U erp_owner `
        -d $Name `
        -c $Sql | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to execute ACL fingerprint probe"
    }
}

function Test-Wave0AclCanonicalization {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $ProbeTable = "erp.w1a_acl_fingerprint_probe"
    $ResetProbeSql = @"
DROP TABLE IF EXISTS $ProbeTable;
CREATE TABLE $ProbeTable (id integer, payload text);
"@
    try {
        Invoke-Wave0AclProbeSql -Name $Name -Sql $ResetProbeSql
        $NullFingerprint = Get-Wave0AclFingerprint -Name $Name
        Invoke-Wave0AclProbeSql -Name $Name `
            -Sql "GRANT ALL ON TABLE $ProbeTable TO erp_owner;"
        $OwnerDefaultFingerprint = Get-Wave0AclFingerprint -Name $Name
        if ($OwnerDefaultFingerprint -ne $NullFingerprint) {
            throw "F1_ACL_OWNER_DEFAULT_CANONICALIZATION_FAILURE"
        }

        $NegativeCases = @(
            @{
                Name = "PUBLIC_GRANTEE"
                Sql = "GRANT SELECT ON TABLE $ProbeTable TO PUBLIC;"
            },
            @{
                Name = "EXTERNAL_GRANTEE"
                Sql = "GRANT SELECT ON TABLE $ProbeTable TO erp_app;"
            },
            @{
                Name = "PRIVILEGE_BIT"
                Sql = "GRANT INSERT ON TABLE $ProbeTable TO erp_app;"
            },
            @{
                Name = "GRANT_OPTION"
                Sql = "GRANT ALL ON TABLE $ProbeTable TO erp_owner WITH GRANT OPTION;"
            },
            @{
                Name = "COLUMN_ACL"
                Sql = "GRANT SELECT (id) ON TABLE $ProbeTable TO erp_app;"
            }
        )
        foreach ($Case in $NegativeCases) {
            Invoke-Wave0AclProbeSql -Name $Name -Sql $ResetProbeSql
            $CaseBaseline = Get-Wave0AclFingerprint -Name $Name
            Invoke-Wave0AclProbeSql -Name $Name -Sql $Case.Sql
            $CaseFingerprint = Get-Wave0AclFingerprint -Name $Name
            if ($CaseFingerprint -eq $CaseBaseline) {
                throw "F1_ACL_NEGATIVE_NOT_DETECTED_$($Case.Name)"
            }
        }

        $GrantorSql = @"
SELECT (
    (
        SELECT min(grantor)
        FROM aclexplode(ARRAY['erp_owner=arwdDxt/erp_owner'::aclitem])
    ) <> (
        SELECT min(grantor)
        FROM aclexplode(ARRAY['erp_owner=arwdDxt/erp_app'::aclitem])
    )
)::text;
"@
        $GrantorResult = & $PsqlExe `
            -v ON_ERROR_STOP=1 `
            -h 127.0.0.1 `
            -p $Port `
            -U erp_owner `
            -d $Name `
            -tAc $GrantorSql
        if ($LASTEXITCODE -ne 0 -or ($GrantorResult -join "").Trim() -ne "true") {
            throw "F1_ACL_NEGATIVE_NOT_DETECTED_GRANTOR"
        }
        Write-Output "F1_ACL_CANONICALIZATION_NEGATIVE_OK"
    }
    finally {
        try {
            Invoke-Wave0AclProbeSql -Name $Name `
                -Sql "DROP TABLE IF EXISTS $ProbeTable;"
        }
        catch {}
    }
}

function Test-W1aObjectsAbsent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $AbsenceSql = @"
SELECT (
    to_regclass('erp.staff_sensitive_identity') IS NULL
    AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'erp'
          AND table_name = 'staff'
          AND column_name = 'phone_normalized'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname IN (
            'ct_staff_position_within_employment',
            'ct_staff_operational_role_within_employment',
            'ct_staff_employment_child_periods_reverse_guard'
        )
    )
    AND NOT EXISTS (
        SELECT 1
        FROM erp.permission_definition
        WHERE permission_code IN ('STAFF_VIEW', 'STAFF_MANAGE')
    )
    AND NOT EXISTS (
        SELECT 1
        FROM erp.account_permission
        WHERE permission_code IN ('STAFF_VIEW', 'STAFF_MANAGE')
    )
);
"@
    $AbsenceResult = & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U erp_owner `
        -d $Name `
        -tAc $AbsenceSql
    if ($LASTEXITCODE -ne 0 -or ($AbsenceResult -join "").Trim() -ne "t") {
        throw "W1A objects remain after downgrade to Wave 0"
    }
}

function Add-W1aPermissionAssignmentFixture {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $AssignmentSql = @'
INSERT INTO erp.account_permission (
    account_id,
    permission_code,
    granted_by_account_id
)
SELECT admin.id, 'STAFF_MANAGE', admin.id
FROM erp.user_account admin
WHERE admin.role_code = 'ADMIN'
  AND NOT EXISTS (
      SELECT 1
      FROM erp.account_permission assignment
      WHERE assignment.permission_code = 'STAFF_MANAGE'
  )
LIMIT 1;
'@
    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U erp_owner `
        -d $Name `
        -c $AssignmentSql | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to insert W1A permission assignment fixture"
    }
}

function Add-Wave0UpgradeFixture {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $FixtureSql = @'
DO $$
DECLARE
    actor_staff_id bigint;
    actor_account_id bigint;
    employment_id bigint;
BEGIN
    INSERT INTO erp.staff (
        name,
        birth_date,
        sex_code,
        phone,
        address,
        display_name,
        memo
    )
    VALUES (
        'Wave0 Seed One',
        DATE '1990-01-01',
        'TEST',
        '010-0000-0000',
        'Synthetic Address',
        'Wave0 Display One',
        'Wave0 Memo One'
    )
    RETURNING id INTO actor_staff_id;

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
        actor_staff_id,
        'WAVE0_ADMIN',
        'Wave0 Admin',
        'ADMIN',
        'synthetic-hash-not-for-login',
        decode(repeat('01', 32), 'hex'),
        1
    )
    RETURNING id INTO actor_account_id;

    INSERT INTO erp.staff_employment (
        staff_id,
        employment_no,
        staff_no,
        staff_no_year,
        staff_no_sequence,
        start_date,
        created_by_account_id
    )
    VALUES (
        actor_staff_id,
        1,
        '2026-001',
        2026,
        1,
        DATE '2026-01-01',
        actor_account_id
    )
    RETURNING id INTO employment_id;

    INSERT INTO erp.business_number_counter (
        number_type,
        number_year,
        last_sequence
    )
    VALUES ('STAFF_EMPLOYMENT', 2026, 1)
    ON CONFLICT (number_type, number_year) DO UPDATE
    SET last_sequence = GREATEST(
            erp.business_number_counter.last_sequence,
            EXCLUDED.last_sequence
        ),
        updated_at_utc = now();

    INSERT INTO erp.staff_position_period (
        staff_id,
        employment_id,
        position_code,
        start_date
    )
    VALUES (
        actor_staff_id,
        employment_id,
        'MANAGER',
        DATE '2026-01-01'
    );

    INSERT INTO erp.staff_operational_role_period (
        staff_id,
        employment_id,
        role_code,
        start_date
    )
    VALUES (
        actor_staff_id,
        employment_id,
        'MANAGEMENT_FUNCTION',
        DATE '2026-01-01'
    );

    INSERT INTO erp.staff (
        name,
        birth_date,
        sex_code,
        display_name,
        memo
    )
    VALUES (
        'Wave0 Seed Two',
        DATE '1991-02-02',
        'TEST',
        NULL,
        NULL
    );

    UPDATE erp.installation_state
    SET bootstrap_completed = true,
        bootstrap_completed_at_utc = now(),
        first_admin_account_id = actor_account_id,
        installed_app_version = 'wave0-upgrade-fixture';
END
$$;
'@
    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U erp_owner `
        -d $Name `
        -c $FixtureSql | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to insert the Wave 0 upgrade fixture"
    }
}

function Set-Wave0AdminSyntheticPin {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    Push-Location $BackendRoot
    try {
        $PinMaterial = & $PythonExe -c "from app.core.security import PinProtector; p=PinProtector('ephemeral-w1a-test-pepper','ephemeral-w1a-test-lookup-key'); print(p.hash_pin('123456')); print(p.lookup_hmac('123456').hex())"
        if ($LASTEXITCODE -ne 0 -or $PinMaterial.Count -lt 2) {
            throw "Unable to generate the synthetic Wave 0 admin PIN material"
        }
    }
    finally {
        Pop-Location
    }

    $AdminHash = [string]$PinMaterial[0]
    $AdminLookupHex = [string]$PinMaterial[1]
    $UpdateSql = @"
UPDATE erp.user_account
SET pin_hash = '$AdminHash',
    pin_lookup_hmac = decode('$AdminLookupHex', 'hex'),
    failed_count = 0,
    locked_until_utc = NULL,
    login_allowed = true
WHERE account_code = 'WAVE0_ADMIN';
"@
    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U erp_owner `
        -d $Name `
        -c $UpdateSql | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to seed the synthetic Wave 0 admin PIN"
    }
}

New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null

try {
    # 1. Initialize DB Cluster
    $InitStartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $InitStartInfo.FileName = $InitDbExe
    $InitStartInfo.Arguments = "--pgdata=`"$DataDirectory`" --username=postgres --auth=trust --encoding=UTF8 --locale=C"
    $InitStartInfo.UseShellExecute = $false
    $InitStartInfo.RedirectStandardOutput = $true
    $InitStartInfo.RedirectStandardError = $true
    $InitProc = [System.Diagnostics.Process]::Start($InitStartInfo)
    $InitProc.WaitForExit()
    if ($InitProc.ExitCode -ne 0) { throw "initdb failed" }

    # 2. Start PostgreSQL Cluster via ProcessStartInfo to avoid pipeline deadlock
    $PgStartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $PgStartInfo.FileName = $PgCtlExe
    $PgStartInfo.Arguments = "start -D `"$DataDirectory`" -l `"$LogFile`" -o `"-h 127.0.0.1 -p $Port`""
    $PgStartInfo.UseShellExecute = $false
    $PgStartInfo.RedirectStandardOutput = $true
    $PgStartInfo.RedirectStandardError = $true
    $PgProc = [System.Diagnostics.Process]::Start($PgStartInfo)
    $PgProc.WaitForExit()

    # Set ClusterStarted immediately so cleanup runs in case of subsequent failures
    $ClusterStarted = $true

    # Verify readiness
    & $PgIsReadyExe -h 127.0.0.1 -p $Port -U postgres -d postgres -t 10 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Ephemeral PostgreSQL cluster did not become ready" }

    # 3. Bootstrap postgres creates least-privilege roles (erp_owner NOT superuser) and test database
    $RoleSql = @"
DO `$$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'erp_owner') THEN
        CREATE ROLE erp_owner WITH LOGIN PASSWORD 'test_owner_pw';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'erp_app') THEN
        CREATE ROLE erp_app WITH LOGIN PASSWORD 'test_app_pw';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'erp_backup') THEN
        CREATE ROLE erp_backup WITH LOGIN PASSWORD 'test_backup_pw';
    END IF;
END `$$;
"@
    & $PsqlExe -h 127.0.0.1 -p $Port -U postgres -d postgres -c $RoleSql | Out-Null

    # Create the primary database owned by the non-superuser migration role.
    New-W1aDatabase -Name $DatabaseName

    # 4. Environment setup (migration performed as erp_owner)
    $PythonExe = Join-Path $BackendRoot ".venv\Scripts\python.exe"

    $env:SSWCENTER_ENVIRONMENT = "test"
    Set-W1aDatabaseContext -Name $DatabaseName
    $env:SSWCENTER_POSTGRES_TEST = "1"
    $env:SSWCENTER_PIN_PEPPER = "ephemeral-w1a-test-pepper"
    $env:SSWCENTER_PIN_LOOKUP_KEY = "ephemeral-w1a-test-lookup-key"
    $env:SSWCENTER_CSRF_SIGNING_KEY = "ephemeral-w1a-test-csrf-key"
    $env:SSWCENTER_RESIDENT_NUMBER_KEY_V1 = (
        "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    )
    $env:SSWCENTER_RESIDENT_NUMBER_LOOKUP_KEY = (
        "YWJjZGVmMDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODk="
    )
    $env:SSWCENTER_RESIDENT_NUMBER_ACTIVE_KEY_VERSION = "1"
    $RuntimeDataRoot = Join-Path $ClusterRoot "sswcenter-test-files"
    $env:SSWCENTER_DATA_ROOT = $RuntimeDataRoot
    New-Item -ItemType Directory -Path $env:SSWCENTER_DATA_ROOT -Force | Out-Null

    # 5. Apply Alembic migrations as erp_owner
    Push-Location $BackendRoot
    try {
        & $PythonExe -m alembic -c alembic.ini upgrade head | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Fresh W1A Alembic upgrade failed"
        }
    }
    finally {
        Pop-Location
    }

    $PrimaryOwnerDatabaseUrl = $env:SSWCENTER_DATABASE_URL
    & (Join-Path $PSScriptRoot "verify-w1a-vs1-db.ps1") `
        -DatabaseUrl $PrimaryOwnerDatabaseUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Fresh W1A PostgreSQL postcheck failed"
    }

    if ($RedOnly) {
        Write-Output "--- Executing W1A PostgreSQL Owner/Migration Test Suite ---"
        Push-Location $BackendRoot
        try {
            $PreviousErrorActionPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            & $PythonExe -m pytest -q `
                tests/test_auth_postgres.py `
                tests/test_w1a_staff_postgres.py
            $OwnerPytestExitCode = $LASTEXITCODE
            if ($OwnerPytestExitCode -eq 0) {
                Write-Output "--- Executing W1A API Transactions as erp_app ---"
                $env:SSWCENTER_DATABASE_URL = $env:SSWCENTER_APP_DATABASE_URL
                & $PythonExe -m pytest -q tests/test_w1a_staff_integration_postgres.py
                $AppPytestExitCode = $LASTEXITCODE
            } else {
                $AppPytestExitCode = 1
            }
            $ErrorActionPreference = $PreviousErrorActionPreference
            if ($OwnerPytestExitCode -ne 0 -or $AppPytestExitCode -ne 0) {
                exit 1
            }
            $env:SSWCENTER_DATABASE_URL = $PrimaryOwnerDatabaseUrl
            & (Join-Path $PSScriptRoot "verify-w1a-vs1-db.ps1") `
                -DatabaseUrl $PrimaryOwnerDatabaseUrl
            if ($LASTEXITCODE -ne 0) {
                exit 1
            }
            exit 0
        }
        finally {
            Pop-Location
        }
    }
    elseif ($E2ERedOnly) {
        Write-Output "--- Starting Backend FastAPI for Playwright E2E ---"

        # Runtime API transactions must use the least-privilege application role.
        $env:SSWCENTER_DATABASE_URL = $env:SSWCENTER_APP_DATABASE_URL

        # Start backend Uvicorn server in background on port 8000
        $BackendStartInfo = New-Object System.Diagnostics.ProcessStartInfo
        $BackendStartInfo.FileName = $PythonExe
        $BackendStartInfo.Arguments = "-m uvicorn app.main:app --host 127.0.0.1 --port 8000"
        $BackendStartInfo.WorkingDirectory = $BackendRoot
        $BackendStartInfo.UseShellExecute = $false
        $BackendProcess = [System.Diagnostics.Process]::Start($BackendStartInfo)

        # Wait on /health/ready endpoint with a bounded loop
        $BackendReady = $false
        for ($i = 0; $i -lt 10; $i++) {
            try {
                $HealthRes = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health/ready" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
                if ($HealthRes.StatusCode -eq 200) {
                    $BackendReady = $true
                    break
                }
            } catch {}
            Start-Sleep -Seconds 1
        }
        if (-not $BackendReady) {
            throw "FastAPI did not become ready for W1A E2E"
        }

        Write-Output "--- Executing Playwright E2E Test ---"
        Push-Location $FrontendRoot
        try {
            $PreviousErrorActionPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            $env:PLAYWRIGHT_NO_COPY_PROMPT = "1"
            & npm.cmd exec playwright -- test e2e/w1a-staff-real-pg.spec.ts --workers=1
            $E2EExitCode = $LASTEXITCODE
            $ErrorActionPreference = $PreviousErrorActionPreference
        }
        finally {
            Pop-Location
        }
        if ($E2EExitCode -ne 0) {
            exit $E2EExitCode
        }
        $env:SSWCENTER_DATABASE_URL = $PrimaryOwnerDatabaseUrl
        & (Join-Path $PSScriptRoot "verify-w1a-vs1-db.ps1") `
            -DatabaseUrl $PrimaryOwnerDatabaseUrl
        if ($LASTEXITCODE -ne 0) {
            exit 1
        }
        exit 0
    }
    else {
        Write-Output "--- Verifying Wave 0 to W1A migration with preserved values ---"
        New-W1aDatabase -Name $UpgradeDatabaseName
        Set-W1aDatabaseContext -Name $UpgradeDatabaseName
        $UpgradeOwnerDatabaseUrl = $env:SSWCENTER_DATABASE_URL

        Push-Location $BackendRoot
        try {
            & $PythonExe -m alembic -c alembic.ini upgrade 20260724_0002 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Wave 0 setup for W1A upgrade failed"
            }
        }
        finally {
            Pop-Location
        }
        Add-Wave0UpgradeFixture -Name $UpgradeDatabaseName
        Test-Wave0AclCanonicalization -Name $UpgradeDatabaseName

        $StaffFingerprintBefore = Get-Wave0StaffFingerprint -Name $UpgradeDatabaseName
        $AclFingerprintBeforeUpgrade = Get-Wave0AclFingerprint -Name $UpgradeDatabaseName
        Push-Location $BackendRoot
        try {
            & $PythonExe -m alembic -c alembic.ini upgrade head | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Wave 0 to W1A Alembic upgrade failed"
            }
        }
        finally {
            Pop-Location
        }
        & (Join-Path $PSScriptRoot "verify-w1a-vs1-db.ps1") `
            -DatabaseUrl $UpgradeOwnerDatabaseUrl
        if ($LASTEXITCODE -ne 0) {
            throw "Wave 0 to W1A PostgreSQL postcheck failed"
        }
        $StaffFingerprintAfterUpgrade = Get-Wave0StaffFingerprint `
            -Name $UpgradeDatabaseName
        if ($StaffFingerprintAfterUpgrade -ne $StaffFingerprintBefore) {
            throw "Wave 0 staff display_name or memo changed during W1A upgrade"
        }
        Add-W1aPermissionAssignmentFixture -Name $UpgradeDatabaseName

        Write-Output "--- Verifying W1A downgrade and re-upgrade round trip ---"
        Push-Location $BackendRoot
        try {
            & $PythonExe -m alembic -c alembic.ini downgrade 20260724_0002 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "W1A downgrade to Wave 0 failed"
            }
        }
        finally {
            Pop-Location
        }
        & (Join-Path $PSScriptRoot "verify-wave0-db.ps1") `
            -DatabaseUrl $UpgradeOwnerDatabaseUrl
        if ($LASTEXITCODE -ne 0) {
            throw "Wave 0 postcheck after W1A downgrade failed"
        }
        Test-W1aObjectsAbsent -Name $UpgradeDatabaseName
        $StaffFingerprintAfterDowngrade = Get-Wave0StaffFingerprint `
            -Name $UpgradeDatabaseName
        if ($StaffFingerprintAfterDowngrade -ne $StaffFingerprintBefore) {
            throw "Wave 0 staff display_name or memo changed during W1A downgrade"
        }
        $AclFingerprintAfterDowngrade = Get-Wave0AclFingerprint -Name $UpgradeDatabaseName
        if ($AclFingerprintAfterDowngrade -ne $AclFingerprintBeforeUpgrade) {
            throw "F1_WAVE0_ACL_FINGERPRINT_CHANGED"
        }

        Push-Location $BackendRoot
        try {
            & $PythonExe -m alembic -c alembic.ini upgrade head | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "W1A re-upgrade failed"
            }
        }
        finally {
            Pop-Location
        }
        & (Join-Path $PSScriptRoot "verify-w1a-vs1-db.ps1") `
            -DatabaseUrl $UpgradeOwnerDatabaseUrl
        if ($LASTEXITCODE -ne 0) {
            throw "W1A re-upgrade postcheck failed"
        }
        $StaffFingerprintAfterReupgrade = Get-Wave0StaffFingerprint `
            -Name $UpgradeDatabaseName
        if ($StaffFingerprintAfterReupgrade -ne $StaffFingerprintBefore) {
            throw "Wave 0 staff display_name or memo changed during W1A re-upgrade"
        }

        Set-Wave0AdminSyntheticPin -Name $UpgradeDatabaseName
        Write-Output "--- Re-running W1A PostgreSQL permission behavior after downgrade/re-upgrade ---"
        $env:SSWCENTER_DATABASE_URL = $env:SSWCENTER_APP_DATABASE_URL
        Push-Location $BackendRoot
        try {
            & $PythonExe -m pytest -q `
                tests/test_w1a_staff_integration_postgres.py::test_staff_permission_matrix_and_capabilities
            $ReupgradeBehaviorExitCode = $LASTEXITCODE
        }
        finally {
            Pop-Location
        }
        if ($ReupgradeBehaviorExitCode -ne 0) {
            throw "W1A re-upgrade permission behavior tests failed"
        }
        $env:SSWCENTER_DATABASE_URL = $UpgradeOwnerDatabaseUrl

        Write-Output "--- Verifying W1A offline SQL generation and application ---"
        New-W1aDatabase -Name $OfflineDatabaseName
        Set-W1aDatabaseContext -Name $OfflineDatabaseName
        $OfflineOwnerDatabaseUrl = $env:SSWCENTER_DATABASE_URL
        Push-Location $BackendRoot
        try {
            $PreviousErrorActionPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            $OfflineSqlLines = & $PythonExe `
                -m alembic `
                -c alembic.ini `
                upgrade head `
                --sql 2> $OfflineErrorFile
            $OfflineAlembicExitCode = $LASTEXITCODE
            $ErrorActionPreference = $PreviousErrorActionPreference
            if ($OfflineAlembicExitCode -ne 0) {
                $OfflineSqlErrors = Get-Content -LiteralPath $OfflineErrorFile -Raw
                throw "W1A offline Alembic SQL generation failed: $OfflineSqlErrors"
            }
            $OfflineSql = (
                $OfflineSqlLines -join [Environment]::NewLine
            ) + [Environment]::NewLine
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
            -U erp_owner `
            -d $OfflineDatabaseName `
            -f $OfflineSqlFile | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "W1A offline Alembic SQL application failed"
        }
        & (Join-Path $PSScriptRoot "verify-w1a-vs1-db.ps1") `
            -DatabaseUrl $OfflineOwnerDatabaseUrl
        if ($LASTEXITCODE -ne 0) {
            throw "W1A offline PostgreSQL postcheck failed"
        }

        Write-Output "--- Executing W1A owner and least-privilege application tests ---"
        Set-W1aDatabaseContext -Name $DatabaseName
        Push-Location $BackendRoot
        try {
            & $PythonExe -m pytest -q `
                tests/test_auth_postgres.py `
                tests/test_w1a_staff_postgres.py
            if ($LASTEXITCODE -ne 0) {
                throw "W1A owner/migration PostgreSQL tests failed"
            }
            $env:SSWCENTER_DATABASE_URL = $env:SSWCENTER_APP_DATABASE_URL
            & $PythonExe -m pytest -q tests/test_w1a_staff_integration_postgres.py
            if ($LASTEXITCODE -ne 0) {
                throw "W1A application-role PostgreSQL tests failed"
            }
        }
        finally {
            Pop-Location
        }
        $env:SSWCENTER_DATABASE_URL = $PrimaryOwnerDatabaseUrl

        Write-Output "--- Verifying revision-aware W1A backup restore postcheck ---"
        $BackupRoot = Join-Path $ClusterRoot "sswcenter-w1a-backups"
        & (Join-Path $PSScriptRoot "backup-postgres.ps1") `
            -DatabaseUrl $PrimaryOwnerDatabaseUrl `
            -DestinationRoot $BackupRoot `
            -DataRoot $env:SSWCENTER_DATA_ROOT `
            -AppVersion "w1a-vs1-test" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "W1A backup failed"
        }
        $BackupDirectory = (
            Get-ChildItem -LiteralPath $BackupRoot -Directory |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
        ).FullName
        $AdminDatabaseUrl = (
            "postgresql+psycopg://postgres@127.0.0.1:{0}/postgres" -f $Port
        )
        & (Join-Path $PSScriptRoot "restore-drill.ps1") `
            -BackupDirectory $BackupDirectory `
            -AdminDatabaseUrl $AdminDatabaseUrl `
            -ReviewDatabaseName "sswcenter_w1a_restore_review" `
            -ReviewDataRoot (
                Join-Path $ClusterRoot "sswcenter-restore-review-w1a"
            ) | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "W1A revision-aware restore drill failed"
        }

        & (Join-Path $PSScriptRoot "verify-w1a-vs1-db.ps1") `
            -DatabaseUrl $PrimaryOwnerDatabaseUrl
        if ($LASTEXITCODE -ne 0) {
            throw "Final W1A PostgreSQL postcheck failed"
        }
        Write-Output "W1A_POSTGRES_HARNESS_OK"
        exit 0
    }
}
finally {
    $ArtifactSaveError = $null
    $StopError = $null
    $StopFailureMessage = $null
    $ManifestCleanupError = $null
    try {
        try {
            if ($BackendProcess -and -not $BackendProcess.HasExited) {
                Stop-Process -Id $BackendProcess.Id -Force -ErrorAction Stop
                if (-not $BackendProcess.WaitForExit(10000)) {
                    throw "backend process did not exit after Stop-Process"
                }
            }
            if ($BackendProcess -and -not $BackendProcess.HasExited) {
                throw "backend process remained running after stop"
            }
            if ($ClusterStarted) {
                $StopStartInfo = New-Object System.Diagnostics.ProcessStartInfo
                $StopStartInfo.FileName = $PgCtlExe
                $StopStartInfo.Arguments = "stop -D `"$DataDirectory`" -m fast"
                $StopStartInfo.UseShellExecute = $false
                $StopProc = [System.Diagnostics.Process]::Start($StopStartInfo)
                $StopProc.WaitForExit()
                if ($StopProc.ExitCode -ne 0) {
                    throw ("pg_ctl stop returned exit code {0}" -f $StopProc.ExitCode)
                }
            }
            if ($TestStopFailure) {
                throw "injected stop failure after normal stop"
            }
        }
        catch {
            $StopError = $_
            $StopFailureMessage = "W1A_STOP_FAILURE: {0}" -f $_.Exception.Message
        }
        if ($null -eq $StopError) {
            try {
                Save-W1aArtifacts
            }
            catch {
                $ArtifactSaveError = $_
            }
        }
        else {
            try {
                Remove-W1aManifestState
            }
            catch {
                $ManifestCleanupError = $_
            }
        }
    }
    finally {
        $ResolvedClusterRoot = [System.IO.Path]::GetFullPath($ClusterRoot)
        if (
            $ResolvedClusterRoot.StartsWith(
                $AllowedTempRoot,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            (Split-Path -Leaf $ResolvedClusterRoot).StartsWith(
                "sswcenter-w1a-pg-",
                [StringComparison]::Ordinal
            ) -and
            (Test-Path -LiteralPath $ResolvedClusterRoot)
        ) {
            Remove-Item `
                -LiteralPath $ResolvedClusterRoot `
                -Recurse `
                -Force `
                -ErrorAction SilentlyContinue
        }
    }
    if ($null -ne $ArtifactSaveError) {
        throw $ArtifactSaveError.Exception
    }
    if ($null -ne $ManifestCleanupError) {
        throw $StopFailureMessage
    }
    if ($null -ne $StopError) {
        throw $StopFailureMessage
    }
}
