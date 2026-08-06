# Wiring a LIVE AI turn to `trusted_verified` — honest design + runbook

This is the map for making the in-app Bro's **live** answers reach a real, honest
`trusted_verified` — not a demonstration, not a fake green. Read
[`CUSTODY_CEREMONY.md`](./CUSTODY_CEREMONY.md) first; production custody is the
prerequisite and is already half-done (the operator's offline root is pinned).

## Where we are

- The crypto chain (challenge → lease → attest → sign → `verify_and_accept`) is **real and
  reproducibly proven in-process** (`proof::in_process_turn`, run by `cargo test -p
  brops-win-live` on any host — it uses the demonstration anchor, so it reports demonstration
  custody, never production). The named-pipe path (`bin/win_live_turn.rs` +
  `win_authority`/`win_supervisor`/`win_signer`) is **built but not reproducibly proven from
  this tree**: `proof/win_live_proof.ps1` needs the operator's offline root private key, which
  is deliberately not here, and no CI workflow runs any of it. See
  [`proof/CROSS_ACCOUNT_PROOF.md`](./proof/CROSS_ACCOUNT_PROOF.md).
- Production **custody** is graduated: `tcb::ROOT_PUBLIC_KEY_HEX` is the operator's key
  whose private half is offline. Nothing in-tree can forge a production manifest.
- **Live chat still runs fail-closed**: the app uses the ungoverned `claude-cli` provider,
  which emits raw text with no signed receipt, so `resolve_trust_state` returns
  `NoTrustedManifest`. The UI never shows a production green for a live turn. Good.

## The one honest gap left: WIRING

A live turn reaches `trusted_verified` only when the **governed chain** executes it and a
real `verify_and_accept` passes under the provisioned manifest. Two seams + the operator's
infrastructure:

### Seam 1 — the executor produces the AI answer (containment resolution)
`bin/win_executor.rs` today writes a fixed byte string. In the governed model the executor
is the ONLY component that produces the turn's output bytes, and those bytes are what the
signer binds. So **the executor IS where the Claude call belongs**: it invokes `claude`
(headless, the same bounded flags the chat path uses) and writes Claude's exact reply to
stdout. The signer then content-addresses + signs *that*, and `verify_and_accept` binds it.

- The executor runs under the supervisor's restricted token / session-0 containment. Giving
  it network + the user's Claude login is the deliberate trust decision: the executor is a
  *trusted principal* in the TCB, launched by the supervisor whose launcher/executor SHA is
  pinned in the manifest (`config.supervisor_cfg.executor_executable_sha256`). Rebuild →
  re-provision so the pinned hash matches, or the supervisor refuses to launch it.
- File: `bin/win_executor.rs` `main()` — replace the fixed buffer with a `claude` subprocess
  whose stdout becomes the output. Keep it deterministic-in, exact-bytes-out (no logging on
  stdout).

### Seam 2 — the desktop drives the governed chain per message
`ai.rs::resolve_provider` must route a live turn through `Provider::GovernedEngine` (not
`ClaudeCli`) when governed mode is selected, and `commands.rs::stream_reply`'s governed
branch already calls `governed_turn` + verifies the receipt via `receipt_store`. The desktop
verification authority must be the real `ManifestReceiptKeyAuthority`
(`core::manifest_authority`) backed by the provisioned manifest — NOT the fail-closed
`NoTrustedManifest`. Then a passing `verify_and_accept` yields `trusted_verified`; any gap
still Blocks.

- Files: `ai.rs:resolve_provider` (select GovernedEngine), `commands.rs` governed branch
  (already verifies), and the authority wiring that currently hands `NoTrustedManifest`.
- Governed turns are **not streamed** (the whole reply must be buffered + verified before
  rendering), so the UX shows a "verifying…" state, then the verified message or a Block.

## Operator runbook (the infrastructure only you can stand up)

1. **Custody** — finish [`CUSTODY_CEREMONY.md`](./CUSTODY_CEREMONY.md): your offline root is
   already pinned; provision a deployment signing the manifest with your offline private:
   `win_provision --root-dir <deploy> --root-key <offline seed> --root-provenance external
   --allowed-broker-sid <SID> --executor-path <path to the rebuilt win_executor.exe>
   --challenge-account <acct> --supervisor-account <acct> --signer-account <acct>`.
   `--root-provenance` is the custody DECLARATION and has no default: nothing in the tool can
   tell where the seed it was handed came from, and only `external` can ever render production.
2. **Build the sidecar bins** (`cargo build --release --bin win_authority --bin win_supervisor
   --bin win_signer --bin win_executor --bin win_live_turn --bin win_tcb_pin`) and record the
   win_executor SHA into provisioning (step 1's `--executor-path`).
3. **Measure the deployment (§2.5 TCB integrity floor)** — run elevated, after provisioning and
   before anything starts: `win_tcb_pin --root-dir <deploy> --bin-dir <bins> --out
   <deploy>\tcb-pin.json`. It pins the five binaries and the four steering files, locks the
   manifest to SYSTEM/Administrators, and self-checks the floor it just wrote. **Until this
   exists the kit will not serve**: each server exits 5 and the driver returns
   `blocked reason=tcb_integrity_floor`. That is the intended fail-closed state, not a bug.
   Re-run it after ANY rebuild or config change — the pin is a start-time measurement.
4. **Run the three server cores** (each in its own process, peer-SID-gated pipes):
   `win_authority`, `win_supervisor`, `win_signer`, pointed at `<deploy>/config.json`.
5. **Point the app at governed mode**: set `BROPS_ALLOW_GOVERNED_ENGINE=1` (+ the deploy
   dir), unset `BROPS_ALLOW_UNGOVERNED`, and select the governed provider. Each message then
   runs the real chain; the UI shows `trusted_verified` **only** when `verify_and_accept`
   passes under your manifest.

## What stays true no matter what

- Until the chain runs AND verifies, the app is **fail-closed** — a live turn shows
  `NoTrustedManifest`, never a fake production green.
- The demonstration self-test (`governed_trust_selftest`) proves the crypto under the
  **demo** anchor and says so; it never flips a live turn.
- Rebuilding the executor changes its SHA → you MUST re-provision, or the supervisor refuses
  to launch it. That refusal is the guarantee that the signed output came from the exact,
  pinned executor image.
