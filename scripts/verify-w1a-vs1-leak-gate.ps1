param(
    [switch]$SelfTest,
    [Alias("PostgresArtifactRoot")]
    [string[]]$ArtifactRoot = @()
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptRoot = $PSScriptRoot
$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $ScriptRoot))
. (Join-Path $ScriptRoot "w1a-rrn-detector.ps1")

$TextExtensions = @(
    ".c", ".cfg", ".conf", ".css", ".csv", ".env", ".html", ".ini", ".js", ".json",
    ".jsonl", ".log", ".md", ".ndjson", ".out", ".py", ".pyi", ".ps1", ".sql", ".text",
    ".toml", ".trace", ".ts", ".tsx", ".txt", ".xml", ".yml", ".yaml"
)
$BinaryExtensions = @(
    ".7z", ".bin", ".bmp", ".class", ".db", ".dll", ".dylib", ".exe", ".gif", ".ico",
    ".jpeg", ".jpg", ".otf", ".pdf", ".pyd", ".pyc", ".so", ".sqlite", ".sqlite3",
    ".png", ".tar", ".traineddata", ".ttf", ".wasm", ".webp", ".woff", ".woff2", ".zip"
)
$ExcludedDirectoryNames = @(
    ".git", ".venv", ".ruff_cache", ".mypy_cache", "node_modules", "dist", "build", "coverage", ".pytest_cache",
    "__pycache__"
)

function Test-ExcludedPath {
    param([Parameter(Mandatory = $true)] [string]$Path)

    $parts = ([System.IO.Path]::GetFullPath($Path)).Split(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.StringSplitOptions]::RemoveEmptyEntries
    )
    foreach ($part in $parts) {
        if ($ExcludedDirectoryNames -contains $part) { return $true }
    }
    return $false
}

function ConvertFrom-GitPathLine {
    param([Parameter(Mandatory = $true)] [string]$Line)

    if ($Line.Length -ge 2 -and $Line[0] -eq '"' -and $Line[$Line.Length - 1] -eq '"') {
        try {
            return [string](ConvertFrom-Json -InputObject $Line -ErrorAction Stop)
        } catch {
            throw "LEAK_GATE_GIT_PATH_FAILURE: quoted path could not be decoded"
        }
    }
    return $Line
}

function Invoke-GitPathCommand {
    param([Parameter(Mandatory = $true)] [string[]]$Arguments)

    $gitArguments = @(
        "-C", $WorkspaceRoot,
        "-c", "core.quotePath=false",
        "-c", "core.autocrlf=false",
        "-c", "core.safecrlf=false"
    ) + $Arguments
    $lines = @(& git @gitArguments 2>$null)
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "LEAK_GATE_GIT_DISCOVERY_FAILURE: git path enumeration failed"
    }
    foreach ($line in $lines) {
        $pathLine = [string]$line
        if ([string]::IsNullOrEmpty($pathLine)) { continue }
        ConvertFrom-GitPathLine -Line $pathLine
    }
}

function Add-ScanPath {
    param(
        [Parameter(Mandatory = $true)] [object]$Paths,
        [Parameter(Mandatory = $true)] [string]$Path
    )

    try {
        $fullPath = [System.IO.Path]::GetFullPath($Path)
    } catch {
        throw "LEAK_GATE_PATH_FAILURE: path could not be normalized"
    }
    if (Test-ExcludedPath -Path $fullPath) { return }
    if (Test-Path -LiteralPath $fullPath -PathType Leaf) {
        $Paths.Add($fullPath) | Out-Null
    }
}

