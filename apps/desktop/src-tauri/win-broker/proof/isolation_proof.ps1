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
# The RUN's verdict, as opposed to one case's. Pure: collected case results in, lines + exit code out.
#
# AUDIT (2026-08-10): the round that gave this harness a comparison also made its PASS line
# unreachable. `Run-Case` ended with
#     Write-Output "$cn (expect $expect)  taskRC=... SERVER=[...]"   # the transcript
#     Test-IsolationCase ...                                        # the verdict
# and PowerShell puts BOTH on the function's success stream, so `$results += Run-Case ...` appended a
# [string] AND a [pscustomobject] per case. `$results.Count` was 4 against `$expectedCases = 2`, so the
# arity guard fired on every run and `RESULT: PASS` could not be reached. The self-test called
# `Test-IsolationCase` directly and so never touched the collection, which is why it stayed green.
#
# It failed in the safe direction; that does not make it less of a defect. A proof that cannot pass
# proves nothing, and this file exists because the previous version could not fail.
#
# The transcript rides on the result object now, and a results array containing anything that is not a
# case result is refused BY NAME — a bare count reported "4 case(s) evaluated" for a run that
# evaluated two.
# ---------------------------------------------------------------------------------------------------
function Resolve-ProofOutcome {
  param(
    [object[]]$Results,
    [int]$ExpectedCases,
    [string]$PassLine
  )
  $lines = New-Object System.Collections.Generic.List[string]
  $stray = @($Results | Where-Object {
    $null -eq $_ -or -not ($_.PSObject.Properties.Name -contains 'Pass')
  })
  if ($stray.Count -gt 0) {
    $lines.Add("RESULT: FAIL - $($stray.Count) non-result object(s) reached the results array;")
    $lines.Add("        a case function wrote to the success stream (put it in Transcript, not Write-Output).")
    return [pscustomobject]@{ Lines = @($lines); ExitCode = 1 }
  }
  $cases = @($Results)
  foreach ($r in $cases) {
    if ($r.Pass) { $lines.Add(("PASS  {0}: VERDICT={1} CLIENT_SID={2}" -f $r.Case, $r.Verdict, $r.Sid)) }
    else         { $lines.Add(("FAIL  {0}: {1}" -f $r.Case, ($r.Problems -join "; "))) }
  }
  if ($cases.Count -ne $ExpectedCases) {
    $lines.Add("RESULT: FAIL - $($cases.Count) case(s) evaluated, expected $ExpectedCases")
    return [pscustomobject]@{ Lines = @($lines); ExitCode = 1 }
  }
  $failed = @($cases | Where-Object { -not $_.Pass })
  if ($failed.Count -gt 0) {
    $lines.Add("RESULT: FAIL - $($failed.Count) of $ExpectedCases case(s) did not match")
    return [pscustomobject]@{ Lines = @($lines); ExitCode = 1 }
  }
  $lines.Add($PassLine)
  [pscustomobject]@{ Lines = @($lines); ExitCode = 0 }
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
  # ---- and the RUN-level decision, which nothing covered until 2026-08-10 ------------------------
  # Every vector above exercises the CASE verdict. The defect that made this harness unable to pass
  # was in the collection between the case verdict and the exit code, so no vector above could see
  # it. These drive `Resolve-ProofOutcome`, including the exact shape the defect produced.
  $okCase  = [pscustomobject]@{ Case="brops-broker";  Verdict="ALLOW"; Sid=$B; Pass=$true;  Problems=@() }
  $badCase = [pscustomobject]@{ Case="brops-sidecar"; Verdict="ALLOW"; Sid=$S; Pass=$false; Problems=@("gate inverted") }
  $runVectors = @(
    @{ n="two passing cases PASS";            r=@($okCase,$okCase);         c=2; want=0 },
    @{ n="one failing case FAILS";            r=@($okCase,$badCase);        c=2; want=1 },
    @{ n="a missing case FAILS";              r=@($okCase);                 c=2; want=1 },
    @{ n="an extra case FAILS";               r=@($okCase,$okCase,$okCase); c=2; want=1 },
    @{ n="no cases at all FAILS";             r=@();                        c=2; want=1 },
    # THE regression vector: the transcript on the success stream beside the verdict.
    @{ n="transcript leaked onto the stream"; r=@("brops-broker ...",$okCase,"brops-sidecar ...",$okCase); c=2; want=1; say="non-result object(s) reached the results array" },
    @{ n="a null in the results FAILS";       r=@($okCase,$null);           c=2; want=1; say="non-result object(s) reached the results array" },
    # The stray check and the count check are NOT the same check, and this vector proves it: four
    # entries against ExpectedCases=4, so the COUNT is satisfied and only the stray check can refuse.
    # Without it, deleting either guard would change no outcome — the mutually-masking pair.
    @{ n="strays that satisfy the count FAIL"; r=@("leak",$okCase,"leak",$okCase); c=4; want=1; say="non-result object(s) reached the results array" },
    @{ n="a missing case says WHICH problem";  r=@($okCase);                 c=2; want=1; say="1 case(s) evaluated, expected 2" },
    @{ n="a failing case names its problems";  r=@($okCase,$badCase);        c=2; want=1; say="FAIL  brops-sidecar: gate inverted" }
  )
  # `say` is asserted, not decorative. The stray check and the failing-case check BOTH refuse a leaked
  # transcript (a [string] has no `Pass`, so it reads as a failed case), so on exit code alone deleting
  # the stray check would change no outcome and the two would mask each other. What the stray check
  # contributes is the CAUSE: without it the run reports two mystery case failures with empty problem
  # lists, which is exactly how this defect survived days of green self-tests.
  foreach ($v in $runVectors) {
    $o = Resolve-ProofOutcome -Results $v.r -ExpectedCases $v.c -PassLine "RESULT: PASS - selftest"
    $ok = ($o.ExitCode -eq $v.want)
    if ($ok -and $v.ContainsKey('say')) { $ok = (($o.Lines -join "`n") -like "*$($v.say)*") }
    if (-not $ok) { $bad++ }
    $mark = if ($ok) { "ok  " } else { "BAD " }
    Write-Output ("{0} run: {1,-33} exit={2} expected={3}" -f $mark, $v.n, $o.ExitCode, $v.want)
  }

  if ($bad -gt 0) { Write-Output "SELFTEST: FAIL ($bad vector(s) wrong)"; exit 1 }
  Write-Output "SELFTEST: PASS (the case comparison AND the run decision accept only honest outcomes)"
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
  # JUDGE it, and return EXACTLY ONE object. The transcript rides on the result: `Write-Output` here
  # made every call return two objects, so `$results += Run-Case ...` collected four for two cases and
  # the run could never pass. See `Resolve-ProofOutcome`.
  $verdict = Test-IsolationCase -Case $cn -ExpectedVerdict $expect -ExpectedSid $sid -ServerOutput $server -TaskRc $rc
  $verdict | Add-Member -NotePropertyName Transcript -NotePropertyValue (
    "{0} (expect {1})  taskRC={2}  SERVER=[{3}]" -f $cn, $expect, ('0x{0:X}' -f $rc), $server)
  $verdict
}

$results = @()
$results += Run-Case "brops-broker"  "ALLOW"
$results += Run-Case "brops-sidecar" "DENY"

# The transcripts, printed here rather than from inside the case function (see `Resolve-ProofOutcome`).
foreach ($r in $results) { if ($r.PSObject.Properties.Name -contains 'Transcript') { Write-Output $r.Transcript } }

# Both cases must have been evaluated AND passed. A run that produced fewer results than cases is a
# failure too — the peer-SID boundary is only demonstrated by showing ALLOW and DENY together.
$outcome = Resolve-ProofOutcome -Results $results -ExpectedCases 2 `
  -PassLine "RESULT: PASS - the challenge-authority pipe allowed ONLY the broker SID and denied the sidecar"
foreach ($l in $outcome.Lines) { Write-Output $l }
exit $outcome.ExitCode
