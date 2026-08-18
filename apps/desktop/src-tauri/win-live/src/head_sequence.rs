//! The execution side's DURABLE monotonic evidence head-sequence counter.
//!
//! # Why this exists (remediation audit **R-42**, and the claim that had nothing behind it)
//!
//! `ExecutionParams::head_sequence` carried this sentence: *"A deployment must advance it across runs
//! or the supervisor's evidence floor has nothing to order; the caller owns that counter."* Both
//! shipped callers violated it. `win_live_turn` passed `cfg.facts.evidence_head_sequence` — a value
//! read out of `config.json`, identical on every run of the deployment — and the in-process proof
//! passed the literal `3`. So the head sequence, the ONE number in the evidence chain whose job is to
//! order two runs against each other, was a constant. A stated precondition that no caller meets is
//! the same defect as a check that cannot fail: the sentence did the work the code did not.
//!
//! `head_sequence` is the re-anchor/re-sign epoch. `event_count` / `last_sequence` /
//! `final_event_hash` describe ONE chain and say nothing about which of two chains is newer;
//! `head_sequence` is the only field that does. Its Linux counterpart is `governed_recorder`'s
//! `next_head_sequence`, which read-increments a single recorder-owned
//! `<evidence_state_dir>/evidence-head-sequence.json` so the number is monotonic across every run of
//! a deployment regardless of task. This is that counter for the Windows kit, byte-compatible in
//! meaning so [`brops_core::supervisor_ledger::evidence_floor_cas`] polices the same quantity on both
//! platforms.
//!
//! # What this establishes, and what it does NOT
//!
//! It establishes **allocation**: no two calls against the same state directory return the same
//! number, even concurrently, because a sequence is claimed by `create_new` — an atomic
//! `O_EXCL` / `CREATE_NEW` — and not by a read-then-write the loser of a race silently wins.
//!
//! It does NOT establish **custody**. Nothing here stops a principal that can write the state
//! directory from deleting the markers and re-allocating a number it already used. That is the
//! deployment's job (in the cross-account kit the directory belongs to the executor principal), and
//! it is why the supervisor keeps its OWN durable floor rather than believing this number: a replayed
//! sequence reaches `evidence_floor_cas` and is refused `evidence_fork`. Said plainly here rather
//! than left to be assumed, because the last three audit rounds all punished the opposite.

use std::io::ErrorKind;
use std::path::{Path, PathBuf};

/// The recorder-owned hint file. Its NAME matches the Linux recorder's so an operator reading either
/// deployment is reading the same artifact.
const COUNTER_FILE: &str = "evidence-head-sequence.json";

/// How far a single allocation will walk past a stale hint before refusing. A run that needs more
/// than this has a state directory somebody else is driving; refusing beats spinning.
const MAX_PROBE: i64 = 4096;

/// The path of the claim marker for one sequence number. Zero-padded so the directory sorts.
fn marker(state_dir: &Path, n: i64) -> PathBuf {
    state_dir.join(format!("seq-{n:012}.claim"))
}

/// Read the durable hint. `Ok(0)` ONLY when the file genuinely does not exist.
///
/// A present-but-unreadable or malformed hint is an ERROR, never `0`. Coercing damage to "no counter
/// yet" is exactly the shape the engine's L-4 head floor was defeated by — a mark that stops existing
/// reads as no mark required, so the cheapest attack on a floor is to break it rather than beat it.
fn read_hint(path: &Path) -> Result<i64, String> {
    let raw = match std::fs::read(path) {
        Ok(b) => b,
        Err(e) if e.kind() == ErrorKind::NotFound => return Ok(0),
        Err(e) => return Err(format!(
            "head-sequence counter unreadable at {}: {e} [{}]", path.display(), read_failure_context(path, &e))),
    };
    let doc: serde_json::Value = serde_json::from_slice(&raw)
        .map_err(|e| format!("head-sequence counter malformed at {}: {e}", path.display()))?;
    match doc.get("head_sequence").and_then(serde_json::Value::as_i64) {
        Some(n) if n >= 0 => Ok(n),
        _ => Err(format!(
            "head-sequence counter at {} has no non-negative integer `head_sequence`",
            path.display()
        )),
    }
}