function Add-DirectoryFiles {
    param(
        [Parameter(Mandatory = $true)] [object]$Paths,
        [Parameter(Mandatory = $true)] [string]$Root,
        [string]$BoundaryRoot
    )

    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return }
    try {
        $rootAttributes = [System.IO.File]::GetAttributes($Root)
    } catch {
        throw "LEAK_GATE_PATH_FAILURE: artifact root could not be inspected"
    }
    if (($rootAttributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "LEAK_GATE_PATH_FAILURE: artifact root is a reparse point"
    }
    $resolvedBoundaryRoot = $null
    if (-not [string]::IsNullOrWhiteSpace($BoundaryRoot)) {
        try {
            $resolvedBoundaryRoot = [System.IO.Path]::GetFullPath($BoundaryRoot).TrimEnd(
                [System.IO.Path]::DirectorySeparatorChar,
                [System.IO.Path]::AltDirectorySeparatorChar
            )
        } catch {
            throw "LEAK_GATE_PATH_FAILURE: artifact boundary could not be normalized"
        }
    }
    foreach ($entry in Get-ChildItem -LiteralPath $Root -Recurse -Force -ErrorAction Stop) {
        if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "LEAK_GATE_PATH_FAILURE: reparse-point artifact could not be scanned"
        }
        if ($entry.PSIsContainer) { continue }
        $file = $entry
        if ($null -ne $resolvedBoundaryRoot) {
            try {
                $resolvedFile = [System.IO.Path]::GetFullPath($file.FullName)
            } catch {
                throw "LEAK_GATE_PATH_FAILURE: artifact file path could not be normalized"
            }
            $boundaryPrefix = $resolvedBoundaryRoot + [System.IO.Path]::DirectorySeparatorChar
            if (-not $resolvedFile.StartsWith($boundaryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw "LEAK_GATE_PATH_FAILURE: artifact file escaped its root"
            }
        }
        Add-ScanPath -Paths $Paths -Path $file.FullName
    }
}

function Resolve-ExplicitArtifactRoot {
    param([Parameter(Mandatory = $true)] [string]$Path)

    $pathText = $Path.Trim()
    if ($pathText.Length -ge 2 -and $pathText[0] -eq '"' -and $pathText[$pathText.Length - 1] -eq '"') {
        $pathText = $pathText.Substring(1, $pathText.Length - 2)
    }
    if ([string]::IsNullOrWhiteSpace($pathText)) {
        throw "LEAK_GATE_PATH_FAILURE: explicit artifact root is empty"
    }
    try {
        $resolved = [System.IO.Path]::GetFullPath($pathText)
    } catch {
        throw "LEAK_GATE_PATH_FAILURE: explicit artifact root could not be normalized"
    }
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "LEAK_GATE_PATH_FAILURE: explicit artifact root does not exist"
    }
    if (Test-ExcludedPath -Path $resolved) {
        throw "LEAK_GATE_PATH_FAILURE: explicit artifact root is excluded"
    }
    try {
        $attributes = [System.IO.File]::GetAttributes($resolved)
    } catch {
        throw "LEAK_GATE_PATH_FAILURE: explicit artifact root could not be inspected"
    }
    if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "LEAK_GATE_PATH_FAILURE: explicit artifact root is a reparse point"
    }
    return $resolved
}

function Add-ExplicitArtifactRoot {
    param(
        [Parameter(Mandatory = $true)] [object]$Paths,
        [Parameter(Mandatory = $true)] [string]$Root
    )

    $resolved = Resolve-ExplicitArtifactRoot -Path $Root
    Add-DirectoryFiles -Paths $Paths -Root $resolved -BoundaryRoot $resolved
}

function Get-ScanFiles {
    $paths = New-Object System.Collections.Generic.HashSet[string]([StringComparer]::OrdinalIgnoreCase)

    foreach ($relative in @(Invoke-GitPathCommand -Arguments @("ls-files", "--cached"))) {
        if ([string]::IsNullOrWhiteSpace($relative)) { continue }
        Add-ScanPath -Paths $paths -Path (Join-Path $WorkspaceRoot $relative)
    }
    foreach ($relative in @(Invoke-GitPathCommand -Arguments @("ls-files", "--others", "--exclude-standard"))) {
        if ([string]::IsNullOrWhiteSpace($relative)) { continue }
        Add-ScanPath -Paths $paths -Path (Join-Path $WorkspaceRoot $relative)
    }
    foreach ($relative in @(Invoke-GitPathCommand -Arguments @("ls-files", "--others", "--ignored", "--exclude-standard"))) {
        if ([string]::IsNullOrWhiteSpace($relative)) { continue }
        Add-ScanPath -Paths $paths -Path (Join-Path $WorkspaceRoot $relative)
    }

    foreach ($relative in @(Invoke-GitPathCommand -Arguments @("diff", "--name-only", "--no-renames"))) {
        if ([string]::IsNullOrWhiteSpace($relative)) { continue }
        Add-ScanPath -Paths $paths -Path (Join-Path $WorkspaceRoot $relative)
    }
    foreach ($relative in @(Invoke-GitPathCommand -Arguments @("diff", "--cached", "--name-only", "--no-renames"))) {
        if ([string]::IsNullOrWhiteSpace($relative)) { continue }
        Add-ScanPath -Paths $paths -Path (Join-Path $WorkspaceRoot $relative)
    }

    foreach ($root in @(
        (Join-Path $WorkspaceRoot "frontend\test-results"),
        (Join-Path $WorkspaceRoot "frontend\playwright-report"),
        (Join-Path $WorkspaceRoot "backend\logs")
    )) {
        Add-DirectoryFiles -Paths $paths -Root $root
    }

    if (-not [string]::IsNullOrWhiteSpace($env:SSWCENTER_DATA_ROOT)) {
        try {
            $dataRoot = [System.IO.Path]::GetFullPath($env:SSWCENTER_DATA_ROOT)
        } catch {
            throw "LEAK_GATE_PATH_FAILURE: data root could not be normalized"
        }
        Add-DirectoryFiles -Paths $paths -Root $dataRoot
    }

    foreach ($root in @($ArtifactRoot)) {
        if ([string]::IsNullOrWhiteSpace([string]$root)) {
            throw "LEAK_GATE_PATH_FAILURE: explicit artifact root is empty"
        }
        Add-ExplicitArtifactRoot -Paths $paths -Root ([string]$root)
    }

    try {
        $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        foreach ($directory in Get-ChildItem -LiteralPath $tempRoot -Directory -Force -ErrorAction Stop) {
            if ($directory.Name.StartsWith("sswcenter-w1a-pg-", [StringComparison]::Ordinal)) {
                Add-DirectoryFiles -Paths $paths -Root $directory.FullName -BoundaryRoot $tempRoot
            }
            if ($directory.Name.StartsWith("sswcenter-w1a-artifacts-", [StringComparison]::Ordinal)) {
                Add-DirectoryFiles -Paths $paths -Root $directory.FullName -BoundaryRoot $tempRoot
            }
        }
    } catch {
        throw "LEAK_GATE_PATH_FAILURE: temporary runtime surface could not be enumerated"
    }

    return @($paths | Sort-Object)
}

