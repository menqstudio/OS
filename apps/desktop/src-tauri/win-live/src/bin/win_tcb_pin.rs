//! Build the deployment's §2.5 TCB pin manifest for the Windows live kit (audit **R2**) — the Windows
//! twin of `engine/ci/live/build_tcb_pin_manifest.py`.
//!
//! `brops_win_live::tcb_floor` decides the floor; without a manifest to present it can only refuse,
//! which is fail-closed but proves nothing. This emits the manifest covering the full
//! `WIN_TCB_REQUIRED_ARTIFACTS` set for THIS deployment: the four serving binaries plus the executor,
//! and the four files that steer them.
//!
//!   win_tcb_pin --root-dir <deploy> --bin-dir <bins> --out <deploy>\tcb-pin.json [--owner-sid <S-1-5-…>]
//!
//! Run AFTER provisioning (manifest.json / manifest.sig / floor.json / config.json must exist) and
//! BEFORE the servers start — the pin is a start-time measurement, so anything changed after it is not
//! covered by it.
//!
//! **The manifest is only as trustworthy as its own ACL.** `tcb_floor::check_manifest_custody` refuses a
//! manifest that is not owned by SYSTEM/Administrators or that any other principal can write, so this
//! tool applies that ACL itself and DELETES the output if it cannot — a pin manifest an adversary can
//! rewrite is worse than none, because the floor would then confirm the digests they chose.

use std::path::{Path, PathBuf};

use brops_win_live::crypto;
use brops_win_live::tcb_floor::{
    WinTcbArtifact, WinTcbPinManifest, TCB_OWNER_SIDS, WIN_TCB_REQUIRED_ARTIFACTS,
};

fn arg(args: &[String], flag: &str) -> Option<String> {
    args.iter().position(|a| a == flag).and_then(|i| args.get(i + 1)).cloned()
}

fn die(msg: &str) -> ! {
    eprintln!("win_tcb_pin: {msg}");
    std::process::exit(2);
}

/// Lock the manifest down to the TCB principals only. Mirrors `win_provision`'s seed ACL: `icacls` is
/// the same command an operator would run and is auditable in the provisioning log.
#[cfg(windows)]
fn restrict_to_tcb(path: &Path) -> Result<(), String> {
    let out = std::process::Command::new("icacls")
        .arg(path)
        .arg("/inheritance:r")
        .arg("/grant:r")
        .arg("*S-1-5-18:F") // SYSTEM, by SID so it is locale-independent
        .arg("/grant:r")
        .arg("*S-1-5-32-544:F") // BUILTIN\Administrators
        .output()
        .map_err(|e| format!("icacls: {e}"))?;
    if !out.status.success() {
        return Err(format!(
            "icacls exited {:?}: {}",
            out.status.code(),
            String::from_utf8_lossy(&out.stderr).trim()
        ));
    }
    // `icacls /grant:r` sets the DACL but not the OWNER. The floor requires a TCB owner, so hand
    // ownership to Administrators explicitly; a non-elevated run fails here rather than producing a
    // manifest the floor will (correctly) reject at serve time.
    let own = std::process::Command::new("icacls")
        .arg(path)
        .arg("/setowner")
        .arg("*S-1-5-32-544")
        .output()
        .map_err(|e| format!("icacls /setowner: {e}"))?;
    if !own.status.success() {
        return Err(format!(
            "icacls /setowner exited {:?}: {} (run elevated)",
            own.status.code(),
            String::from_utf8_lossy(&own.stderr).trim()
        ));
    }
    Ok(())
}

