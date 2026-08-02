//! Wave 3b-1B — the contained model **executor** as a SEPARATE binary crate (design-GREEN rev-30 §2/§2.7).
//!
//! This is the tiny, pinned image the privileged launcher `fexecve`s at the second exec boundary. By
//! construction it is the least-privileged process in the system:
//!   * it inherits EXACTLY the rev-30 §2.7 data descriptors — three READ-ONLY inputs (fd 3 = `system`,
//!     fd 4 = `history`, fd 5 = `generation_config`) and one WRITE-ONLY output pipe (fd 6),
//!   * it reads each of 3/4/5 to EOF, derives its output purely from those exact bytes, writes the output
//!     to fd 6, and exits 0,
//!   * it holds NO signing key, NO store handle, and NO socket, and it OPENS NOTHING ELSE — no file, no
//!     network, no additional descriptor (§2). Everything it may touch is a descriptor the launcher already
//!     verified and handed it.
//!
//! The launcher (a separate crate) is what proves the descriptor table, privilege drop, and image identity
//! before this binary ever runs; the executor therefore trusts its three inputs are the lease-bound store
//! bytes and does the one job it exists for — turn those bytes into an output on fd 6, deterministically.
//!
//! The input→output transform here is a **pure, host-independent binding** ([`build_output`]) computed from
//! the three inputs via the shared `brops_core` SHA-256 convention (rev-30 §4.0a / §5 manifest contract),
//! so the executor and the receipt/store side agree byte-for-byte on how the inputs are bound. It is a
//! deterministic placeholder for the pinned model-inference step, which lands with the model-image slice;
//! keeping it pure lets it be unit-tested on any OS with no process spawn and no syscall.
//!
//! The real fd I/O (`std::os::fd` / `File::from_raw_fd` on 3/4/5/6) exists only on Linux (Model A) and is
//! gated behind `#[cfg(target_os = "linux")]`. On every other host `main` prints the platform-unsupported
//! banner and exits non-zero — governed real mode is unavailable, so it fails closed.

use brops_core::governed_message_store::sha256_hex;

// ---------------------------------------------------------------------------------------------------
// The rev-30 §2.7 inherited data descriptors. These are the ONLY fds the executor touches; it never
// opens, dups, or closes-and-reopens anything. Bound here as named constants so the contract is explicit.
// ---------------------------------------------------------------------------------------------------
/// fd 3 — read-only `system` input.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const FD_SYSTEM: i32 = 3;
/// fd 4 — read-only `history` input.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const FD_HISTORY: i32 = 4;
/// fd 5 — read-only `generation_config` input.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const FD_GENERATION_CONFIG: i32 = 5;
/// fd 6 — write-only output pipe.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const FD_OUTPUT: i32 = 6;

// ---------------------------------------------------------------------------------------------------
// Exit codes (fail-closed). Success is a plain exit 0 after the output is written and flushed to fd 6.
// ---------------------------------------------------------------------------------------------------
/// A clean run: all three inputs read to EOF, output written and flushed to fd 6.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const EXIT_OK: i32 = 0;
/// An fd read/write/flush failed. No partial success is claimed — the executor exits non-zero.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const EXIT_IO_FAILURE: i32 = 1;
/// Real governed mode is only available on Linux (Model A). Any other host fails closed.
const EXIT_PLATFORM_UNSUPPORTED: i32 = 2;

/// The version tag prefixing the executor's output binding. Bumping the transform bumps this tag so the
/// receipt/store side can never silently accept an output produced under a different binding.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
const OUTPUT_BINDING_VERSION: &str = "brops-exec-output.v1";

/// Derive the executor's output bytes **purely** from its three inputs.
///
/// This is the whole computational contract of the executor expressed as a total, deterministic function:
/// identical inputs always yield identical output, and changing ANY one of the three inputs changes the
/// output (each is bound by its own SHA-256, and a final `binding` hash covers all three together). It uses
/// the shared `brops_core::sha256_hex` convention so the bytes it emits hash-bind exactly the way the
/// receipt manifest (`system`/`history`/`generation_config`) expects.
///
/// It is a stand-in for the pinned model-inference step (which lands with the model-image slice); the point
/// of this slice is the *plumbing* — three read-only inputs in, one deterministic output on fd 6 — and that
/// plumbing is exercised by a pure test rather than a spawned process.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
fn build_output(system: &[u8], history: &[u8], generation_config: &[u8]) -> Vec<u8> {
    let system_h = sha256_hex(system);
    let history_h = sha256_hex(history);
    let generation_config_h = sha256_hex(generation_config);
    // Bind all three together, order-fixed and length-unambiguous (each field is a fixed-width 64-hex
    // digest on its own line), so the combined `binding` cannot collide across different input splits.
    let binding_src = format!("{system_h}\n{history_h}\n{generation_config_h}");
    let binding_h = sha256_hex(binding_src.as_bytes());
    format!(
        "{OUTPUT_BINDING_VERSION}\n\
         system={system_h}\n\
         history={history_h}\n\
         generation_config={generation_config_h}\n\
         binding={binding_h}\n"
    )
    .into_bytes()
}

// ---------------------------------------------------------------------------------------------------
// Entry point.
// ---------------------------------------------------------------------------------------------------

fn main() {
    std::process::exit(run());
}

#[cfg(not(target_os = "linux"))]
fn run() -> i32 {
    // No inherited-fd execution model off Linux ⇒ governed real mode is unavailable. Fail closed, and do
    // NOT touch fds 3–6 (they carry no contract meaning on this host).
    eprintln!("executor: platform unsupported (governed real-mode disabled)");
    EXIT_PLATFORM_UNSUPPORTED
}