function Get-FileText {
    param([Parameter(Mandatory = $true)] [string]$Path)

    $strictUtf8 = [System.Text.UTF8Encoding]::new($false, $true)
    try {
        $extension = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()
    } catch {
        throw "LEAK_GATE_READ_FAILURE: file extension could not be determined"
    }

    if ($BinaryExtensions -contains $extension) {
        return $null
    }

    if ($extension -eq ".gz") {
        try {
            $stream = [System.IO.File]::OpenRead($Path)
            try {
                $gzip = [System.IO.Compression.GzipStream]::new(
                    $stream,
                    [System.IO.Compression.CompressionMode]::Decompress
                )
                try {
                    $reader = [System.IO.StreamReader]::new($gzip, $strictUtf8)
                    try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
                } finally { $gzip.Dispose() }
            } finally { $stream.Dispose() }
        } catch {
            throw "LEAK_GATE_READ_FAILURE: compressed file could not be read"
        }
    }

    try {
        # Unknown extensions are read as strict UTF-8 instead of being skipped.
        # This keeps text artifacts such as traces and generated outputs fail-closed.
        return [System.IO.File]::ReadAllText($Path, $strictUtf8)
    } catch {
        throw "LEAK_GATE_READ_FAILURE: text file could not be read"
    }
}

function Write-Utf8Gzip {
    param(
        [Parameter(Mandatory = $true)] [string]$Path,
        [Parameter(Mandatory = $true)] [string]$Text
    )

    $fileStream = [System.IO.File]::Create($Path)
    try {
        $gzip = [System.IO.Compression.GzipStream]::new(
            $fileStream,
            [System.IO.Compression.CompressionMode]::Compress
        )
        try {
            $writer = [System.IO.StreamWriter]::new($gzip, [System.Text.UTF8Encoding]::new($false))
            try { $writer.Write($Text) } finally { $writer.Dispose() }
        } finally { $gzip.Dispose() }
    } finally { $fileStream.Dispose() }
}

function Invoke-GateSubprocess {
    param(
        [Parameter(Mandatory = $true)] [string]$DataRoot,
        [string[]]$ExplicitArtifactRoot = @()
    )

    $previousDataRoot = $env:SSWCENTER_DATA_ROOT
    $previousErrorActionPreference = $ErrorActionPreference
    $env:SSWCENTER_DATA_ROOT = $DataRoot
    try {
        $ErrorActionPreference = "Continue"
        $childArguments = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $PSCommandPath
        )
        foreach ($root in @($ExplicitArtifactRoot)) {
            $childArguments += @("-ArtifactRoot", [string]$root)
        }
        $output = [string](& powershell.exe @childArguments 2>&1 | Out-String)
        $exitCode = $LASTEXITCODE
        return [PSCustomObject]@{ ExitCode = $exitCode; Output = $output }
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($null -eq $previousDataRoot) {
            Remove-Item -LiteralPath Env:SSWCENTER_DATA_ROOT -ErrorAction SilentlyContinue
        } else {
            $env:SSWCENTER_DATA_ROOT = $previousDataRoot
        }
    }
}

