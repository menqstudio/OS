//! `brops-audit-signer.exe` — the process that owns the audit-head anchor key.
//!
//! Registered by an elevated installer as the Windows service `BroPSAuditSigner`, running under
//! the virtual account `NT SERVICE\BroPSAuditSigner` (no password anywhere, SID derived from the
//! name). On first start, under that account and inside a directory the app's account is absent
//! from, it mints its own Ed25519 seed and publishes only the public half. Then it serves one
//! anchor per connection on a peer-authenticated named pipe.
//!
//! # The startup order is the security property
//!
//! ```text
//! 1. who am I?            winimpl::current_user_sid()
//! 2. who must I be?       audit_signer::service_account_sid(SIGNER_SERVICE_NAME)  [derived, offline]
//! 3. refuse if different  -> exit 8, NO key file is opened or created
//! 4. who may talk to me?  register::read_allowed_app_sid()  [installer-written, app-unwritable]
//! 5. mint or load the key
//! 6. serve
//! ```
//!
//! Step 3 comes before step 5 deliberately. If this binary is launched by the app's own account —
//! which is exactly what pointing `BRO_AUDIT_ANCHOR_SIGNER` straight at it would do — it must not
//! create a key file that the launching account then owns. Refusing before the mint is what makes
//! "run the signer yourself" produce nothing at all rather than produce a key under the wrong
//! custody. `audit_signer::anchor_request` re-checks the same fact per request, so the guard
//! survives an edit to this file.
//!
//! There is no flag, environment variable or file that supplies the identity in step 1. The only
//! argument is the signer directory, and pointing it elsewhere does not change who the process is.

fn main() {
    std::process::exit(real_main());
}

#[cfg(not(windows))]
fn real_main() -> i32 {
    eprintln!(
        "brops-audit-signer: this service exists to create a SECOND WINDOWS PRINCIPAL. On {} the \
         audit signer is already a separate uid whose key file the engine's account cannot read, \
         provisioned outside this crate. There is nothing here to run.",
        brops_provision::platform_name()
    );
    brops_audit_signer::relay::EXIT_UNSUPPORTED
}

#[cfg(windows)]
fn real_main() -> i32 {
    use brops_audit_signer::{custody, register, AnchorCore};
    use brops_provision::audit_signer as spec;

    let args: Vec<String> = std::env::args().skip(1).collect();
    let signer_dir = match args.as_slice() {
        [] => default_signer_dir(),
        [dir] => std::path::PathBuf::from(dir),
        _ => {
            eprintln!("usage: brops-audit-signer [<signer-directory>]");
            return brops_audit_signer::relay::EXIT_BAD_ARGS;
        }
    };

    // 1 + 2 + 3. Identity, before anything else exists.
    let running_as = match spec::winimpl::current_user_sid() {
        Ok(sid) => sid,
        Err(why) => {
            eprintln!("brops-audit-signer: cannot read this process's own SID: {why}");
            return 9;
        }
    };
    let expected = spec::service_account_sid(spec::SIGNER_SERVICE_NAME);
    if running_as != expected {
        eprintln!(
            "{}",
            spec::SignRefusal::WrongPrincipal { expected: expected.clone(), actual: running_as }
        );
        eprintln!(
            "brops-audit-signer: refusing BEFORE the key file is opened. This binary is the \
             service `{}`; it is started by the SCM under the virtual account `NT SERVICE\\{}`, \
             never by the application. Running it as the application's own account is the defect \
             the second principal exists to close — a key minted here would be owned by the \
             account that writes the ledger.",
            spec::SIGNER_SERVICE_NAME,
            spec::SIGNER_SERVICE_NAME
        );
        return 8;
    }

    // 4. The one peer the pipe admits, from a file only the TCB and this service can write.
    let app_sid = match register::read_allowed_app_sid(&signer_dir) {
        Ok(sid) => sid,
        Err(why) => {
            eprintln!("brops-audit-signer: {why}");
            return 9;
        }
    };
    if app_sid == running_as {
        // `audit_signer::check_principals` refuses this at provisioning time; refuse it again
        // here, because a plan that was right at install is not evidence about what is on disk now.
        eprintln!("{}", spec::AnchorRefusal::SamePrincipal { sid: app_sid });
        return 9;
    }

    // 5. Mint or load, under this account, in this directory.
    let held = match custody::load_or_mint(&signer_dir, &running_as) {
        Ok(c) => c,
        Err(why) => {
            eprintln!("brops-audit-signer: {why}");
            return 9;
        }
    };
    if held.freshly_minted {
        eprintln!(
            "brops-audit-signer: minted a new anchor key ({}) under {running_as}. {}",
            held.key_id,
            spec::MINT_LOCATION_NOTE
        );
    }
    let state_path = signer_dir.join(spec::STATE_FILE_NAME);
    let core = match AnchorCore::new(held, &expected, &running_as, &state_path) {
        Ok(c) => c,
        Err(why) => {
            eprintln!("brops-audit-signer: {why}");
            return 9;
        }
    };

    // 6. Serve. `run_server` exits the process rather than serve on a pipe it cannot restrict.
    eprintln!(
        "brops-audit-signer: serving key {} on \\\\.\\pipe\\{} for peer {app_sid}",
        core.key_id(),
        spec::SIGNER_PIPE_NAME
    );
    brops_audit_signer::win::serve(spec::SIGNER_PIPE_NAME, &app_sid, &core)
}

#[cfg(windows)]
fn default_signer_dir() -> std::path::PathBuf {
    let root = std::env::var("ProgramData").unwrap_or_else(|_| "C:\\ProgramData".to_string());
    std::path::PathBuf::from(root).join("BroPS").join(brops_provision::audit_signer::SIGNER_DIR_NAME)
}
