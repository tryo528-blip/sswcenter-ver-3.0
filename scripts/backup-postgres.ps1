param(
    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$DestinationRoot,

    [Parameter(Mandatory = $true)]
    [string]$DataRoot,

    [string]$AppVersion = "unknown"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "PostgresTools.psm1") -Force

$Connection = ConvertFrom-SswPostgresUrl -DatabaseUrl $DatabaseUrl
if ($Connection.Database -in @("postgres", "template0", "template1")) {
    throw "Backup refuses PostgreSQL maintenance databases"
}

if (-not [System.IO.Path]::IsPathRooted($DestinationRoot)) {
    throw "Backup destination must be an absolute path"
}
$ResolvedDestination = [System.IO.Path]::GetFullPath($DestinationRoot)
if (-not [System.IO.Path]::IsPathRooted($DataRoot)) {
    throw "Data root must be an absolute path"
}
$ResolvedDataRoot = [System.IO.Path]::GetFullPath($DataRoot)
if (-not (Test-Path -LiteralPath $ResolvedDataRoot -PathType Container)) {
    throw "Data root directory is missing"
}
if (
    $ResolvedDestination.StartsWith(
        $ResolvedDataRoot + [System.IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "Backup destination must not be inside the live data root"
}
New-Item -ItemType Directory -Path $ResolvedDestination -Force | Out-Null

$Timestamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$BackupDirectory = Join-Path $ResolvedDestination (
    "{0}-{1}-{2}" -f $Connection.Database, $Timestamp, [Guid]::NewGuid().ToString("N").Substring(0, 8)
)
if (Test-Path -LiteralPath $BackupDirectory) {
    throw "Refusing to overwrite an existing backup directory"
}
New-Item -ItemType Directory -Path $BackupDirectory | Out-Null

$DumpFile = Join-Path $BackupDirectory "database.dump"
$ManifestFile = Join-Path $BackupDirectory "manifest.json"
$BundleHashFile = Join-Path $BackupDirectory "bundle.sha256"
$BackupDataRoot = Join-Path $BackupDirectory "data"
$PgDumpExe = Get-SswPostgresExecutable -Name "pg_dump.exe"
$PsqlExe = Get-SswPostgresExecutable -Name "psql.exe"
$AlembicRevision = ""

try {
    Invoke-WithPgPassword -Password $Connection.Password -Action {
        & $PgDumpExe `
            --host=$($Connection.Host) `
            --port=$($Connection.Port) `
            --username=$($Connection.User) `
            --dbname=$($Connection.Database) `
            --format=custom `
            --compress=9 `
            --no-password `
            --file=$DumpFile
        if ($LASTEXITCODE -ne 0) {
            throw "pg_dump failed"
        }

        $RevisionOutput = & $PsqlExe `
            --host=$($Connection.Host) `
            --port=$($Connection.Port) `
            --username=$($Connection.User) `
            --dbname=$($Connection.Database) `
            --no-password `
            --tuples-only `
            --no-align `
            --command="SELECT version_num FROM erp.alembic_version"
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to read the Alembic revision"
        }
        $script:AlembicRevision = ($RevisionOutput -join "").Trim()
    }

    New-Item -ItemType Directory -Path $BackupDataRoot | Out-Null
    $FileEntries = @()
    foreach ($DirectoryName in @("blobs", "official-documents")) {
        $SourceDirectory = Join-Path $ResolvedDataRoot $DirectoryName
        if (-not (Test-Path -LiteralPath $SourceDirectory -PathType Container)) {
            continue
        }
        foreach ($SourceFile in Get-ChildItem -LiteralPath $SourceDirectory -File -Recurse) {
            $RelativePath = Get-SswRelativePath `
                -BasePath $ResolvedDataRoot `
                -TargetPath $SourceFile.FullName
            $BackupFile = Join-Path $BackupDataRoot $RelativePath
            $BackupFileParent = Split-Path -Parent $BackupFile
            New-Item -ItemType Directory -Path $BackupFileParent -Force | Out-Null
            Copy-Item -LiteralPath $SourceFile.FullName -Destination $BackupFile
            $FileEntries += [ordered]@{
                relative_path = $RelativePath.Replace("\", "/")
                sha256 = (
                    Get-FileHash -LiteralPath $BackupFile -Algorithm SHA256
                ).Hash.ToLowerInvariant()
                size_bytes = $SourceFile.Length
            }
        }
    }

    $DumpHash = (Get-FileHash -LiteralPath $DumpFile -Algorithm SHA256).Hash.ToLowerInvariant()
    $Manifest = [ordered]@{
        format_version = 1
        database_name = $Connection.Database
        created_at_utc = [DateTime]::UtcNow.ToString("o")
        app_version = $AppVersion
        alembic_revision = $AlembicRevision
        dump_file = "database.dump"
        dump_sha256 = $DumpHash
        dump_size_bytes = (Get-Item -LiteralPath $DumpFile).Length
        files = $FileEntries
        restore_target_policy = "*_review only"
    }
    $Manifest | ConvertTo-Json | Set-Content -LiteralPath $ManifestFile -Encoding utf8

    $HashLines = @()
    foreach (
        $BundleFile in Get-ChildItem -LiteralPath $BackupDirectory -File -Recurse |
            Where-Object FullName -ne $BundleHashFile |
            Sort-Object FullName
    ) {
        $RelativeBundlePath = (
            Get-SswRelativePath `
                -BasePath $BackupDirectory `
                -TargetPath $BundleFile.FullName
        ).Replace("\", "/")
        $BundleHash = (
            Get-FileHash -LiteralPath $BundleFile.FullName -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        $HashLines += "$BundleHash *$RelativeBundlePath"
    }
    [System.IO.File]::WriteAllLines(
        $BundleHashFile,
        $HashLines,
        [System.Text.UTF8Encoding]::new($false)
    )
}
catch {
    if (
        (Test-Path -LiteralPath $BackupDirectory) -and
        [System.IO.Path]::GetFullPath($BackupDirectory).StartsWith(
            $ResolvedDestination,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        Remove-Item -LiteralPath $BackupDirectory -Recurse -Force
    }
    throw
}

Write-Output "BACKUP_OK $BackupDirectory"
