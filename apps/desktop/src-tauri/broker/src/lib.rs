//! Wave 3b-1B — the trusted broker's library surface.
//!
//! The broker binary ([`main.rs`]) wires the renderer→broker transport; this library holds the
//! governed-chain ORCHESTRATION, so that the binary and the Linux proof drivers (the `proof` crate) call
//! the same code and no driver re-implements a hop or a crypto check. There are TWO chains here, and
//! they are not interchangeable:
//!
//!  * [`ladder_executor::LadderChain`] — the rev-30 §4.10(g) sidecar ladder. It is the ONLY chain the
//!    `brops-broker` binary builds, and `proof/src/bin/ladder_turn.rs` builds the same object.
//!  * [`chain_executor::linux::LinuxGovernedTurnChain`] (with
//!    [`chain_executor::linux::LinuxGovernedExecution`]) — the DIRECT challenge-authority → supervisor →
//!    execution → isolated-signer chain. **No shipped binary constructs it.** Its one constructor is
//!    `proof/src/bin/live_turn.rs`, which is what `engine/ci/live/run_live_turn.sh` proves the §2.5
//!    floor and the §5 lifecycle with.
//!
//! What the two share is real and is here once: [`chain_executor::linux::LinuxHopConnector`], the hop
//! and reply parser ([`chain_hops`]), the key resolution ([`manifest_resolver`]) and the final
//! `verify_and_accept`. This paragraph used to say the proof driver instantiates "the SAME
//! `LinuxGovernedTurnChain` the broker uses" and that there is "exactly one implementation" of the
//! flow; the broker stopped building that chain on 2026-08-12.
//!
//! The pure orchestration ([`chain_executor::GovernedChain`] + its trait seams) and the per-hop message
//! layer ([`chain_hops`]) are cross-platform and unit-tested on any host; only the AF_UNIX transport + the
//! privileged execution spawn are `#[cfg(target_os = "linux")]`.

pub mod chain_hops;

pub mod chain_executor;

/// The root-anchor rules: the parser for the TCB anchor FILE the broker reads its root from, and the
/// one compiled-in root that may be called `external`. The Linux broker no longer PINS that
/// constant as its root (T-131 slice C) — see the module's own header.
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

/// The broker's database path, derived from its listening-socket path: `<stem>.sock` → `<stem>.db`.
///
/// `None` unless the socket path ENDS in `.sock` with something before it. That is the whole point
/// of having this function: the rule used to be `socket_path.replace(".sock", ".db")`, written
/// separately in `main.rs` and in the preflight (and a third way, `with_extension("db")`, in the
/// binary's end-to-end test). `replace` leaves a path that does not contain `.sock` unchanged — so
/// the "database path" WAS the socket path, and the broker opened its ledger there and then
/// unlinked it as a stale socket — and rewrites every occurrence, including one in a directory
/// name. A caller that gets `None` has no database path and must not invent one.
pub fn broker_db_path(socket_path: &str) -> Option<String> {
    let stem = socket_path.strip_suffix(".sock").filter(|stem| !stem.is_empty())?;
    Some(format!("{stem}.db"))
}

#[cfg(test)]
mod tests {
    use super::broker_db_path;

    #[test]
    fn the_database_sits_beside_the_socket_under_the_same_stem() {
        assert_eq!(broker_db_path("/run/brops/broker.sock").as_deref(), Some("/run/brops/broker.db"));
        assert_eq!(broker_db_path("broker.sock").as_deref(), Some("broker.db"));
        // Only the SUFFIX is rewritten: a `.sock` earlier in the path is a directory's name.
        assert_eq!(
            broker_db_path("/run/brops.sock.d/broker.sock").as_deref(),
            Some("/run/brops.sock.d/broker.db")
        );
    }

    #[test]
    fn a_socket_path_that_does_not_end_in_sock_has_no_database_path() {
        // Each of these came back UNCHANGED from the old `replace`, i.e. as the socket path itself.
        for path in ["/run/brops/broker", "/run/brops/broker.socket", "/run/brops/broker.sock.bak", ""] {
            assert_eq!(broker_db_path(path), None, "{path:?}");
        }
        // `.sock` in a directory name is not a suffix either.
        assert_eq!(broker_db_path("/run/brops.sock/broker"), None);
        // And a path that is nothing but the suffix names no file to sit beside.
        assert_eq!(broker_db_path(".sock"), None);
        // The property itself: whatever comes back is never the socket path.
        for path in ["/a/b.sock", "x.sock", "/run/brops.sock.d/broker.sock"] {
            assert_ne!(broker_db_path(path).as_deref(), Some(path));
        }
    }
}
