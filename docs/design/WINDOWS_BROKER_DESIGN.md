# Windows Governed-Execution Broker — Design (Wave 3b-1B, Windows normative target)

> Status: NORMATIVE TARGET, UNAUDITED. This document specifies the Windows governed-execution
> broker that `docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md` §0.W names as the future
> Windows equivalent of the audited Linux isolation. Until an implementation of every section
> below exists **and passes its own Architect audit**, `platform_governed_execution_supported()`
> MUST keep returning **false** on Windows, every governed turn is fail-closed (dev/blocked,
> never `trusted_verified`), and no governed-turn lease is issued. Flipping the gate true on
> Windows is gated on this document's §10 machine-proof passing on a Windows CI runner, exactly
> as `engine/ci/isolation_proof.sh` gates Linux.

This design maps each §0.1 isolation primitive to a concrete Win32/.NET mechanism enforced by
the OS reference monitor — **SIDs, tokens, NTFS/registry/CNG-key DACLs, named-pipe peer-SID
checks, restricted/AppContainer tokens, job objects, and WDAC** — never by process name, image
path, or window title. Every boundary is an ACCESS-CHECK against a principal the attacker does
not control, not a code convention.

---

## 0. Scope and three-actor threat model

### 0.0 Scope

The broker mediates one thing: a single governed model turn executed under a supervisor-issued
lease, producing a signed execution receipt that the desktop may render as `trusted_verified`.
It **preserves the Linux invariant** — the runtime principals are **different OS principals**, and
every key store, evidence store, IPC endpoint, and TCB binary boundary is enforced by the Windows
kernel against all in-scope attackers — by mapping each Linux isolation primitive to a Windows
mechanism that enforces the same property. This is a mapping of **equivalent enforced invariants**,
not a claim that the mechanisms are byte-for-byte identical: several carry Windows-specific
asymmetries (most importantly the named-pipe **server-impersonates-client** hazard, §2.5, which has
no `AF_UNIX` analog and forces client-side hardening the Linux design never needed). Each such gap
is called out and closed at the section that owns it, never papered over with a parity claim.

**In scope (must be denied):** confidentiality and integrity of the receipt-signing key, the
supervisor attestation key, the challenge-authority key, and the evidence-recorder key; integrity
of the protected evidence store; integrity of every TCB binary/config; unforgeability of the
`trusted_verified` verdict; the "sidecar never reaches the signer" IPC boundary.

**Out of scope (same exclusion as Linux "admin/root/kernel out of scope"):** the local Windows
kernel, `NT AUTHORITY\SYSTEM`, `TrustedInstaller`, holders of `SeDebugPrivilege` /
`SeTcbPrivilege` / `SeTakeOwnershipPrivilege` / `SeRestorePrivilege`, and anyone who can load a
kernel driver or disable WDAC. Physical attacks and offline-disk tampering are out of scope
(mitigations noted where cheap, e.g. DPAPI-machine + WDAC). The broker defends against
**unprivileged, standard-user-level code execution**, which is exactly the ratified base scope.

### 0.1 Threat actors

Every requirement in this document is evaluated against these three actors. They are, by
construction, **three distinct Windows security principals (SIDs)** — that is the whole point.

- **A1 — malicious interactive login user.** Holds the interactive desktop logon token for the
  active console session. May be an admin-adjacent standard user but is NOT a local admin, NOT
  SYSTEM, and holds none of the out-of-scope privileges above. Corresponds to the Linux
  "same-login-user attacker."
- **A2 — compromised desktop renderer / client.** The desktop-UI process(es) — the challenge
  requester and, separately, the challenge authority's only permitted peer. A distinct principal
  from A1 and A3. May emit arbitrary IPC on any pipe it can reach.
- **A3 — RCE inside the dedicated sidecar service account.** Arbitrary code execution as the
  sidecar's own service principal (`NT SERVICE\BropsSidecar`), NOT the login user, NOT desktop-UI.
  This is the Linux "sidecar compromised-in-scope" actor and the **sharpest test**: A3 already
  holds code execution behind the front door, so every denial that stops A3 must be an OS
  access-check, not an application-layer convention.

**Core invariant (the §2.6 linchpin, restated for Windows):** A1, A2, A3, and each runtime
service principal resolve to **pairwise-distinct SIDs, none equal to the interactive login SID**,
and this is machine-verified at broker start (§7.1). If any two collapse to one SID — most
dangerously the sidecar sharing the login SID or the desktop-UI SID — the separation model is
void and the platform gate MUST report unsupported.

---

## 1. Service / principal topology (SIDs)

Eight Linux principals map to eight Windows identities. Long-lived roles are **Windows services**
with SCM-derived per-service SIDs (`NT SERVICE\<Name>`, `S-1-5-80-…`, viewable via
`sc showsid <Name>`); per-turn spawned roles (launcher target, contained executor) are **dedicated
local accounts** with all logon rights denied except the batch/service right they are spawned
with, further reduced to an **empty-capability AppContainer (lowbox) token** at spawn (§1.2, §4.4).

