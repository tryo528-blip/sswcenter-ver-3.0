# SemVer 2.0.0 fail-closed helpers for scripts/verify-runtime.ps1.
# Grammar: https://semver.org/#backusnaur-form-grammar-for-valid-semver-versions

Set-StrictMode -Version Latest

function Test-SswcenterNumericIdentifier {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
    return $Value -cmatch '^(0|[1-9][0-9]*)$'
}

function Test-SswcenterPrereleaseIdentifier {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
    if ([string]::IsNullOrEmpty($Value)) {
        return $false
    }
    if ($Value -cmatch '^[0-9]+$') {
        return (Test-SswcenterNumericIdentifier -Value $Value)
    }
    return $Value -cmatch '^[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*$'
}

function Test-SswcenterBuildIdentifier {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
    if ([string]::IsNullOrEmpty($Value)) {
        return $false
    }
    return $Value -cmatch '^[0-9A-Za-z-]+$'
}

function Test-SswcenterStrictSemVer {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
    # Official regex (semver.org FAQ): no leading zeros in major/minor/patch
    # or numeric prerelease identifiers; prerelease/build dot identifiers
    # must be non-empty; build identifiers may have leading zeros.
    $SswcenterStrictSemVerPattern = '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$'
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }
    if ($Value -cnotmatch $SswcenterStrictSemVerPattern) {
        return $false
    }
    $CoreAndBuild = $Value.Split([char]'+', 2)
    $CoreAndPre = $CoreAndBuild[0]
    if ($CoreAndBuild.Length -eq 2) {
        foreach ($BuildIdentifier in $CoreAndBuild[1].Split([char]'.')) {
            if (-not (Test-SswcenterBuildIdentifier -Value $BuildIdentifier)) {
                return $false
            }
        }
    }
    $DashIndex = $CoreAndPre.IndexOf([char]'-')
    $Core = $CoreAndPre
    if ($DashIndex -ge 0) {
        $Core = $CoreAndPre.Substring(0, $DashIndex)
        $Prerelease = $CoreAndPre.Substring($DashIndex + 1)
        foreach ($PrereleaseIdentifier in $Prerelease.Split([char]'.')) {
            if (-not (Test-SswcenterPrereleaseIdentifier -Value $PrereleaseIdentifier)) {
                return $false
            }
        }
    }
    $CoreParts = $Core.Split([char]'.')
    if ($CoreParts.Length -ne 3) {
        return $false
    }
    foreach ($CorePart in $CoreParts) {
        if (-not (Test-SswcenterNumericIdentifier -Value $CorePart)) {
            return $false
        }
    }
    return $true
}

Export-ModuleMember -Function @(
    'Test-SswcenterNumericIdentifier',
    'Test-SswcenterPrereleaseIdentifier',
    'Test-SswcenterBuildIdentifier',
    'Test-SswcenterStrictSemVer'
)