function Get-VectorCaseById {
    param([Parameter(Mandatory = $true)] [string]$Id)

    $matches = @(Get-W1ARRNVectorCases | Where-Object { [string]$_.id -eq $Id })
    if ($matches.Count -ne 1) {
        throw "LEAK_GATE_SELF_TEST_FAILURE: required vector is missing"
    }
    return $matches[0]
}

function Get-DisplayPath {
    param([Parameter(Mandatory = $true)] [string]$Path)

    $display = $Path.Replace($WorkspaceRoot + [System.IO.Path]::DirectorySeparatorChar, "")
    return $display -replace '(?<![0-9])[0-9]{6}(?:[-_/:. ]?[0-9]{7})(?![0-9])', '[REDACTED-CANDIDATE-PATH]'
}

if ($SelfTest) {
    $nonAsciiPathMarker = ([char]0xD55C).ToString() + ([char]0xAE00).ToString()
    $fixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sswcenter-w1a-leak-" + [Guid]::NewGuid().ToString("N"))
    $negativeArtifactPrefixRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sswcenter-w1a-artifacts-" + [Guid]::NewGuid().ToString("N"))
    $negativeExplicitArtifactRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sswcenter w1a explicit artifact " + $nonAsciiPathMarker + " " + [Guid]::NewGuid().ToString("N"))
    $negativePrefixDataRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sswcenter-w1a-prefix-data-" + [Guid]::NewGuid().ToString("N"))
    $negativeExplicitDataRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sswcenter-w1a-explicit-data-" + [Guid]::NewGuid().ToString("N"))
    $cleanDataRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sswcenter-w1a-clean-" + [Guid]::NewGuid().ToString("N"))
    $cleanArtifactPrefixRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sswcenter-w1a-artifacts-" + [Guid]::NewGuid().ToString("N"))
    $cleanExplicitArtifactRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sswcenter w1a clean artifact " + $nonAsciiPathMarker + " " + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $fixtureRoot -Force | Out-Null
    try {
        $vectorSummary = Test-W1ARRNVectorParity
        if ($vectorSummary.Total -ne 40 -or $vectorSummary.Sensitive -ne 32 -or $vectorSummary.Negative -ne 8) {
            throw "LEAK_GATE_SELF_TEST_FAILURE: unexpected vector classification counts"
        }
        $syntheticCase = Get-VectorCaseById -Id "raw-code-1"
        $synthetic = New-W1ARRNVectorText -Case $syntheticCase
        $surfaceDefinitions = @(
            @{ Directory = "tracked"; Name = "tracked-surface.log" },
            @{ Directory = "staged"; Name = "staged-surface.txt" },
            @{ Directory = "unstaged"; Name = "unstaged-surface.json" },
            @{ Directory = "untracked"; Name = "untracked-surface.yaml" },
            @{ Directory = "text"; Name = "text-surface.trace" }
        )
        foreach ($surface in $surfaceDefinitions) {
            $directory = Join-Path $fixtureRoot $surface.Directory
            New-Item -ItemType Directory -Path $directory -Force | Out-Null
            $path = Join-Path $directory $surface.Name
            [System.IO.File]::WriteAllText($path, ("fixture=" + $synthetic), [System.Text.UTF8Encoding]::new($false))
        }
        $gzipDirectory = Join-Path $fixtureRoot "gzip"
        New-Item -ItemType Directory -Path $gzipDirectory -Force | Out-Null
        Write-Utf8Gzip -Path (Join-Path $gzipDirectory "gzip-surface.log.gz") -Text ("fixture=" + $synthetic)

        foreach ($fixtureArtifactRoot in @($negativeArtifactPrefixRoot, $negativeExplicitArtifactRoot)) {
            New-Item -ItemType Directory -Path $fixtureArtifactRoot -Force | Out-Null
            [System.IO.File]::WriteAllText(
                (Join-Path $fixtureArtifactRoot "artifact-surface.log"),
                ("fixture=" + $synthetic),
                [System.Text.UTF8Encoding]::new($false)
            )
        }

        New-Item -ItemType Directory -Path $negativePrefixDataRoot, $negativeExplicitDataRoot -Force | Out-Null
        $prefixRun = Invoke-GateSubprocess -DataRoot $negativePrefixDataRoot
        if ($prefixRun.ExitCode -ne 1) {
            throw "LEAK_GATE_SELF_TEST_FAILURE: temp artifact prefix was not rejected"
        }
        Remove-Item -LiteralPath $negativeArtifactPrefixRoot -Recurse -Force -ErrorAction SilentlyContinue

        $explicitRun = Invoke-GateSubprocess `
            -DataRoot $negativeExplicitDataRoot `
            -ExplicitArtifactRoot $negativeExplicitArtifactRoot
        if ($explicitRun.ExitCode -ne 1) {
            throw "LEAK_GATE_SELF_TEST_FAILURE: explicit artifact root was not rejected"
        }

        $negativeRun = Invoke-GateSubprocess `
            -DataRoot $fixtureRoot `
            -ExplicitArtifactRoot @()
        if ($negativeRun.ExitCode -ne 1) {
            throw "LEAK_GATE_SELF_TEST_FAILURE: gate subprocess did not reject injected surface"
        }
        if ((Get-W1ARRNMatchCount -Text (Get-FileText -Path (Join-Path $gzipDirectory "gzip-surface.log.gz"))) -eq 0) {
            throw "LEAK_GATE_SELF_TEST_FAILURE: gzip fixture was not detected"
        }

        $invalidTextPath = Join-Path $fixtureRoot "invalid-utf8.txt"
        [System.IO.File]::WriteAllBytes($invalidTextPath, [byte[]]@(0xC3, 0x28))
        $invalidTextFailedClosed = $false
        try { Get-FileText -Path $invalidTextPath | Out-Null } catch { $invalidTextFailedClosed = $true }
        if (-not $invalidTextFailedClosed) {
            throw "LEAK_GATE_SELF_TEST_FAILURE: invalid UTF-8 was not rejected"
        }

        $corruptGzipPath = Join-Path $fixtureRoot "corrupt.log.gz"
        [System.IO.File]::WriteAllText($corruptGzipPath, "not gzip", [System.Text.UTF8Encoding]::new($false))
        $corruptGzipFailedClosed = $false
        try { Get-FileText -Path $corruptGzipPath | Out-Null } catch { $corruptGzipFailedClosed = $true }
        if (-not $corruptGzipFailedClosed) {
            throw "LEAK_GATE_SELF_TEST_FAILURE: corrupt gzip was not rejected"
        }

        Remove-Item -LiteralPath $negativeExplicitArtifactRoot -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Path $cleanDataRoot, $cleanArtifactPrefixRoot, $cleanExplicitArtifactRoot -Force | Out-Null
        foreach ($cleanRoot in @($cleanArtifactPrefixRoot, $cleanExplicitArtifactRoot)) {
            [System.IO.File]::WriteAllText(
                (Join-Path $cleanRoot "clean-surface.log"),
                "artifact=clean",
                [System.Text.UTF8Encoding]::new($false)
            )
        }
        $cleanRun = Invoke-GateSubprocess `
            -DataRoot $cleanDataRoot `
            -ExplicitArtifactRoot $cleanExplicitArtifactRoot
        if ($cleanRun.ExitCode -ne 0 -or $cleanRun.Output -notmatch "W1A_LEAK_GATE_GREEN") {
            throw "LEAK_GATE_SELF_TEST_FAILURE: clean artifact surface was not green"
        }

        Write-Output "W1A_LEAK_GATE_SELF_TEST_OK"
        exit 0
    } finally {
        foreach ($root in @(
            $fixtureRoot,
            $negativeArtifactPrefixRoot,
            $negativeExplicitArtifactRoot,
            $negativePrefixDataRoot,
            $negativeExplicitDataRoot,
            $cleanDataRoot,
            $cleanArtifactPrefixRoot,
            $cleanExplicitArtifactRoot
        )) {
            Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

$violations = 0
$scanned = 0
foreach ($path in @(Get-ScanFiles)) {
    $text = Get-FileText -Path $path
    if ($null -eq $text) { continue }
    $scanned++
    $count = Get-W1ARRNMatchCount -Text $text
    if ($count -gt 0) {
        $violations += $count
        $displayPath = Get-DisplayPath -Path $path
        Write-Error "LEAK_GATE_FAILURE: sensitive candidate detected in scanned surface $displayPath"
    }
}

Write-Output "W1A_LEAK_GATE_SCANNED_FILES=$scanned"
if ($violations -gt 0) {
    exit 1
}
Write-Output "W1A_LEAK_GATE_GREEN"
exit 0