| # | Linux principal | Windows identity | Kind | SID form | Interactive logon |
|---|---|---|---|---|---|
| 1 | desktop-UI / client | `NT SERVICE\BropsDesktopUI` (or the desktop app's own dedicated account) | service / app principal (A2) | `S-1-5-80-…` | denied |
| 2 | desktop-challenge-authority | `NT SERVICE\BropsChallengeAuthority` | service | `S-1-5-80-…` | denied |
| 3 | sidecar (`engine_sidecar.py`) | `NT SERVICE\BropsSidecar` | service (A3) | `S-1-5-80-…` | denied |
| 4 | supervisor | `NT SERVICE\BropsSupervisor` (WRITE_RESTRICTED) | service | `S-1-5-80-…` | denied |
| 5 | evidence-recorder runner | `NT SERVICE\BropsRecorder` (WRITE_RESTRICTED) | service | `S-1-5-80-…` | denied |
| 6 | privileged launcher | `NT SERVICE\BropsLauncher` | service (holds `SeAssignPrimaryTokenPrivilege` + `SeIncreaseQuotaPrivilege`, §1.2) | `S-1-5-80-…` | denied |
| 7 | contained executor | local account `brops-executor` → **empty-capability AppContainer (lowbox) token** (§1.2, §4.4) | per-turn spawned | `S-1-…` + lowbox `S-1-15-2-…` | explicitly denied (§1.2) |
| 8 | isolated signer | `NT SERVICE\BropsSigner` (WRITE_RESTRICTED) | service | `S-1-5-80-…` | denied |
| — | TCB owner (installer/servicer) | `NT SERVICE\TrustedInstaller` or dedicated `brops-admin` | non-runtime | `S-1-5-80-956008885-…` | denied |
| — | interactive attacker | the console user (A1) | login | `WTSQueryUserToken`→`TokenUser` | n/a |

### 1.1 Why services for the long-lived roles

`NT SERVICE\<Name>` SIDs are (a) deterministically derived from the service name by the SCM, so
the installer never manages a password; (b) **not usable for interactive logon**, which alone
denies A1 the ability to *become* any service principal; (c) individually ACL-able as a first-class
SID on every object. The signer, supervisor, and recorder services are additionally configured
`SERVICE_SID_TYPE_RESTRICTED` via `ChangeServiceConfig2(SERVICE_CONFIG_SERVICE_SID_INFO)` (§1.3).

### 1.2 The per-turn worker accounts (launcher target and executor)

The launcher and the contained executor image are spawned per turn, not run as services. The
executor runs under a dedicated local account `brops-executor` created with
`NetUserAdd`/`New-LocalUser`, granted **only** `SeBatchLogonRight` (or the token-assignment path
below), and explicitly stripped of all logon reach:

- `LsaAddAccountRights` grants `SeDenyInteractiveLogonRight`, `SeDenyRemoteInteractiveLogonRight`,
  `SeDenyNetworkLogonRight` — so A1 can never log in as, or pivot to, the executor account.
- **The launcher's own privileges (there is no single "spawn right").** `CreateProcessAsUserW`
  requires the *caller* to hold **both `SeAssignPrimaryTokenPrivilege` and `SeIncreaseQuotaPrivilege`**;
  a default `NT SERVICE\BropsLauncher` holds neither. The installer therefore grants exactly these
  two privileges to the launcher account via `LsaAddAccountRights`
  (`SeAssignPrimaryTokenPrivilege`, `SeIncreaseQuotaPrivilege`) and **nothing else** — not
  `SeTcbPrivilege`, not `SeImpersonatePrivilege` beyond what pipe I/O needs. Because
  `SeAssignPrimaryTokenPrivilege` on a non-SYSTEM service is itself a sensitive grant (it lets the
  holder set the primary token of a new process), the launcher account is an **elevated-trust TCB
  component**: its binary is in `TCB_ARTIFACTS` (§3.4), its exact privilege set is enumerated in
  the pin manifest, and §7.1 re-asserts that it holds *only* those two privileges. (The alternative
  `CreateProcessWithTokenW` — which needs `SeImpersonatePrivilege` instead — is **not** used, to
  keep the launcher's privilege surface minimal and explicit.)
- The launcher spawns the executor via `CreateProcessAsUserW` under a token that is reduced to an
  **empty-capability AppContainer (lowbox) token** (§4.4). AppContainer — not a bare
  `CreateRestrictedToken` — is what actually delivers the "3 read-only input FDs + 1 write-only
  output FD and nothing else" guarantee: with an empty capability set a lowbox process is denied
  every securable object that does not explicitly grant its package SID (or a capability, or
  `ALL APPLICATION PACKAGES`), and the Windows Firewall/WFP default blocks all network for a
  capability-less package. The executor receives exactly the input handles + the output handle at
  spawn and has **no ambient filesystem, registry, or network reach**. A plain restricted token is
  **not** an equivalent substitute here (see §4.4 for why); this is the canonical AppContainer
  target.

### 1.3 WRITE_RESTRICTED confinement (a Windows primitive with no POSIX analog)

`SERVICE_SID_TYPE_RESTRICTED` marks the token WRITE_RESTRICTED and places the service's own SID into
the token's **restricting-SID set**. For a *write*, the access check becomes the **intersection** of
the normal-SID pass and a second pass evaluated only against the restricting SIDs; the write
succeeds only if some restricting SID is granted the access.

**Scope of the protection — stated honestly.** The restricting-SID set is **not** just the service's
own SID. Windows also seeds it with the token's **logon SID**, the **`WRITE RESTRICTED` SID
(`S-1-5-33`)**, and **`Everyone`/`World`**. Consequently a WRITE_RESTRICTED service can still write to
any object whose DACL grants **`Everyone`, `Authenticated Users`, or that token's logon SID** a write
right. WRITE_RESTRICTED therefore backstops the DACL in exactly one case: an object whose DACL
*names a runtime SID* (e.g. a misprovisioned ACE granting the recorder write on `sup\`) — the second
pass fails because the recorder SID is not a restricting SID. It gives **no** protection against a
DACL that grants `Everyone`/`World`/logon-SID write.

The load-bearing primary control is therefore **DACL hygiene**: protected objects (keys, store,
TCB) MUST carry **no `Everyone`, no `Authenticated Users`, and no logon-SID write ACE** — and this
is enforced and re-verified independently (§3.2, §3.3, §7.1), *not* assumed to be caught by
WRITE_RESTRICTED. WRITE_RESTRICTED is a genuine second wall only against the "named a runtime SID by
mistake" class of DACL error. It restricts WRITE only — READ denial always comes from the DACL (§3).
Applied to signer, recorder, and supervisor.

### 1.4 Distinct-principal resolution (input to §7.1's `verify_distinct_principals()`)

At install and at every broker start, each role's configured SID is resolved with
`LookupAccountNameW` / `LsaLookupNames2`. All eight runtime SIDs plus the interactive login SID are
then compared pairwise with `EqualSid`. This is the raw material the §7.1 start-time verifier
consumes; the actual gating decision lives in §7.

**Who resolves the login SID, and why not a runtime service.** The obvious call —
`WTSQueryUserToken(WTSGetActiveConsoleSessionId())` → `GetTokenInformation(TokenUser)` —
**requires `SeTcbPrivilege`**. None of the runtime service principals holds it (the supervisor is
WRITE_RESTRICTED; none runs as SYSTEM), and `SeTcbPrivilege` holders are explicitly **out of scope**
per §0.0, so a runtime service *must not* be the thing that calls `WTSQueryUserToken`. Login-SID
resolution is therefore performed by a **TCB/servicer-context helper** (SYSTEM/`TrustedInstaller`,
the same context that provisions ACLs and holds the pin manifest), which writes the resolved console
login SID(s) into the **TCB-owned, runtime-read-only pin manifest** (§4.3). The runtime
`verify_distinct_principals()` (§7.1) reads the login SID from that manifest and does only
`EqualSid` comparisons — it never itself calls a `SeTcbPrivilege` API.

Equivalently, where a runtime path is preferred, login sessions may be enumerated without
`SeTcbPrivilege` via `LsaEnumerateLogonSessions` / `LsaGetLogonSessionData` (reading each session's
`Sid` and `Session`) filtered to the active console session; this returns the login SID without
minting the user's token. Either way the login SID is obtained by a legitimately-privileged path,
not by a runtime service escalating.

**Fail-closed on no resolvable console session.** `WTSGetActiveConsoleSessionId()` returns
`0xFFFFFFFF` when there is no attached console (headless, RDP-only, session switched or locked
mid-resolution), and `WTSQueryUserToken` then fails. This is treated as a **verification failure,
not "no attacker present"**: if the console login SID cannot be resolved for any reason, the pin
manifest records it as *unresolved*, `verify_distinct_principals()` cannot prove the runtime SIDs
are disjoint from the login SID, and the platform gate reports **unsupported** (every governed turn
Blocks). The broker never proceeds on an assumed-empty or best-effort login SID.

---

## 2. Named-pipe peer authentication (the `SO_PEERCRED` equivalent)

Each IPC endpoint that Linux implements as an `AF_UNIX` socket + `SO_PEERCRED` UID-allowlist
becomes a **named pipe with a bound client-SID allowlist**. The transport changes
(Unix-socket → named pipe); the `brops_protocol` frame contract (u32 length prefix, 256 KiB cap,
strict decode, one request/one reply per connection) is unchanged and rides `PIPE_TYPE_MESSAGE`
`ReadFile`/`WriteFile`.

**Two directions, not one — the Windows asymmetry.** `SO_PEERCRED` on `AF_UNIX` only ever needed
the **server to authenticate the client**. Named pipes add a second hazard with no Unix analog: a
named-pipe **server can impersonate its connecting client** and inherit that client's SID. So the
Windows design must authenticate **both** directions — §2.2–2.3 are the server-authenticates-client
half (the direct `SO_PEERCRED` port), and **§2.5 is the client-authenticates-server half** that
Linux never required. Both are normative; the parity with Linux is on the *enforced property*, and
the extra client-side control is called out here rather than hidden under a "primitive-for-primitive"
claim.

### 2.1 Pipe endpoints and SID allowlists (mirror the Linux allowlists exactly)

| Pipe | Server principal | Allowlisted client SID(s) — ONLY | Linux analog |
|---|---|---|---|
| `\\.\pipe\brops-signer` | `BropsSigner` | `BropsSupervisor` | `BROPS_ALLOWED_PEER_UIDS=$SUPUID` |
| `\\.\pipe\brops-supervisor` | `BropsSupervisor` | `BropsSidecar` | `BROPS_SUPERVISOR_ALLOWED_PEER_UIDS=$MYUID` |
| `\\.\pipe\brops-challenge` | `BropsChallengeAuthority` | `BropsDesktopUI` | desktop-UI-UID SO_PEERCRED allowlist |
| `\\.\pipe\brops-ingress` | `BropsSupervisor` | `BropsSidecar` | §2.4 supervisor-owned staging channel |

Consequences enforced by SID, not convention:
- **A3 (sidecar) → signer pipe: DENIED** — sidecar SID ≠ supervisor SID. "The sidecar never
  reaches the signer; only the supervisor does" becomes an OS access-check.
- **A2 (desktop) → supervisor / signer pipe: DENIED** — desktop SID is on neither allowlist.
- **A1 (login user) → every pipe: DENIED** — the login SID is on no allowlist.
- The sidecar reaches the supervisor and ingress pipes ONLY (its two legitimate channels), and
  can never *read* staging.

### 2.2 Server creation (squat-proof, remote-proof, fail-closed)

```
CreateNamedPipeW(
    L"\\\\.\\pipe\\brops-signer",
    PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,      // (A) anti-squat
    PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE
        | PIPE_REJECT_REMOTE_CLIENTS,                         // (B) local-only
    PIPE_UNLIMITED_INSTANCES, outBuf, inBuf, 0,
    &sa);                                                     // (C) connect-time DACL
```
- **(A) `FILE_FLAG_FIRST_PIPE_INSTANCE`** — creation fails if a pipe of that name already exists,
  defeating A1/A3 **pipe-name squatting** (a pre-created same-name pipe impersonating the server).
  On any failure the server exits fail-closed; it never proceeds on a pipe it did not create.
- **(B) `PIPE_REJECT_REMOTE_CLIENTS`** — bars network peers; combined with the local-only threat
  model.
- **(C) `sa.lpSecurityDescriptor`** — a DACL (built by SDDL or `SetEntriesInAcl`) that gates connect
  at the SID level, granting **nothing** to `Everyone`/`Authenticated Users`/the login SID.
  **Critically, client SIDs are NOT granted `FILE_GENERIC_WRITE`.** On a named-pipe object bit
  `0x0004` is **`FILE_CREATE_PIPE_INSTANCE`** (the same bit value as `FILE_APPEND_DATA`), and
  `FILE_GENERIC_WRITE` *includes* it — so granting `FILE_GENERIC_WRITE` to a client SID would also
  grant that client the right to **stand up additional instances of the pipe**, i.e. a rogue server
  instance of a governance pipe. Since the allowlisted client on the supervisor/ingress pipes is
  `BropsSidecar` (A3) and on the challenge pipe is `BropsDesktopUI` (A2) — both in-scope attackers —
  that would hand the attacker a server-impersonation primitive. The DACL therefore grants:
  - **to each allowlisted client SID:** exactly
    `FILE_GENERIC_READ | FILE_WRITE_DATA | FILE_WRITE_ATTRIBUTES | SYNCHRONIZE`
    — i.e. `(FILE_GENERIC_READ | FILE_GENERIC_WRITE) & ~FILE_CREATE_PIPE_INSTANCE`. This is
    connect + read + write-message rights **without** the create-instance bit. State this bit
    explicitly in the SDDL/`SetEntriesInAcl` (do not use the `GW`/`FILE_GENERIC_WRITE` shorthand).
  - **`FILE_CREATE_PIPE_INSTANCE` (0x0004): to the server's own service SID ONLY.** No client SID,
    ever, receives it — only `PIPE_UNLIMITED_INSTANCES` under the server principal creates further
    instances.

  This is a first-line SID gate at connect time; the per-connection check below is authoritative.

### 2.3 Per-connection peer identity — authoritative, TOCTOU-free

After `ConnectNamedPipe`, resolve the connected principal and check it against the explicit SID
allowlist, **fail-closed on any inability to resolve** (mirrors `brops_socket`: an unreadable peer
UID is FAIL-CLOSED, never world-open).

**Primary (impersonation, no PID-reuse race):**
```
if (!ImpersonateNamedPipeClient(hPipe)) {            // MUST check — never proceed on failure
    CloseHandle(hPipe); return;                       // fail-closed; do NOT query in server context
}
if (!OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, TRUE, &hTok)) {
    RevertToSelf(); CloseHandle(hPipe); return;       // fail-closed
}
ok = GetTokenInformation(hTok, TokenUser, &tu, ...); // TOKEN_USER.User.Sid
allowed = ok && EqualSid(tu.User.Sid, kAllowedClientSid); // exact-SID allowlist
RevertToSelf();                                       // always revert before acting
CloseHandle(hTok);
if (!allowed) { CloseHandle(hPipe); return; }         // deny WITHOUT reading a frame
```
Every call's return is checked and **any** failure closes the connection without reading a frame;
the code never silently falls back to querying the *server's own* thread token (which would compare
the server SID against the allowlist and could self-authorize). `RevertToSelf` runs on every path.
Impersonation binds atomically to the *actual connected token*, so there is no PID-reuse TOCTOU.
The SID comparison is exact-`EqualSid` against the frozen allowlist — never a name, never a group
membership check, never "is admin."

**`SeImpersonatePrivilege` is a prerequisite, checked at start (§7.1).** `ImpersonateNamedPipeClient`
succeeds only if the server principal holds **`SeImpersonatePrivilege`**. A signer/supervisor/
challenge server that is over-locked-down (e.g. a WRITE_RESTRICTED token that strips the privilege)
would fail *every* impersonation — a self-inflicted DoS, not a bypass, but it would make the pipe
unusable. The installer therefore grants `SeImpersonatePrivilege` to each pipe-server service
account, and §7.1's start-time checks **assert each server principal actually holds and retains it**
(and that it is compatible with the service's `SERVICE_SID_TYPE_RESTRICTED` config) before the
service advertises ready. Note this privilege is *not* granted to the launcher (§1.2).

**Corroboration (the chain §0.W literally names):**
`GetNamedPipeClientProcessId(hPipe,&pid)` → `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,…,pid)`
→ `OpenProcessToken(TOKEN_QUERY)` → `GetTokenInformation(TokenUser)` → `EqualSid`. This has a
**PID-reuse TOCTOU** (the PID is captured at connect; the process could exit/recycle before
`OpenProcess`), so it is used ONLY as a secondary cross-check while the pipe is still connected
(peer provably alive), never as the sole gate.

**Failure handling:** any failure of `ImpersonateNamedPipeClient`,
`OpenThreadToken`, `GetTokenInformation`, or a SID that does not exactly match ⇒ close the
connection without reading the request frame. Exactly the `_serve_one` fail-closed drop.

### 2.4 Framing and lower-level note

The `brops_protocol` u32-length-prefix + 256 KiB cap + strict decode sits on top of message-mode
`ReadFile`/`WriteFile`. ALPC ports (`NtAlpcCreatePort`, `AlpcGetMessageAttribute` with
`ALPC_MESSAGE_TOKEN_ATTRIBUTE`) would give kernel-mediated caller-token attributes without
impersonation, but named pipes are the practical, auditable surface and are normative here.

### 2.5 Client-side hardening — the client authenticates the server (no Unix analog)

Because a named-pipe **server can impersonate its client**, a *trusted client* that connects at the
default `SECURITY_IMPERSONATION` level to a pipe stood up by a rogue/squatting server lets that
server impersonate it and act with its SID. The at-risk clients are exactly the trusted ones:
`BropsSupervisor` connecting to the signer, and `BropsDesktopUI` connecting to the challenge
authority. `FILE_FLAG_FIRST_PIPE_INSTANCE` + fail-closed-on-start (§2.2A) already blocks the primary
way an attacker would *own* the signer pipe name, so this is **defense-in-depth, not a proven bypass
today** — but it is required and specified, not left implicit:

- **Deny server impersonation via SQOS.** Every client opens the pipe with
  `SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION` (via `CreateFileW`'s `dwFlagsAndAttributes`, or
  the `SecurityQualityOfService` `ImpersonationLevel = SecurityIdentification`) — **never**
  `SECURITY_IMPERSONATION` or `SECURITY_DELEGATION`. At `SecurityIdentification` a server can *learn*
  the client's SID (which the §2.3 check needs) but **cannot impersonate the client to access
  objects** — so a rogue server that captures the connection gains nothing it could act with.
- **Verify the server's SID before sending a byte.** After `CreateFileW` succeeds and before writing
  any request, the client resolves the server principal —
  `GetNamedPipeServerProcessId(hPipe, &pid)` → `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,…)` →
  `OpenProcessToken(TOKEN_QUERY)` → `GetTokenInformation(TokenUser)` → **`EqualSid` against the
  expected server service SID** (signer SID for the signer pipe, challenge-authority SID for the
  challenge pipe). Mismatch or any resolution failure ⇒ close the handle and fail-closed, sending
  nothing. (This mirrors the server-side check's own PID-reuse caveat: the server process is
  provably alive for the duration of the connection, so the live cross-check is sound while
  connected.)
- **Start-time confirmation.** §7.1 step 5 already has each server confirm a downstream pipe is *its
  own* via a server-SID check against the expected server SID; this client-side SID check
  is the per-connection counterpart of that, run by every client on every connect.

This is the explicit client-side counterpart to the server-side SID allowlist. It does **not**
replace or weaken the §2.3 `ImpersonateNamedPipeClient` primary check — both run: the server still
authenticates the client by exact SID, and additionally the client now authenticates the server.

---

## 3. NTFS / registry / CNG-key ACL matrix

Every POSIX owner+mode boundary becomes an NTFS (and registry, and CNG-key) DACL with: owner set
to a **TCB principal none of A1/A2/A3 controls**; **explicit deny-write** to the login user and
every non-owning runtime SID; and **inheritance severed** so a loose parent cannot widen the
object.

### 3.1 How every security descriptor is set

- Build the DACL with `SetEntriesInAcl` (or ordered `AddAccessDeniedAceEx` **before**
  `AddAccessAllowedAceEx` — deny ACEs MUST precede allow ACEs in canonical DACL order) and apply:
  ```
  SetNamedSecurityInfoW(path, SE_FILE_OBJECT,
      OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
        | PROTECTED_DACL_SECURITY_INFORMATION,   // SE_DACL_PROTECTED — severs inheritance
      pTcbOwnerSid, NULL, pDacl, NULL);
  ```
- `PROTECTED_DACL_SECURITY_INFORMATION` is the analog of the Linux design's §2.5 "a writable ancestor
  directory is treated as writable" rule at the object; **in addition** the installer independently walks
  and locks every ancestor directory up to the volume root (§3.4, §8).
- **Owner = a TCB principal, not a runtime principal.** `NT SERVICE\TrustedInstaller` or a
  dedicated non-runtime `brops-admin`. The object owner always holds implicit `WRITE_DAC`, so the
  owner must be a principal none of A1/A2/A3 controls — otherwise they could rewrite the DACL.
  Setting owner requires `SeRestorePrivilege`/`SeTakeOwnershipPrivilege`, held by the
  installer/servicer only. Direct analog of "owned by a TCB principal (root or brops-admin that is
  NOT any runtime principal)."

### 3.2 Private-key stores (the `0700` owner-only dirs)

Receipt-signer key, supervisor-attestation key, challenge-authority key, evidence-recorder key,
governed-turn-recorder key (supervisor-held). DACL grants Full ONLY to the owning service SID +
the TCB owner; **no ACE (and an explicit deny) for login user, sidecar, executor, desktop, and
every other runtime SID**.

Prefer key material that is **also encrypted at rest**, stronger than a bare file DACL:
- **CNG persisted keys** in a per-service key container: `NCryptCreatePersistedKey` +
  `NCryptSetProperty(NCRYPT_SECURITY_DESCR_PROPERTY, sd, NCRYPT_SILENT_FLAG)` ACLing the private
  key so only the owning service SID can open it; or
- **DPAPI machine-scope** (`NCryptProtectSecret` DPAPI-NG) with an SDDL protection descriptor
  naming ONLY the owning service SID.

| Key store | Owner (write) | Read | Denied write AND read |
|---|---|---|---|
| signer receipt key | `BropsSigner` | — | login, sidecar, executor, desktop, supervisor, recorder |
| supervisor attestation key | `BropsSupervisor` | — | login, sidecar, executor, desktop, signer, recorder |
| governed-turn-recorder key | `BropsSupervisor` | — | (as above) |
| evidence-recorder key | `BropsRecorder` | — | login, sidecar, executor, desktop, signer, supervisor |
| challenge-authority key | `BropsChallengeAuthority` | — | login, sidecar, executor, supervisor, signer, recorder, **desktop-UI** |

### 3.3 Content-addressed evidence store (the `2750` owner-write / group-read model)

Linux uses `store\sup\` owner=supervisor, `store\rec\` owner=recorder, group `brops-store`
read-traverse-only (`2750`, setgid, **no group write**), signer read-only, and
sidecar/executor/desktop in no group. Windows reproduces the exact write/read topology:

| Object | Owner (Full) | Read + traverse (no write/delete) | Explicit deny-write | No access |
|---|---|---|---|---|
| `store\` (root) | `brops-admin` (TCB) | supervisor, recorder, signer | login, sidecar, executor, desktop | — |
| `store\sup\` | `BropsSupervisor` | recorder, signer | **recorder** (write), login, sidecar, executor, desktop | — |
| `store\rec\` | `BropsRecorder` | supervisor, signer | **supervisor** (write), login, sidecar, executor, desktop | — |
| artifacts (`*.json`) | namespace owner | supervisor/recorder/signer per namespace (read) | all non-owners (write) | login, sidecar, executor, desktop |

- The read-group ACE grants exactly `FILE_GENERIC_READ | FILE_TRAVERSE` and **explicitly withholds**
  `FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_DELETE_CHILD | DELETE | WRITE_DAC | WRITE_OWNER`. This
  is the "group `r-x`, no group `w`" of `2750` — a group member (the signer, the other namespace
  owner) can read and traverse but cannot create/rename/unlink.
- Cross-namespace **deny-write** ACEs enforce "recorder cannot write `sup\`" and "supervisor
  cannot write `rec\`," which POSIX gets for free from single-owner directories.
- Per-file DACLs equivalent to `0640` (owner write, group read, no delete for non-owner) prevent a
  non-owning reader from overwriting an existing artifact.
- `BropsSigner` is **read-only everywhere** in the store; the WRITE_RESTRICTED token on the signer
  is a second wall behind these DACLs.
- **sidecar, executor, desktop have NO ACE at all** on `store\` — no read, write, or list.
- **Runtime enforcement floor:** the store-loader (Windows analog of
  `brops_evidence_store._harden_dir`) MUST, at load, re-read each store descriptor and **refuse to
  start** if any non-owner runtime SID holds any write/delete right or if inheritance is not
  protected — fail-closed at load, not only in CI (mirrors "refuse `S_IWGRP`").

### 3.4 TCB binaries and config (the Linux §2.5 non-writability floor)

`TCB_ARTIFACTS` on Windows = the supervisor, recorder-runner, launcher, contained-executor image,
and signer **executables**; their config/policy bundles; the `GOVERNED_EXECUTION_ALLOWLIST`
source; the key-manifest/root-anchor; and the **service definitions** (SCM config + any WDAC/
AppLocker policy files).

- Every path in `TCB_ARTIFACTS` **and every ancestor directory up to the volume root** is
  **owned by the TCB principal** (`TrustedInstaller`/`brops-admin`) and grants runtime/login SIDs
  **read+execute only** — **no `FILE_WRITE_DATA`, `FILE_APPEND_DATA`, `FILE_ADD_FILE`,
  `FILE_ADD_SUBDIRECTORY`, `DELETE`, `FILE_DELETE_CHILD`, `WRITE_DAC`, `WRITE_OWNER`** for A1, the
  sidecar, supervisor, recorder, launcher, executor, signer, or desktop SIDs.
- A **writable ancestor directory is treated as writable** (a rename/replace vector). The
  installer locks the whole chain and the start-time verifier (§4.3, §7.1) re-checks it via
  `GetNamedSecurityInfo` on each opened handle.
- Registry equivalent: the services' SCM keys under `HKLM\SYSTEM\CurrentControlSet\Services\Brops*`
  carry the same DACL — the login user cannot rewrite `ImagePath`, `ObjectName`, or the service
  SID type.

---

## 4. Privilege-separated verified exec (the `fexecve` / TCB-integrity equivalent)

Linux: the setuid launcher validates the input FDs, drops caps, **re-hashes the on-disk executor
image**, verifies TCB ownership + non-writability (`O_NOFOLLOW`, `fstat` the opened fd — never a
path re-lookup), then `setuid(executor)+fexecve`s the exact verified fd so the bytes hashed are
the bytes executed. Windows has no `fexecve`; the TOCTOU-closure is reconstructed from **an opened,
sharing-locked file handle + hash + Authenticode + ACL verification, launched under the executor's
empty-capability AppContainer token** (§4.4).

### 4.1 Launch sequence (`BropsLauncher`, per turn)

1. **Receive the lease** over the supervisor→launcher channel; validate `launcher_executable_sha256`
   and `executor_executable_sha256` equal the start-time TCB pins (§7.1); refuse any other digest.
2. **Open the executor image once, with a deny-write share mode** so it cannot be swapped after
   verification:
   `CreateFileW(exePath, GENERIC_READ | FILE_EXECUTE, FILE_SHARE_READ, … , OPEN_EXISTING,
   FILE_FLAG_SEQUENTIAL_SCAN, NULL)` — critically **without `FILE_SHARE_WRITE`/`FILE_SHARE_DELETE`**,
   so from this point no principal can overwrite/rename/delete the on-disk image. This handle is the
   TOCTOU anchor that stands in for `fexecve`'s fd.
3. **Verify on that exact handle** (never a path re-lookup):
   - re-hash the bytes read through the handle; refuse unless SHA256 == lease
     `executor_executable_sha256`;
   - `GetSecurityInfo(hExe, SE_FILE_OBJECT, …)` — refuse unless owner ∈ TCB principals and **no
     write/delete ACE for any runtime/login SID** (the Linux §2.5 non-writable check on the handle);
   - `WinVerifyTrust` (WTD_CHOICE_FILE) — refuse unless Authenticode signature chains to the
     pinned publisher/leaf-hash (§5); and confirm WDAC would permit this image (§5).
4. **Build the executor token (AppContainer is mandatory here — see §4.4):** duplicate the launcher's
   assignable token, then reduce to the contained principal via `CreateAppContainerProfile` (or reuse
   a pinned profile) + a lowbox token with an **empty capability set** — no filesystem/registry/
   network capability SIDs, no `ALL APPLICATION PACKAGES` reliance. This is what actually yields "no
   ambient reach." A `CreateRestrictedToken` step (deny-only user SID, all non-essential privileges
   dropped, executor SID as sole restricting SID) MAY be layered *on top* as extra privilege
   stripping, but it is **not** an alternative to AppContainer for the ambient-reach guarantee (§4.4).
5. **Hand exactly the four handles** the executor is allowed: three read-only input file handles
   (system / history / generation_config, each verified `S_ISREG`-equivalent regular file, offset 0,
   size ≤ its ceiling — 256 KiB / 8 MiB / 64 KiB — backed by a `store\` inode) and one write-only
   output pipe handle. All are marked inheritable **for this spawn only**; `bInheritHandles=TRUE`
   with a `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` allowlist so **no other handle leaks** into the
   executor (the Windows equivalent of "close every other FD").
6. **Spawn:** `CreateProcessAsUserW(hExecutorAppContainerToken, exePath-from-verified-handle, …,
   CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT, …, &si, &pi)` with the job object (§6) assigned
   **before** `ResumeThread`. Because the image handle was opened deny-write in step 2 and the ACL
   forbids write to every runtime/login SID (§3.4), the bytes verified in step 3 are the bytes
   executed — the `fexecve` no-TOCTOU guarantee reconstructed from a locked handle + immutable ACL.
7. Any hash mismatch, writable image, wrong owner, failed Authenticode, or WDAC block ⇒ **no
   spawn, no receipt**, refused reason `tcb_integrity_violation` (§4.5 of the addendum).

### 4.2 Capability profile

The executor token carries the closed `INVOKE_GOVERNED_MODEL` capability profile only — never
`EXECUTE_CODE`/`WRITE_FILESYSTEM`/`WRITE_REPOSITORY`, no arbitrary path, no arbitrary executable,
no tool invocation (`max_tool_calls = 0`). An empty AppContainer capability set gives it no
ambient reach; the store, keys, and every pipe deny its SID (§3, §2), so even arbitrary code inside
the executor can touch only its four handles.

### 4.3 Start-time TCB pin (`verify_tcb_integrity()` equivalent)

Before the broker issues any lease, the supervisor holds a TCB-owned pin manifest of the expected
SHA256 of every `TCB_ARTIFACT` and, for each, opens a handle and: (a) verifies owner ∈ TCB
principals and no runtime/login write ACE (on the handle, via `GetSecurityInfo`, no path
re-lookup); (b) re-hashes and refuses on mismatch; (c) confirms Authenticode + WDAC. Failure ⇒ the
platform gate reports unsupported ⇒ every governed turn Blocks. Never a partial/degraded launch.

### 4.4 Why AppContainer, not a bare restricted token (they are NOT equivalent)

The two are frequently conflated; for the executor's "three input FDs + one output FD and **nothing
else**" property they are not interchangeable, and this design **mandates AppContainer (lowbox) with
an empty capability set**:

- **AppContainer (lowbox), empty capabilities** is *default-deny by construction*. A lowbox process
  is denied any securable object whose DACL does not explicitly grant its **package SID**, a granted
  **capability SID**, or `ALL APPLICATION PACKAGES`. With an empty capability set and store/keys/
  pipes carrying no such ACE (§3, §2), it reaches nothing ambient. Crucially, **network is denied
  too**: the Windows Firewall/WFP blocks a capability-less AppContainer from any socket
  (`internetClient`/`internetClientServer`/`privateNetworkClientServer` capabilities are all absent).
- **A plain `CreateRestrictedToken`** does *not* give this. Unless the base **user SID is made
  deny-only (or removed)** and a minimal restricting-SID set is supplied, the token still carries the
  user's ordinary grants (anything ACL'd to that user, or to `Users`/`Everyone`, remains reachable),
  and — decisively — a restricted token has **no network confinement at all**: WFP does not treat it
  as an AppContainer, so outbound network is *not* blocked by the token. "No ambient reach" therefore
  does **not** follow from a restricted token in general.

Consequently: AppContainer is the load-bearing mechanism for the executor's ambient-reach and
network denial. A restricted token, if used, is only additive privilege stripping and must itself
(a) mark the base user SID deny-only and (b) is documented as **not** providing network denial. The
denial matrix (§9) and CI (§10) assert the executor cannot reach filesystem/registry/**network** —
which a bare restricted token would fail.

---

## 5. Code integrity (WDAC / AppLocker)

The launcher's per-image `WinVerifyTrust` proves *this* image is signed; WDAC proves the **login
user cannot substitute any TCB binary at all**, which is the actual Linux §2.5 property.

- **WDAC (primary).** Ship a signed **WDAC policy** in enforced mode that allows execution of the
  broker's TCB images ONLY by **publisher + file-hash rule** (leaf-cert + PcaCertificate +
  per-binary Authenticode hash), and denies unsigned/unknown code in the broker's directories. WDAC
  is kernel-enforced and cannot be bypassed by A1/A3 (disabling it needs admin + reboot, out of
  scope). This is the strongest analog of "the login user cannot substitute a TCB binary."
- **AppLocker (fallback where WDAC is unavailable, e.g. some SKUs).** Publisher + hash rules for the
  TCB images with a default-deny for the broker directories, enforced (not audit) mode, via the
  `AppIDSvc` service. Weaker than WDAC (user-mode, more bypass surface) but acceptable as a
  documented fallback paired with the §3.4 ACL floor.
- **Binding to §4.** The launcher's pinned publisher/leaf-hash and the WDAC hash rules are derived
  from the **same** `executor_executable_sha256` / `launcher_executable_sha256` pins, so image
  verification, the code-integrity policy, and the lease all name the identical bytes. A binary the
  installer did not place cannot run even if an attacker wins a directory ACL misprovision, and a
  binary the WDAC policy does not name cannot run even if `WinVerifyTrust` is somehow satisfied.
- The WDAC/AppLocker policy files are themselves `TCB_ARTIFACTS` (§3.4) — TCB-owned, non-writable
  by any runtime/login SID, pinned and re-verified at start.

---

## 6. Job-object containment

The Linux cgroup + process-group kill/teardown becomes a **Windows job object** that the executor
cannot escape and that guarantees clean teardown.

- **Assign before resume.** The executor is created `CREATE_SUSPENDED`; the launcher
  `CreateJobObjectW` → `AssignProcessToJobObject(hJob, pi.hProcess)` → `ResumeThread`. The job is
  created with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` so closing the job handle kills the whole tree,
  and (Windows 8+) the executor cannot break away (`JOB_OBJECT_LIMIT_BREAKAWAY_OK` NOT set;
  silent-breakaway NOT set) — no child escapes containment.
