param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Live = Invoke-RestMethod -Method Get -Uri "$BaseUrl/health/live"
if ($Live.status -ne "ok") {
    throw "Liveness check failed"
}

try {
    $Ready = Invoke-RestMethod -Method Get -Uri "$BaseUrl/health/ready"
}
catch {
    throw "Readiness check failed: $($_.Exception.Message)"
}

if ($Ready.status -ne "ok") {
    throw "Readiness check did not return ok"
}
