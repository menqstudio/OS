//! Wave 3b-1B — the trusted broker's library surface.
//!
//! The broker binary ([`main.rs`]) wires the renderer→broker transport; this library exposes the
//! governed-chain ORCHESTRATION so the Linux live-turn driver (the `proof` crate) can instantiate the SAME
//! [`chain_executor::linux::LinuxGovernedTurnChain`] / [`chain_executor::linux::LinuxHopConnector`] /
//! [`chain_executor::linux::LinuxGovernedExecution`] the broker uses. There is exactly one implementation of
//! the real challenge-authority → supervisor → execution → isolated-signer → `verify_and_accept` flow, and
//! it lives here — no driver re-implements a hop or a crypto check.
//!
//! The pure orchestration ([`chain_executor::GovernedChain`] + its trait seams) and the per-hop message
//! layer ([`chain_hops`]) are cross-platform and unit-tested on any host; only the AF_UNIX transport + the
//! privileged execution spawn are `#[cfg(target_os = "linux")]`.

pub mod chain_hops;

pub mod chain_executor;

/// The broker's compiled-in TCB root anchor (production-trust root public key).
pub mod tcb;

/// The REAL filesystem probe + loader behind the §2.5 TCB-integrity floor (audit F-10). The floor's
/// decision core lives in `brops_core::tcb_integrity` and was fully implemented with no caller and no
/// non-test `FsProbe`; this is the half that makes it run.
pub mod tcb_probe;

/// The broker's production `TurnResolver` — fail-closed by default; the real manifest resolution when a
/// trusted manifest is provisioned.
pub mod manifest_resolver;

/// The rev-30 §4.10(g) SIDECAR LADDER: the broker-side governed turn whose three artifact digests are
/// derived from the actual conversation rather than read out of deployment config. It is the caller
/// `brops_core::governed_submit::governed_turn_submit_prepared` never had.
pub mod ladder_executor;

/// **Provisioning preflight**: which of the governed turn's prerequisites does THIS machine meet?
///
/// `build_governed_executor` is a ladder of `return fail_closed()` branches that all produce the same
/// observable — a `blocked` reply. This module walks the same requirement set and reports each one by
/// name, with who would have to provision it. It reads; it never writes, provisions or flips anything.
/// Served to an operator by the `brops-preflight` binary.
pub mod preflight;
