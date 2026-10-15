$ErrorActionPreference = "Stop"
$backend = Join-Path $PSScriptRoot "backend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"

Write-Host "TraceGuard V2 setup - standard Python 3.12 is required." -ForegroundColor Cyan
if (-not (Test-Path $backend)) { throw "Could not find backend folder at $backend" }
if (-not (Test-Path $venvPython)) {
    Push-Location $backend
    try {
        & py -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Could not create venv. Install standard Python 3.12 and confirm 'py -3.12 --version' works." }
    } finally { Pop-Location }
}
if (-not (Test-Path $venvPython)) { throw "Expected virtualenv interpreter was not created: $venvPython" }

& $venvPython -c "import sys; print('Using:', sys.executable); print('Python:', sys.version.split()[0]); assert sys.version_info[:2] == (3, 12), 'Use standard Python 3.12 for this setup.'"
if ($LASTEXITCODE -ne 0) { throw "The backend .venv is not using Python 3.12. Delete backend\.venv and rerun setup." }
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $venvPython -m pip install -r (Join-Path $backend "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed" }

Push-Location $backend
try {
    & $venvPython seed.py
    if ($LASTEXITCODE -ne 0) { throw "Demo data seeding failed" }
} finally { Pop-Location }
Write-Host "`nBackend setup complete." -ForegroundColor Green
Write-Host "Start backend: cd backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
Write-Host "Then start frontend in another terminal: cd frontend; npm install; npm run dev"
