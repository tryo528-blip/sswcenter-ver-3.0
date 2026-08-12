$ErrorActionPreference = "Continue"

$WorkspaceRoot = Split-Path -Parent $PSScriptRoot
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$FrontendRoot = Join-Path $WorkspaceRoot "frontend"
. (Join-Path $WorkspaceRoot "scripts\w1a-rrn-detector.ps1")

Write-Output "========================================================="
Write-Output " W1A-VS1 RED Test Suite Runner "
Write-Output " Base SHA: 73ee1c3887de9cfe5af9ceea01724c24d0144ce7"
Write-Output "========================================================="

$Results = @()

# Command 1: backend pytest (semantics, absence, openapi)
Write-Output "`n[1/6] Running backend semantics, absence, openapi pytest..."
Push-Location $BackendRoot
$Output1 = & .venv\Scripts\python.exe -m pytest -q tests/test_w1a_staff_semantics.py tests/test_w1a_staff_absence_contract.py tests/test_w1a_staff_openapi_contract.py 2>&1 | Out-String
$Code1 = $LASTEXITCODE
Pop-Location
Write-Output "Exit Code: $Code1"
$Results += [PSCustomObject]@{
    Index = 1
    Command = "backend: .venv\Scripts\python.exe -m pytest -q tests/test_w1a_staff_semantics.py tests/test_w1a_staff_absence_contract.py tests/test_w1a_staff_openapi_contract.py"
    ExitCode = $Code1
    Output = $Output1
    RequiredMarker = "W1A_SEM_|W1A_ABS_|W1A_OA_"
}

# Command 2: repo root postgres RedOnly
Write-Output "`n[2/6] Running PostgreSQL harness RED test..."
Push-Location $WorkspaceRoot
$Output2 = & powershell -NoProfile -File scripts/test-w1a-vs1-postgres.ps1 -RedOnly 2>&1 | Out-String
$Code2 = $LASTEXITCODE
Pop-Location
Write-Output "Exit Code: $Code2"
$Results += [PSCustomObject]@{
    Index = 2
    Command = "repository root: powershell -NoProfile -File scripts/test-w1a-vs1-postgres.ps1 -RedOnly"
    ExitCode = $Code2
    Output = $Output2
    RequiredMarker = "W1A_DB_"
}

# Command 3: backend pytest API
Write-Output "`n[3/6] Running backend API pytest..."
Push-Location $BackendRoot
$Output3 = & .venv\Scripts\python.exe -m pytest -q tests/test_w1a_staff_api.py 2>&1 | Out-String
$Code3 = $LASTEXITCODE
Pop-Location
Write-Output "Exit Code: $Code3"
$Results += [PSCustomObject]@{
    Index = 3
    Command = "backend: .venv\Scripts\python.exe -m pytest -q tests/test_w1a_staff_api.py"
    ExitCode = $Code3
    Output = $Output3
    RequiredMarker = "W1A_API_"
}

# Command 4: generate openapi types check
Write-Output "`n[4/6] Running OpenAPI typescript drift check..."
Push-Location $WorkspaceRoot
$Output4 = & powershell -NoProfile -File scripts/generate-openapi-types.ps1 -Check 2>&1 | Out-String
$Code4 = $LASTEXITCODE
Pop-Location
Write-Output "Exit Code: $Code4"
$Results += [PSCustomObject]@{
    Index = 4
    Command = "repository root: powershell -NoProfile -File scripts/generate-openapi-types.ps1 -Check"
    ExitCode = $Code4
    Output = $Output4
    RequiredMarker = "W1A_OPENAPI_CONTRACT_FAILURE"
}

# Command 5: frontend vitest
Write-Output "`n[5/6] Running frontend vitest DOM contract..."
Push-Location $FrontendRoot
$Output5 = & npm.cmd exec vitest -- run src/test/W1AStaffPage.test.tsx --environment jsdom 2>&1 | Out-String
$Code5 = $LASTEXITCODE
Pop-Location
Write-Output "Exit Code: $Code5"
$Results += [PSCustomObject]@{
    Index = 5
    Command = "frontend: npm.cmd exec vitest -- run src/test/W1AStaffPage.test.tsx --environment jsdom"
    ExitCode = $Code5
    Output = $Output5
    RequiredMarker = "W1A_UI_"
}

