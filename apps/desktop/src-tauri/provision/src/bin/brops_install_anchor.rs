//! `brops_install_anchor` — the root-run installer for the POSIX trust anchor.
//!
//! A thin shell over `brops_provision::posix_install`; every decision lives there, where the
//! test suite reaches it. See that module for why this exists, why root never writes inside
//! the desktop account's tree, and why success is reported only after the application's own
//! launch-time verification has passed AS the desktop account.
//!
//! Exit status: `0` installed (or already installed and verified), `1` refused, `2` usage.

use std::process::ExitCode;

#[cfg(not(unix))]
fn main() -> ExitCode {
    eprintln!(
        "brops_install_anchor is the POSIX installer. On Windows the application establishes \
         its own trust anchor at first launch, unelevated; there is nothing for this tool to do."
    );
    ExitCode::from(2)
}

#[cfg(unix)]
fn main() -> ExitCode {
    use brops_provision::posix_install::{self as install, Invocation};
    use brops_provision::{anchor, ProvisionError};
    use std::path::PathBuf;

    let args: Vec<String> = std::env::args().skip(1).collect();
    let invocation = match install::parse_args(&args) {
        Ok(invocation) => invocation,
        Err(why) => {
            eprintln!("brops_install_anchor: {why}\n\n{}", install::USAGE);
            return ExitCode::from(2);
        }
    };

    let machine_root = |given: Option<PathBuf>| -> Result<PathBuf, ProvisionError> {
        match given {
            Some(root) => Ok(root),
            None => anchor::default_machine_root(),
        }
    };

    let outcome: Result<String, ProvisionError> = match invocation {
        Invocation::Help => {
            print!("{}", install::USAGE);
            return ExitCode::SUCCESS;
        }
        Invocation::Install { user, app_data, machine_root: root } => (|| {
            // Root first: an unprivileged caller is told that, not that some path is wrong.
            install::refuse_unless_root(anchor::posix_euid()?)?;
            let passwd = install::read_passwd()?;
            let user = install::resolve_user(&passwd, &user)?;
            let helper = std::env::current_exe().map_err(|source| ProvisionError::Io {
                what: "locating this installer's own binary, to re-run it as the desktop account"
                    .into(),
                path: PathBuf::from("/proc/self/exe"),
                source,
            })?;
            let request = install::InstallRequest {
                user,
                app_data_dir: app_data,
                machine_root: machine_root(root)?,
                helper,
            };
            let done = install::install_anchor(&request, &passwd)?;
            Ok(format!(
                "{}: {} for {} (uid {})\n  anchor      {}\n  trust store {}\n\
                 Root's measurement of the path (owner, mode):\n    {}\n\
                 The application's launch-time verification, run AS uid {}:\n{}",
                anchor::INSTALLER_TOOL,
                if done.freshly_minted {
                    "MINTED a new trust anchor"
                } else {
                    "an anchor was ALREADY installed and it verifies; nothing was changed"
                },
                done.user.name,
                done.user.uid,
                done.anchor_dir.display(),
                done.trust_dir.display(),
                done.proof.floor.join("\n    "),
                done.user.uid,
                done.proof.report,
            ))
        })(),
        Invocation::Verify { app_data, machine_root: root } => machine_root(root)
            .and_then(|root| install::verify_as_current_account(&app_data, &root)),
        Invocation::Deliver { from, app_data } => {
            install::deliver_as_current_account(&from, &app_data)
                .map(|trust| format!("delivered {}", trust.display()))
        }
        Invocation::Rollback { app_data } => install::rollback_as_current_account(&app_data)
            .map(|()| "removed the undelivered store".to_string()),
    };

    match outcome {
        Ok(report) => {
            println!("{}", report.trim_end());
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("brops_install_anchor: REFUSED — {error}");
            ExitCode::from(1)
        }
    }
}
