# docs/design/WINDOWS_BROKER_IMPL_PLAN.md

> **STATUS: NORMATIVE TARGET — UNAUDITED. This is an implementation plan, not evidence of a working broker.**
> The `platform_governed_execution_supported()` gate (addendum §0.1) **stays `false` on Windows** — governed turns are fail-closed (dev/blocked, never `trusted_verified`) — **until** the Windows broker is (a) Architect design-audited, (b) implemented, (c) code-audited, and (d) proven by its own Windows CI machine-proof at exact head. This plan builds on the **rev-28** addendum §0.W (Windows normative stance) + §2 topology and the queued `docs/design/WINDOWS_BROKER_DESIGN.md` (branch `docs/windows-broker-design`; relied on here via §0.W + §2 since it is not on this working tree). **CI-green ≠ design/audit-green; a passing unit test ≠ a working install; a Linux isolation proof ≠ a Windows production proof** (addendum stop-gates; `config/current_state.json.product_roadmap.windows_production_isolation = not_done`).
>
> _Review-mode note (menqstudio/Bro contract): the OS tree is READ-ONLY context, so this is the **proposed file content + a build/test plan**, not a filesystem mutation. Draft artifact paths below (`engine/ci/…`, a `windows-broker-*` CI job) are targets to be created on an implementation branch after design-GREEN, not files placed by this pass._

---

## §0.W.1 Scope and honest status

Linux is the **currently-audited** platform (dedicated UIDs, `AF_UNIX` + `SO_PEERCRED`, root/TCB setuid launcher + `fexecve`, POSIX ownership/ACL, `engine/ci/isolation_proof.sh`). Windows is the **primary release platform** but is a **release blocker**: none of the five §0.1 primitives is verified on Windows today, so the enforced gate returns `false` and every governed turn Blocks (`platform_unsupported`, `NoTrustedManifest`-equivalent). This document specifies the concrete Windows equivalents and the build/test/CI plan that could eventually flip the gate — **after its own audit**. Nothing here changes the disputed 3b-1B architecture, the rev-28 principal topology, or the PR #31 audit candidate; it is additive Windows detail under §0.W.

**Non-goals / invariants preserved.** The nine-role topology (addendum §0), the launcher **Model A** lock (§2.7), the challenge-authority create-pending/issue split (§2.1), the `verify_distinct_principals()`/`verify_tcb_integrity()`/`platform_governed_execution_supported()` predicates (§0.1/§2.5/§2.6), and the stop-gates are **unchanged**. This plan only supplies the Windows realization of each.

## §0.W.2 Principal → Windows SID topology (rev-28, nine roles / seven runtime service SIDs)

Each of the seven runtime service principals gets a **dedicated, non-interactive service SID**; the renderer is the interactive login identity (a service SID for none of them); the launcher is a **TCB-owned file**, not a runtime SID; the executor runs under a **restricted / AppContainer token** derived for its own SID.

| # | Role (addendum §0) | Linux identity | Windows identity (TARGET) | In `verify_distinct_principals()`? |
|---|---|---|---|---|
| 1 | Renderer / session UI | login UID (Actors A/B) | **interactive login user** (the webview process) — owns no key/DB/manifest/authority handle | No — must be **≠** every service SID |
| 2 | Trusted desktop verifier / **broker** (TCB final authority) | broker service UID | dedicated **service SID** (own account/gMSA); owns receipt-challenge DB + pinned manifest | Yes |
| 3 | `desktop-challenge-authority` | authority UID | dedicated **service SID**; owns challenge CNG key + pending store | Yes |
| 4 | `sidecar` (Actor C RCE scope) | sidecar UID | dedicated **service SID** (NOT login, NOT renderer, NOT broker) | Yes |
| 5 | `supervisor` (lease issuer, terminal record) | supervisor UID | dedicated **service SID** | Yes |
| 6 | evidence-recorder runner (`brops-recorder`) | recorder UID | dedicated **service SID**; only caller of the launcher | Yes |
| 7 | privileged launcher (**Model A**) | root/TCB-owned **setuid file** | **TCB-owned binary** (owner `TrustedInstaller`-class / `brops-admin`), NOT a runtime SID; the CreateProcessAsUser host | **No** — `verify_tcb_integrity()` confirms; not counted as a service SID |
| 8 | contained model executor | executor UID | dedicated **executor SID**, launched under a **restricted / AppContainer token** | Yes |
| 9 | isolated receipt signer | signer UID | dedicated **service SID**; only peer is the supervisor | Yes |