#[cfg(target_os = "linux")]
fn run() -> i32 {
    match linux::real_main() {
        Ok(()) => EXIT_OK,
        Err(e) => {
            // Fail closed: report which fd stage failed, write NO partial output, exit non-zero.
            eprintln!("executor: io failure ({e}), no output written");
            EXIT_IO_FAILURE
        }
    }
}

// ---------------------------------------------------------------------------------------------------
// Linux real path (§2/§2.7). The executor takes ownership of ONLY the four inherited data fds and touches
// nothing else. Reads reuse the pure binding above; the sole write is the output to fd 6.
// ---------------------------------------------------------------------------------------------------
#[cfg(target_os = "linux")]
mod linux {
    use super::*;
    use std::fs::File;
    use std::io::{Read, Write};
    use std::os::fd::FromRawFd;

    pub fn real_main() -> Result<(), &'static str> {
        // Read the three READ-ONLY inputs to EOF, in fd order. `from_raw_fd` adopts the inherited
        // descriptor the launcher handed us; we open nothing new.
        let system = read_fd_to_end(FD_SYSTEM).map_err(|_| "read system(fd3)")?;
        let history = read_fd_to_end(FD_HISTORY).map_err(|_| "read history(fd4)")?;
        let generation_config =
            read_fd_to_end(FD_GENERATION_CONFIG).map_err(|_| "read generation_config(fd5)")?;

        // Pure, deterministic input→output binding — no key, no store, no network.
        let output = build_output(&system, &history, &generation_config);

        // The single side effect: write the output to the WRITE-ONLY pipe on fd 6, then flush. A short
        // write or flush error is a hard failure — the executor never claims a partial success.
        // SAFETY: fd 6 is the inherited write-only output pipe the launcher verified and handed us; this is
        // the sole owner of that descriptor for the rest of the (about-to-exit) process lifetime.
        let mut out = unsafe { File::from_raw_fd(FD_OUTPUT) };
        out.write_all(&output).map_err(|_| "write output(fd6)")?;
        out.flush().map_err(|_| "flush output(fd6)")?;
        Ok(())
    }

    /// Adopt an inherited read-only descriptor and drain it to EOF. The `File` is dropped (closing the fd)
    /// as the process exits — the executor opens nothing and leaves nothing dangling.
    fn read_fd_to_end(fd: i32) -> std::io::Result<Vec<u8>> {
        // SAFETY: `fd` is one of the inherited read-only data descriptors (3/4/5) the launcher verified;
        // adopting it here gives this `File` sole ownership until the process exits.
        let mut f = unsafe { File::from_raw_fd(fd) };
        let mut buf = Vec::new();
        f.read_to_end(&mut buf)?;
        Ok(buf)
    }
}

// ---------------------------------------------------------------------------------------------------
// Tests — pure, offline, host-independent (run on Windows/macOS/Linux alike). They pin the deterministic
// input→output binding: no fd, no process spawn, no syscall.
// ---------------------------------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_output_is_deterministic() {
        let a = build_output(b"sys", b"hist", b"gencfg");
        let b = build_output(b"sys", b"hist", b"gencfg");
        assert_eq!(a, b, "identical inputs must yield identical output");
    }

    #[test]
    fn build_output_binds_each_input_independently() {
        let base = build_output(b"sys", b"hist", b"gencfg");
        // Changing ANY single input must change the output.
        assert_ne!(base, build_output(b"SYS", b"hist", b"gencfg"), "system change must alter output");
        assert_ne!(base, build_output(b"sys", b"HIST", b"gencfg"), "history change must alter output");
        assert_ne!(base, build_output(b"sys", b"hist", b"GENCFG"), "gen-config change must alter output");
    }

    #[test]
    fn build_output_does_not_confuse_field_boundaries() {
        // A naive concat transform would collide when bytes shift across the input boundary; the per-field
        // digest + combined binding must keep these distinct.
        let x = build_output(b"ab", b"c", b"d");
        let y = build_output(b"a", b"bc", b"d");
        assert_ne!(x, y, "boundary-shifted inputs must produce different outputs");
    }

    #[test]
    fn build_output_shape_is_the_pinned_binding() {
        let out = build_output(b"", b"", b"");
        let text = String::from_utf8(out).expect("output is valid UTF-8");
        // Version tag first, then the four bound fields, each a 64-hex digest, newline-terminated.
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 5);
        assert_eq!(lines[0], OUTPUT_BINDING_VERSION);
        assert!(lines[1].starts_with("system="));
        assert!(lines[2].starts_with("history="));
        assert!(lines[3].starts_with("generation_config="));
        assert!(lines[4].starts_with("binding="));
        // Each field carries a full 64-char lowercase-hex sha256.
        for l in &lines[1..] {
            let hex = l.split('=').nth(1).unwrap();
            assert_eq!(hex.len(), 64);
            assert!(hex.bytes().all(|b| b.is_ascii_hexdigit()));
        }
        assert!(text.ends_with('\n'), "output is newline-terminated");
    }

    #[test]
    fn build_output_matches_the_shared_sha256_convention() {
        // The per-field digests are exactly brops_core::sha256_hex of the raw input bytes — the executor
        // shares ONE hashing convention with the receipt/store manifest side.
        let out = String::from_utf8(build_output(b"hello", b"[]", b"{}")).unwrap();
        let want_system = format!("system={}", sha256_hex(b"hello"));
        assert!(out.lines().any(|l| l == want_system));
    }
}