- **UI/desktop isolation & limits.** `SetInformationJobObject` with
  `JOBOBJECT_BASIC_UI_RESTRICTIONS` (deny handles, USER handles, desktop switch, global atoms,
  clipboard, display settings) and `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` (process-memory cap,
  active-process = 1, no child processes) — the executor holds no key/store handle, only its four
  handles, and is treated as potentially hostile.
- **Bounded output + timeout (from §4.7, LOCKED).** The recorder reads the FD-6/output pipe
  continuously into a bounded buffer; on `MAX_OUTPUT_BYTES + 1` (8 MiB + 1) it **stops reading,
  `TerminateJobObject`s the executor**, and returns `output_oversize` with no receipt. Elapsed time
  is measured on a **monotonic** source (`QueryPerformanceCounter`/`GetTickCount64`, immune to NTP
  steps); at `EXECUTION_TIMEOUT_MS = 120000` it `TerminateJobObject`s and returns `output_timeout`
  with no receipt. Only signed `_ms` fields use the wall clock.
- **Teardown deadlines (LOCKED).** Immediate kill (not TERM→KILL — the executor is potentially
  hostile and holds nothing worth graceful shutdown); **termination grace 5000 ms** for the kernel
  to reap; **teardown deadline 10000 ms** to confirm the job has no live processes
  (`QueryInformationJobObject` `JOBOBJECT_BASIC_PROCESS_ID_LIST` empty) and close the job handle.
  Empty-by-deadline ⇒ `teardown_outcome = "contained"` (only this + `contained:true` yields a
  record); not-empty ⇒ `orphan-quarantined`/`timed-out` ⇒ **no accepted record**.
