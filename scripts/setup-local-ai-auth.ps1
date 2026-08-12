#requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$ValidateOnly,
    [switch]$Replace
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$targetPath = [System.IO.Path]::GetFullPath('C:\sswcenter\api-keys.local.env')
$targetDirectory = [System.IO.Path]::GetDirectoryName($targetPath)
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)

function Assert-LocalAiAuthFile {
    if (-not [System.IO.File]::Exists($targetPath)) {
        throw 'LOCAL_AI_AUTH_FILE_MISSING'
    }
    $lines = [System.IO.File]::ReadAllLines($targetPath, $utf8)
    $matches = @($lines | Where-Object { $_ -match '^\s*DEEPSEEK_API_KEY\s*=' })
    if ($matches.Count -ne 1) { throw 'LOCAL_AI_AUTH_ENTRY_COUNT_INVALID' }
    $value = ([string]$matches[0] -replace '^\s*DEEPSEEK_API_KEY\s*=\s*', '').Trim().Trim('"').Trim("'")
    if ([string]::IsNullOrWhiteSpace($value)) { throw 'LOCAL_AI_AUTH_KEY_EMPTY' }
}

if ($ValidateOnly) {
    Assert-LocalAiAuthFile
    Write-Output ('LOCAL_AI_AUTH=PASS PATH=' + $targetPath)
    exit 0
}

if ([System.IO.File]::Exists($targetPath) -and -not $Replace) {
    throw 'LOCAL_AI_AUTH_FILE_EXISTS: pass -Replace only when replacement is intentional'
}
if (-not [System.IO.Directory]::Exists($targetDirectory)) {
    throw 'LOCAL_AI_AUTH_PARENT_MISSING: create C:\sswcenter first'
}
$directory = [System.IO.DirectoryInfo]::new($targetDirectory)
if (($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'LOCAL_AI_AUTH_PARENT_REPARSE_POINT_FORBIDDEN'
}

$secureKey = Read-Host 'DeepSeek API key (input is hidden)' -AsSecureString
$pointer = [IntPtr]::Zero
$plainText = ''
$temporaryPath = Join-Path $targetDirectory ('api-keys.local.env.' + [guid]::NewGuid().ToString('N') + '.tmp')
try {
    $pointer = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $plainText = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if ([string]::IsNullOrWhiteSpace($plainText)) { throw 'LOCAL_AI_AUTH_KEY_EMPTY' }
    if ($plainText.IndexOfAny([char[]]@("`r", "`n", [char]0)) -ge 0) {
        throw 'LOCAL_AI_AUTH_KEY_INVALID_CHARACTER'
    }
    [System.IO.File]::WriteAllText($temporaryPath, 'DEEPSEEK_API_KEY=' + $plainText + [Environment]::NewLine, $utf8)
    if ([System.IO.File]::Exists($targetPath)) {
        [System.IO.File]::Move($temporaryPath, $targetPath, $true)
    }
    else {
        [System.IO.File]::Move($temporaryPath, $targetPath)
    }
    Assert-LocalAiAuthFile
    Write-Output ('LOCAL_AI_AUTH=CREATED PATH=' + $targetPath)
}
finally {
    $plainText = $null
    if ($pointer -ne [IntPtr]::Zero) {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    if ([System.IO.File]::Exists($temporaryPath)) {
        [System.IO.File]::Delete($temporaryPath)
    }
}
