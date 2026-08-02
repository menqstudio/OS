# Debian/Linux continuation — Wave 3b-1B end-to-end (paste this as your first message)

> Paste the block below into a fresh Claude Code session on the Debian box. It is self-contained: it points
> at the repo, the exact branch, what is already built + verified, and the LINUX-ONLY work that could not be
> done on the Windows dev box. Keep the repo's `CLAUDE.md` startup contract + the honesty law.

---

You are continuing **menqstudio/OS**, Wave **3b-1B** (governed-AI trust chain), on a real **Debian Linux**
box. This session does the **LINUX-ONLY** end-to-end that the Windows dev box could not run. Read the repo's
`CLAUDE.md` first (canonical read manifest + startup hook + operating mode) and follow it.

## Context (do NOT re-derive — it is real, verify by reading)
- **Security DESIGN** is **Architect DESIGN GREEN** at **rev-30** and **MERGED to `main`** (PR #31, with the
  3b-1A isolated-signer boundary code = Architect Code GREEN). Design ≠ code ≠ running: no production
  `trusted_verified` exists; `NoTrustedManifest` is fail-closed.
- The **implementation** is on branch **`impl/wave-3b1b-core`** (PR #46), unit-verified but **NOT Architect
  code-audited** and **never run end-to-end** (the Windows box can't do AF_UNIX/setuid/fexecve/`/proc`).
- Normative design: `docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`.
- Module→test map + honest open items: `docs/design/WAVE_3B1B_IMPL_CODE_AUDIT_REQUEST.md`.

## What is already built + unit-tested (~300+ tests: cargo / python / vitest)
- `apps/desktop/src-tauri/core/src/`: `governed_turn_ipc`, `governed_message_store` (commit-readback),
  `broker_turns`, `broker_orchestrator`, `supervisor_ledger` (§5), `governed_verification` (§7, ed25519),
  `fd_lifecycle`, `privilege_drop`, `tcb_integrity`, `governed_output_stream`, `ipc_framing` (SO_PEERCRED),
  `windows_broker`, `real_ids`, `broker_client`, `key_manifest` (3b-2), `production_trust` (3b-3).
- Crates: `launcher/` (Model-A setuid), `executor/` (FD 3-5→6), `broker/` (DB + AF_UNIX + orchestrator +
  `chain_executor` + `chain_hops`).
- Python services: `engine/runtime/{challenge_authority,challenge_authority_server,governed_supervisor,
  isolated_signer}.py`.
- Renderer: `apps/desktop/src/services/governedTurn.ts` + `desktop.ts` + `governed_turn.rs` Tauri command.

## Setup (Debian)
```bash
git clone https://github.com/menqstudio/OS.git && cd OS
git fetch origin impl/wave-3b1b-core && git checkout impl/wave-3b1b-core
# toolchains
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y && . "$HOME/.cargo/env"
sudo apt-get update && sudo apt-get install -y python3 python3-pip nodejs npm \
  libwebkit2gtk-4.1-dev build-essential curl wget file libssl-dev libayatana-appindicator3-dev librsvg2-dev
# verify the unit suites pass on Linux first (must be green before end-to-end)
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
( cd engine && python3 -m unittest discover -s tests )
( cd apps/desktop && npm ci && npm run test && npm run typecheck )
```

## The LINUX-ONLY tasks (in order; fail-closed; NEVER fake a pass)
1. **Full build on Linux**: `cargo build --manifest-path apps/desktop/src-tauri/Cargo.toml` (all crates:
   core, launcher, executor, broker) + the Tauri host. Fix any Linux-only compile issue.
2. **Provisioning harness**: create the 7 dedicated service accounts (or a rootless test-namespace harness)
   — `brops-verifier/broker`, `brops-challenge`, `brops-sidecar`, `brops-supervisor`, `brops-recorder`,
   `brops-executor`, `brops-signer` — with the socket dirs owned per §2.6, and a root/TCB-owned setuid
   launcher. `verify_distinct_principals()` + `verify_tcb_integrity()` must pass.
3. **Wire the live chain** (`broker/src/chain_executor.rs::linux::LinuxGovernedTurnChain`): implement the
   real AF_UNIX hops via `chain_hops` — broker→challenge-authority (create-pending/issue), broker→supervisor
   (open+lease), supervisor→launcher→executor (`fexecve`, FD 3-6 survival per `fd_lifecycle`/`privilege_drop`),
   broker→isolated-signer (sign-result), then `governed_verification::verify_and_accept` → `AcceptedOutput`.
4. **End-to-end isolation proof** — extend `engine/ci/isolation_proof.sh` (or add
   `engine/ci/governed_chain_proof.sh`): spin up all services, run ONE governed turn, and ASSERT (fail
   closed on any miss): (a) the executor inherits ONLY FDs 3-6 (`/proc/<pid>/fd`); (b) it drops to the
   executor UID with empty caps + `no_new_privs`; (c) the challenge-authority pipe denies the renderer +
   sidecar UIDs (SO_PEERCRED); (d) a committed reply carries `trust_state` bound to the real signed
   envelope; (e) a tampered output / wrong-peer / rolled-back manifest all fail closed.
5. **First production `trusted_verified`** — provision a test signed key manifest (a production-class key,
   root-signed), wire `key_manifest::verify_manifest` + `check_and_advance` + `production_trust::
   resolve_trust_state` into the committed turn, and prove ONE end-to-end `Production` trusted_verified —
   AND prove it fails closed to `NoTrustedManifest` without the manifest / with a dev key / rolled back.
6. Add a **Linux CI job** (`.github/workflows/`) that runs the end-to-end proof so it stays green.

## Gates + honesty (do NOT bypass)
- This is the **implementation**; the **Architect CODE-audit** is a separate external gate — do NOT
  self-declare code-GREEN. Prepare evidence (the proof output) for the audit.
- `NoTrustedManifest` stays fail-closed until step 5 genuinely passes on a real run. No faked green, no
  `|| true`, no stubbed "it works". If a step can't pass, say so with the real output.
- Keep the coordination docs synced (repo hook enforces it). Owner merges + release are Gev's gates.
- Every code change: real compile + real run evidence. CI-green ≠ code-audit-green ≠ release-green.

When the end-to-end proof passes on Linux, report: the proof output, the exact commit, and what remains
(Architect code-audit → 3b-2/3b-3 production wiring merge → signed release per `docs/RELEASE_SETUP.md`).