/// What the refusal above could not say, and the next CI occurrence will need (`T-039`).
///
/// On 2026-08-18 `concurrent_allocations_never_return_the_same_number` failed once in CI with
/// `Access is denied. (os error 5)` while the other 106 tests in the same binary passed, and the
/// message carried nothing that could tell the two candidate causes apart. Both were then measured
/// on a real Windows box and **both were eliminated**:
///
/// * reading this path while two threads continuously `rename`-replace it produced **zero** errors
///   over ~27 000 reads — so it is not the writer's own replace window, and `T-039`'s proposed
///   "serialise the writer" fix is not what the evidence supports;
/// * a third party holding the file with `share_mode(0)` — an on-access antivirus scan — produces
///   **error 32** (`ERROR_SHARING_VIOLATION`), not error 5.
///
/// The cause is therefore still unidentified, and the honest response to an unidentified
/// intermittent refusal on an anti-rollback floor is **not** a retry loop (which would turn "read
/// succeeded" into "read eventually succeeded", a different claim about a floor) and **not** a
/// coercion to `0`. It is to make the next occurrence diagnosable in one shot. This function is
/// message-only: it changes nothing about WHEN the read refuses.
fn read_failure_context(path: &Path, e: &std::io::Error) -> String {
    let code = e.raw_os_error().map_or_else(|| "none".to_string(), |c| c.to_string());
    let exists = path.try_exists().map_or("unknown", |b| if b { "yes" } else { "no" });
    let meta = std::fs::symlink_metadata(path)
        .map(|m| format!("len={} readonly={} dir={}",
                         m.len(), m.permissions().readonly(), m.is_dir()))
        .unwrap_or_else(|_| "stat-failed".to_string());
    // A `.writing` sibling means a `write_hint` was in flight when this read refused, which is the
    // hypothesis the measurement above did NOT support -- so if the next occurrence shows one, that
    // conclusion is the thing to revisit first.
    let staging = path.parent()
        .and_then(|d| std::fs::read_dir(d).ok())
        .map(|rd| rd.filter_map(Result::ok)
                    .filter(|x| x.file_name().to_string_lossy().ends_with(".writing"))
                    .count())
        .map_or_else(|| "?".to_string(), |n| n.to_string());
    format!("raw_os_error={code} kind={:?} exists={exists} {meta} staging_siblings={staging}", e.kind())
}

/// Persist the hint. A failure here REFUSES the allocation rather than being swallowed: the markers
/// are the authority, but a hint that never advances makes every later allocation walk further, and
/// silently degrading a durable counter into a linear scan is how this class of defect hides.
///
/// The staging file is named for the sequence being written, which is unique by construction (it was
/// just claimed with `create_new`). A SHARED staging name is the engine's R-30 defect — two
/// concurrent turns racing over one temp path, where the loser's `rename` finds nothing and the
/// allocation fails for no reason. `concurrent_allocations_never_return_the_same_number` found
/// exactly that here before this line said `{n}`.
///
/// Under concurrency the hint may transiently record a LOWER number than another thread already
/// claimed. That costs the next caller a short walk over taken markers and can never issue a
/// duplicate, because the markers — not the hint — decide.
fn write_hint(path: &Path, n: i64) -> Result<(), String> {
    let body = format!("{{\"head_sequence\":{n}}}");
    let tmp = path.with_extension(format!("{n}.writing"));
    std::fs::write(&tmp, body.as_bytes())
        .map_err(|e| format!("head-sequence counter not writable at {}: {e}", tmp.display()))?;
    // Same directory, so this is an atomic replace on both platforms (Windows `MoveFileExW` with
    // `MOVEFILE_REPLACE_EXISTING`, POSIX `rename`). A reader never sees a half-written counter.
    std::fs::rename(&tmp, path)
        .map_err(|e| format!("head-sequence counter not replaceable at {}: {e}", path.display()))
}

