[CmdletBinding()]
param()

$expectedValue = "1"
$currentUserValue = [Environment]::GetEnvironmentVariable(
    "PYTHONUTF8",
    [EnvironmentVariableTarget]::User
)
$restartRequired = $currentUserValue -ne $expectedValue

if ($restartRequired) {
    [Environment]::SetEnvironmentVariable(
        "PYTHONUTF8",
        $expectedValue,
        [EnvironmentVariableTarget]::User
    )
}

$env:PYTHONUTF8 = $expectedValue
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue

if ($null -eq $pythonCommand) {
    Write-Output "PYTHONUTF8_USER=1"
    Write-Output "PYTHON_NOT_INSTALLED"
    Write-Output "RESTART_REQUIRED=$($restartRequired.ToString().ToLowerInvariant())"
    exit 0
}

$utf8Mode = & $pythonCommand.Source -c "import sys; print(sys.flags.utf8_mode)"
if ($LASTEXITCODE -ne 0 -or $utf8Mode -ne "1") {
    throw "Python UTF-8 mode verification failed."
}

Write-Output "PYTHONUTF8_USER=1"
Write-Output "PYTHON_UTF8_MODE=$utf8Mode"
Write-Output "RESTART_REQUIRED=$($restartRequired.ToString().ToLowerInvariant())"
