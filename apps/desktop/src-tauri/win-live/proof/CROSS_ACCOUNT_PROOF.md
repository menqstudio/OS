# Windows cross-account governed-turn proof

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
the accounts hold `SeBatchLogonRight`). Each creates a **NULL-DACL** pipe (anyone may
CONNECT, like the Linux `0777` socket) and, on every connection, reads the connecting
client's **kernel-attested SID** via `ImpersonateNamedPipeClient` (the `SO_PEERCRED`
equivalent) and accepts **only** the broker SID — every other principal is denied before
dispatch. The store directory is content-addressed; the signer re-derives every digest.

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

## The broker principal — proven as SYSTEM (session 0)

The three **servers** are dedicated service accounts (the security-critical isolation: they
hold the private keys and must be distinct, mutually-isolated principals). The **broker** is
the trusted orchestrator — the TCB — so its correct Windows deployment is **`SYSTEM`
(LocalSystem)**, the standard non-interactive service identity that holds the privileges the
broker needs (`SeAssignPrimaryToken`, `SeImpersonate`) and runs cleanly in **session 0**.

**Proven (session-0, cross-account):** the broker/driver running as **`SYSTEM`** via a
session-0 scheduled task, with the three servers as their distinct dedicated service accounts
(peer allowlist = the broker's `SYSTEM` SID `S-1-5-18`), completes the full governed turn →

```
RESULT: trusted_verified(production key=<signer-key-id> epoch=2) production_verified=true bound=true
```

This closes the earlier `STATUS_DLL_INIT_FAILED` (`0xC0000142`) concern: that limitation only
affects a **non-privileged service-account CONSOLE** process doing child-spawning in session 0
— it does **not** affect `SYSTEM`, so it is not a blocker for the broker's real deployment. A
dedicated non-`SYSTEM` `brops-broker` service account remains an option for a future
least-privilege hardening, but running the broker as the `SYSTEM`/LocalSystem TCB principal is
the correct and now-proven deployment.

The governed-turn machinery itself is fully proven:

1. **Crypto chain** → `trusted_verified`, host-independent: `cargo test -p brops-win-live`
   (runs on the Linux CI runner too).
2. **Real named pipes, same-account** (3 processes) → `trusted_verified`, with the peer-SID
   gate fail-closed both directions: `win_live_proof.ps1`.
3. **Cross-account** (3 distinct service-account servers) → `trusted_verified` (this document).