/// Allocate the next head sequence for this install, durably.
///
/// Returns a value strictly greater than every value this state directory has ever returned, for as
/// long as its claim markers survive. The first call against a fresh directory returns `1`
/// (`evidence_floor_cas` refuses `head_sequence < 1`, so 0 is not a legal head).
///
/// `create_dir_all` is deliberate: this function establishes allocation, not custody (see the module
/// docs). The directory's ACL is `win_provision`'s job and the supervisor's floor is what makes a
/// broken counter a refusal rather than a bypass.
pub fn next_head_sequence(state_dir: &Path) -> Result<i64, String> {
    std::fs::create_dir_all(state_dir).map_err(|e| {
        format!("head-sequence state dir unusable at {}: {e}", state_dir.display())
    })?;
    let counter = state_dir.join(COUNTER_FILE);
    let hint = read_hint(&counter)?;
    let mut candidate = hint + 1;
    for _ in 0..MAX_PROBE {
        match std::fs::OpenOptions::new().write(true).create_new(true).open(marker(state_dir, candidate))
        {
            // Claimed. `create_new` is atomic, so exactly one concurrent caller reaches here for a
            // given number and the other walks on — no read-then-write window to lose.
            Ok(_) => {
                write_hint(&counter, candidate)?;
                return Ok(candidate);
            }
            Err(e) if e.kind() == ErrorKind::AlreadyExists => candidate += 1,
            Err(e) => {
                return Err(format!(
                    "head-sequence claim failed at {}: {e}",
                    marker(state_dir, candidate).display()
                ))
            }
        }
    }
    Err(format!(
        "head-sequence could not be allocated: {MAX_PROBE} consecutive claims from {} are already taken",
        hint + 1
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("brops-headseq-{tag}-{}", brops_core::id()));
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    /// The property the constant did not have: two runs get two numbers, in order.
    #[test]
    fn the_counter_advances_across_calls() {
        let d = tmp("advance");
        assert_eq!(next_head_sequence(&d).unwrap(), 1);
        assert_eq!(next_head_sequence(&d).unwrap(), 2);
        assert_eq!(next_head_sequence(&d).unwrap(), 3);
        let _ = std::fs::remove_dir_all(&d);
    }

    /// And the property an in-process counter could not have: it survives the process.
    ///
    /// There is no process to restart in a unit test, so this asserts what a restart depends on —
    /// that the number is reconstructed from the DIRECTORY and not from anything held in memory.
    #[test]
    fn the_counter_is_reconstructed_from_disk_not_from_memory() {
        let d = tmp("durable");
        assert_eq!(next_head_sequence(&d).unwrap(), 1);
        assert_eq!(next_head_sequence(&d).unwrap(), 2);
        // A second, entirely independent caller — the moral equivalent of a restarted recorder.
        assert_eq!(next_head_sequence(&d).unwrap(), 3);
        assert!(d.join(COUNTER_FILE).exists(), "the hint must be durable, not in-process");
        let _ = std::fs::remove_dir_all(&d);
    }

    /// A damaged counter REFUSES. It must not read as "no counter yet", which would restart the
    /// sequence at 1 and hand a replayed head straight past the floor.
    /// `T-039`. An unreadable counter must still REFUSE — that half is unchanged and is asserted
    /// first — and the refusal must now carry enough to identify the cause. The one CI occurrence
    /// said only `Access is denied. (os error 5)`, which is compatible with a replace window, an
    /// antivirus scan and an ACL, and both of the first two were measured and eliminated without
    /// the message's help. A directory reproduces exactly that errno deterministically on Windows.
    #[test]
    fn an_unreadable_counter_refuses_AND_says_enough_to_diagnose_it() {
        let d = tmp("unreadable");
        std::fs::create_dir_all(&d).unwrap();
        // A directory where the counter file belongs: `read` fails with ERROR_ACCESS_DENIED (5) on
        // Windows and EISDIR on POSIX. Either way it is the not-NotFound branch.
        std::fs::create_dir_all(d.join(COUNTER_FILE)).unwrap();
        let err = next_head_sequence(&d).unwrap_err();
        assert!(err.contains("unreadable"), "still refuses: {err}");
        assert!(err.contains("raw_os_error="), "names the OS error code: {err}");
        assert!(err.contains("kind="), "names the ErrorKind: {err}");
        assert!(err.contains("exists=yes"), "distinguishes absent from unreadable: {err}");
        assert!(err.contains("dir=true"), "reports what the path actually is: {err}");
        assert!(err.contains("staging_siblings="),
                "reports whether a write_hint was in flight, which is the hypothesis to revisit                  first if a future occurrence shows one: {err}");
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn a_malformed_counter_refuses_rather_than_reading_as_absent() {
        let d = tmp("malformed");
        next_head_sequence(&d).unwrap();
        std::fs::write(d.join(COUNTER_FILE), b"not json at all").unwrap();
        let err = next_head_sequence(&d).unwrap_err();
        assert!(err.contains("malformed"), "{err}");

        std::fs::write(d.join(COUNTER_FILE), br#"{"head_sequence":"7"}"#).unwrap();
        let err = next_head_sequence(&d).unwrap_err();
        assert!(err.contains("non-negative integer"), "{err}");

        std::fs::write(d.join(COUNTER_FILE), br#"{"head_sequence":-1}"#).unwrap();
        let err = next_head_sequence(&d).unwrap_err();
        assert!(err.contains("non-negative integer"), "{err}");
        let _ = std::fs::remove_dir_all(&d);
    }

    /// A hint rolled BACKWARD does not re-issue a number: the claim markers are the authority, so the
    /// allocation walks up past every sequence this directory has already handed out.
    ///
    /// This is the whole reason a sequence is claimed by `create_new` rather than computed from the
    /// hint. Without the markers, `head_sequence` = hint+1 and rewriting one small file replays the
    /// entire chain order.
    #[test]
    fn a_rolled_back_hint_cannot_re_issue_a_sequence_already_claimed() {
        let d = tmp("rollback");
        for expected in 1..=5 {
            assert_eq!(next_head_sequence(&d).unwrap(), expected);
        }
        std::fs::write(d.join(COUNTER_FILE), br#"{"head_sequence":0}"#).unwrap();
        assert_eq!(
            next_head_sequence(&d).unwrap(),
            6,
            "a rewritten hint must not re-issue 1..5 — those markers exist"
        );
        let _ = std::fs::remove_dir_all(&d);
    }

    /// The walk is bounded, and says so, rather than spinning on a directory somebody else owns.
    #[test]
    fn the_probe_is_bounded_rather_than_unbounded() {
        let d = tmp("bounded");
        // Claim every sequence in [1, MAX_PROBE] directly, then ask for one.
        for n in 1..=MAX_PROBE {
            std::fs::write(marker(&d, n), b"").unwrap();
        }
        let err = next_head_sequence(&d).unwrap_err();
        assert!(err.contains("already taken"), "{err}");
        // ...and one free slot inside the window is still found, so the bound is a bound and not a
        // blanket refusal.
        std::fs::remove_file(marker(&d, MAX_PROBE)).unwrap();
        assert_eq!(next_head_sequence(&d).unwrap(), MAX_PROBE);
        let _ = std::fs::remove_dir_all(&d);
    }

    /// Two allocations never collide, because the claim is `create_new` and not read-then-write.
    #[test]
    fn concurrent_allocations_never_return_the_same_number() {
        let d = tmp("concurrent");
        let mut handles = Vec::new();
        for _ in 0..8 {
            let dir = d.clone();
            handles.push(std::thread::spawn(move || {
                (0..8).map(|_| next_head_sequence(&dir).unwrap()).collect::<Vec<_>>()
            }));
        }
        let mut all: Vec<i64> = handles.into_iter().flat_map(|h| h.join().unwrap()).collect();
        all.sort_unstable();
        let issued = all.len();
        all.dedup();
        assert_eq!(all.len(), issued, "a sequence number was issued twice");
        let _ = std::fs::remove_dir_all(&d);
    }
}

