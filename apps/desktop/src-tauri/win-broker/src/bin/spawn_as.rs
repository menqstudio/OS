//! Windows broker launcher primitive — run a program AS a service account via a batch-logon token +
//! `CreateProcessWithTokenW` (§0.W launcher; the Windows analogue of the Linux setuid launcher).
//!
//!   spawn_as --password-stdin <account> <exe> [args...]      # password on stdin, one line
//!
//! `LogonUserW(account, ".", password, LOGON32_LOGON_BATCH)` mints a primary token for the dedicated service
//! principal; `CreateProcessWithTokenW` (which requires `SeImpersonatePrivilege` — held by the elevated
//! broker) launches the target under that token, so it runs as a genuinely distinct OS principal with that
//! account's SID. Waits for the child and propagates its exit code. This is the mechanism the real broker
//! uses to run the isolated servers / executor as their own principals. cfg(windows) only.
//!
//! # The password never travels on the command line
//!
//! This used to be `spawn_as <account> <password> <exe>`, taking the service account's password as
//! `argv[2]`. A Windows process command line is not private: `Win32_Process.CommandLine` over WMI,
//! `NtQueryInformationProcess` + a PEB read, Sysmon/EDR process-creation logs and the ETW
//! process-start events all carry it, and none of that requires the account that owns the process.
//! The password of a dedicated service principal — the identity this whole isolation model rests on —
//! was therefore readable by any local account for as long as the launch took, and durable in
//! whatever logs were collecting.
//!
//! It is now read from stdin instead: one line, no echo path, never in `argv`, never in the child's
//! environment, and the buffers holding it are zeroed as soon as `LogonUserW` returns.
//!
//! `--password-stdin` is REQUIRED and must be the first argument. It is not a convenience flag — it
//! exists so an old three-positional invocation (`spawn_as acct hunter2 target.exe`) fails loudly with
//! a usage error instead of silently logging on as the account named `acct` with the *exe* path used
//! as a password, or worse, treating the password as an account name.

/// Exact invocation shape. Note what is NOT in here: a password. There is no argv position
/// that can carry one, which is the property this type exists to make structural.
pub const USAGE: &str = "usage: spawn_as --password-stdin <account> <exe> [args...]\n\
                         the service account's password is read from stdin (one line), never from argv";

#[derive(Debug, PartialEq, Eq)]
pub struct Invocation<'a> {
    pub account: &'a str,
    pub exe: &'a str,
    pub child_args: &'a [String],
}

/// Parse `argv` (including argv[0]) into an [`Invocation`], or an error to print above [`USAGE`].
///
/// Deliberately strict rather than tolerant: `--password-stdin` is mandatory and positional, so the
/// removed three-positional form (`spawn_as <account> <password> <exe>`) cannot be silently
/// reinterpreted. A tolerant parser that accepted both would have taken the old call's password as
/// the exe path — and, in the arrangement where the operator swapped the order, would have logged
/// on as the account named by the password.
#[allow(dead_code)]
pub fn parse_args(args: &[String]) -> Result<Invocation<'_>, String> {
    if args.len() < 4 {
        return Err("spawn_as: too few arguments".to_string());
    }
    if args[1] != "--password-stdin" {
        return Err(format!(
            "spawn_as: first argument must be --password-stdin (got {:?}); the password is never an argument",
            args[1]
        ));
    }
    let account = args[2].as_str();
    let exe = args[3].as_str();
    if account.is_empty() {
        return Err("spawn_as: <account> must not be empty".to_string());
    }
    if exe.is_empty() {
        return Err("spawn_as: <exe> must not be empty".to_string());
    }
    Ok(Invocation { account, exe, child_args: &args[4..] })
}

/// Read the service account's password as ONE line from stdin.
///
/// A trailing CR/LF is stripped (so a PowerShell pipe, which writes CRLF, works) and nothing else
/// is trimmed: a password may legitimately start or end with a space. An empty line is an error —
/// logging on with an empty password would silently degrade the isolation this binary exists to
/// establish.
#[allow(dead_code)]
pub fn read_password_from_stdin() -> Result<String, String> {
    use std::io::BufRead;
    let mut line = String::new();
    std::io::stdin()
        .lock()
        .read_line(&mut line)
        .map_err(|e| format!("cannot read the password from stdin: {e}"))?;
    while line.ends_with('\n') || line.ends_with('\r') {
        line.pop();
    }
    if line.is_empty() {
        return Err("no password on stdin (pipe it in: `... | spawn_as --password-stdin ...`)".to_string());
    }
    Ok(line)
}

