//! challenge-authority server bin — serves the pure `Authority` core over its named pipe (peer-SID gated to
//! the broker). Run as the `brops-authority` account in a cross-account deploy. Windows-only.

fn main() {
    #[cfg(not(windows))]
    {
        eprintln!("win_authority is Windows-only");
        std::process::exit(2);
    }
    #[cfg(windows)]
    win::main();
}

#[cfg(windows)]
mod win {
    use brops_win_live::config::{read_seed, Config};
    use brops_win_live::pipe;
    use brops_win_live::servers::{Authority, AuthorityConfig};

    fn arg(flag: &str) -> Option<String> {
        let a: Vec<String> = std::env::args().collect();
        a.iter().position(|x| x == flag).and_then(|i| a.get(i + 1)).cloned()
    }

    pub fn main() {
        let cfg_path = arg("--config").expect("--config required");
        let cfg = Config::load(&cfg_path).expect("config");
        // §2.5 TCB integrity floor (audit R2) BEFORE the signing seed is touched: an unmeasured binary
        // must not be handed a production key. Refusal exits the process.
        brops_win_live::tcb_floor::enforce_or_exit(
            "challenge-authority",
            cfg.tcb_pin_manifest_path().as_deref(),
        );
        let seed = read_seed(&cfg.keys.challenge_seed).expect("challenge seed");
        let core = Authority::new(AuthorityConfig {
            challenge_key_id: cfg.key_ids.challenge.clone(),
            supervisor_id: cfg.facts.supervisor_id.clone(),
            challenge_signing_seed: seed,
        });
        println!("RESULT: authority listening pipe={} broker_sid={}", cfg.pipes.authority, cfg.allowed_broker_sid);
        pipe::run_server(&cfg.pipes.authority, &cfg.allowed_broker_sid, &core);
    }
}
