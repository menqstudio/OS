//! Windows broker launcher primitive — run a program AS a service account via a batch-logon token +
//! `CreateProcessWithTokenW` (§0.W launcher; the Windows analogue of the Linux setuid launcher).
//!
//!   spawn_as <account> <password> <exe> [args...]
//!
//! `LogonUserW(account, ".", password, LOGON32_LOGON_BATCH)` mints a primary token for the dedicated service
//! principal; `CreateProcessWithTokenW` (which requires `SeImpersonatePrivilege` — held by the elevated
//! broker) launches the target under that token, so it runs as a genuinely distinct OS principal with that
//! account's SID. Waits for the child and propagates its exit code. This is the mechanism the real broker
//! uses to run the isolated servers / executor as their own principals. cfg(windows) only.

#[cfg(not(windows))]
fn main() {
    eprintln!("spawn_as is Windows-only");
    std::process::exit(2);
}

#[cfg(windows)]
fn main() {
    std::process::exit(win::run());
}

#[cfg(windows)]
mod win {
    use windows::core::{Error, PCWSTR, PWSTR};
    use windows::Win32::Foundation::{CloseHandle, HANDLE, WAIT_OBJECT_0};
    use windows::Win32::Security::{
        LogonUserW, LOGON32_LOGON_BATCH, LOGON32_PROVIDER_DEFAULT,
    };
    use windows::Win32::System::Threading::{
        CreateProcessWithTokenW, GetExitCodeProcess, WaitForSingleObject, CREATE_UNICODE_ENVIRONMENT,
        PROCESS_INFORMATION, STARTUPINFOW, CREATE_PROCESS_LOGON_FLAGS,
    };

    fn wide(s: &str) -> Vec<u16> {
        s.encode_utf16().chain(std::iter::once(0)).collect()
    }

    pub fn run() -> i32 {
        let args: Vec<String> = std::env::args().collect();
        if args.len() < 4 {
            eprintln!("usage: spawn_as <account> <password> <exe> [args...]");
            return 2;
        }
        let account = &args[1];
        let password = &args[2];
        let exe = &args[3];
        // Build the child command line: "exe" arg1 arg2 ...
        let mut cmd = format!("\"{exe}\"");
        for a in &args[4..] {
            cmd.push(' ');
            cmd.push_str(a);
        }

        let acct_w = wide(account);
        let dom_w = wide("."); // local machine
        let pw_w = wide(password);
        let mut cmd_w = wide(&cmd);
        let exe_w = wide(exe);

        unsafe {
            // 1) Batch-logon token for the service principal.
            let mut token = HANDLE::default();
            if let Err(e) = LogonUserW(
                PCWSTR(acct_w.as_ptr()),
                PCWSTR(dom_w.as_ptr()),
                PCWSTR(pw_w.as_ptr()),
                LOGON32_LOGON_BATCH,
                LOGON32_PROVIDER_DEFAULT,
                &mut token,
            ) {
                eprintln!("spawn_as: LogonUserW failed for {account}: {e:?}");
                return 3;
            }

            // 2) Launch the target under that token (needs SeImpersonatePrivilege).
            let mut si = STARTUPINFOW::default();
            si.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
            let mut pi = PROCESS_INFORMATION::default();
            let launch = CreateProcessWithTokenW(
                token,
                CREATE_PROCESS_LOGON_FLAGS(0),
                PCWSTR(exe_w.as_ptr()),
                PWSTR(cmd_w.as_mut_ptr()),
                CREATE_UNICODE_ENVIRONMENT,
                None,
                PCWSTR::null(),
                &si,
                &mut pi,
            );
            let _ = CloseHandle(token);
            if let Err(e) = launch {
                eprintln!("spawn_as: CreateProcessWithTokenW failed: {e:?} ({:?})", Error::from_win32());
                return 4;
            }

            // 3) Wait for the child + propagate its exit code.
            let mut code = 0u32;
            let _ = WaitForSingleObject(pi.hProcess, 30_000);
            let _ = GetExitCodeProcess(pi.hProcess, &mut code);
            let _ = CloseHandle(pi.hThread);
            let _ = CloseHandle(pi.hProcess);
            let _ = WAIT_OBJECT_0; // silence unused import on some toolchains
            code as i32
        }
    }
}
