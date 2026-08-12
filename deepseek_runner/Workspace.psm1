# Workspace.psm1
# DeepSeek Writer Runner - File system abstraction with SHA, path safety, exact-byte ops
# PowerShell 7.x required. UTF-8 no BOM + LF preferred.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# PowerShell 7 normally exposes LinkCount, but some Windows filesystems do
# not surface that extended property for ordinary files. Use the NTFS handle
# metadata as the authoritative fallback so absence of the PS property is not
# a hard-link fail-open.
if ($IsWindows -and -not ('DswRunnerLinkInfo' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public static class DswRunnerLinkInfo {
    [StructLayout(LayoutKind.Sequential)]
    private struct ByHandleFileInformation {
        public uint FileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(
        SafeFileHandle file, out ByHandleFileInformation information);

    public static uint GetLinkCount(string path) {
        using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read,
            FileShare.ReadWrite | FileShare.Delete)) {
            ByHandleFileInformation information;
            if (!GetFileInformationByHandle(stream.SafeFileHandle, out information)) {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            return information.NumberOfLinks;
        }
    }
}
'@
}

# ---------------------------------------------------------------------------
# Constants / Config (overridable by caller)
# ---------------------------------------------------------------------------
$script:ForbiddenPathPatterns = @(
    '\.git($|[/\\])',
    '\.codex($|[/\\])',
    '\.grok($|[/\\])',
    '\.claude($|[/\\])',
    '\.ssh($|[/\\])',
    '\.aws($|[/\\])',
    '\.azure($|[/\\])',
    '\.kube($|[/\\])',
    '\.env($|[/\\.]|$)',
    'credentials',
    'secret',
    '\.pem$',
    '\.key$',
    '\.pfx$',
    '\.p12$'
)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------
class FileState {
    [string]$Path          # relative to RepoRoot, normalized / separators
    [string]$Sha256        # lowercase hex of exact file bytes (or $null if MISSING)
    [long]$Size
    [bool]$Exists
    [string]$Content       # optional; only populated when read
}

# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------
function Get-NormalizedRelativePath {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$RepoRoot
    )
    $full = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
    $rootFull = [System.IO.Path]::GetFullPath($RepoRoot)
    $relative = [System.IO.Path]::GetRelativePath($rootFull, $full)
    if ([System.IO.Path]::IsPathRooted($relative) -or
        $relative -eq '..' -or
        $relative.StartsWith('../', [StringComparison]::Ordinal) -or
        $relative.StartsWith('..\', [StringComparison]::Ordinal)) {
        throw "PATH_OUTSIDE_REPOSITORY: $Path"
    }
    $rel = if ($relative -eq '.') { '' } else { $relative }
    # normalize to forward slash for consistent keys
    # Preserve the repository-root empty relative path as an actual string;
    # otherwise PowerShell's pipeline turns it into no output/null.
    return ,($rel -replace '\\','/')
}

function Test-PathIsSensitive {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$RelativePath
    )
    $p = $RelativePath -replace '\\','/'
    foreach ($pat in $script:ForbiddenPathPatterns) {
        if ($p -match $pat) { return $true }
    }
    return $false
}

