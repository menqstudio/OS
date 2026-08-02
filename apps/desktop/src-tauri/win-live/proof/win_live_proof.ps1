# Windows LIVE governed-turn machine-proof harness (self-contained, same-account).
#
# Proves, over REAL \\.\pipe\ named pipes across THREE separate Windows processes (challenge-authority /
# governed-supervisor / isolated-signer) + a driver, that one full governed turn reaches production
# trusted_verified — and that the peer-SID trust boundary is fail-closed.
#
#   POSITIVE: driver's peer SID == the provisioned broker SID  -> trusted_verified production_verified=true bound=true
#   NEGATIVE: a bogus broker SID in the config                 -> blocked (the servers deny the driver's peer SID)
#
# The crypto chain itself (challenge -> lease -> attest -> sign -> verify_and_accept) is additionally proven
# host-independently by `cargo test -p brops-win-live` (runs on the Linux CI runner too). For the CROSS-ACCOUNT
# proof (the three servers as distinct dedicated service accounts) see CROSS_ACCOUNT_PROOF.md.
#
# Run from an elevated PowerShell. Requires the workspace built: cargo build -p brops-win-live --bins
param(
  [string]$Dbg  = "$PSScriptRoot\..\..\target\debug",
  [string]$Root = "C:\ProgramData\brops-live-selfproof"
)
$ErrorActionPreference = "Stop"
$bin = Join-Path $Root "bin"
$cfg = Join-Path $Root "config.json"
New-Item -ItemType Directory -Force -Path $bin | Out-Null
foreach ($e in "win_provision.exe","win_authority.exe","win_supervisor.exe","win_signer.exe","win_live_turn.exe","win_executor.exe") {
  Copy-Item (Join-Path $Dbg $e) (Join-Path $bin $e) -Force
}

function Invoke-Turn([string]$brokerSid, [string]$prefix, [string]$label) {
  & (Join-Path $bin "win_provision.exe") --root-dir $Root --allowed-broker-sid $brokerSid `
      --executor-path (Join-Path $bin "win_executor.exe") --pipe-prefix $prefix | Out-Null
  $a = Start-Process (Join-Path $bin "win_authority.exe")  -ArgumentList "--config",$cfg -PassThru -WindowStyle Hidden
  $s = Start-Process (Join-Path $bin "win_supervisor.exe") -ArgumentList "--config",$cfg -PassThru -WindowStyle Hidden
  $g = Start-Process (Join-Path $bin "win_signer.exe")     -ArgumentList "--config",$cfg -PassThru -WindowStyle Hidden
  Start-Sleep -Milliseconds 900
  $out = & (Join-Path $bin "win_live_turn.exe") --config $cfg 2>&1 | Out-String
  Stop-Process -Id $a.Id,$s.Id,$g.Id -Force -ErrorAction SilentlyContinue
  Write-Output ("{0}: {1}" -f $label, $out.Trim())
}

$mySid = ([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value)
Invoke-Turn $mySid                         "brops-pos" "POSITIVE (correct broker SID)"
Invoke-Turn "S-1-5-21-0-0-0-9999"          "brops-neg" "NEGATIVE (wrong broker SID)"