/// On non-Windows there is nothing to restrict and nothing that will consume the manifest — the floor
/// itself refuses on a non-Windows host. The tool still emits the JSON so the mapping can be reviewed.
#[cfg(not(windows))]
fn restrict_to_tcb(_path: &Path) -> Result<(), String> {
    Ok(())
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let root = arg(&args, "--root-dir").unwrap_or_else(|| die("--root-dir <deployment dir> required"));
    let bins = arg(&args, "--bin-dir").unwrap_or_else(|| die("--bin-dir <dir with win_*.exe> required"));
    let out = arg(&args, "--out").unwrap_or_else(|| die("--out <tcb-pin.json> required"));
    // Defaults to BUILTIN\Administrators. Must be one of the compiled-in TCB principals — the floor
    // refuses any other value, so a typo fails here instead of silently weakening the pin.
    let owner_sid =
        arg(&args, "--owner-sid").unwrap_or_else(|| "S-1-5-32-544".to_string());
    if !TCB_OWNER_SIDS.contains(&owner_sid.as_str()) {
        die(&format!(
            "--owner-sid {owner_sid} is not a TCB principal; allowed: {TCB_OWNER_SIDS:?}"
        ));
    }

    let root = PathBuf::from(&root);
    let bins = PathBuf::from(&bins);

    // logical role -> the file that genuinely serves it in THIS kit. Every name in
    // WIN_TCB_REQUIRED_ARTIFACTS must appear or the floor's coverage check refuses the manifest — which
    // is the behaviour we want if this map ever falls behind the required set.
    let mapping: Vec<(&str, PathBuf)> = vec![
        ("challenge-authority.bin", bins.join("win_authority.exe")),
        ("governed-supervisor.bin", bins.join("win_supervisor.exe")),
        ("isolated-signer.bin", bins.join("win_signer.exe")),
        ("trusted-verifier-broker.bin", bins.join("win_live_turn.exe")),
        ("contained-executor.bin", bins.join("win_executor.exe")),
        ("kit.config", root.join("config.json")),
        ("key-manifest.root-anchor", root.join("manifest.json")),
        ("key-manifest.root-signature", root.join("manifest.sig")),
        ("anti-rollback-floor", root.join("floor.json")),
    ];
    for req in WIN_TCB_REQUIRED_ARTIFACTS {
        if !mapping.iter().any(|(n, _)| n == req) {
            die(&format!("no path mapped for required artifact {req}"));
        }
    }

    let mut artifacts = Vec::new();
    for (logical_name, path) in &mapping {
        let bytes = std::fs::read(path).unwrap_or_else(|e| {
            die(&format!("{} is missing for {logical_name}: {e}", path.display()))
        });
        // Absolute so the floor can walk the ancestor chain; a relative pin is refused at verify time.
        let abs = std::fs::canonicalize(path)
            .map(|p| p.to_string_lossy().trim_start_matches(r"\\?\").to_string())
            .unwrap_or_else(|_| path.to_string_lossy().to_string());
        artifacts.push(WinTcbArtifact {
            logical_name: (*logical_name).to_string(),
            path: abs,
            expected_sha256: crypto::sha256_hex(&bytes),
            expected_owner_sid: owner_sid.clone(),
        });
    }

    let manifest = WinTcbPinManifest { artifacts };
    let json = serde_json::to_vec_pretty(&manifest).expect("serialize pin manifest");
    std::fs::write(&out, &json).unwrap_or_else(|e| die(&format!("cannot write {out}: {e}")));
    if let Err(why) = restrict_to_tcb(Path::new(&out)) {
        let _ = std::fs::remove_file(&out);
        eprintln!("win_tcb_pin: cannot restrict {out}: {why}");
        eprintln!("win_tcb_pin: refusing to leave a pin manifest that a non-TCB principal could rewrite");
        std::process::exit(4);
    }
    // Self-verify: run the SAME floor the servers will run, against the manifest just written. A pin
    // manifest that the floor rejects is worthless — every server would exit 5 — and the operator should
    // learn that here, from the tool that can explain it, rather than from three services dying at start.
    // This is also the only place the real `WindowsFsProbe` is exercised outside a live deployment.
    match brops_win_live::tcb_floor::verify_deployment_tcb(Some(&out)) {
        Ok(()) => println!(
            "RESULT: pinned {} artifacts (owner {owner_sid}) -> {out}  [floor self-check: PASS]",
            manifest.artifacts.len()
        ),
        Err(why) => {
            println!(
                "RESULT: pinned {} artifacts (owner {owner_sid}) -> {out}  [floor self-check: FAIL]",
                manifest.artifacts.len()
            );
            eprintln!("win_tcb_pin: the floor REJECTS the manifest just written: {why}");
            eprintln!(
                "win_tcb_pin: the kit will refuse to serve until this is fixed. Typically the deployment \
                 directory or an ancestor grants write to a non-TCB principal — lock it down with \
                 `icacls <dir> /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F /grant:r *S-1-5-32-544:(OI)(CI)F` \
                 and set its owner to Administrators."
            );
            std::process::exit(6);
        }
    }
    println!("  point config.tcb_pin_manifest (or BROPS_WIN_TCB_PIN_MANIFEST) at it before starting the kit.");
}
