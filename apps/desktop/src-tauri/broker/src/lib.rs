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

/// The broker's production `TurnResolver` — fail-closed by default; the real manifest resolution when a
/// trusted manifest is provisioned.
pub mod manifest_resolver;
