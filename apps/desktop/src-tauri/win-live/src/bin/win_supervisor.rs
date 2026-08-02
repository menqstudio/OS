//! governed-supervisor server bin — serves the pure `Supervisor` core (accept-open / launch-gate / attest-run)
//! over its named pipe, peer-SID gated to the broker. Run as `brops-supervisor`. Windows-only.

fn main() {
    #[cfg(not(windows))]
    {
        eprintln!("win_supervisor is Windows-only");
        std::process::exit(2);
    }
    #[cfg(windows)]
    win::main();
}

#[cfg(windows)]
mod win {
    use brops_win_live::config::{read_seed, Config};
    use brops_win_live::pipe;
    use brops_win_live::servers::{Supervisor, SupervisorConfig};

    fn arg(flag: &str) -> Option<String> {
        let a: Vec<String> = std::env::args().collect();
        a.iter().position(|x| x == flag).and_then(|i| a.get(i + 1)).cloned()
    }

    pub fn main() {
        let cfg_path = arg("--config").expect("--config required");
        let cfg = Config::load(&cfg_path).expect("config");
        let seed = read_seed(&cfg.keys.attest_seed).expect("attest seed");
        let core = Supervisor::new(SupervisorConfig {
            supervisor_id: cfg.facts.supervisor_id.clone(),
            supervisor_attestation_key_id: cfg.key_ids.sup_attest.clone(),
            challenge_public_key_hex: cfg.pubs.challenge.clone(),
            attest_signing_seed: seed,
            launcher_executable_sha256: cfg.supervisor_cfg.launcher_executable_sha256.clone(),
            executor_executable_sha256: cfg.supervisor_cfg.executor_executable_sha256.clone(),
        });
        println!("RESULT: supervisor listening pipe={} broker_sid={}", cfg.pipes.supervisor, cfg.allowed_broker_sid);
        pipe::run_server(&cfg.pipes.supervisor, &cfg.allowed_broker_sid, &core);
    }
}
