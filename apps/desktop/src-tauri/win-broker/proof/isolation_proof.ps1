# Windows broker machine-proof — cross-account named-pipe peer-SID isolation (the Windows analogue of the
# Linux engine/ci/isolation_proof.sh). PROVEN 2026-08-02 on real service accounts.
#
# Model (Gev-approved "right path"): principals run in SESSION 0 (no interactive window station/desktop, so
# no STATUS_DLL_INIT_FAILED 0xC0000142). The lightest session-0 launch is a scheduled task whose principal is
# the dedicated service account (batch logon; the account holds SeBatchLogonRight). The trust boundary is the
# named-pipe peer-SID auth (SO_PEERCRED equivalent), NOT the pipe DACL: the server creates a NULL-DACL pipe
# (everyone may CONNECT, like the Linux 0777 socket), then reads the connecting client's KERNEL-ATTESTED SID
# via ImpersonateNamedPipeClient and gates it with the pure brops_core::windows_broker::authorize_pipe_peer.
#
# Prereqs (provisioned once, elevated): the 7 brops-* service accounts + SeBatchLogonRight; pipe_proof.exe +
# spawn_as.exe staged in a world-readable dir the service accounts can execute (e.g. C:\ProgramData\brops-proof
# — service accounts cannot read a user profile). Run ELEVATED.
#
# Expected GREEN result:
#   brops-broker  -> CLIENT_SID=<broker SID>  VERDICT=ALLOW   (broker is the only peer the challenge-authority pipe accepts)
#   brops-sidecar -> CLIENT_SID=<sidecar SID> VERDICT=DENY    (every other principal is denied)
param(
  [string]$Dir   = "C:\ProgramData\brops-proof",
  [string]$Creds = "C:\ProgramData\brops-proof\accounts_creds.txt"  # name`tSID`tpassword, admin-locked
)
$ErrorActionPreference = "Stop"
$exe  = Join-Path $Dir "pipe_proof.exe"
$comp = $env:COMPUTERNAME
$rows = Get-Content $Creds | Where-Object { $_ -match 'brops-' }
function F($n,$i){ (($rows | Where-Object { $_ -like "$n`t*" }) -split "`t")[$i] }
$brokerSid = F "brops-broker" 1

function Run-Case($cn,$expect){
  $pw = F $cn 2; $sid = F $cn 1
  $pipe = "brops-proof-" + [guid]::NewGuid().ToString('N')
  $sOut = Join-Path $Dir "out\srv_$cn.out"; Remove-Item $sOut -ErrorAction SilentlyContinue
  # Server as the caller; allowlist = broker SID (challenge-authority pipe accepts ONLY the broker).
  $srv = Start-Process -FilePath $exe -ArgumentList @("server",$pipe,$brokerSid) -RedirectStandardOutput $sOut -PassThru -NoNewWindow
  Start-Sleep -Milliseconds 600
  # Client AS the service account, in SESSION 0 via a scheduled task (no desktop -> no 0xC0000142).
  $tn = "brops-pc-$cn"
  $act = New-ScheduledTaskAction -Execute $exe -Argument "client $pipe"
  Register-ScheduledTask -TaskName $tn -Action $act -User "$comp\$cn" -Password $pw -RunLevel Limited -Force | Out-Null
  Start-ScheduledTask -TaskName $tn
  $srv.WaitForExit(15000) | Out-Null
  if (-not $srv.HasExited) { $srv.Kill() }
  $rc = (Get-ScheduledTaskInfo -TaskName $tn).LastTaskResult
  Unregister-ScheduledTask -TaskName $tn -Confirm:$false -ErrorAction SilentlyContinue
  $server = if (Test-Path $sOut) { ((Get-Content $sOut) -join ' | ') } else { "<none>" }
  Write-Output "$cn (expect $expect)  taskRC=$('0x{0:X}' -f $rc)  SERVER=[$server]"
}

Run-Case "brops-broker"  "ALLOW"
Run-Case "brops-sidecar" "DENY"
