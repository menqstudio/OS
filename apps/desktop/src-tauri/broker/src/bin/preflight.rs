//! `brops-preflight` — say, by name, which prerequisites of a governed turn this machine meets.
//!
//! ```text
//! brops-preflight [--socket /run/brops/broker.sock]
//! ```
//!
//! Reads `$BROPS_BROKER_CONFIG` and the deployment it names, measures every requirement in
//! [`brops_broker::preflight::REQUIREMENTS`], and prints one line per requirement. `--socket` is the
//! broker's listening socket as its launcher would pass it in argv: the broker derives its database
//! path from that and from nothing else, so without it the durable-ledger row is reported as
//! unmeasurable rather than guessed.
//!
//! Exit codes — deliberately three, so "ready" cannot be collapsed with "could not tell":
//!
//! * `0` every requirement measured and met
//! * `1` at least one requirement NOT met
//! * `2` nothing not-met, but something could not be measured here
//!
//! This binary is a REPORT. It opens no socket, spawns no process, writes no file, and cannot make
//! any governed surface reachable — an all-met report still leaves
//! `governed_verification_unconfigured()`, `connect_broker()` and `UpstreamBlockedExecutor` exactly
//! where they are.

use brops_broker::preflight::{evaluate, RealHost};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut socket: Option<String> = None;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--socket" => {
                match args.get(i + 1) {
                    Some(v) => socket = Some(v.clone()),
                    None => {
                        eprintln!("brops-preflight: --socket needs a path");
                        std::process::exit(64);
                    }
                }
                i += 2;
            }
            "-h" | "--help" => {
                println!("usage: brops-preflight [--socket <broker socket path>]");
                std::process::exit(0);
            }
            other => {
                eprintln!("brops-preflight: unknown argument `{other}`");
                std::process::exit(64);
            }
        }
    }

    let report = evaluate(&RealHost, socket.as_deref());
    print!("{}", report.render());
    std::process::exit(report.exit_code());
}