**The seven runtime service SIDs** — broker(2), authority(3), sidecar(4), supervisor(5), recorder(6), executor(8), signer(9) — MUST be present, **pairwise-distinct**, and **≠ the interactive login SID**. Any collision, or any of the seven defaulting to the login SID, ⇒ `verify_distinct_principals()` Block ⇒ gate `false`. Broker(2) compromise is **out of scope** (it defines the `Verified` guarantee; it is inside the TCB). Renderer(1) reaching *past* the broker is **in scope** and denied by SID separation + peer auth + ACLs.

## §0.W.3 Dedicated service SIDs per principal — build/provision plan

**Design.** Use one of two provisioning modes, chosen at install time and both audited:
- **(M1) Per-principal service accounts** — seven standalone service accounts (or **gMSAs** in a domain), each mapped to a Windows service. Preferred where a service manager owns the process lifetime (broker, authority, sidecar, supervisor, signer, recorder).
- **(M2) Per-principal restricted tokens under one hardened host** — where separate OS accounts are impractical, a single hardened host process derives a **restricted token / AppContainer** with a distinct **capability/package SID per principal** (addendum §0.W: "an isolated service with a per-principal restricted token / AppContainer"). Each derived token still yields a distinct owning SID for ACL and peer-auth checks.

The executor(8) is always **M2** (restricted / AppContainer token, §0.W.6). The launcher(7) is a **file**, not a running SID.

**Build steps.**
1. Installer creates the seven principals (M1 accounts or M2 package/capability SIDs) with **`SeDenyInteractiveLogonRight` + `SeDenyRemoteInteractiveLogonRight`** so none can be the interactive user; grant only `SeServiceLogonRight` where M1.
2. Register each service with its SID under **`NT SERVICE\<name>`** (per-service SID type = `unrestricted`/`restricted` as appropriate) so DACLs can name the exact service SID.
3. Record every principal SID in a **provisioning manifest** the broker reads at start; `verify_distinct_principals()` resolves each configured SID, asserts all seven set + pairwise-distinct + ≠ login SID.

**Tests (normative).** (a) all-seven-distinct fixture ⇒ predicate true; (b) any two sharing a SID ⇒ Block; (c) sidecar SID == login SID ⇒ Block; (d) broker SID == login/renderer SID **or** == authority SID ⇒ Block (P0-1: a renderer can never *become* the final verifier; the broker can never be the authority); (e) any of the seven unset/defaulted to login ⇒ Block.

## §0.W.4 Named-pipe peer-SID authentication (both directions) — the `SO_PEERCRED` equivalent

**Design.** Every local IPC is a **named pipe** owned by the server principal with a DACL that grants connect only to the exact allowed client SID(s). On accept, the **server** authenticates the client, and — because trust is mutual across the TCB seam — the **client** also authenticates the server (both directions), so neither a login-user impostor server nor an impostor client is accepted:

- **Server → client:** `ImpersonateNamedPipeClient` → `OpenThreadToken` → `GetTokenInformation(TokenUser)` → compare the client **SID against the exact allowlist**; reject any other SID; then `RevertToSelf`. Also `GetNamedPipeClientProcessId` → `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` → `OpenProcessToken` as a cross-check that the impersonated SID matches the peer process token (defends against a token-swap between connect and impersonate).
- **Client → server:** the client resolves the pipe server's owner via `GetSecurityInfo(OWNER_SECURITY_INFORMATION)` on the pipe handle and confirms the **server SID is the expected service SID** before sending any authoritative bytes; the pipe is opened with `SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION` so the server **cannot** impersonate the client beyond identification.

**Allowlist matrix (mirrors §2.1/§2.3/§2.6).**

| Pipe (server) | Accepts client SID | Denies |
|---|---|---|
| challenge-authority | **broker only** | renderer/login, sidecar, all others |
| supervisor | sidecar (relay) + broker as configured | login/renderer directly, signer |
| signer | **supervisor only** | login, sidecar, renderer |
| broker (from renderer) | interactive login (renderer) — **closed command only** `{conversation_id, agent?}` | any authoritative field (system/history/config/hashes/nonces/receipt fields) rejected at parse |

**Tests (normative).** Actor A/B (login/renderer SID) connecting the broker, authority, supervisor, or signer pipe ⇒ **denied**; Actor C (sidecar service SID) connecting the signer or authority pipe ⇒ **denied**; a positive broker→signer round-trip ⇒ **signed**; a client that finds the server SID ≠ expected ⇒ aborts before sending (server-impersonation negative).

