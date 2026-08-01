# Local CI before push/CD (PowerShell).
# Prereq: MySQL up. Starts Flask on 8080 if not already listening.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Repo = Split-Path -Parent $Root
Set-Location $Root

Write-Host "== prepare E2E env =="
python local_tests/prepare_e2e_env.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== pytest =="
python -m pytest tests/ -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$flaskAlready = $false
try {
  $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 8080 -WarningAction SilentlyContinue
  $flaskAlready = $tcp.TcpTestSucceeded
} catch { $flaskAlready = $false }

$flaskProc = $null
if (-not $flaskAlready) {
  Write-Host "== start Flask :8080 =="
  $flaskProc = Start-Process -FilePath "python" -ArgumentList "run.py" -WorkingDirectory $Root -PassThru -WindowStyle Hidden
  $ready = $false
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 1
    try {
      $r = Invoke-WebRequest -Uri "http://127.0.0.1:8080/" -UseBasicParsing -TimeoutSec 2
      if ($r.StatusCode -ge 200) { $ready = $true; break }
    } catch {}
  }
  if (-not $ready) {
    Write-Host "[FAIL] Flask did not become ready on 8080"
    if ($flaskProc) { Stop-Process -Id $flaskProc.Id -Force -ErrorAction SilentlyContinue }
    exit 1
  }
} else {
  Write-Host "== Flask already on 8080 =="
}

try {
  Write-Host "== Playwright admin (incl. Manage UI money) =="
  Set-Location (Join-Path $Repo "tests\e2e")
  if (-not (Test-Path "node_modules")) { npm install }
  npm run test:ci-local
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  Write-Host "== money E2E suite =="
  Set-Location $Root
  python local_tests/e2e_full_suite.py
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  Write-Host "LOCAL CI PASSED"
  exit 0
} finally {
  if ($flaskProc -and -not $flaskAlready) {
    Stop-Process -Id $flaskProc.Id -Force -ErrorAction SilentlyContinue
  }
}
