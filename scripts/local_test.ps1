# Load .env.local, then run the full verification suite.
# The bash equivalent is:  set -a; . ./.env.local; set +a; bash testing/run_all.sh
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

foreach ($line in Get-Content ".env.local") {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $k, $v = $line -split '=', 2
    [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), "Process")
}

$fail = 0
python scripts/migrate.py; if ($LASTEXITCODE -ne 0) { $fail = 1 }
foreach ($t in @('concept_layer','knowledge_layer','client_layer','run_engine',
                 'case_events','knowledge_inbox','prompt_contracts','measurement',
                 'intake','normalization','ontology_seed')) {
    Write-Host ""
    Write-Host "=== $t ==="
    python "testing/test_$t.py"
    if ($LASTEXITCODE -ne 0) { $fail = 1; Write-Host "  ^^ SUITE FAILED" }
}
Write-Host ""
if ($fail -eq 0) { Write-Host "ALL SUITES PASSED" } else { Write-Host "FAILURES PRESENT" }
exit $fail