- A complete, accepted output (executor exit 0, within `MAX_OUTPUT_BYTES`, before timeout,
  `contained==true`) is the only path that produces `output_handle == output_sha256` and a signed
  receipt; any crash/timeout/oversize publishes nothing (fail-closed).

---

## 7. Startup ordering + crash recovery

### 7.1 Startup ordering (fail-closed at every step)

The broker enables governed real-mode ONLY if `platform_governed_execution_supported()` returns
true, which requires ALL five §0.1 primitives verified in this order. Any failure ⇒ gate reports
unsupported ⇒ no lease, every turn Blocks (`NoTrustedManifest`-equivalent), desktop never renders
`trusted_verified`.

1. **`verify_distinct_principals()`** — resolve all eight runtime SIDs (`LookupAccountNameW`) and read
   the console **login SID from the TCB-owned pin manifest** (§1.4 — resolved by the SYSTEM/servicer
   context, never by a runtime service, since `WTSQueryUserToken` needs the out-of-scope
   `SeTcbPrivilege`). Assert all are set, pairwise-distinct via `EqualSid`, and none equal the login
   SID, the desktop-UI SID, or each other. In particular the **sidecar SID ≠ login SID and ≠
   desktop-UI SID**. If the login SID is recorded *unresolved* (no active console session — §1.4),
   distinctness cannot be proven ⇒ **unsupported**. On a single-account dev box or a mis-provisioned
   install this fails ⇒ unsupported.
