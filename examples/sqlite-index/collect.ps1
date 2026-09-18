<#
collect.ps1 -- one-command collection for the SQLite index-selection study.

Resumable and safe to re-run: finished review verdicts are skipped, and nothing is
ever deleted.  Run it after the orchestrator stops, or part-way through to see where
things stand.

  pwsh -File collect.ps1
  pwsh -File collect.ps1 -SkipReview      # just integrity checks and the report
#>
param(
    [int]$Top = 15,
    [int]$Sample = 15,
    [int]$ChunkChars = 20000,
    [int]$AuditLimit = 0,
    [switch]$SkipReview
)
$ErrorActionPreference = 'Continue'
# <repo>/examples/sqlite-index/collect.ps1 -> <repo>/skills/aar-harness/scripts
$AAR = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\skills\aar-harness\scripts')).Path
Set-Location $PSScriptRoot

Write-Host "=== 1/7  held-out and forum integrity ==="
python "$AAR\aar.py" heldout verify --store heldout-store --run run
python "$AAR\aar.py" forum verify --run run

Write-Host ""
Write-Host "=== 2/7  regenerate the report from what is on disk ==="
python "$AAR\orchestrator.py" --run run --report-only

if (-not $SkipReview) {
    Write-Host ""
    Write-Host "=== 3/7  post-hoc PAPER_MONITOR (top $Top plus $Sample sampled) ==="
    python "$AAR\review.py" --run run --mode paper --top $Top --sample $Sample --exclude-rejected

    Write-Host ""
    Write-Host "=== 4/7  post-hoc INTEGRITY_JUDGE over trajectory chunks (chunk size $ChunkChars) ==="
    $auditArgs = @("--run", "run", "--mode", "audit", "--exclude", "--chunk-chars", "$ChunkChars")
    if ($AuditLimit -gt 0) { $auditArgs += @("--limit", "$AuditLimit") }
    python "$AAR\review.py" @auditArgs
}

Write-Host ""
Write-Host "=== 5/7  status ==="
python "$AAR\aar.py" status --run run

Write-Host ""
Write-Host "=== 6/7  final report ==="
if (Test-Path "run\reports\final.md") { Get-Content "run\reports\final.md" }
else { Write-Host "no report yet" }

Write-Host ""
Write-Host "=== 7/7  run observatory (derived view, rebuilt from the run directory) ==="
$title = "SQLite 索引选择研究"
python "$AAR\dashboard.py" render --run run --title $title --reference-file reference.json
Write-Host ('  看进度（实时，每 30 秒整页重载）：python "' + $AAR + '\dashboard.py" serve --run run --title "' + $title + '" --reference-file reference.json')
