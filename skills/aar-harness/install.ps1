<#
install.ps1 -- idempotent installer / verifier for the aar-harness skill.

This script ships inside the aar-harness plugin repository, where the skill lives at
<repo>/skills/aar-harness/.  That layout is NOT auto-discovered: DSH scans a project's
.dsh/skills and the user-level skills root, and a clone of this repo is neither of them.
So the real install action is -Global, which mirrors this directory into
$env:USERPROFILE\.agents\skills\<name> and makes the skill visible to every session.
Without -Global this is a read-only in-place verification of the checkout.
The script is location-independent: it finds the skill through $PSScriptRoot.

Usage
  pwsh -File install.ps1                 # verify in place
  pwsh -File install.ps1 -Global         # also mirror into the user-level skills root
  pwsh -File install.ps1 -RunTests       # verify, then run the unit tests
#>
[CmdletBinding()]
param(
    [switch]$Global,
    [switch]$RunTests
)

$ErrorActionPreference = 'Stop'
$SkillDir = $PSScriptRoot
$SkillName = Split-Path $SkillDir -Leaf

function Say($msg) { Write-Host "[aar-harness] $msg" }

Say "skill directory: $SkillDir"

# ---------------------------------------------------------------- 1. layout
$required = @(
    'SKILL.md',
    'references\framework.md',
    'references\contracts.md',
    'references\scoring.md',
    'references\integrity.md',
    'references\forum.md',
    'references\heldout.md',
    'references\survey.md',
    'references\prompts.md',
    'references\benchmark-sourcing.md',
    'references\backlog.md',
    'scripts\aar.py',
    'scripts\orchestrator.py',
    'scripts\dashboard.py',
    'scripts\lib\aar_lib.py',
    'scripts\lib\sources.py',
    'scripts\lib\rundata.py',
    'scripts\dashboard\template.html',
    'scripts\tests\test_aar.py',
    'scripts\toy\runner.py',
    'scripts\toy\frame.py'
)
$missing = @()
foreach ($rel in $required) {
    if (-not (Test-Path (Join-Path $SkillDir $rel))) { $missing += $rel }
}
if ($missing.Count -gt 0) {
    Say "MISSING $($missing.Count) required file(s):"
    $missing | ForEach-Object { Say "  - $_" }
    exit 1
}
Say "layout ok: $($required.Count) required files present"

foreach ($i in 0..11) {
    $prefix = "{0:d2}-*" -f $i
    $p = Get-ChildItem (Join-Path $SkillDir 'references\steps') -Filter $prefix -ErrorAction SilentlyContinue
    if (-not $p) { Say "warning: no step file matched $prefix" }
}

# ------------------------------------------------------------ 2. frontmatter
$skill = Get-Content (Join-Path $SkillDir 'SKILL.md') -Raw
if ($skill -notmatch '(?s)^---\s*(.*?)\s*---') {
    Say 'SKILL.md has no YAML frontmatter; DSH will skip this skill'
    exit 1
}
$fm = $Matches[1]
if ($fm -notmatch 'name:\s*' + [regex]::Escape($SkillName)) {
    Say "frontmatter name does not match the directory name '$SkillName'"
    exit 1
}
if ($fm -notmatch 'description:') {
    Say 'frontmatter has no description'
    exit 1
}
Say "frontmatter ok (name = $SkillName)"

# --------------------------------------------------------------- 3. hygiene
Get-ChildItem $SkillDir -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force; Say "removed $($_.FullName)" }

# ----------------------------------------------------------------- 4. tests
if ($RunTests) {
    Say 'running unit tests'
    Push-Location (Join-Path $SkillDir 'scripts')
    try {
        & python tests\test_aar.py
        if ($LASTEXITCODE -ne 0) { Say 'unit tests FAILED'; exit 1 }
    } finally { Pop-Location }
    Say 'unit tests passed'
}

# ---------------------------------------------------------------- 5. global
if ($Global) {
    $target = Join-Path $env:USERPROFILE '.agents\skills'
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    $dest = Join-Path $target $SkillName
    Say "mirroring to $dest"
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    Copy-Item $SkillDir $dest -Recurse -Force
    Get-ChildItem $dest -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item $_.FullName -Recurse -Force }
    Say 'global mirror written'
}

Say 'done'
exit 0
