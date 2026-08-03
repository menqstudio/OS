//! Offline root-key ceremony (audit condition 1, custody half). Generate the production trust ROOT ed25519
//! keypair on an OFFLINE machine. The PRIVATE seed is written to `--out` and MUST stay off the serving box —
//! carry it on removable media, feed it only to `win_provision --root-key`. The PUBLIC hex printed here is the
//! ONLY root material that gets compiled into the broker TCB (`crate::tcb::ROOT_PUBLIC_KEY_HEX`).
//!
//! This is the honest graduation from the compiled-in demonstration anchor: once this real public key is
//! pinned in the TCB, the demo root seed embedded in `proof.rs` no longer signs a manifest the driver will
//! accept — production trust rests solely on a private key held offline that never appears in any binary.
//!
//!   win_gen_root --out <root.private.seed> [--root-key-id brops-tcb-root-1]
//!
//! Cross-platform on purpose: run it on an airgapped machine, not the serving box.

use std::path::Path;

use brops_win_live::crypto;

fn arg(args: &[String], flag: &str) -> Option<String> {
    args.iter().position(|a| a == flag).and_then(|i| args.get(i + 1)).cloned()
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let out = arg(&args, "--out").unwrap_or_else(|| {
        eprintln!("win_gen_root: --out <path to write the OFFLINE root private seed hex> required");
        eprintln!("  run this on an AIRGAPPED machine; the file it writes must never reach the serving box.");
        std::process::exit(2);
    });
    let root_key_id = arg(&args, "--root-key-id").unwrap_or_else(|| "brops-tcb-root-1".to_string());

    // Never clobber an existing root: overwriting would silently rotate the offline private and orphan every
    // manifest already signed by the old one. The operator must delete/move it deliberately.
    if Path::new(&out).exists() {
        eprintln!("win_gen_root: refusing to overwrite existing file {out}");
        eprintln!("  a root private may already live there — move it aside deliberately if you mean to rotate.");
        std::process::exit(3);
    }

    // Fresh 32-byte seed from the OS CSPRNG, exactly the on-disk `*.seed` format `win_provision --root-key` reads.
    let seed = crypto::gen_seed();
    let sk = crypto::signing_key(&seed);
    let public_hex = crypto::public_key_hex(&sk);
    let private_hex = crypto::hex(&seed);

    std::fs::write(&out, &private_hex).unwrap_or_else(|e| {
        eprintln!("win_gen_root: cannot write {out}: {e}");
        std::process::exit(2);
    });

    // Do NOT print the private seed to stdout — it must live only in the file the operator controls.
    println!("RESULT: root keypair generated");
    println!("  root_key_id      : {root_key_id}");
    println!("  ROOT_PUBLIC_KEY  : {public_hex}");
    println!("  private_seed_file: {out}   (KEEP OFFLINE — never copy to the serving box)");
    println!();
    println!("Next steps (production custody):");
    println!("  1. Give ONLY the ROOT_PUBLIC_KEY above to the build; it is pinned in src-tauri/win-live/src/tcb.rs");
    println!("     as ROOT_PUBLIC_KEY_HEX (the private half stays in {out}, offline).");
    println!("  2. Provision a deployment, signing the manifest with the offline private:");
    println!("       win_provision --root-dir <deploy> --root-key {out} --allowed-broker-sid <S-1-5-...>");
    println!("  3. Copy the <deploy> dir to the serving box. The root private is NOT written into it (audit A);");
    println!("     it never leaves your offline media.");
}
