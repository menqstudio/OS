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
#
# ---------------------------------------------------------------------------------------------------
# AUDIT: THIS SCRIPT USED TO EXIT 0 REGARDLESS OF THE ANSWER
# ---------------------------------------------------------------------------------------------------
# `Run-Case` printed "$cn (expect $expect) taskRC=... SERVER=[$server]" and never compared $expect to
# what the server actually said, nor checked $rc. The script then ended after two Run-Case calls, so a
# completed run exited 0 whatever the pipe answered — a DENY where ALLOW was expected, an ALLOW where
# DENY was expected, a client that never launched, or a server that printed PROOF_ERROR and nothing
# else. It printed its expectation beside an unexamined result: a transcript, not a proof.
#
# `Test-IsolationCase` below now DECIDES, and the script exits 1 on any failing case. The decision is a
# pure function of the observed strings, so it is testable without service accounts:
#
#     .\isolation_proof.ps1 -SelfTest
#
# runs it against synthetic transcripts (including the exact ones the old script waved through) and
# fails if the comparison is not doing its job. That self-test needs no elevation, no accounts and no
# pipes; the real run needs all three.
param(
  [string]$Dir   = "C:\ProgramData\brops-proof",
  [string]$Creds = "C:\ProgramData\brops-proof\accounts_creds.txt",  # name`tSID`tpassword, admin-locked
  # Exercise the verdict logic against synthetic transcripts and exit. No hardware required.
  [switch]$SelfTest
)
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------------------------------
# The verdict. Pure: observed strings in, pass/fail + reasons out. Nothing here touches the OS, which
# is what lets -SelfTest prove it can FAIL on a machine with no service accounts.
# ---------------------------------------------------------------------------------------------------

# pipe_proof.exe prints `CLIENT_SID=<sid>` and `VERDICT=ALLOW|DENY` (or `PROOF_ERROR=...`). The caller
# joins those lines with ' | ', so a field runs to the next whitespace or separator.
function Get-ProofField([string]$Text, [string]$Key) {
  if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
  $m = [regex]::Match($Text, ("(?m)" + [regex]::Escape($Key) + "=([^\s|]+)"))
  if ($m.Success) { return $m.Groups[1].Value }
  return $null
}

function Test-IsolationCase {
  param(
    [string]$Case,
    [ValidateSet("ALLOW","DENY")][string]$ExpectedVerdict,
    [string]$ExpectedSid,
    [string]$ServerOutput,
    $TaskRc
  )
  $problems = New-Object System.Collections.Generic.List[string]

  # The server must have RUN and authenticated a peer. A PROOF_ERROR line means it never got to a
  # verdict, and an absent VERDICT means the same thing more quietly — neither may pass.
  if ($ServerOutput -match 'PROOF_ERROR=([^\s|]*)') {
    $problems.Add("server reported PROOF_ERROR=$($Matches[1])")
  }

  # The client task must have launched and exited cleanly; otherwise nothing connected to the pipe and
  # the server's silence proves nothing about the SID gate.
  if ($null -eq $TaskRc) {
    $problems.Add("client task result unavailable (task never ran?)")
  } elseif ([int]$TaskRc -ne 0) {
    $problems.Add(("client task exited 0x{0:X} (expected 0)" -f [int]$TaskRc))
  }

  $verdict = Get-ProofField $ServerOutput "VERDICT"
  if (-not $verdict) {
    $problems.Add("server printed no VERDICT (it never authenticated a peer)")
  } elseif ($verdict -ne $ExpectedVerdict) {
    $problems.Add("VERDICT=$verdict but this case requires $ExpectedVerdict")
  }

  # The gate must have judged the RIGHT principal. Without this, a case could pass because some other
  # account happened to connect.
  $sid = Get-ProofField $ServerOutput "CLIENT_SID"
  if (-not $sid) {
    $problems.Add("server printed no CLIENT_SID")
  } elseif ($ExpectedSid -and $sid -ne $ExpectedSid) {
    $problems.Add("CLIENT_SID=$sid but $Case is $ExpectedSid")
  }

  [pscustomobject]@{
    Case     = $Case
    Expected = $ExpectedVerdict
    Verdict  = $verdict
    Sid      = $sid
    TaskRc   = $TaskRc
    Pass     = ($problems.Count -eq 0)
    Problems = @($problems)
  }
}