## §0.W.5 NTFS + CNG-key DACLs — the ownership/ACL isolation primitive

**Design.** Owner of all TCB assets = a **TCB principal** (`TrustedInstaller`-class or `brops-admin`). DACLs **DENY write** to the interactive user and every **non-owning runtime SID**; grant read/write only to the owning principal (owner-only) or owner-write + peer-read where the Linux model uses a shared group.

| Asset | Owner | Grant | Explicit DENY |
|---|---|---|---|
| Receipt-signer key store | signer SID | signer: read | login, renderer, sidecar, all others: read+write |
| Supervisor attestation key | supervisor SID | supervisor: read | everyone else |
| Challenge **CNG key** + pending store | authority SID | authority: read/write | login, renderer, **sidecar**, broker: read+write+list |
| Broker receipt-challenge DB + pinned manifest | broker SID | broker: read/write | login, renderer, sidecar, signer |
| Protected evidence store | supervisor SID (+ signer read) | owner write, signer read | login, sidecar: write; login: read |
| All TCB binaries/config (broker, authority, sidecar, supervisor, recorder, signer, **launcher**) | TCB principal | runtime SIDs: read+execute | **any runtime/login SID: write** |

**CNG specifics.** Keys are **CNG persisted keys** (`NCryptOpenStorageProvider`/`NCryptOpenKey`) with a **key DACL** set via `NCryptSetProperty(NCRYPT_SECURITY_DESCR_PROPERTY, DACL_SECURITY_INFORMATION)` denying the login/non-owning SIDs — the CNG-key equivalent of the `0700` key dir. Where TPM-backing is available, use the **Platform Crypto Provider** so the private key is non-exportable regardless of DACL.

**Ancestor-directory rule (mirrors §2.5).** Every **parent directory up to the drive root** of a TCB path must also be non-writable by runtime/login SIDs; a writable ancestor ⇒ `verify_tcb_integrity()` refuses at start (a writable ancestor allows a swap-by-rename TOCTOU).

**Tests (normative).** Actor A/B/C × each protected asset ⇒ **DENIED** with the stated enforcing DACL; a writable ancestor of any TCB path ⇒ start refused.

## §0.W.6 CreateProcessAsUser + restricted / AppContainer executor token — the launcher **Model A** equivalent

**Design (§2.7 Windows equivalent).** There is no setuid on Windows; the launcher is a **TCB-owned host binary** invoked **only by the recorder** that calls **`CreateProcessAsUser`** (or `CreateProcessAsUserW` with a restricted token, or `CreateAppContainerProfile` + `CreateProcess` for AppContainer) to run the **pinned executor image** under the executor's low-privilege token. It holds **no key/store handle** and can be coerced into no action other than "run this exact pinned image as the executor, with these exact handles, fully unprivileged, or refuse."

- **Executor token.** Build via `CreateRestrictedToken` from a bare executor-SID token: **`DISABLE_MAX_PRIVILEGE`** (strip all privileges), **`LUA_TOKEN`**, `SidsToRestrict` = the executor SID only, deny-only the login/admin groups; set integrity to **Low** (or **Untrusted**). Preferred: an **AppContainer** token with an empty capability set + a unique package SID so the executor cannot touch any TCB DACL. No network capability.
- **Image verification BEFORE launch (exec-time integrity).** Open the executor image `GENERIC_READ` with `FILE_FLAG_OPEN_REPARSE_POINT`-off / no-symlink-follow; verify **(a) SHA-256 == the lease `executor_executable_sha256`**, **(b) Authenticode signature** (`WinVerifyTrust` chained to the pinned publisher), **(c) NTFS ACL: not writable by any login/runtime SID**, **(d) owner = TCB principal**. Any mismatch ⇒ `tcb_integrity_violation`, **no launch, no receipt**. Launch **that exact verified handle** (`STARTUPINFOEX` with the image handle) so bytes-verified == bytes-executed (no path-relookup TOCTOU — the Windows analog of `fexecve(fd)`).
- **FD / handle-list SURVIVAL (P0-2 correction, Windows form).** The executor's I/O channel is the three read-only input handles + one write-only output handle (the FD 3/4/5/6 analog). These MUST **survive the process-creation boundary**: create them **inheritable** (`SECURITY_ATTRIBUTES.bInheritHandle = TRUE` or `SetHandleInformation(HANDLE_FLAG_INHERIT)`), pass **exactly those four** via `STARTUPINFOEX` + `UpdateProcThreadAttribute(PROC_THREAD_ATTRIBUTE_HANDLE_LIST, {h_in0,h_in1,h_in2,h_out})`, and call `CreateProcessAsUser` with **`bInheritHandles = TRUE`**. The explicit handle list makes inheritance **exhaustive** — every other inheritable handle is excluded (the Windows equivalent of clearing `FD_CLOEXEC` on 3–6 while `close_range`-ing the rest). A required data handle that is not inheritable, or any extra handle in the list, ⇒ **refuse before signing any receipt**.
- **Closed argv / cleared env (mirrors §2.7).** A fixed, closed command line (lease handle + pinned executor index + job-object name); **`lpEnvironment` = an explicitly built minimal block**, not the parent's, so no `PATH`/`__COMPAT`/`BROPS_*` inheritance. Bind to a **Job Object** (kill-on-close, no breakaway) for teardown = the cgroup analog; the recorder terminates the job on any failure and produces **no** receipt/evidence/record.
- **Failure/teardown.** Any check failure ⇒ **no CreateProcess**, non-zero exit, recorder kills the job object. A crash mid-setup cannot leave a privileged executor (the restricted token is built and applied before `CreateProcessAsUser`; the launcher host is short-lived and holds no key/store handle).