# Command 6: repo root postgres E2ERedOnly
Write-Output "`n[6/6] Running PostgreSQL real PG Playwright E2E RED test..."
Push-Location $WorkspaceRoot
$Output6 = & powershell -NoProfile -File scripts/test-w1a-vs1-postgres.ps1 -E2ERedOnly 2>&1 | Out-String
$Code6 = $LASTEXITCODE
Pop-Location
Write-Output "Exit Code: $Code6"
$Results += [PSCustomObject]@{
    Index = 6
    Command = "repository root: powershell -NoProfile -File scripts/test-w1a-vs1-postgres.ps1 -E2ERedOnly"
    ExitCode = $Code6
    Output = $Output6
    RequiredMarker = "W1A_E2E_"
}

# Validation Gate Checks
$ForbiddenPatterns = @(
    "SyntaxError",
    "ERROR collecting",
    "ImportError while importing",
    "fixture-not-found",
    "command-not-found",
    "missing executable",
    "port-in-use",
    "database connection refused",
    "UndefinedTable",
    "ProgrammingError",
    "Traceback \(most recent call last\)",
    "no tests ran",
    "skipped"
)

$AllValidRed = $true

foreach ($R in $Results) {
    # Check 1: Exit code must be exactly 1
    if ($R.ExitCode -ne 1) {
        Write-Error "INVALID_RED_EXIT_CODE: Step [$($R.Index)] returned ExitCode $($R.ExitCode) instead of 1."
        $AllValidRed = $false
        continue
    }

    # Check 2: Output must contain required stable W1A marker
    if (-not [regex]::IsMatch($R.Output, $R.RequiredMarker)) {
        Write-Error "INVALID_RED_MARKER: Step [$($R.Index)] output missing required marker family '$($R.RequiredMarker)'."
        $AllValidRed = $false
        continue
    }

    # Check 3: Output must NOT contain any forbidden environment/syntax error
    foreach ($Forbidden in $ForbiddenPatterns) {
        if ([regex]::IsMatch($R.Output, $Forbidden)) {
            Write-Error "FORBIDDEN_FAILURE_PATTERN: Step [$($R.Index)] output contains forbidden error '$Forbidden'."
            $AllValidRed = $false
            break
        }
    }
}

# Sensitive Leak Gate Check
$CombinedOutput = ($Results | ForEach-Object { $_.Output }) -join "`n"
$VectorParityPassed = $true
try {
    Test-W1ARRNVectorParity | Out-Null
} catch {
    Write-Error "LEAK_GATE_FAILURE: common RRN vector parity failed"
    $VectorParityPassed = $false
    $AllValidRed = $false
}
$OutputLeakCount = Get-W1ARRNMatchCount -Text $CombinedOutput

Write-Output "`n========================================================="
Write-Output " RED Suite Summary & Leak Gate "
Write-Output "========================================================="

foreach ($R in $Results) {
    Write-Output "[$($R.Index)] ExitCode: $($R.ExitCode) | Marker Verified: YES | Cmd: $($R.Command)"
}

if ($OutputLeakCount -gt 0) {
    Write-Error "LEAK_GATE_FAILURE: sensitive candidates found in RED command output"
    exit 1
} else {
    Write-Output "LEAK_GATE_PASS: no sensitive candidates found in RED command output."
}

Write-Output "`n[7/7] Running independent W1A GREEN leak gate..."
$GreenGateScript = Join-Path $WorkspaceRoot "scripts\verify-w1a-vs1-leak-gate.ps1"
$GreenGateOutput = [string](& powershell -ExecutionPolicy Bypass -NoProfile -File $GreenGateScript 2>&1 | Out-String)
$GreenGateCode = $LASTEXITCODE
if ($GreenGateCode -ne 0) {
    Write-Error "LEAK_GATE_FAILURE: independent W1A GREEN leak gate failed."
    exit 1
}
Write-Output "LEAK_GATE_PASS: independent W1A GREEN leak gate exit 0."

if ($AllValidRed) {
    Write-Output "`nSUCCESS: All 6 RED test commands failed as expected with valid W1A contract assertions."
    exit 0
} else {
    Write-Error "`nFAILURE: One or more test commands did not pass valid RED validation."
    exit 1
}