2. **Privilege-set assertions.** Confirm the **launcher** account holds **only**
   `SeAssignPrimaryTokenPrivilege` + `SeIncreaseQuotaPrivilege` (§1.2) and no more; confirm each
   **pipe-server** principal (signer, supervisor, challenge-authority) **holds and retains
   `SeImpersonatePrivilege`** so `ImpersonateNamedPipeClient` cannot silently fail (§2.3), and that
   this is compatible with its `SERVICE_SID_TYPE_RESTRICTED` config. Any drift ⇒ unsupported.
3. **`verify_tcb_integrity()`** (§4.3) — every `TCB_ARTIFACT` handle: TCB-owned, no runtime/login
   write ACE, hash == pin, Authenticode + WDAC OK, and every ancestor directory locked.
4. **Key-store ACL check** — each private-key container/dir (§3.2) is owner-only for its service
   SID; deny for all others; **no `Everyone`/`Authenticated Users`/logon-SID write ACE anywhere**
   (the DACL-hygiene control WRITE_RESTRICTED does *not* backstop — §1.3); store loader refuses
   `S_IWGRP`-equivalent leaks (§3.3).
5. **IPC bring-up** — each service creates its pipe with `FILE_FLAG_FIRST_PIPE_INSTANCE`
   (fail-closed on squat), the connect-time DACL that grants client SIDs read+write-message **but
   NOT `FILE_CREATE_PIPE_INSTANCE`** (§2.2C), and the frozen SID allowlist. Services are
   started by SCM with an ordering dependency chain: signer → supervisor (depends on signer pipe) →
   recorder → challenge-authority → sidecar last. The supervisor (as a **client**, opening pipes at
   `SECURITY_IDENTIFICATION` SQOS) confirms each downstream pipe is **its own** by verifying the pipe
   server's SID (§2.5) — the client-side counterpart to the server-side allowlist — before advertising
   ready.
