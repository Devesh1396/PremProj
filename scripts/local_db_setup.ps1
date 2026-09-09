# Bring up the LOCAL development database, migrate it, and set the runtime
# role passwords. Idempotent: safe to re-run.
#
# The Windows equivalent of scripts/local_db_setup.sh, and the local mirror
# of docs/OPERATIONS.md steps 3-6. It never touches docker-compose.yml, the
# `phi` compose project, or the n8n network.
#
#   powershell -ExecutionPolicy Bypass -File scripts\local_db_setup.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\local_db_setup.ps1 -Reset

param([switch]$Reset)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$ComposeFile = "docker-compose.local.yml"
$EnvFile     = ".env.local"

if (-not (Test-Path $EnvFile)) {
    Write-Host "no $EnvFile - copying from .env.local.example"
    Copy-Item ".env.local.example" $EnvFile
}

# Load .env.local into this process AND into the environment, so that
# migrate.py and the test suites below see DATABASE_URL.
$cfg = @{}
foreach ($line in Get-Content $EnvFile) {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $k, $v = $line -split '=', 2
    $k = $k.Trim(); $v = $v.Trim()
    $cfg[$k] = $v
    [Environment]::SetEnvironmentVariable($k, $v, "Process")
}

foreach ($required in @('POSTGRES_DB','POSTGRES_ADMIN_USER','POSTGRES_ADMIN_PASSWORD',
                        'POSTGRES_RUNTIME_USER','POSTGRES_RUNTIME_PASSWORD',
                        'POSTGRES_PRACTITIONER_USER','POSTGRES_PRACTITIONER_PASSWORD',
                        'DATABASE_URL')) {
    if (-not $cfg[$required]) { throw "$required is not set in $EnvFile" }
}

function Invoke-Compose { docker compose -f $ComposeFile --env-file $EnvFile @args }
function Invoke-PsqlAdmin {
    Invoke-Compose exec -T postgres psql -v ON_ERROR_STOP=1 `
        -U $cfg['POSTGRES_ADMIN_USER'] -d $cfg['POSTGRES_DB'] @args
}

if ($Reset) {
    Write-Host "== destroying the local volume (development data only) =="
    Invoke-Compose down -v
}

Write-Host "== 1. up =="
Invoke-Compose up -d

Write-Host "== 2. waiting for healthy =="
$state = "starting"
for ($i = 0; $i -lt 60; $i++) {
    $state = (docker inspect -f '{{.State.Health.Status}}' phi-postgres-local 2>$null)
    if ($state -eq "healthy") { break }
    Start-Sleep -Seconds 2
}
if ($state -ne "healthy") {
    Invoke-Compose logs --tail=40 postgres
    throw "postgres did not become healthy"
}
Write-Host "healthy"

Write-Host "== 3. migrate (admin role, from the host) =="
python scripts/migrate.py
if ($LASTEXITCODE -ne 0) { throw "migrations failed" }

# Roles are CREATED by migration 005 with no password (see its section 1),
# so this has to happen after migrate, exactly as on the VPS. Delegated to
# a script shared with CI and with the bash setup: it quotes the password
# as a SQL literal rather than interpolating it into a command line, which
# a password containing a quote does not survive, and it verifies the roles
# afterwards.
Write-Host "== 4. role passwords and verification =="
python scripts/set_role_passwords.py
if ($LASTEXITCODE -ne 0) { throw "role setup failed" }

Write-Host "== 5. capabilities =="
Invoke-PsqlAdmin -c "SELECT capability, enabled FROM system_capabilities ORDER BY capability;"

Write-Host ""
Write-Host "Local database ready."
Write-Host "  DATABASE_URL=$($cfg['DATABASE_URL'])"
Write-Host ""
Write-Host "Run the suites with:"
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\local_test.ps1"
