# Wave 3b-1B — implementation CODE-AUDIT request (rev-30 design-GREEN → code)

> **STATUS: implementation WIP on `impl/wave-3b1b-core` (PR #46). This requests the Architect CODE-audit —
> distinct from the rev-30 DESIGN-GREEN gate (already passed + merged via PR #31). Design-green ≠ code-green.
> `NoTrustedManifest` stays fail-closed; no production `trusted_verified` exists.**

The rev-30 design addendum (`WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`, Architect DESIGN GREEN, on `main`)
is implemented as the modules below. Every module is compiled + unit-tested (`cargo` / `python -m unittest`
/ `vitest`) — see the counts. Linux-only syscall paths (`AF_UNIX` `SO_PEERCRED`, setuid, `fexecve`,
`/proc`) are `#[cfg(target_os="linux")]`-gated so the crates compile cross-platform; their **runtime**
behaviour is exercised by the Linux CI isolation proof + real deployment, NOT by a host unit test — those
are called out as **[LINUX-RUN-PENDING]**.

## Design § → implementation module → verification

| rev-30 § | Implementation | Verification |
|----------|----------------|--------------|
| §4.10(g) P0/P1-1 contract | `core/governed_turn_ipc.rs` — strict request decode (`deny_unknown_fields`), UUIDv4 `client_request_id`, closed `TurnReason` enum, committed/blocked reply, idempotency state machine | 13 cargo |
| §4.10(g) P0 delivery | `core/governed_message_store.rs` — persist + in-tx **commit-readback** fail-closed; `trust_state` pinned by DB CHECK; body/hash/trust equality | 5 cargo |
| P1-1 idempotency (durable) | `core/broker_turns.rs` — rusqlite store backing the state machine (reattach/retry_conflict/turn_in_progress) | 10 cargo |
| §4.10(g) P0 flow | `core/broker_orchestrator.rs` — decode → idempotency → execute → commit-readback → committed/blocked | 4 cargo |
| §2.7 P1-2/P0-3 FD | `core/fd_lifecycle.rs` — launcher FD-set verifier ({0..6}, inert 0/1/2, RDONLY store 3-5, output 6, no CLOEXEC on data FDs, no fd≥7) | 7 cargo |
| §2.7 P0-2 privilege | `core/privilege_drop.rs` — drop-sequence order validator + fail-closed final-state verifier | 6 cargo |
| §2.5 TCB floor | `core/tcb_integrity.rs` — `verify_tcb_integrity` over the EXPANDED `TCB_ARTIFACTS` (broker+authority incl.) via injected `FsProbe` | cargo |
| §4.10(f) output-stream | `core/governed_output_stream.rs` — LIVE→expired→swept, one-shot token, TTL, FIFO evict | 7 cargo |
| §5 supervisor ledger | `core/supervisor_ledger.rs` — durable acceptance state machine (DB-trigger + Rust guards) + outbox + evidence-head-floor CAS | cargo |
| §7 verification | `core/governed_verification.rs` — `verify_and_accept` (ed25519 envelope + supervisor attestation + request_sha256 recompute + output-hash + replay/nonce) → `AcceptedOutput` | cargo |
| §2.1 transport | `core/ipc_framing.rs` — bounded length-prefixed frame + `SO_PEERCRED` peer-auth (allow ONLY broker UID, deny renderer/sidecar) | 6 cargo |
| §0.W Windows | `core/windows_broker.rs` — restricted-token / named-pipe peer-auth / image / STARTUPINFOEX verifiers | 5 cargo |
| P1-1 ids | `core/real_ids.rs` — UUIDv4 broker_turn_id/request_nonce | 1 cargo |
| §4.10(g) renderer client | `core/broker_client.rs` — renderer→broker framed roundtrip (injected transport) | 3 cargo |
| §2.7 launcher | `launcher/` crate — Model-A setuid launcher (Linux: FD survival + privilege drop + fexecve) **[LINUX-RUN-PENDING]** | 12 cargo (pure) |
| §2 executor | `executor/` crate — reads FD 3/4/5, writes FD 6 (Linux) **[LINUX-RUN-PENDING]** | 5 cargo (pure) |
| §0 role #2 broker | `broker/` crate — DB init + `AF_UNIX` listener + orchestrator; `ChainExecutor` + per-hop `chain_hops` clients **[LINUX-RUN-PENDING for sockets]** | cargo |
| §2.1 authority | `engine/runtime/challenge_authority{,_server}.py` — create-pending/issue split + `SO_PEERCRED` broker allowlist | 27 py |
| §5 supervisor svc | `engine/runtime/governed_supervisor.py` — two-phase challenge verify + lease + launch gate | py |
| §7 signer svc | `engine/runtime/isolated_signer.py` — recompute-then-sign (not a sign(bytes) oracle) + attestation verify | py |
| §4.10(g) renderer (TS) | `apps/desktop/src/services/governedTurn.ts` — thin proxy (only closed fields) + read-only committed/blocked parse; `desktop.ts` transport; `governed_turn.rs` Tauri command | 11 vitest |

## What the auditor should focus on
1. **Trust boundary**: the renderer sends ONLY `{conversation_id, agent?, client_request_id}`; confirm no
   path lets it supply system/history/config/hashes/nonces/verdict or mint `trusted_verified`.
2. **Commit-readback + trust pinning**: `governed_message_store` + the DB CHECK constraint — a forged trust
   state must be unrepresentable; a post-commit re-read mismatch must fail closed.
3. **No oracle**: `isolated_signer` recomputes its own envelope; the supervisor builds evidence from ids.
4. **FD + privilege contracts** (`fd_lifecycle`, `privilege_drop`, launcher crate) — the exact rev-30 §2.7.
5. **Fail-closed everywhere**: every module returns a closed reason on bad input; no `unwrap`/panic in
   non-test code.

## Honest open items (NOT claimed done)
- **[LINUX-RUN-PENDING]** the real 7-service `AF_UNIX` run (broker↔authority↔supervisor↔signer↔launcher↔
  executor) + the end-to-end Linux isolation proof — the `LinuxGovernedTurnChain` sequences the hops but
  its live socket wiring + the multi-service run are exercised only on a real Linux box, not a host unit
  test.
- The `ChainExecutor`'s crypto assembly (building `verify_and_accept` inputs from the live hop replies) is
  wired to the abstraction; the end-to-end crypto path is proven per-module (`governed_verification`), not
  yet as one live run.
- 3b-2 (signed manifest + pinned root + anti-rollback) / 3b-3 (resolver + first production
  `trusted_verified`) are NOT started.

**No production `trusted_verified` until this code-audit is GREEN, the Linux end-to-end proof passes, and
the 3b-2/3b-3 chain lands.**
