# Windows cross-account governed-turn proof

> **Reproducibility correction (remediation audit R1/R2/R3, 2026-08-07).** Read this before the rest
> of the document.
>
> This file is a **narrative record of runs performed on the author's machine**, not a reproducible
> artifact. The tree contains no transcript, log, or captured output for the cross-account run, and
> the `RESULT:` lines below are prose. Treat them as an operator's report, not as evidence a reader
> can re-derive.
>
> Three specific corrections to what this document previously implied:
>
> 1. **`win_live_proof.ps1` could not run at all.** It passed `win_provision` the DEMONSTRATION root
>    seed (the one embedded in `win-live/src/proof.rs`), which `win_provision` rejects with `exit 3`
>    because it checks the supplied private against the TCB-pinned PRODUCTION public key. It also
>    omitted the `--*-account` arguments the seed-ACL step requires (`exit 4`). The script now
>    **requires** `-RootKey <offline root private seed>` and **fails loudly** without it, because that
>    key is deliberately not in this repository and not on any serving box. Anyone who does not hold
>    the operator's offline root **cannot** reproduce a production `trusted_verified` from this tree.
> 2. **A §2.5 TCB integrity floor now exists on Windows and is enforced.** The runs described below
>    predate it — they measured nothing before serving. A current deployment additionally needs
>    `win_tcb_pin` to have produced an Administrators-owned pin manifest, or every server exits 5 and
>    the driver returns `blocked reason=tcb_integrity_floor`.
> 3. **The pipe DACL was NULL** during those runs, so `FILE_FLAG_FIRST_PIPE_INSTANCE` protected
>    nothing (a NULL DACL grants everyone `FILE_CREATE_PIPE_INSTANCE`). That is now an explicit
>    restrictive DACL. The "NULL-DACL pipe (anyone may CONNECT, like the Linux `0777` socket)"
>    description in the next section therefore describes the OLD behaviour and is no longer the code.
>
> The reproducible-on-any-host part of this kit remains `cargo test -p brops-win-live`, which proves
> the crypto chain, the §2.5 floor decision, and the pipe-DACL plan without Windows. Note that this
> command still runs in **no CI workflow** — that gap is unfixed and is an open finding.

This records the CROSS-ACCOUNT machine-proof: one full governed turn reaching production
`trusted_verified` with the three trusted principals running as **distinct dedicated Windows
service accounts**, communicating over real `\\.\pipe\` named pipes with **peer-SID
authentication across genuine OS account boundaries**.

## What ran

| Principal | Windows account | SID tail |
|---|---|---|
| challenge-authority (`win_authority.exe`) | `brops-authority` | `…-1007` |
| governed-supervisor (`win_supervisor.exe`) | `brops-supervisor` | `…-1009` |
| isolated-signer (`win_signer.exe`) | `brops-signer` | `…-1006` |
| broker / driver (`win_live_turn.exe`) | the broker principal (the provisioned `allowed_broker_sid`) | — |

Each server is launched as its own account via a **session-0 scheduled task** (batch logon;
the accounts hold `SeBatchLogonRight`). On every connection it reads the connecting client's
**kernel-attested SID** via `ImpersonateNamedPipeClient` (the `SO_PEERCRED` equivalent) and
accepts **only** the broker SID — every other principal is denied before dispatch. The store
directory is content-addressed; the signer re-derives every digest.

> At the time of these runs each server created a **NULL-DACL** pipe, described then as "anyone may
> CONNECT, like the Linux `0777` socket". That was wrong in a way that mattered: a NULL DACL also
> grants everyone `FILE_CREATE_PIPE_INSTANCE`, so any local principal could add a second instance of
> a trusted pipe name and collect the next connection — which made the
> `FILE_FLAG_FIRST_PIPE_INSTANCE` "pipe-squat fix" inert. The pipe now carries an explicit DACL
> (server principal + SYSTEM + Administrators full; the broker SID read/write **without**
> create-instance; everyone else absent), and the server holds the name continuously across
> instances. See `win-live/src/pipe_acl.rs`.

## Result

```
RESULT: trusted_verified(production key=<signer-key-id> epoch=2) production_verified=true bound=true
```

The full chain ran end-to-end across the three isolated service accounts: challenge →
lease → attest-run → sign-result → `verify_and_accept`, producing a genuine
`trusted_verified` bound to the root-signed manifest's production signer key.

### Peer-SID boundary, both directions (across real accounts)

- **Allowed:** the driver's peer SID == `allowed_broker_sid` → `trusted_verified`.
- **Denied:** a driver whose SID is NOT `allowed_broker_sid` (e.g. a different principal, or
  a config provisioned with a bogus broker SID) → `blocked reason=chain:UpstreamBlocked`
  (the servers deny the peer before dispatch). Verified with the three servers running as
  their service accounts.

## The broker principal — proven as a dedicated NON-SYSTEM service account (session 0)

The three **servers** are dedicated service accounts (the security-critical isolation: they
hold the private keys and must be distinct, mutually-isolated principals). The **broker** is
the trusted orchestrator; for **least privilege** it runs as its OWN dedicated non-`SYSTEM`
service account (`brops-broker`) — NOT `SYSTEM`, so it cannot read the signer service's memory
or DPAPI-sealed seed (which a `SYSTEM` broker could, defeating signer isolation).

**Proven (session-0, cross-account):** the broker/driver running as **`brops-broker`** via a
session-0 scheduled task, with the three servers as their distinct dedicated service accounts
(peer allowlist = the broker account's exclusive SID), and the manifest signed by the operator's
**offline** root key, completes the full governed turn →

```
RESULT: trusted_verified(production key=<signer-key-id> epoch=2) production_verified=true bound=true
```

**Resolving the earlier `0xC0000142`:** the `STATUS_DLL_INIT_FAILED` a limited service-account
console process hit in session 0 was the **debug-CRT DLL dependency** (e.g. `vcruntime140d.dll`)
that account could not load — NOT a fundamental session-0 limitation. Building the win-live bins
with **`-C target-feature=+crt-static`** removes the dynamic CRT dependency, and the dedicated
`brops-broker` account then runs the full turn cleanly. (`SYSTEM` also works, but a dedicated
non-`SYSTEM` broker is the correct least-privilege deployment and is what is now proven.)
**Deployment note:** build the Windows kit with `+crt-static`.

Where the evidence for each layer actually stands:

1. **Crypto chain** — host-independent and reproducible by anyone: `cargo test -p brops-win-live`.
   It signs with the compiled-in DEMONSTRATION anchor, so it reports **demonstration custody**, never
   production; that is the honest outcome of a fixture root, not a shortfall. *(Caveat: this command
   is in no CI workflow, so nothing runs it automatically.)*
2. **Real named pipes, same-account** (3 processes) — `win_live_proof.ps1`. **Requires the operator's
   offline root private key**; without it the script fails loudly and produces nothing. It is
   same-account by construction, so it demonstrates the peer-SID gate in both directions and does
   **not** demonstrate cross-account isolation or pipe-squat resistance.
3. **Cross-account** (3 distinct service-account servers) — this document, as an operator's narrative
   report. No script or captured output for it exists in the tree, and it predates the §2.5 floor and
   the pipe DACL, so it is not a statement about the current code.