6. **Positive control (mirrors `isolation_proof.sh` step 6)** — a real supervisor→signer signed
   round-trip on a known fixture; if the signing path is dead, the broker refuses to advertise
   ready (so §10's denials are real denials, not a dead path silently "passing").

`SCM` `SERVICE_CONFIG_FAILURE_ACTIONS` for each service is set to **not** auto-relax security on
repeated failure; a service that cannot satisfy its ACL/pipe invariants exits non-zero and the
gate stays false.

### 7.2 Crash recovery

- **Executor / launcher crash mid-turn:** the job object (`KILL_ON_JOB_CLOSE`) guarantees no
  orphan; the recorder finds a partial/absent output, publishes nothing, and the acceptance ledger
  moves the attempt to `RECOVERY_REQUIRED` — never a partial signed receipt.
- **Signer / supervisor / recorder crash:** SCM restarts the service, which re-runs §7.1 from step
  1 before serving; if any invariant now fails (e.g. an ACL drifted), it stays down and the gate is
  false. Persisted CNG keys and the content-addressed store survive restart; in-flight leases whose
  window has elapsed are rejected by the monotonic/`_ms` checks.
- **Pipe-instance recovery:** because the first instance is claimed with
  `FILE_FLAG_FIRST_PIPE_INSTANCE`, a restarting server that finds the name already present treats it
  as a **squat** and fails closed rather than joining an attacker's pipe — recovery requires the
  stale instance to be gone (guaranteed once the crashed process is reaped).
- **Idempotent publish:** the store publish path (temp → flush → verify size+sha256 →
  create-if-absent (`CREATE_NEW`) → divergent-refuse → flush dir) makes re-drives after a crash
  safe; a divergent re-publish is refused, not silently overwritten.

---

## 8. Installer: ACL provisioning, update/rollback, uninstall

The installer runs as SYSTEM/`TrustedInstaller` (out of the attacker's scope) and is the ONLY
component that holds `SeRestorePrivilege`/`SeTakeOwnershipPrivilege`. All provisioning is
**idempotent** — re-running converges to the same secure state and never widens an ACL.

### 8.1 Provision (idempotent)

1. **Create principals and grant exact privileges:** register the six services (`sc create` /
   `New-Service`) with `obj= "NT SERVICE\<Name>"` where applicable; set `SERVICE_SID_TYPE_RESTRICTED`
   on signer, recorder, supervisor and `SERVICE_SID_TYPE_UNRESTRICTED` on the rest via
   `ChangeServiceConfig2`. Grant, via `LsaAddAccountRights`, exactly:
   - **launcher:** `SeAssignPrimaryTokenPrivilege` + `SeIncreaseQuotaPrivilege` (required by
     `CreateProcessAsUserW`; §1.2) and **nothing else** — no `SeImpersonatePrivilege`, no
     `SeTcbPrivilege`;
   - **signer, supervisor, challenge-authority (pipe servers):** `SeImpersonatePrivilege` (required
     by `ImpersonateNamedPipeClient`; §2.3), verified compatible with their `SERVICE_SID_TYPE_RESTRICTED`
     config;
   - **`brops-executor` local account:** `SeBatchLogonRight` only, and DENY interactive/remote/network
     logon (`SeDeny*LogonRight`).

   Login-SID resolution for §1.4 is performed here in the installer/servicer (SYSTEM/`TrustedInstaller`)
   context, which legitimately holds `SeTcbPrivilege`, and written into the pin manifest — never done
   by a runtime service. Creation and grants are guarded by existence/idempotence checks so re-runs
   are no-ops and never *widen* a privilege set.
2. **Lay down TCB binaries** into a TrustedInstaller-owned directory tree; apply the §3.4 DACL
   (read+execute for runtime/login, no write/delete) with `PROTECTED_DACL_SECURITY_INFORMATION`
   and **walk every ancestor** to strip inherited write.
3. **Provision key containers** (CNG persisted keys / DPAPI-NG) with per-service-SID protection
   descriptors (§3.2); provision the store tree with the §3.3 owner/read/deny matrix.
4. **Install the WDAC/AppLocker policy** (§5) in enforced mode, publisher+hash-pinned to the laid
   binaries; the policy file itself is added to `TCB_ARTIFACTS`.
5. **Write the pin manifest** (§4.3) as a TCB-owned artifact.
6. **Verify-after-provision:** the installer re-reads every descriptor it set
   (`GetNamedSecurityInfo`) and asserts the exact expected owner/ACE set — a **mode/ACL-regression
   guard** analogous to the §2.3 "`stat` MUST equal `2750`" check. Any drift ⇒ installer fails,
   gate stays false.

### 8.2 Update / rollback

- Updates run under the same TCB principal, are **transactional**: new binaries are staged in a
  TCB-owned staging dir, verified (hash + Authenticode), the WDAC policy is re-pinned to the new
  hashes, and only then are binaries swapped and the pin manifest rewritten — atomically per file
  (`ReplaceFileW` / rename-into-place). The broker is stopped during the swap (SCM), so no lease is
  in flight.
- **Rollback** restores the prior binaries + prior pin manifest + prior WDAC policy from the staged
  copy; because identity is derived from the config/binary hash (never a mutable map), a rolled-back
  broker re-verifies cleanly at start (§7.1). A failed update leaves the old, still-pinned,
  still-WDAC-allowed binaries in place — never a half-updated TCB.
- Every update re-runs §8.1's verify-after-provision before the services are allowed to advertise
  ready.

### 8.3 Uninstall

Stop services, remove the WDAC/AppLocker policy, delete the service registrations and the
`brops-executor` account and its rights, and **securely delete the key containers** (`NCryptDeleteKey`
/ DPAPI secret removal). The store may be retained (content-addressed evidence) but its DACL is left
TCB-owned deny-all-runtime so a later reinstall re-provisions from a known state. Uninstall is
itself privileged (TCB) — A1/A2/A3 cannot trigger it.

---

## 9. Denial matrix (each actor × each asset → DENIED, with the enforcing mechanism)

Every cell is an OS access-check against a SID, not an application convention. "DENIED" means the
Windows reference monitor refuses the operation for that principal.

| Asset ↓ / Actor → | A1 login user | A2 desktop-UI | A3 sidecar (RCE) | Enforcing mechanism |
|---|---|---|---|---|
| Read/steal **signer key** | DENIED | DENIED | DENIED | CNG/DPAPI SD names only `BropsSigner`; NTFS DACL deny; §3.2 |
| Read/steal **attestation / recorder / challenge key** | DENIED | DENIED (own key excepted for authority) | DENIED | per-service key-container SD + DACL; §3.2 |
| Connect **signer pipe** (forge a receipt request) | DENIED | DENIED | DENIED | pipe DACL + `EqualSid` allowlist = supervisor only; §2.1–2.3 |
| Connect **supervisor pipe** | DENIED | DENIED | ALLOWED (its legit channel) | allowlist = sidecar only; A1/A2 denied by SID |
| Connect **challenge-authority pipe** | DENIED | ALLOWED (its legit channel) | DENIED | allowlist = desktop-UI only; A1/A3 denied by SID |
| **Squat** any broker pipe name | DENIED | DENIED | DENIED | `FILE_FLAG_FIRST_PIPE_INSTANCE` fail-closed; §2.2 |
| **Create a 2nd instance** of a pipe it is allowlisted to *connect* (rogue server) | DENIED | DENIED | DENIED | client SIDs lack `FILE_CREATE_PIPE_INSTANCE` (0x0004); server SID only; §2.2C |
| **Impersonate a trusted client** via a rogue pipe server | DENIED | DENIED | DENIED | clients open at `SECURITY_IDENTIFICATION` SQOS + verify server SID; §2.5 |
| Executor reaches the **network** | DENIED | DENIED | DENIED (executor SID) | empty-capability AppContainer ⇒ WFP blocks all sockets; §4.4 |
| Write/rename/delete in **store\sup\** or **store\rec\** | DENIED | DENIED | DENIED | no ACE for these SIDs; owner-only write; §3.3 |
| Read the **protected store** | DENIED | DENIED | DENIED | no read ACE (sidecar/executor/desktop); §3.3 |
| Overwrite/replace a **TCB binary/config** | DENIED | DENIED | DENIED | TCB-owned no-write DACL + locked ancestors + WDAC; §3.4, §5 |
| Substitute the **executor image** before exec | DENIED | DENIED | DENIED | deny-write share handle + on-handle hash/ACL/Authenticode; §4.1 |
| Run an **unsigned/unknown TCB image** | DENIED | DENIED | DENIED | WDAC/AppLocker enforced publisher+hash; §5 |
| **Become** a service principal (interactive) | DENIED | DENIED | DENIED | service SIDs not interactively logon-able; §1.1 |
| **Log in as** `brops-executor` | DENIED | DENIED | DENIED | `SeDeny*LogonRight`; §1.2 |
| **Escape** the executor job / spawn a child | DENIED | DENIED | DENIED (executor SID) | job object no-breakaway + active-process=1; §6 |
| Executor reaches **store / keys / any pipe** | DENIED | DENIED | DENIED (executor SID) | empty-capability AppContainer + deny ACEs; §4.2, §4.4 |
| **Collapse** two principals onto one SID | detected → gate false | detected → gate false | detected → gate false | `verify_distinct_principals()`; §1.4, §7.1 |
| Forge a `trusted_verified` **verdict end-to-end** | DENIED | DENIED | DENIED | composition of all rows: cannot sign, cannot reach signer, cannot swap image, cannot write store |

The sharpest cell — **A3 (sidecar RCE) forging a receipt** — is denied by four independent OS
walls: it cannot read the signer key (§3.2), cannot connect the signer pipe (§2, supervisor-only),
cannot write the store (§3.3), and cannot substitute the executor/signer binary (§3.4/§4/§5). Any
single wall holding is sufficient; all four hold.

---

## 10. CI / machine-proof strategy (Windows-runner isolation proof)

A Windows CI job — the direct analog of `engine/ci/isolation_proof.sh` — is the gate on flipping
`platform_governed_execution_supported()` true on Windows. **No skip, no placeholder, no
audit-mode.** The job runs on a Windows runner with admin (to provision principals/ACLs, exactly as
the Linux job uses passwordless sudo) and proves both a live positive control and every denial.

`engine\ci\isolation_proof.ps1` (normative shape):

1. **Provision distinct principals.** Create `BropsSigner`, `BropsSupervisor`, `BropsRecorder`,
   `BropsChallengeAuthority`, `BropsSidecar`, `BropsLauncher` services (or standalone processes
   under those service SIDs via a token-assignment harness) and the `brops-executor` account;
   resolve every SID and assert pairwise-distinct + ≠ the runner/login SID (`verify_distinct_principals`
   positive fixture). Grant the launcher exactly `SeAssignPrimaryTokenPrivilege` +
   `SeIncreaseQuotaPrivilege` and each pipe server `SeImpersonatePrivilege`, and assert those exact
   sets (§7.1 step 2, §1.2, §2.3).
2. **Provision custody.** Apply the §3 DACLs to key containers, the store namespaces, and the TCB
   binaries; run the §8.1 verify-after-provision (owner/ACE regression guard, WDAC pinned).
3. **Start signer + supervisor as their SIDs**, signer allowlisting ONLY the supervisor SID,
   supervisor allowlisting ONLY the sidecar SID; wait for both pipes to be created **by the
   expected server SID** (guards a false "denied" from a down service).
4. **POSITIVE CONTROL (before denials).** A real sidecar→supervisor→signer signed round-trip
   (`brops.evidence-request.v1` → `status:"signed"`, non-empty envelope+signature). Proves the
   signing path is ALIVE, so the denials below are real denials, not a dead path passing. (Mirrors
   `isolation_proof.sh` step 6.)
5. **Denial prover, run AS the login/attacker SID and AS the sidecar SID** (a
   `brops_isolation_prover` equivalent using `CreateProcessAsUser` under each attacker token), each
   attack asserted DENIED by the OS:
   - login/sidecar **connect to `\\.\pipe\brops-signer`** → refused (peer-SID allowlist).
   - login/sidecar/desktop **connect to `\\.\pipe\brops-supervisor` / `\\.\pipe\brops-challenge`**
     from a non-allowlisted SID → refused.
   - **pipe-name squat**: pre-create `\\.\pipe\brops-signer`, then the server's
     `FILE_FLAG_FIRST_PIPE_INSTANCE` create fails → server fail-closed.
   - **create-instance denial**: run AS `BropsSidecar` (allowlisted *client* of the supervisor pipe)
     and AS `BropsDesktopUI` (allowlisted *client* of the challenge pipe) and attempt
     `CreateNamedPipeW` on that same pipe name → `ACCESS_DENIED` (the client SID lacks
     `FILE_CREATE_PIPE_INSTANCE`; only the server SID has it — §2.2C).
   - **rogue-server / client-side SQOS**: stand up an attacker-owned pipe server on a governance
     name (only possible if `FILE_FLAG_FIRST_PIPE_INSTANCE` is bypassed in the harness) and connect a
     trusted client; assert the client opened at `SECURITY_IDENTIFICATION` so the rogue server's
     `ImpersonateNamedPipeClient` yields an identification-only token that **cannot** open the
     client's objects, and assert the client's server-SID verification refuses the connection and
     sends no request (§2.5).
   - login/sidecar/executor **open the signer/attestation/recorder key** → `ACCESS_DENIED`.
   - login/sidecar/executor **write/rename/delete/chmod in `store\sup\` and `store\rec\`**, and
     **read** the store → `ACCESS_DENIED` (run AS signer: read/traverse OK, all writes DENIED; AS
     recorder: write `rec\` OK, write `sup\` DENIED; AS supervisor: write `sup\` OK, write `rec\`
     DENIED — the §3.3 matrix machine-checked from each principal, exactly as §2.3's "run AS each
     principal" tests).
   - login/sidecar **overwrite a TCB binary / the WDAC policy / the pin manifest** → `ACCESS_DENIED`;
     and an **unsigned substitute binary** → WDAC-blocked at exec.
   - **executor-swap TOCTOU**: after the launcher opens the deny-write handle and pins the hash,
     attempt to replace the image → `SHARING_VIOLATION`/`ACCESS_DENIED`; and a pre-pin swap →
     hash-mismatch → `tcb_integrity_violation`, no receipt.
   - **job escape**: the executor attempts to spawn a child / break away → denied by the job object.
   - **executor network denial**: the empty-capability AppContainer executor attempts an outbound
     socket (TCP connect / DNS) → blocked by WFP (no network capability), proving the "nothing else"
     reach includes network — a property a bare `CreateRestrictedToken` would NOT satisfy (§4.4).
   - **login-SID fail-closed**: with **no active console session** (headless runner leg), assert
     `verify_distinct_principals()` records the login SID unresolved and the gate reports
     **unsupported** rather than proceeding (§1.4).
6. **Gate-shim tests (§0.1).** A shim that reports ANY single primitive missing (a shared SID, a
   writable TCB path, a missing pipe allowlist, a WDAC-absent host) ⇒
   `platform_governed_execution_supported()` == **false** ⇒ a governed turn Blocks with **no lease**
   and the desktop never renders `trusted_verified`. The all-present Windows fixture ⇒ gate ==
   **true** and steps 4–5 run.
7. **ACL/mode-regression guard.** Re-read every store/key/TCB descriptor and assert it exactly
   matches the expected owner + ACE set (the Windows analog of "`stat` MUST equal `2750`") — fail
   closed if anyone widens an ACL or drops `PROTECTED_DACL`.

The job is REQUIRED and blocking. Only when it is green on a Windows runner — every denial an OS
`ACCESS_DENIED`/refusal, the positive control alive, the gate-shim negative tests passing, and this
document Architect-audited — may `platform_governed_execution_supported()` return true on Windows.
Until then, the gate stays **false** and Windows governed real-mode is an explicit, tested refusal,
not a gap.

---

### Traceability to §0.1 primitives

| §0.1 primitive | Linux mechanism | Windows mechanism | Sections |
|---|---|---|---|
| 1. Distinct OS principals | 7 dedicated UIDs, `verify_distinct_principals()` | 8 SIDs (services + accounts), `EqualSid` verifier | 1, 7.1 |
| 2. Local-IPC peer auth | `AF_UNIX` + `SO_PEERCRED` UID allowlist | named pipe: server-side `ImpersonateNamedPipeClient` SID allowlist **+** client-side `SECURITY_IDENTIFICATION` SQOS + server-SID check (no Unix analog) | 2, 2.5 |
| 3. File/key/store ACL isolation | POSIX owner+mode (`0700`/`2750`) | NTFS/CNG/registry DACLs (deny-write, no `Everyone`/logon-SID write, protected inheritance) — WRITE_RESTRICTED only backstops named-runtime-SID DACL errors (§1.3) | 3 |
| 4. Privilege-dropping verified exec | `setuid(executor)+fexecve` | `CreateProcessAsUser` (launcher holds `SeAssignPrimaryTokenPrivilege`+`SeIncreaseQuotaPrivilege`) + **empty-capability AppContainer** token + deny-write handle + hash/ACL/Authenticode | 4 |
| 5. TCB code integrity | TCB-owned non-writable + start-time pin | §3.4 ACL floor + `verify_tcb_integrity()` + **WDAC/AppLocker** | 4.3, 5 |
| (containment) | cgroup kill/teardown | job object (kill-on-close, no-breakaway) | 6 |
| (gate) | `platform_governed_execution_supported()` + `isolation_proof.sh` | same predicate + `isolation_proof.ps1` on a Windows runner | 7.1, 10 |