Set-StrictMode -Version Latest

function ConvertFrom-SswPostgresUrl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DatabaseUrl
    )

    $NormalizedUrl = $DatabaseUrl -replace '^postgresql\+psycopg://', 'postgresql://'
    try {
        $Parsed = [Uri]$NormalizedUrl
    }
    catch {
        throw "Invalid PostgreSQL URL"
    }
    if ($Parsed.Scheme -ne "postgresql") {
        throw "Only PostgreSQL URLs are supported"
    }
    $UserInfo = $Parsed.UserInfo -split ":", 2
    if ($UserInfo.Count -lt 1 -or [string]::IsNullOrWhiteSpace($UserInfo[0])) {
        throw "PostgreSQL URL must include a user"
    }
    $DatabaseName = [Uri]::UnescapeDataString($Parsed.AbsolutePath.TrimStart("/"))
    if ([string]::IsNullOrWhiteSpace($DatabaseName)) {
        throw "PostgreSQL URL must include a database name"
    }
    $Port = if ($Parsed.IsDefaultPort) { 5432 } else { $Parsed.Port }
    $Password = if ($UserInfo.Count -eq 2) {
        [Uri]::UnescapeDataString($UserInfo[1])
    }
    else {
        ""
    }

    [PSCustomObject]@{
        Host = $Parsed.Host
        Port = $Port
        User = [Uri]::UnescapeDataString($UserInfo[0])
        Password = $Password
        Database = $DatabaseName
    }
}

function Get-SswPostgresExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $BundledPath = Join-Path "C:\Program Files\PostgreSQL\17\bin" $Name
    if (Test-Path -LiteralPath $BundledPath) {
        return $BundledPath
    }
    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $Command) {
        throw "Required PostgreSQL executable is missing: $Name"
    }
    return $Command.Source
}

function Get-SswRelativePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BasePath,
        [Parameter(Mandatory = $true)]
        [string]$TargetPath
    )

    $ResolvedBase = [System.IO.Path]::GetFullPath($BasePath).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $ResolvedTarget = [System.IO.Path]::GetFullPath($TargetPath)
    $Prefix = $ResolvedBase + [System.IO.Path]::DirectorySeparatorChar
    if (-not $ResolvedTarget.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Target path is outside the expected base path"
    }
    return $ResolvedTarget.Substring($Prefix.Length)
}

function Invoke-WithPgPassword {
    param(
        [AllowEmptyString()]
        [string]$Password,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action
    )

    $HadPassword = Test-Path Env:PGPASSWORD
    $PreviousPassword = $env:PGPASSWORD
    try {
        if ($Password) {
            $env:PGPASSWORD = $Password
        }
        else {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
        & $Action
    }
    finally {
        if ($HadPassword) {
            $env:PGPASSWORD = $PreviousPassword
        }
        else {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
    }
}

Export-ModuleMember -Function ConvertFrom-SswPostgresUrl
Export-ModuleMember -Function Get-SswPostgresExecutable
Export-ModuleMember -Function Get-SswRelativePath
Export-ModuleMember -Function Invoke-WithPgPassword
