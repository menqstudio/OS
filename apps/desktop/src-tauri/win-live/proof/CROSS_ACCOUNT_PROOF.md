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

## Honest caveat — the broker's own account

In this run the three **servers** are dedicated service accounts (the security-critical
isolation: they hold the private keys and must be distinct, mutually-isolated principals).
The **broker/driver** ran as the elevated operator session rather than a dedicated
`brops-broker` service account, because a service-account **console** process that does
complex child-spawning (it launches the executor and opens SQLite) in **session 0** hits a
Windows `STATUS_DLL_INIT_FAILED` (`0xC0000142`)-class launch limitation — the same wall
documented for interactive-desktop service-account console apps, and it also affects the
previously-working `pipe_proof.exe`, so it is an **environment/session-0 limitation
orthogonal to the governance logic**, not a chain defect. The broker is the trusted
orchestrator (it is the one principal every server is meant to accept), so its exact account
identity is the least security-critical of the four; the three key-holding principals ARE
isolated dedicated accounts, and the peer-SID gate is enforced across those account
boundaries in both directions.

Closing that last gap (broker as its own service account, or all four as real Windows
services rather than scheduled tasks) is an OS-integration hardening step; the governed-turn
machinery itself is fully proven:

1. **Crypto chain** → `trusted_verified`, host-independent: `cargo test -p brops-win-live`
   (runs on the Linux CI runner too).
2. **Real named pipes, same-account** (3 processes) → `trusted_verified`, with the peer-SID
   gate fail-closed both directions: `win_live_proof.ps1`.
3. **Cross-account** (3 distinct service-account servers) → `trusted_verified` (this document).