function Test-WorkspacePathAllowed {
    param(
        [Parameter(Mandatory)][AllowEmptyString()][string]$RelativePath,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$AllowList,
        [switch]$AllowAncestor
    )

    if ($AllowList.Count -eq 0) { return $true }
    $path = ($RelativePath -replace '\\','/').Trim('/')
    if ([string]::IsNullOrWhiteSpace($path)) { return $true }

    foreach ($entry in @($AllowList)) {
        $allowed = ([string]$entry -replace '\\','/').Trim('/')
        # A root scope must be explicit in the task packet; it is never
        # inferred merely because a caller omitted an allowlist.
        if ($allowed -eq '.' -or $allowed -eq '*') { return $true }
        if ([string]::IsNullOrWhiteSpace($allowed)) { continue }
        if ($path -eq $allowed -or $path.StartsWith("$allowed/", [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
        if ($AllowAncestor -and $allowed.StartsWith("$path/", [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Get-FileSha256Exact {
    param([Parameter(Mandatory)][string]$FullPath)
    if (-not (Test-Path -LiteralPath $FullPath -PathType Leaf)) {
        return $null
    }
    $bytes = [System.IO.File]::ReadAllBytes($FullPath)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha.ComputeHash($bytes)
        return ([BitConverter]::ToString($hash) -replace '-','').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-FileContentExact {
    param([Parameter(Mandatory)][string]$FullPath)
    # Exact bytes → string via UTF8 (no BOM strip special; we keep content as-is for SHA consistency)
    # Design: SHA is on original bytes. For content we return the decoded text for model.
    # We assume UTF-8. If other encoding, model still gets best-effort text.
    $bytes = [System.IO.File]::ReadAllBytes($FullPath)
    return [System.Text.Encoding]::UTF8.GetString($bytes)
}

function Write-FileExactUtf8NoBom {
    param(
        [Parameter(Mandatory)][string]$FullPath,
        [Parameter(Mandatory)][AllowEmptyString()][string]$Content
    )
    $dir = Split-Path -Parent $FullPath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    # UTF8 no BOM + preserve LF if present (PowerShell default on Core is better)
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($FullPath, $Content, $utf8NoBom)
}

# ---------------------------------------------------------------------------
# Public API used by runner
# ---------------------------------------------------------------------------
function New-Workspace {
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [string[]]$WriteAllowList = @(),
        [string[]]$ReadAllowList  = @()    # empty = all under RepoRoot readable
    )
    $root = [System.IO.Path]::GetFullPath($RepoRoot)
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        throw "REPO_ROOT_NOT_FOUND: $root"
    }
    $effectiveWriteAllowList = @($WriteAllowList | ForEach-Object { ([string]$_).Trim() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($effectiveWriteAllowList.Count -eq 0) {
        throw 'WRITER_ALLOWLIST_REQUIRED: New-Workspace requires a non-empty WriteAllowList'
    }
    try {
        $rootItem = Get-Item -LiteralPath $root -Force -ErrorAction Stop
        $rootLinkType = $rootItem.PSObject.Properties['LinkType']
        $rootIsReparse = (([System.IO.FileAttributes]$rootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
        if ($rootIsReparse -or ($rootLinkType -and -not [string]::IsNullOrWhiteSpace([string]$rootLinkType.Value))) {
            throw "REPARSE_POINT_FORBIDDEN: repository root '$root' is a link or reparse point"
        }
    } catch {
        if ($_.Exception.Message -match '^REPARSE_POINT_FORBIDDEN:') { throw }
        throw "REPO_ROOT_UNVERIFIABLE: cannot inspect '$root'"
    }
    return [PSCustomObject]@{
        RepoRoot       = $root
        WriteAllowList = [string[]]$effectiveWriteAllowList
        ReadAllowList  = $ReadAllowList
        # known_file_states: path -> FileState (lazy)
        KnownStates    = [System.Collections.Generic.Dictionary[string,FileState]]::new()
        InitialStates  = [System.Collections.Generic.Dictionary[string,FileState]]::new()
    }
}

function Assert-WorkspaceItemSafe {
    param(
        [Parameter(Mandatory)]$Item,
        [Parameter(Mandatory)][string]$FullPath,
        [Parameter(Mandatory)][string]$Segment
    )
    try {
        $linkTypeProp = $Item.PSObject.Properties['LinkType']
        $linkType = if ($linkTypeProp) { [string]$linkTypeProp.Value } else { '' }
        $isReparse = (([System.IO.FileAttributes]$Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
        if ($isReparse -or -not [string]::IsNullOrWhiteSpace($linkType)) {
            throw "REPARSE_POINT_FORBIDDEN: link/reparse component '$Segment' ($FullPath)"
        }
        if (-not $Item.PSIsContainer) {
            $linkCountProp = $Item.PSObject.Properties['LinkCount']
            if ($linkCountProp -and $null -ne $linkCountProp.Value) {
                $linkCount = [int]$linkCountProp.Value
            } elseif ($IsWindows) {
                try { $linkCount = [int][DswRunnerLinkInfo]::GetLinkCount($FullPath) }
                catch { throw "HARDLINK_COUNT_UNAVAILABLE: cannot verify hard-link count for '$FullPath'" }
            } else {
                throw "HARDLINK_COUNT_UNAVAILABLE: cannot verify hard-link count for '$FullPath'"
            }
            if ($linkCount -gt 1) {
                throw "REPARSE_POINT_FORBIDDEN: hardlink component '$Segment' ($FullPath)"
            }
        }
    } catch {
        if ($_.Exception.Message -match '^(REPARSE_POINT_FORBIDDEN|HARDLINK_COUNT_UNAVAILABLE):') { throw }
        throw "PATH_COMPONENT_UNVERIFIABLE: cannot inspect '$FullPath'"
    }
}

function Resolve-WorkspacePath {
    param(
        [Parameter(Mandatory)]$Workspace,
        [Parameter(Mandatory)][string]$RelativePath,
        [ValidateSet('Read','Write')][string]$Mode = 'Read'
    )
    $rel = Get-NormalizedRelativePath -Path $RelativePath -RepoRoot $Workspace.RepoRoot
    if (Test-PathIsSensitive -RelativePath $rel) {
        throw "SENSITIVE_PATH: $rel"
    }
    # reparse / junction simple check (Linux symlink, Windows reparse)
    $full = if ([string]::IsNullOrEmpty($rel)) {
        $Workspace.RepoRoot
    } else {
        Join-Path $Workspace.RepoRoot ($rel -replace '/','\')  # OS will handle
    }
    $full = [System.IO.Path]::GetFullPath($full)
    $rootFull = $Workspace.RepoRoot
    $relativeCheck = [System.IO.Path]::GetRelativePath($rootFull, $full)
    if ([System.IO.Path]::IsPathRooted($relativeCheck) -or
        $relativeCheck -eq '..' -or
        $relativeCheck.StartsWith('../', [StringComparison]::Ordinal) -or
        $relativeCheck.StartsWith('..\', [StringComparison]::Ordinal)) {
        throw "PATH_OUTSIDE_REPOSITORY: $RelativePath"
    }
    # Every existing path component, including the final leaf, must be an
    # ordinary singly-linked entry.  This is used by read/search/list as well
    # as edits, so a traversal result can never be used before its leaf has
    # been checked for symlink/junction/reparse/hardlink indirection.
    $segments = @($rel -split '/' | Where-Object { $_ -ne '' })
    $walk = $rootFull
    foreach ($seg in $segments) {
        $walk = Join-Path $walk $seg
        try {
            $item = Get-Item -LiteralPath $walk -Force -ErrorAction Stop
        } catch {
            if ($_.Exception -is [System.Management.Automation.ItemNotFoundException]) { break }
            throw "PATH_COMPONENT_UNVERIFIABLE: cannot inspect '$walk'"
        }
        Assert-WorkspaceItemSafe -Item $item -FullPath $walk -Segment $seg
    }
    if ($Mode -eq 'Write') {
        $allowed = $false
        foreach ($a in $Workspace.WriteAllowList) {
            $an = ($a -replace '\\','/').TrimEnd('/')
            if ($an -eq '.' -or $an -eq '*' -or $rel -eq $an -or
                $rel.StartsWith("$an/", [StringComparison]::OrdinalIgnoreCase)) {
                $allowed = $true
                break
            }
        }
        if (-not $allowed) { throw "PATH_NOT_WRITE_ALLOWLISTED: $rel" }
    }
    elseif ($Workspace.ReadAllowList.Count -gt 0 -and
        -not (Test-WorkspacePathAllowed -RelativePath $rel -AllowList $Workspace.ReadAllowList)) {
        throw "PATH_NOT_READ_ALLOWLISTED: $rel"
    }
    return @{
        Relative = $rel
        Full     = $full
    }
}

function Get-OrRecordFileState {
    param(
        [Parameter(Mandatory)]$Workspace,
        [Parameter(Mandatory)][string]$RelativePath,
        [bool]$AsInitial = $false,
        [bool]$ForceRefresh = $false
    )
    $key = $RelativePath -replace '\\','/'
    if (-not $ForceRefresh -and $Workspace.KnownStates.ContainsKey($key)) {
        return $Workspace.KnownStates[$key]
    }
    $resolved = Resolve-WorkspacePath -Workspace $Workspace -RelativePath $key -Mode Read
    $exists = Test-Path -LiteralPath $resolved.Full -PathType Leaf
    $state = [FileState]::new()
    $state.Path = $key
    $state.Exists = $exists
    if ($exists) {
        $state.Sha256 = Get-FileSha256Exact -FullPath $resolved.Full
        $state.Size = (Get-Item -LiteralPath $resolved.Full).Length
    } else {
        $state.Sha256 = $null
        $state.Size = 0
    }
    $Workspace.KnownStates[$key] = $state
    if ($AsInitial -and -not $Workspace.InitialStates.ContainsKey($key)) {
        $init = [FileState]::new()
        $init.Path = $state.Path
        $init.Exists = $state.Exists
        $init.Sha256 = $state.Sha256
        $init.Size = $state.Size
        $Workspace.InitialStates[$key] = $init
    }
    return $state
}

function Get-SafeUtf8SliceEnd {
    param(
        [byte[]]$Bytes,
        [int]$Start,
        [int]$EndExclusive
    )
    # Returns the largest index in [Start, EndExclusive] that ends on a complete UTF-8 character boundary.
    if ($EndExclusive -le $Start) { return $Start }
    if ($EndExclusive -gt $Bytes.Length) { $EndExclusive = $Bytes.Length }

    # Walk back over trailing continuation bytes (10xxxxxx)
    $pos = $EndExclusive - 1
    while ($pos -ge $Start -and ($Bytes[$pos] -band 0xC0) -eq 0x80) {
        $pos--
    }
    if ($pos -lt $Start) {
        return $Start  # slice is only continuations — nothing complete
    }

    $lead = $Bytes[$pos]
    $needed = 1
    if (($lead -band 0x80) -eq 0x00) {
        $needed = 1
    } elseif (($lead -band 0xE0) -eq 0xC0) {
        $needed = 2
    } elseif (($lead -band 0xF0) -eq 0xE0) {
        $needed = 3
    } elseif (($lead -band 0xF8) -eq 0xF0) {
        $needed = 4
    } else {
        # invalid lead at boundary — cut before it
        return $pos
    }

    $available = $EndExclusive - $pos
    if ($available -ge $needed) {
        return $EndExclusive
    }
    return $pos
}

function Read-WorkspaceFile {
    param(
        [Parameter(Mandatory)]$Workspace,
        [Parameter(Mandatory)][string]$Path,
        [int]$Offset = 0,
        [int]$MaxBytes = 0
    )
    $resolved = Resolve-WorkspacePath -Workspace $Workspace -RelativePath $Path -Mode Read
    $state = Get-OrRecordFileState -Workspace $Workspace -RelativePath $resolved.Relative -AsInitial $true -ForceRefresh $true
    if (-not $state.Exists) {
        return @{
            ok = $false
            error = 'FILE_NOT_FOUND'
            path = $resolved.Relative
            sha = $null
            content = $null
        }
    }

    # Always work from original file bytes (exact, no re-encode roundtrip)
    $allBytes = [System.IO.File]::ReadAllBytes($resolved.Full)
    $totalBytes = $allBytes.Length
    $state.Size = $totalBytes
    $defaultCap = 120000
    $cap = if ($MaxBytes -gt 0) { $MaxBytes } else { $defaultCap }
    $start = [Math]::Max(0, $Offset)

    if ($start -ge $totalBytes) {
        return @{
            ok = $true
            path = $resolved.Relative
            sha = $state.Sha256
            size = $totalBytes
            content = ''
            offset = $start
            truncated = $false
            bytes_returned = 0
            next_offset = $totalBytes
        }
    }

    $candidateEnd = [Math]::Min($start + $cap, $totalBytes)
    $safeEnd = Get-SafeUtf8SliceEnd -Bytes $allBytes -Start $start -EndExclusive $candidateEnd
    $bytesReturned = $safeEnd - $start

    if ($bytesReturned -le 0) {
        # max_bytes too small to hold even one complete UTF-8 character at this offset
        return @{
            ok = $false
            error = 'UTF8_CHUNK_TOO_SMALL'
            path = $resolved.Relative
            sha = $state.Sha256
            size = $totalBytes
            content = $null
            offset = $start
            message = "max_bytes=$cap cannot fit a complete UTF-8 character at offset $start. Increase max_bytes (character may need up to 4 bytes)."
        }
    }

    $slice = New-Object byte[] $bytesReturned
    [Array]::Copy($allBytes, $start, $slice, 0, $bytesReturned)

    # Strict decode: throw on invalid sequences (no U+FFFD)
    $utf8Strict = New-Object System.Text.UTF8Encoding $false, $true
    try {
        $content = $utf8Strict.GetString($slice)
    } catch {
        return @{
            ok = $false
            error = 'UTF8_DECODE_FAILED'
            path = $resolved.Relative
            sha = $state.Sha256
            size = $totalBytes
            content = $null
            offset = $start
            message = $_.Exception.Message
        }
    }

    # Guard: never return replacement char
    if ($content.Contains([char]0xFFFD)) {
        return @{
            ok = $false
            error = 'UTF8_REPLACEMENT_DETECTED'
            path = $resolved.Relative
            sha = $state.Sha256
            size = $totalBytes
            content = $null
            offset = $start
            message = 'Decoded chunk contained U+FFFD; refusing to return corrupted text.'
        }
    }

    $truncated = ($safeEnd -lt $totalBytes)
    $result = @{
        ok = $true
        path = $resolved.Relative
        sha = $state.Sha256
        size = $totalBytes
        content = $content
        offset = $start
        truncated = $truncated
        bytes_returned = $bytesReturned
        next_offset = $safeEnd
    }
    if ($truncated) {
        $result.hint = "TRUNCATED at byte offset $safeEnd of $totalBytes. Call read_file again with offset=$safeEnd to continue."
    }
    return $result
}

function Search-WorkspaceText {
    param(
        [Parameter(Mandatory)]$Workspace,
        [Parameter(Mandatory)][string]$Query,
        [string]$PathPrefix = '',
        [int]$MaxResults = 50
    )
    $results = [System.Collections.Generic.List[object]]::new()
    $root = $Workspace.RepoRoot
    $searchRoot = if ($PathPrefix) {
        $r = Resolve-WorkspacePath -Workspace $Workspace -RelativePath $PathPrefix -Mode Read
        $r.Full
    } else { $root }

    $excludeDirs = @(
        'node_modules', '.venv', 'venv', 'dist', 'build', 'coverage',
        '__pycache__', '.cache', '.next', '.git', '.tox', '.mypy_cache',
        '.pytest_cache', 'vendor', 'bower_components'
    )
    $maxFileBytes = 2MB

    Get-ChildItem -LiteralPath $searchRoot -Recurse -File -ErrorAction SilentlyContinue |
        ForEach-Object {
            if ($results.Count -ge $MaxResults) { return }
            $candidate = $_
            $rel = $candidate.FullName.Substring($root.Length).TrimStart('\','/') -replace '\\','/'
            if (Test-PathIsSensitive -RelativePath $rel) { return }
            if (-not (Test-WorkspacePathAllowed -RelativePath $rel -AllowList $Workspace.ReadAllowList)) { return }
            foreach ($part in ($rel -split '/')) {
                if ($excludeDirs -contains $part) { return }
            }
            if ($candidate.Length -gt $maxFileBytes) { return }

            # Enumeration is not authorization. Before opening every leaf,
            # resolve its final path and every ancestor through the same
            # fail-closed link/reparse/hardlink guard used by direct reads.
            try {
                $verified = Resolve-WorkspacePath -Workspace $Workspace -RelativePath $rel -Mode Read
                if (-not (Test-Path -LiteralPath $verified.Full -PathType Leaf)) { return }
                $text = Get-FileContentExact -FullPath $verified.Full
            } catch {
                # Search/list never expose or open an unverified candidate.
                return
            }

            if ($text -match [regex]::Escape($Query) -or $text.Contains($Query)) {
                # simple line-oriented hits
                $lines = $text -split "`n"
                for ($i = 0; $i -lt $lines.Count; $i++) {
                    if ($lines[$i].Contains($Query)) {
                        $results.Add([PSCustomObject]@{
                            path = $verified.Relative
                            line = $i + 1
                            text = $lines[$i].Substring(0, [Math]::Min(200, $lines[$i].Length))
                        })
                        if ($results.Count -ge $MaxResults) { break }
                    }
                }
            }
        }
    return [object[]]@($results.ToArray())
}

function Get-WorkspaceFileList {
    param(
        [Parameter(Mandatory)]$Workspace,
        [string]$Path = '',
        [int]$MaxDepth = 4
    )
    $resolved = if ($Path) {
        Resolve-WorkspacePath -Workspace $Workspace -RelativePath $Path -Mode Read
    } else {
        @{ Relative = ''; Full = $Workspace.RepoRoot }
    }
    $excludeDirs = @('node_modules','.venv','venv','dist','build','coverage','__pycache__','.cache','.next','.git','.tox','vendor')
    $items = [System.Collections.Generic.List[object]]::new()
    function Walk([string]$dir, [string]$rel, [int]$depth) {
        if ($depth -gt $MaxDepth) { return }
        Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue | ForEach-Object {
            $name = $_.Name
            if ($excludeDirs -contains $name) { return }
            $childRel = if ($rel) { "$rel/$name" } else { $name }
            $childRel = $childRel -replace '\\','/'
            if (Test-PathIsSensitive -RelativePath $childRel) { return }
            if (-not (Test-WorkspacePathAllowed -RelativePath $childRel -AllowList $Workspace.ReadAllowList -AllowAncestor)) { return }
            try {
                # A list entry is a capability disclosure. Do not surface a
                # leaf or descend into a directory until Resolve verifies its
                # final component and all ancestors as non-link paths.
                $verified = Resolve-WorkspacePath -Workspace $Workspace -RelativePath $childRel -Mode Read
            } catch {
                return
            }
            if ($_.PSIsContainer) {
                $items.Add([PSCustomObject]@{ path = $verified.Relative; type = 'dir' })
                Walk $verified.Full $verified.Relative ($depth + 1)
            } else {
                $items.Add([PSCustomObject]@{ path = $verified.Relative; type = 'file'; size = $_.Length })
            }
        }
    }
    Walk $resolved.Full $resolved.Relative 0
    return [object[]]@($items.ToArray())
}

function Assert-Fresh {
    param(
        [Parameter(Mandatory)]$Workspace,
        [Parameter(Mandatory)][string]$Path,
        [string]$ExpectedSha   # known_preimage_sha
    )
    $state = Get-OrRecordFileState -Workspace $Workspace -RelativePath $Path -ForceRefresh $true
    if (-not $state.Exists) {
        if ($ExpectedSha) {
            return @{ ok = $false; error = 'FILE_NOT_FRESH'; message = "Expected sha $ExpectedSha but file is MISSING" }
        }
        return @{ ok = $true; state = $state }  # expected missing
    }
    if ($ExpectedSha -and $state.Sha256 -ne $ExpectedSha) {
        return @{ ok = $false; error = 'FILE_NOT_FRESH'; live_sha = $state.Sha256; expected = $ExpectedSha }
    }
    return @{ ok = $true; state = $state }
}

function Get-NetChangedPaths {
    param([Parameter(Mandatory)]$Workspace)
    $changed = [System.Collections.Generic.List[string]]::new()
    foreach ($key in $Workspace.KnownStates.Keys) {
        $cur = $Workspace.KnownStates[$key]
        if (-not $Workspace.InitialStates.ContainsKey($key)) {
            # created during session and still exists, or was read after create?
            if ($cur.Exists) { $changed.Add($key) }
            continue
        }
        $init = $Workspace.InitialStates[$key]
        if ($init.Exists -ne $cur.Exists) {
            $changed.Add($key)
            continue
        }
        if ($init.Exists -and $init.Sha256 -ne $cur.Sha256) {
            $changed.Add($key)
        }
    }
    # also check Initial that became missing but never re-recorded? we force refresh on known
    return @($changed)
}

function Restore-WorkspaceFileStates {
    param(
        [Parameter(Mandatory)]$Workspace,
        [Parameter(Mandatory)][ValidateSet('Initial','Known')][string]$Kind,
        [object[]]$States = @()
    )
    $target = if ($Kind -eq 'Initial') { $Workspace.InitialStates } else { $Workspace.KnownStates }
    foreach ($saved in @($States)) {
        $pathProp = $saved.PSObject.Properties['path']
        $path = if ($pathProp) { [string]$pathProp.Value } else { '' }
        if ([string]::IsNullOrWhiteSpace($path)) { throw 'CHECKPOINT_INVALID: file state path is missing' }
        $state = [FileState]::new()
        $state.Path = $path
        $existsProp = $saved.PSObject.Properties['exists']
        $shaProp = $saved.PSObject.Properties['sha256']
        $sizeProp = $saved.PSObject.Properties['size']
        $state.Exists = if ($existsProp) { [bool]$existsProp.Value } else { $false }
        $state.Sha256 = if ($shaProp) { [string]$shaProp.Value } else { $null }
        $state.Size = if ($sizeProp) { [long]$sizeProp.Value } else { 0 }
        $target[$path] = $state
    }
}

Export-ModuleMember -Function @(
    'New-Workspace',
    'Resolve-WorkspacePath',
    'Get-OrRecordFileState',
    'Read-WorkspaceFile',
    'Search-WorkspaceText',
    'Get-WorkspaceFileList',
    'Assert-Fresh',
    'Get-NetChangedPaths',
    'Restore-WorkspaceFileStates',
    'Get-FileSha256Exact',
    'Write-FileExactUtf8NoBom',
    'Get-NormalizedRelativePath',
    'Test-PathIsSensitive'
)
