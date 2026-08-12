param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WorkspaceRoot = Split-Path -Parent $PSScriptRoot
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$FrontendRoot = Join-Path $WorkspaceRoot "frontend"
$PythonExe = Join-Path $BackendRoot ".venv\Scripts\python.exe"
$NpmExe = "C:\Program Files\nodejs\npm.cmd"
$NodeRoot = Split-Path -Parent $NpmExe

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Backend virtual environment is missing"
}
if (-not (Test-Path -LiteralPath $NpmExe)) {
    throw "Node.js is missing"
}

$BackendJob = Start-Job -ScriptBlock {
    param($WorkingDirectory, $PythonPath)
    Set-Location -LiteralPath $WorkingDirectory
    & $PythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
} -ArgumentList $BackendRoot, $PythonExe

$FrontendJob = Start-Job -ScriptBlock {
    param($WorkingDirectory, $NpmPath, $NodePath)
    Set-Location -LiteralPath $WorkingDirectory
    $env:Path = "$NodePath;$env:Path"
    & $NpmPath run dev -- --host 127.0.0.1
} -ArgumentList $FrontendRoot, $NpmExe, $NodeRoot

try {
    Write-Output "Backend: http://127.0.0.1:8000"
    Write-Output "Frontend: http://127.0.0.1:5173"
    Write-Output "Press Ctrl+C to stop both development servers."
    Wait-Job -Job $BackendJob, $FrontendJob -Any | Out-Null
    Receive-Job -Job $BackendJob, $FrontendJob
    throw "A development server stopped unexpectedly"
}
finally {
    Stop-Job -Job $BackendJob, $FrontendJob -ErrorAction SilentlyContinue
    Remove-Job -Job $BackendJob, $FrontendJob -Force -ErrorAction SilentlyContinue
}
