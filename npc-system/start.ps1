$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path '.venv-win/Scripts/python.exe')) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv .venv-win
    } else {
        & python -m venv .venv-win
    }
    if ($LASTEXITCODE -ne 0) { throw 'Python venv creation failed. Install Python 3.12 or newer.' }
}
$NpcPython = Join-Path $PSScriptRoot '.venv-win/Scripts/python.exe'
& $NpcPython -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ required"'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or newer is required.' }
& $NpcPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }

Push-Location frontend
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed. Install a supported Node.js LTS version.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }

Write-Host 'Open http://127.0.0.1:8000 ; Ctrl+C to stop.'
Write-Host 'Configure DEEPSEEK_API_KEY in .env for real dialogue. Rules work without an API key.'
& $NpcPython -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
exit $LASTEXITCODE