**Real-executable integration test (normative).** A tiny **pinned** test executor reads all three input handles to EOF and writes a known output through the output handle; it MUST run successfully through the real recorder → launcher → `CreateProcessAsUser` path (proving handle survival + the restricted-token drop actually work), and the full negative matrix (§0.W.11) MUST fail closed.

## §0.W.7 WDAC / AppLocker TCB code integrity

**Design (§0.W: "WDAC/AppLocker (or signature + ACL) so the login user cannot substitute any TCB binary").**
- Ship a **WDAC policy** (signed, in **enforced** mode) that allows **only** the TCB binaries (broker, authority, sidecar, supervisor, recorder, signer, launcher host, and the pinned executor image) by **publisher + file hash**; everything else in the install tree is deny-by-default. WDAC is kernel-enforced and cannot be bypassed by the login user.
- **AppLocker** (or the WDAC AppID) rules as a defense-in-depth layer keyed to the TCB install directory + publisher.
- **`verify_tcb_integrity()` (Windows form), fail-closed at start.** For every TCB artifact: `fstat`-equivalent (owner = TCB principal, ACL non-writable by runtime/login SIDs), **SHA-256 == start-time pin**, **Authenticode valid**, and — if WDAC is available — the active policy is **enforced** and lists this binary. Any failure ⇒ start refused ⇒ gate `false`.

**Tests (normative).** Login-user-writable TCB binary ⇒ start refused; a TCB binary whose bytes were swapped after pinning ⇒ hash/Authenticode mismatch ⇒ refuse; WDAC in audit-only (not enforced) mode on a host that claims support ⇒ the integrity primitive reports absent ⇒ gate `false`.

## §0.W.8 Installer: ACL provisioning (idempotent) + update / rollback + uninstall

**Provisioning (idempotent).** The installer (MSI custom action or signed PowerShell, run elevated) is **re-runnable to the same end state**:
1. Create/reconcile the seven principals (skip-if-exists; never duplicate) and their logon-right denials.
2. Lay down TCB binaries to a protected dir; set **owner = TCB principal**, DACLs per §0.W.5, and ancestor-directory non-writability, using `icacls`/`SetNamedSecurityInfo` in a **set-exact** (not additive) manner so a re-run repairs drift.
3. Create CNG keys with their key-DACLs (create-if-absent; never overwrite an existing private key on re-run).
4. Register services with per-service SIDs; deploy + **enforce** the WDAC policy; write the provisioning manifest (principal SIDs + start-time hash pins).
5. **Post-provision self-check:** run `verify_distinct_principals()` + `verify_tcb_integrity()` + the four denial probes in a dry-run; **abort + roll back** if any fails (never leave a half-provisioned TCB that could look supported).

**Update.** Stage new binaries side-by-side; re-pin hashes + WDAC; **atomically** flip the manifest pointer; keep the previous version staged for rollback. The gate is held `false` during the flip window.

**Rollback.** Restore the previous manifest pointer + WDAC policy + binaries; re-run the post-provision self-check.