# ---------------------------------------------------------------------------------------------------
# -SelfTest: drive the verdict with synthetic transcripts. Every vector below that is marked $false was
# accepted (exit 0) by this script before the comparison existed.
# ---------------------------------------------------------------------------------------------------
if ($SelfTest) {
  $B = "S-1-5-21-11-22-33-1001"   # broker
  $S = "S-1-5-21-11-22-33-1002"   # sidecar
  $vectors = @(
    @{ n="broker allowed (the real GREEN)";        c="brops-broker";  e="ALLOW"; sid=$B; out="CLIENT_SID=$B | VERDICT=ALLOW"; rc=0; want=$true  },
    @{ n="sidecar denied (the real GREEN)";        c="brops-sidecar"; e="DENY";  sid=$S; out="CLIENT_SID=$S | VERDICT=DENY";  rc=0; want=$true  },
    @{ n="GATE INVERTED: sidecar was ALLOWED";     c="brops-sidecar"; e="DENY";  sid=$S; out="CLIENT_SID=$S | VERDICT=ALLOW"; rc=0; want=$false },
    @{ n="GATE INVERTED: broker was DENIED";       c="brops-broker";  e="ALLOW"; sid=$B; out="CLIENT_SID=$B | VERDICT=DENY";  rc=0; want=$false },
    @{ n="wrong principal reached the pipe";       c="brops-sidecar"; e="DENY";  sid=$S; out="CLIENT_SID=$B | VERDICT=DENY";  rc=0; want=$false },
    @{ n="server errored before any verdict";      c="brops-broker";  e="ALLOW"; sid=$B; out="PROOF_ERROR=ConnectNamedPipe: ...";  rc=0; want=$false },
    @{ n="server produced no output at all";       c="brops-broker";  e="ALLOW"; sid=$B; out="<none>";                       rc=0; want=$false },
    @{ n="client task failed to launch";           c="brops-broker";  e="ALLOW"; sid=$B; out="CLIENT_SID=$B | VERDICT=ALLOW"; rc=0xC0000142; want=$false },
    @{ n="client task result unavailable";         c="brops-broker";  e="ALLOW"; sid=$B; out="CLIENT_SID=$B | VERDICT=ALLOW"; rc=$null; want=$false }
  )
  $bad = 0
  foreach ($v in $vectors) {
    $r = Test-IsolationCase -Case $v.c -ExpectedVerdict $v.e -ExpectedSid $v.sid -ServerOutput $v.out -TaskRc $v.rc
    $ok = ($r.Pass -eq $v.want)
    if (-not $ok) { $bad++ }
    $mark = if ($ok) { "ok  " } else { "BAD " }
    Write-Output ("{0} {1,-38} verdict-says-pass={2,-5} expected={3,-5} {4}" -f `
      $mark, $v.n, $r.Pass, $v.want, ($r.Problems -join "; "))
  }
  if ($bad -gt 0) { Write-Output "SELFTEST: FAIL ($bad vector(s) wrong)"; exit 1 }
  Write-Output "SELFTEST: PASS (the comparison accepts only the two real GREEN transcripts)"
  exit 0
}

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
  # ...and now JUDGE it. The line above is the transcript; this is the proof.
  Test-IsolationCase -Case $cn -ExpectedVerdict $expect -ExpectedSid $sid -ServerOutput $server -TaskRc $rc
}

$results = @()
$results += Run-Case "brops-broker"  "ALLOW"
$results += Run-Case "brops-sidecar" "DENY"

# Both cases must have been evaluated AND passed. A run that produced fewer results than cases is a
# failure too — the peer-SID boundary is only demonstrated by showing ALLOW and DENY together.
$expectedCases = 2
$failed = @($results | Where-Object { -not $_.Pass })
foreach ($r in $results) {
  if ($r.Pass) {
    Write-Output ("PASS  {0}: VERDICT={1} CLIENT_SID={2}" -f $r.Case, $r.Verdict, $r.Sid)
  } else {
    Write-Output ("FAIL  {0}: {1}" -f $r.Case, ($r.Problems -join "; "))
  }
}
if ($results.Count -ne $expectedCases) {
  Write-Output "RESULT: FAIL — $($results.Count) case(s) evaluated, expected $expectedCases"
  exit 1
}
if ($failed.Count -gt 0) {
  Write-Output "RESULT: FAIL — $($failed.Count) of $expectedCases case(s) did not match"
  exit 1
}
Write-Output "RESULT: PASS — the challenge-authority pipe allowed ONLY the broker SID and denied the sidecar"
exit 0