/// Overwrite a `String`'s bytes in place. Best effort — Rust may have copied the value during a
/// reallocation — but it removes the obvious residue, and the caller drops it immediately after.
#[allow(dead_code)]
pub fn zero_string(s: &mut str) {
    // SAFETY: zero bytes are valid UTF-8, so the String stays well-formed.
    unsafe { s.as_bytes_mut().fill(0) };
}

/// Overwrite the wide (UTF-16) buffer handed to `LogonUserW`, keeping the buffer's length.
#[allow(dead_code)]
pub fn zero_wide(buf: &mut [u16]) {
    buf.fill(0);
}

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
    use super::{parse_args, read_password_from_stdin, zero_string, zero_wide, USAGE};
    use windows::core::{Error, PCWSTR, PWSTR};
    use windows::Win32::Foundation::{CloseHandle, LocalFree, BOOL, HANDLE, HLOCAL, WAIT_OBJECT_0};
    use windows::Win32::Security::Authorization::{
        SetEntriesInAclW, EXPLICIT_ACCESS_W, NO_MULTIPLE_TRUSTEE, SET_ACCESS, TRUSTEE_IS_SID,
        TRUSTEE_IS_USER, TRUSTEE_W,
    };
    use windows::Win32::Security::{
        GetLengthSid, GetSecurityDescriptorDacl, GetTokenInformation, GetUserObjectSecurity,
        InitializeSecurityDescriptor, LogonUserW, SetSecurityDescriptorDacl, SetUserObjectSecurity,
        TokenUser, ACE_FLAGS, ACL, CONTAINER_INHERIT_ACE, DACL_SECURITY_INFORMATION, INHERIT_ONLY_ACE,
        LOGON32_LOGON_BATCH, LOGON32_PROVIDER_DEFAULT, NO_PROPAGATE_INHERIT_ACE, OBJECT_INHERIT_ACE,
        PSECURITY_DESCRIPTOR, SECURITY_DESCRIPTOR, TOKEN_USER,
    };
    use windows::Win32::System::StationsAndDesktops::{GetProcessWindowStation, GetThreadDesktop};
    use windows::Win32::System::SystemServices::SECURITY_DESCRIPTOR_REVISION;
    use windows::Win32::System::Threading::{
        CreateProcessWithTokenW, GetCurrentThreadId, GetExitCodeProcess, WaitForSingleObject,
        CREATE_PROCESS_LOGON_FLAGS, CREATE_UNICODE_ENVIRONMENT, PROCESS_INFORMATION, STARTUPINFOW,
    };

    const WINSTA_ALL: u32 = 0x0000_037F;
    const DESKTOP_ALL: u32 = 0x0000_01FF;

    fn wide(s: &str) -> Vec<u16> {
        s.encode_utf16().chain(std::iter::once(0)).collect()
    }

    /// Copy the user SID bytes out of a token so the SID outlives the info buffer.
    unsafe fn token_sid_bytes(token: HANDLE) -> Result<Vec<u8>, Error> {
        let mut needed = 0u32;
        let _ = GetTokenInformation(token, TokenUser, None, 0, &mut needed);
        if needed == 0 {
            return Err(Error::from_win32());
        }
        let mut buf = vec![0u8; needed as usize];
        GetTokenInformation(token, TokenUser, Some(buf.as_mut_ptr() as *mut _), needed, &mut needed)?;
        let tu = &*(buf.as_ptr() as *const TOKEN_USER);
        let len = GetLengthSid(tu.User.Sid) as usize;
        let mut out = vec![0u8; len];
        std::ptr::copy_nonoverlapping(tu.User.Sid.0 as *const u8, out.as_mut_ptr(), len);
        Ok(out)
    }

    fn explicit(sid: *mut std::ffi::c_void, mask: u32, inherit: u32) -> EXPLICIT_ACCESS_W {
        EXPLICIT_ACCESS_W {
            grfAccessPermissions: mask,
            grfAccessMode: SET_ACCESS,
            grfInheritance: ACE_FLAGS(inherit),
            Trustee: TRUSTEE_W {
                pMultipleTrustee: std::ptr::null_mut(),
                MultipleTrusteeOperation: NO_MULTIPLE_TRUSTEE,
                TrusteeForm: TRUSTEE_IS_SID,
                TrusteeType: TRUSTEE_IS_USER,
                ptstrName: PWSTR(sid as *mut u16),
            },
        }
    }

    /// Merge `entries` into the object's existing DACL (SetEntriesInAclW) and write it back — grants the SID
    /// access to a window station / desktop so a CreateProcessWithTokenW child under that principal doesn't
    /// hang attaching to WinSta0\Default.
    unsafe fn grant_user_object(handle: HANDLE, entries: &[EXPLICIT_ACCESS_W]) -> Result<(), Error> {
        let sec_info = DACL_SECURITY_INFORMATION.0;
        // Size then fetch the current security descriptor.
        let mut needed = 0u32;
        let _ = GetUserObjectSecurity(handle, &sec_info, PSECURITY_DESCRIPTOR::default(), 0, &mut needed);
        let mut sd_buf = vec![0u8; needed as usize];
        let psd = PSECURITY_DESCRIPTOR(sd_buf.as_mut_ptr() as *mut _);
        GetUserObjectSecurity(handle, &sec_info, psd, needed, &mut needed)?;
        // Existing DACL.
        let mut present = BOOL(0);
        let mut old_dacl: *mut ACL = std::ptr::null_mut();
        let mut defaulted = BOOL(0);
        GetSecurityDescriptorDacl(psd, &mut present, &mut old_dacl, &mut defaulted)?;
        // Merge in the new entries.
        let mut new_dacl: *mut ACL = std::ptr::null_mut();
        let rc = SetEntriesInAclW(Some(entries), Some(old_dacl as *const ACL), &mut new_dacl);
        if rc.0 != 0 {
            return Err(Error::from_win32());
        }
        // Fresh SD carrying the merged DACL.
        let mut new_sd = SECURITY_DESCRIPTOR::default();
        let npsd = PSECURITY_DESCRIPTOR(&mut new_sd as *mut _ as *mut _);
        InitializeSecurityDescriptor(npsd, SECURITY_DESCRIPTOR_REVISION)?;
        SetSecurityDescriptorDacl(npsd, true, Some(new_dacl as *const ACL), false)?;
        let res = SetUserObjectSecurity(handle, &DACL_SECURITY_INFORMATION, npsd);
        let _ = LocalFree(HLOCAL(new_dacl as *mut _));
        res
    }

    /// Grant the service principal access to the current process window station + thread desktop.
    unsafe fn grant_winsta_desktop(sid: *mut std::ffi::c_void) -> Result<(), Error> {
        let hwinsta = GetProcessWindowStation()?;
        // Two ACEs: one inheritable to desktops, one applying to the window station itself.
        let winsta_entries = [
            explicit(
                sid,
                WINSTA_ALL,
                CONTAINER_INHERIT_ACE.0 | INHERIT_ONLY_ACE.0 | OBJECT_INHERIT_ACE.0,
            ),
            explicit(sid, WINSTA_ALL, NO_PROPAGATE_INHERIT_ACE.0),
        ];
        grant_user_object(HANDLE(hwinsta.0), &winsta_entries)?;
        let hdesk = GetThreadDesktop(GetCurrentThreadId())?;
        let desk_entries = [explicit(sid, DESKTOP_ALL, 0)];
        grant_user_object(HANDLE(hdesk.0), &desk_entries)?;
        Ok(())
    }

    pub fn run() -> i32 {
        let args: Vec<String> = std::env::args().collect();
        let inv = match parse_args(&args) {
            Ok(inv) => inv,
            Err(msg) => {
                eprintln!("{msg}");
                eprintln!("{USAGE}");
                return 2;
            }
        };
        let account = inv.account;
        let exe = inv.exe;
        // Build the child command line: "exe" arg1 arg2 ...
        let mut cmd = format!("\"{exe}\"");
        for a in inv.child_args {
            cmd.push(' ');
            cmd.push_str(a);
        }

        let mut password = match read_password_from_stdin() {
            Ok(pw) => pw,
            Err(msg) => {
                eprintln!("spawn_as: {msg}");
                return 2;
            }
        };

        let acct_w = wide(account);
        let dom_w = wide("."); // local machine
        let mut pw_w = wide(&password);
        // The plaintext String is no longer needed once it is in the wide buffer we hand to
        // LogonUserW; drop it as soon as possible and zero it first so it is not left in the heap.
        zero_string(&mut password);
        drop(password);
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
                zero_wide(&mut pw_w);
                eprintln!("spawn_as: LogonUserW failed for {account}: {e:?}");
                return 3;
            }
            // The token is minted; the secret has no further use in this process.
            zero_wide(&mut pw_w);

            // 1b) Grant the service principal access to the process window station + thread desktop, so the
            // child under its token doesn't hang attaching to WinSta0\Default.
            match token_sid_bytes(token) {
                Ok(mut sid) => {
                    if let Err(e) = grant_winsta_desktop(sid.as_mut_ptr() as *mut _) {
                        eprintln!("spawn_as: grant_winsta_desktop failed: {e:?}");
                    }
                }
                Err(e) => eprintln!("spawn_as: token_sid_bytes failed: {e:?}"),
            }

            // 2) Launch the target under that token (needs SeImpersonatePrivilege). Pin lpDesktop explicitly.
            let mut si = STARTUPINFOW::default();
            si.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
            let mut desktop_w = wide(r"WinSta0\Default");
            si.lpDesktop = PWSTR(desktop_w.as_mut_ptr());
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
            eprintln!("spawn_as: launched pid={}", pi.dwProcessId);
            let mut code = 0u32;
            let w = WaitForSingleObject(pi.hProcess, 30_000);
            eprintln!("spawn_as: wait={:?} (WAIT_OBJECT_0={:?})", w, WAIT_OBJECT_0);
            let _ = GetExitCodeProcess(pi.hProcess, &mut code);
            eprintln!("spawn_as: child_exit_code={code}");
            let _ = CloseHandle(pi.hThread);
            let _ = CloseHandle(pi.hProcess);
            code as i32
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn argv(parts: &[&str]) -> Vec<String> {
        parts.iter().map(|s| s.to_string()).collect()
    }

    /// The point of the whole change: NO argv position carries a password.
    ///
    /// The old contract was `spawn_as <account> <password> <exe> [args...]`, so a
    /// service-principal password sat in a Windows process command line — readable through
    /// `Win32_Process.CommandLine`, a PEB read, or any process-creation log, by accounts other
    /// than the one running the process. This test pins the removal: the legacy three-positional
    /// call must be REFUSED, not reinterpreted.
    #[test]
    fn the_legacy_password_positional_form_is_refused() {
        let legacy = argv(&["spawn_as.exe", "brops-signer", "hunter2", "C:/brops/signer.exe"]);
        let err = parse_args(&legacy).unwrap_err();
        assert!(
            err.contains("--password-stdin"),
            "the legacy form must fail with the flag requirement, got: {err}"
        );
        // And crucially it must not have been quietly accepted with the password in some slot.
        assert!(parse_args(&legacy).is_err());
    }

    #[test]
    fn the_stdin_form_parses_account_exe_and_child_args() {
        let args = argv(&[
            "spawn_as.exe",
            "--password-stdin",
            "brops-signer",
            "C:/brops/signer.exe",
            "--socket",
            "C:/brops/run/signer.sock",
        ]);
        let inv = parse_args(&args).unwrap();
        assert_eq!(inv.account, "brops-signer");
        assert_eq!(inv.exe, "C:/brops/signer.exe");
        assert_eq!(inv.child_args, &args[4..]);
        // Nothing in the parsed invocation is a secret, and nothing in argv was one.
        assert!(!args.iter().any(|a| a == "hunter2"));
    }

    #[test]
    fn empty_account_or_exe_is_refused() {
        assert!(parse_args(&argv(&["spawn_as.exe", "--password-stdin", "", "x.exe"])).is_err());
        assert!(parse_args(&argv(&["spawn_as.exe", "--password-stdin", "acct", ""])).is_err());
        assert!(parse_args(&argv(&["spawn_as.exe", "--password-stdin", "acct"])).is_err());
    }

    #[test]
    fn usage_text_does_not_advertise_a_password_argument() {
        assert!(USAGE.contains("--password-stdin"));
        assert!(!USAGE.contains("<password>"));
    }

    #[test]
    fn zeroing_clears_both_buffers() {
        let mut s = String::from("hunter2");
        zero_string(&mut s);
        assert!(s.bytes().all(|b| b == 0));
        let mut w = vec![b'h' as u16, b'i' as u16, 0];
        zero_wide(&mut w);
        assert!(w.iter().all(|c| *c == 0));
    }
}
