$script:W1ARRNPattern = '(?<![0-9])(?:[0-9]{6}(?:[-_/:.\t ][0-9]{7})|[0-9]{13})(?![0-9])'
$script:W1ARRNVectorPath = Join-Path $PSScriptRoot "w1a-rrn-vectors.json"
$script:W1ARRNCenturyByCode = @{
    "0" = 1800
    "1" = 1900
    "2" = 1900
    "3" = 2000
    "4" = 2000
    "5" = 1900
    "6" = 1900
    "7" = 2000
    "8" = 2000
    "9" = 1800
}
$script:W1ARRNTimestampMarkers = @(
    "created_at",
    "created at",
    "updated_at",
    "updated at",
    "timestamp",
    "epoch",
    "unix",
    "millis",
    "milliseconds",
    "time_ms",
    "occurred_at",
    "issued_at",
    "logged_at",
    "datetime",
    "타임스탬프",
    "시간"
)
$script:W1ARRNSensitiveMarkers = @(
    "resident_number",
    "resident number",
    "registration_number",
    "registration number",
    "rrn",
    "resident",
    "identity",
    "social security",
    "주민등록",
    "주민번호"
)

function Get-W1ARRNVectorData {
    if (-not (Test-Path -LiteralPath $script:W1ARRNVectorPath -PathType Leaf)) {
        throw "W1A_RRN_VECTOR_FAILURE: vector file is missing"
    }
    $encoding = [System.Text.UTF8Encoding]::new($false, $true)
    try {
        $json = [System.IO.File]::ReadAllText($script:W1ARRNVectorPath, $encoding)
        return $json | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "W1A_RRN_VECTOR_FAILURE: vector file could not be read"
    }
}

function Get-W1ARRNVectorCases {
    $data = Get-W1ARRNVectorData
    $cases = New-Object System.Collections.Generic.List[object]
    foreach ($propertyName in @("rrnCases", "boundaryCases", "delimiterCases", "negativeCases", "epochCases")) {
        $property = $data.PSObject.Properties[$propertyName]
        if ($null -ne $property -and $null -ne $property.Value) {
            foreach ($case in @($property.Value)) {
                $cases.Add($case)
            }
        }
    }
    return $cases.ToArray()
}

function New-W1ARRNVectorValue {
    param([Parameter(Mandatory = $true)] [object]$Case)

    if ([string]$Case.kind -eq "epoch-ms") {
        try {
            $dateTime = [DateTimeOffset]::Parse(
                [string]$Case.iso,
                [System.Globalization.CultureInfo]::InvariantCulture,
                [System.Globalization.DateTimeStyles]::AssumeUniversal
            )
            return $dateTime.ToUnixTimeMilliseconds().ToString(
                [System.Globalization.CultureInfo]::InvariantCulture
            )
        } catch {
            throw "W1A_RRN_VECTOR_FAILURE: epoch vector could not be constructed"
        }
    }

    if ([string]$Case.kind -ne "rrn") {
        throw "W1A_RRN_VECTOR_FAILURE: unknown vector kind"
    }
    return [string]::Concat(
        [string]$Case.birthDate,
        [string]$Case.separator,
        [string]$Case.genderCode,
        [string]$Case.serial
    )
}

function New-W1ARRNVectorText {
    param([Parameter(Mandatory = $true)] [object]$Case)

    return [string]::Concat(
        [string]$Case.prefix,
        (New-W1ARRNVectorValue -Case $Case),
        [string]$Case.suffix
    )
}

