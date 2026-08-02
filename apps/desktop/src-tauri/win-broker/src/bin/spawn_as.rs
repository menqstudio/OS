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
