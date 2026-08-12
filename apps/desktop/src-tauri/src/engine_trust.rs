//! The app's view of the one place this deployment hands the engine its provisioned trust material.
//!
//! **The rule itself lives in [`brops_core::engine_trust`]**, and this file is a re-export plus the
//! one adapter that reads `brops_provision`. It moved on 2026-08-12, and the reason is the whole
//! point of the move:
//!
//! The rule used to live here, in the renderer-hosting binary crate, because its only consumer
//! (`ai::governed_sidecar_call`) did. §4.10(g) then put the governed submit hop in the BROKER
//! service (§0 role #2) — a separate, synchronous binary that cannot depend on a binary crate at
//! all. A spawn there would have been a SECOND spawn, and therefore a second trust application:
//! one path consulting the provisioned registry and the other the stale committed one, with nothing
//! to say so. That is precisely the "half-wired export" the old seam's own comment called worse than
//! no export at all. So the spawn and the trust rule both moved down into `brops-core`, the crate
//! both binaries share, and `brops_core::governed_sidecar::GovernedSidecar` is now the only thing in
//! the tree that starts `python bridge/engine_sidecar.py`.
//!
//! This file stays because the ADAPTER has to live somewhere the `brops_provision` types are
//! visible — `brops-core` deliberately does not depend on the crate that holds private key halves —
//! and because `brops_lib::engine_trust::resolve` is what `tests/o3_conductor_session.rs` drives
//! against the real Python verifiers. Both this file and
//! `apps/desktop/src-tauri/core/src/engine_trust.rs` are in [`crate::ai::BRO_PROTECTED_PATHS`].
//!
//! Read the precedence rule, the six refusals, and why each is a refusal rather than an order, in
//! [`brops_core::engine_trust`]'s module docs. Nothing about that decision changed in the move.

pub use brops_core::engine_trust::{
    apply, resolve, TrustEnvironment, NOT_PROVISIONED, RAW_CI_FLOOR, RAW_CI_PIN, SELF_OWNED_ACK,
    SELF_OWNED_ACK_FILE,
};

/// Record what first-launch provisioning produced. Called once, from startup.
///
/// The one adapter: [`brops_provision::Provisioned::engine_env`] is still the single source of the
/// SET (a variable added there is automatically covered), and this hands it to the crate that
/// applies it. A second call is ignored rather than panicking, exactly as before — provisioning runs
/// once per process by construction, and a startup path that somehow called twice must not take the
/// app down after the trust store is already established.
pub fn record(provisioned: &brops_provision::Provisioned) {
    brops_core::engine_trust::record(provisioned.engine_env(), &provisioned.operator_public_key);
}