function Test-W1AValidRRNDigits {
    param([Parameter(Mandatory = $true)] [string]$Digits)

    if ($Digits -notmatch '^[0-9]{13}$') { return $false }
    $code = $Digits.Substring(6, 1)
    $century = $script:W1ARRNCenturyByCode[$code]
    if ($null -eq $century) { return $false }

    try {
        [DateTime]::new(
            ($century + [int]$Digits.Substring(0, 2)),
            [int]$Digits.Substring(2, 2),
            [int]$Digits.Substring(4, 2)
        ) | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Get-W1AContext {
    param(
        [Parameter(Mandatory = $true)] [string]$Text,
        [Parameter(Mandatory = $true)] [int]$Start,
        [Parameter(Mandatory = $true)] [int]$Length
    )

    $contextStart = [Math]::Max(0, $Start - 64)
    $contextEnd = [Math]::Min($Text.Length, $Start + $Length + 64)
    return $Text.Substring($contextStart, $contextEnd - $contextStart).ToLowerInvariant()
}

function Test-W1AContextMarker {
    param(
        [Parameter(Mandatory = $true)] [string]$Context,
        [Parameter(Mandatory = $true)] [string[]]$Markers
    )

    foreach ($marker in $Markers) {
        if ($Context.IndexOf($marker, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            return $true
        }
    }
    return $false
}

function Test-W1AEpochContext {
    param(
        [Parameter(Mandatory = $true)] [string]$Text,
        [Parameter(Mandatory = $true)] [System.Text.RegularExpressions.Match]$Match,
        [Parameter(Mandatory = $true)] [string]$Digits
    )

    if ($Match.Value.IndexOfAny([char[]]@("-", "_", "/", ":", ".", " ", "`t")) -ge 0) {
        return $false
    }
    if ($Digits.Length -ne 13) { return $false }

    $numeric = 0L
    if (-not [long]::TryParse(
        $Digits,
        [System.Globalization.NumberStyles]::Integer,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [ref]$numeric
    )) {
        return $false
    }

    $epochMinimum = [DateTimeOffset]::Parse(
        "1970-01-01T00:00:00Z",
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AssumeUniversal
    ).ToUnixTimeMilliseconds()
    $epochMaximum = [DateTimeOffset]::Parse(
        "2100-01-01T00:00:00Z",
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AssumeUniversal
    ).ToUnixTimeMilliseconds()
    if ($numeric -lt $epochMinimum -or $numeric -gt $epochMaximum) { return $false }

    $context = Get-W1AContext -Text $Text -Start $Match.Index -Length $Match.Length
    $timestampContext = Test-W1AContextMarker -Context $context -Markers $script:W1ARRNTimestampMarkers
    $sensitiveContext = Test-W1AContextMarker -Context $context -Markers $script:W1ARRNSensitiveMarkers
    return $timestampContext -and -not $sensitiveContext
}

function Get-W1ARRNMatchCount {
    param([Parameter(Mandatory = $true)] [AllowEmptyString()] [string]$Text)

    $count = 0
    foreach ($match in [regex]::Matches(
        $Text,
        $script:W1ARRNPattern,
        [System.Text.RegularExpressions.RegexOptions]::CultureInvariant
    )) {
        $digits = $match.Value -replace '[^0-9]', ''
        if (-not (Test-W1AValidRRNDigits -Digits $digits)) { continue }
        if (Test-W1AEpochContext -Text $Text -Match $match -Digits $digits) { continue }
        $count++
    }
    return [int]$count
}

function Test-W1ARRNVectorParity {
    $cases = @(Get-W1ARRNVectorCases)
    $sensitiveCount = 0
    $negativeCount = 0
    foreach ($case in $cases) {
        $text = New-W1ARRNVectorText -Case $case
        $actual = Get-W1ARRNMatchCount -Text $text
        $expected = [bool]$case.expectedSensitive
        if ($expected) { $sensitiveCount++ } else { $negativeCount++ }
        if ($expected -and $actual -eq 0) {
            throw "W1A_RRN_VECTOR_FAILURE: expected sensitive vector was missed"
        }
        if (-not $expected -and $actual -ne 0) {
            throw "W1A_RRN_VECTOR_FAILURE: expected negative vector was detected"
        }
    }
    return [PSCustomObject]@{
        Total = $cases.Count
        Sensitive = $sensitiveCount
        Negative = $negativeCount
    }
}