**Uninstall.** Stop + delete services; remove WDAC/AppLocker rules; **securely delete CNG keys** (`NCryptDeleteKey`) and the protected store; delete the seven principals; remove the manifest. Leave **no** orphaned service SID that a later install could silently reuse.

**Tests (normative).** Install → assert full DACL/SID/WDAC state; **re-run installer → byte-identical end state** (idempotency); simulate a mid-install failure → rollback leaves the gate `false` and no partial TCB; uninstall → keys gone, principals gone, no residual writable TCB path.

## §0.W.9 Windows-CI machine-proof (analogous to `engine/ci/isolation_proof.sh`)

Two proposed jobs (draft in `.github/workflows/ci.yml`, actions **pinned by full commit SHA**, stdlib-only python gate — matching the repo's style):

- **`windows-broker-gate` (PROPOSED, and it does not exist — corrected 2026-08-09).** This bullet said “REQUIRED today”. There is no `windows-broker-gate` job in `.github/workflows/ci.yml` and no `engine/ci/platform_gate_windows.py` in the tree; the Windows job that DOES run is `windows-broker`, which executes the §0.W predicates, the real named-pipe peer-SID authentication, the `brops-win-live` kit and a `cargo check` of the shipped host — it does not assert the §0.1 gate at all. Nor is any check *required*: `main` has no branch protection and no rulesets. Read the rest of this bullet as the DESIGN it always was. As designed it would run `python engine/ci/platform_gate_windows.py` and assert **`platform_governed_execution_supported()` == false** on `windows-latest`. This is the enforced, tested refusal: it fails CI if anyone makes Windows claim support before the real broker lands.
- **`windows-broker-isolation` (allowed-to-fail today, `continue-on-error: true`).** Elevated runner runs `engine/ci/windows_isolation_proof.ps1`, which — mirroring the Linux script — provisions dedicated service SIDs, ACLs the CNG key store + protected store + broker/authority pipes, starts the broker + signer **as those principals**, runs a **positive broker→signer signed round-trip** (proving the path is alive), then runs the prover **as the login (attacker) identity** requiring all four attacks to be **DENIED**. `engine/ci/check_windows_broker_proof.py` adjudicates the JSON verdict fail-closed. This job **flips to REQUIRED only after** the broker passes its own Architect audit + the proof is green at exact head — that green is the event that lets §0.1 return `true` on Windows.

**Four denial rows + positive control (mirror the Linux prover):** `login_cannot_connect_broker_pipe`, `login_cannot_read_cng_key`, `login_cannot_write_protected_store`, `renderer_cannot_reach_authority_pipe`; positive = `broker_to_signer_signed_roundtrip`. The adjudicator also requires the gate to have **flipped true under the provisioned fixture** — otherwise the "proof" proved nothing.

## §0.W.10 `platform_governed_execution_supported()` — the Windows arm

A stdlib-only, fail-closed Windows arm evaluates the same five primitives (§0.1), each as a **verified probe**, ANDed together. Today every probe is a stub reporting **absent**, so the arm returns **`false`** by construction — the correct, tested refusal. The real broker replaces each stub with a verified Win32/CNG/WDAC check; only when **all five** pass does the arm return `true`, and even then only on a host that also passes the §0.W.9 proof.

## §0.W.11 Threat model → Windows SID denial matrix (Actors A / B / C)

| Attacker | Holds | Attempt | Enforcing Windows mechanism ⇒ result |
|---|---|---|---|
| **A** login user | login SID | read CNG key / write protected store / write any TCB binary | NTFS + CNG-key DACL DENY (§0.W.5); WDAC blocks substituted binary ⇒ **DENIED** |
| **A** login user | login SID | connect broker/authority/supervisor/signer pipe | pipe DACL + peer-SID allowlist (§0.W.4) ⇒ **DENIED** |
| **B** compromised renderer | login identity (webview) | reach past the broker: call authority/sidecar/signer, supply system/history/config/hashes/nonces/receipt fields, forge a "Verified" event | renderer holds no key/DB/manifest/authority handle; broker accepts only the **closed** `{conversation_id, agent?}` and resolves all authoritative inputs itself; only the broker's committed verification tx creates a `Verified` message ⇒ **DENIED** |
| **C** RCE in sidecar | **sidecar service SID** (NOT login, NOT broker) | connect signer/authority pipe, read any key/store, make an authority sign caller-supplied evidence | peer-SID allowlist denies sidecar; DACLs deny sidecar read/write; may only trigger a run + relay the final receipt (transport only) ⇒ **DENIED** |
| launcher coercion | recorder-invoked | wrong caller SID, extra handle, non-inheritable data handle, target ≠ pinned hash/Authenticode, writable/login-owned image, residual privilege in executor token, cleared-env violation | §0.W.6 negative matrix ⇒ **refuse, no receipt** |

This is the exact rev-28 §9 matrix ((i)–(n)) realized with Windows SIDs; the launcher-Model-A success path (tiny pinned executor reading the three input handles, writing the output handle) MUST run end-to-end (handle survival + token drop proven).

## §0.W.12 Build/test phases + exit criteria

1. **P-W0 Enforced refusal (smallest first).** Land the Windows arm of `platform_governed_execution_supported()` (returns `false`) + the `windows-broker-gate` CI job asserting `false`. **Exit:** Windows CI proves the gate is false; desktop renders dev/blocked, never `trusted_verified`.
2. **P-W1 Principals + peer auth.** Installer provisions seven service SIDs; named-pipe peer-SID auth both directions; `verify_distinct_principals()` Windows arm + negative tests.
3. **P-W2 ACLs + CNG + WDAC.** NTFS/CNG DACLs; `verify_tcb_integrity()` Windows arm; WDAC enforced policy + tests.
4. **P-W3 Launcher Model A.** `CreateProcessAsUser` + restricted/AppContainer token + handle-list survival + pinned-image/Authenticode verify; real-executor integration test + full negative matrix.
5. **P-W4 Installer lifecycle.** Idempotent provisioning + update/rollback/uninstall tests.
6. **P-W5 Full proof.** `windows_isolation_proof.ps1` + `check_windows_broker_proof.py` green; four denials fire, positive control signs, gate flips true under fixture.
7. **P-W6 Audit + flip.** Architect **design-GREEN → implemented → code-audit GREEN → Windows CI proof GREEN at exact head**; only then does `windows-broker-isolation` become REQUIRED and the gate is permitted to return `true` on Windows. **Until P-W6 completes, the gate stays `false`.**

---

## Appendix W-A — Machine-verification results (this pass, honest)

I authored the gate/proof/CI-job skeletons and syntax-verified them (they are draft targets, not yet placed in the OS tree):

- **Existing `.github/workflows/ci.yml`** — parsed with PyYAML 6.0.3 (Python 3.13.14): **valid YAML, 9 jobs** (`cockpit-frontend, cockpit-core, cockpit-host, engine, bridge, coordination, repo-state, capabilities, signer-isolation`). The two proposed Windows jobs would be additive.
- **`platform_gate_windows.py`** (draft §0.W.10) — `py_compile` **OK**; run output `platform_governed_execution_supported() == False`, process exit `0` (its contract: it must be False today). Fail-closed by construction (all five primitive probes stubbed absent, ANDed).
- **`check_windows_broker_proof.py`** (draft §0.W.9 adjudicator) — `py_compile` **OK**; behavioral check: all-denials-fired + positive-passed + gate-true fixture ⇒ `[]` (accept); a denial returning `ALLOWED-BUG` ⇒ rejected with the exact row; gate not flipped true ⇒ rejected. Fail-closed on any missing/wrong row.
- **`windows_isolation_proof.ps1`** (draft §0.W.9 driver skeleton) — parsed with the PowerShell 7 AST parser: **no parse errors** (177 tokens). It emits `unknown` rows in skeleton form, which the adjudicator **fails closed** on — correct until the body is implemented.
- **`windows-broker-proof.job.yml`** (draft CI jobs) — parsed with PyYAML: **valid**, jobs `windows-broker-gate` (required, asserts gate false) + `windows-broker-isolation` (`continue-on-error: true` until audited); actions pinned by the same full commit SHAs as `ci.yml`.

**Honest caveats.** These verifications prove **syntax + the fail-closed adjudication logic**, nothing more. I did **not** provision service SIDs, set DACLs, deploy WDAC, or run the real isolation proof (that needs an elevated CI runner and is out of scope for review mode). A green `py_compile`/AST-parse is **not** a working broker, and this whole document is an **unaudited normative target**. The Windows gate remains **`false`**, and no production `Verified` is possible on Windows, until the broker passes its own Architect audit + Windows CI proof at exact head (addendum §0.W, stop-gates; `windows_production_isolation = not_done`).
