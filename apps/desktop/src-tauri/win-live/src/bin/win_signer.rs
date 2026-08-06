//! isolated-signer server bin — serves the pure `Signer` core (sign-result: recompute-then-sign the 23-key
//! receipt envelope) over its named pipe, peer-SID gated to the broker. Run as `brops-signer`. Windows-only.

fn main() {
    #[cfg(not(windows))]
    {
        eprintln!("win_signer is Windows-only");
        std::process::exit(2);
    }
    #[cfg(windows)]
    win::main();
}

#[cfg(windows)]
mod win {
    use brops_win_live::config::{read_seed, Config};
    use brops_win_live::pipe;
    use brops_win_live::servers::{Signer, SignerConfig};
    use std::path::PathBuf;

    fn arg(flag: &str) -> Option<String> {
        let a: Vec<String> = std::env::args().collect();
        a.iter().position(|x| x == flag).and_then(|i| a.get(i + 1)).cloned()
    }

    pub fn main() {
        let cfg_path = arg("--config").expect("--config required");
        let cfg = Config::load(&cfg_path).expect("config");
        let seed = read_seed(&cfg.keys.signer_seed).expect("signer seed");
        let core = Signer::new(SignerConfig {
            receipt_key_id: cfg.key_ids.signer.clone(),
            supervisor_attestation_key_id: cfg.key_ids.sup_attest.clone(),
            supervisor_attestation_public_key_hex: cfg.pubs.attest.clone(),
            receipt_signing_seed: seed,
            store_dir: PathBuf::from(&cfg.store_dir),
            allowed_executors: cfg.identities.allowed_executors.clone(),
            allowed_builders: cfg.identities.allowed_builders.clone(),
            allowed_supervisors: cfg.identities.allowed_supervisors.clone(),
        });
        println!("RESULT: signer listening pipe={} broker_sid={}", cfg.pipes.signer, cfg.allowed_broker_sid);
        pipe::run_server(&cfg.pipes.signer, &cfg.allowed_broker_sid, &core);
    }
}
