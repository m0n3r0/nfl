# deploy.ps1 - sync the live draft driver + board into the deploy directory.
#
# The deployed copy (default C:\edge-debug-profile) silently drifts from the repo:
# a fix applied here may never reach the copy that actually runs the draft. This
# script makes the deploy a one-command, verified step (issue #21):
#   1. copies driver/draft_driver.py and data/board/original_board.json
#   2. writes DEPLOY_SHA.txt (the current git SHA) next to them
#   3. checksums both copies against the sources so a partial copy fails loudly
#
# Usage:  powershell -File tools/deploy.ps1
#         powershell -File tools/deploy.ps1 -DeployDir "D:\other\path"
param(
    [string]$DeployDir = "C:\edge-debug-profile"
)

$ErrorActionPreference = "Stop"

# Repo root is the parent of the directory this script lives in (tools/).
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DriverSrc = Join-Path $RepoRoot "driver\draft_driver.py"
$BoardSrc  = Join-Path $RepoRoot "data\board\original_board.json"
$DriverDst = Join-Path $DeployDir "draft_driver.py"
$BoardDst  = Join-Path $DeployDir "original_board.json"
$ShaFile   = Join-Path $DeployDir "DEPLOY_SHA.txt"

if (-not (Test-Path $DriverSrc)) { throw "driver not found: $DriverSrc" }
if (-not (Test-Path $BoardSrc))  { throw "board not found: $BoardSrc" }
if (-not (Test-Path $DeployDir)) { New-Item -ItemType Directory -Path $DeployDir | Out-Null }

# Capture the current repo SHA so the running driver can report which code it is.
$Sha = (& git -C $RepoRoot rev-parse HEAD 2>$null).Trim()
if (-not $Sha) { $Sha = "unknown" }

Copy-Item $DriverSrc $DriverDst -Force
Copy-Item $BoardSrc  $BoardDst  -Force
Set-Content -Path $ShaFile -Value $Sha -NoNewline

# Verify copies are byte-identical to the sources.
function Check($src, $dst) {
    $a = (Get-FileHash $src -Algorithm SHA256).Hash
    $b = (Get-FileHash $dst -Algorithm SHA256).Hash
    if ($a -ne $b) { throw "HASH MISMATCH $dst ($a vs $b)" }
}
Check $DriverSrc $DriverDst
Check $BoardSrc  $BoardDst

Write-Host "OK: deployed driver + board to $DeployDir"
Write-Host "DEPLOY_SHA=$Sha"
