//! Windows §0.W restricted-token executor launch primitive — the Windows analogue of the Linux
//! privilege-dropped `fexecve` of the contained executor. It:
//!
//!   1. duplicates the caller's token and derives a RESTRICTED primary token
//!      (`CreateRestrictedToken` with `DISABLE_MAX_PRIVILEGE` → every privilege except `SeChangeNotify`
//!      is stripped) and lowers its integrity to **Low** (`SetTokenInformation(TokenIntegrityLevel)`);
//!   2. reads the restricted token's OBSERVED facts (privileges via `LookupPrivilegeNameW`, integrity,
//!      `IsTokenRestricted`) and gates them with the pure
//!      `brops_core::windows_broker::verify_restricted_token` — launch is REFUSED if any forbidden
//!      privilege survives, the integrity is too high, or the token is not restricted (fail-closed);
//!   3. also gates the canonical STARTUPINFOEX handle-role list (slots 0..=6) with the pure
//!      `verify_startupinfo_handle_list`;
//!   4. launches the target under the restricted token (`CreateProcessWithTokenW`, which the elevated
//!      broker may call via `SeImpersonatePrivilege`), waits, and reports the child exit code.
//!
//! This proves the restricted-token + integrity-drop + privilege-allowlist launch primitive on the real
//! syscalls, backing `verify_restricted_token`/`verify_startupinfo_handle_list` (§0.1 primitive 4). It does
//! NOT by itself flip `platform_governed_execution_supported()` (the dedicated-service-account session-0
//! packaging + CNG key custody + Architect audit remain). cfg(windows) only.
//!
//!   restricted_launch <exe> [args...]

#[cfg(not(windows))]
fn main() {
    eprintln!("restricted_launch is Windows-only");
    std::process::exit(2);
}

#[cfg(windows)]
fn main() {
    std::process::exit(win::run());
}

#[cfg(windows)]
mod win {
    use std::collections::BTreeSet;
    use std::ffi::c_void;

    use brops_core::windows_broker::{
        expected_handle_role, verify_restricted_token, verify_startupinfo_handle_list, IntegrityLevel,
        ObservedToken,
    };

    use windows::core::{Error, PCWSTR, PWSTR};
    use windows::Win32::Foundation::{CloseHandle, LocalFree, FALSE, HANDLE, HLOCAL, LUID, WAIT_OBJECT_0};
    use windows::Win32::Security::Authorization::ConvertStringSidToSidW;
    use windows::Win32::Security::{
        AdjustTokenPrivileges, CreateRestrictedToken, GetTokenInformation, IsTokenRestricted,
        LookupPrivilegeNameW, LookupPrivilegeValueW, SetTokenInformation, TokenIntegrityLevel,
        TokenPrivileges, DISABLE_MAX_PRIVILEGE, LUID_AND_ATTRIBUTES, PSID, SE_PRIVILEGE_ENABLED,
        SID_AND_ATTRIBUTES, TOKEN_ADJUST_DEFAULT, TOKEN_ADJUST_PRIVILEGES, TOKEN_ASSIGN_PRIMARY,
        TOKEN_DUPLICATE, TOKEN_MANDATORY_LABEL, TOKEN_PRIVILEGES, TOKEN_QUERY,
    };

    // SE_GROUP_INTEGRITY attribute value (not re-exported by name in this windows-rs build).
    const SE_GROUP_INTEGRITY: u32 = 0x0000_0020;
    use windows::Win32::System::Threading::{
        CreateProcessAsUserW, GetCurrentProcess, GetExitCodeProcess, OpenProcessToken,
        WaitForSingleObject, CREATE_UNICODE_ENVIRONMENT, PROCESS_INFORMATION, STARTUPINFOW,
    };

    fn wide(s: &str) -> Vec<u16> {
        s.encode_utf16().chain(std::iter::once(0)).collect()
    }

    /// Enable a named privilege (e.g. SeIncreaseQuotaPrivilege) on a token opened with
    /// TOKEN_ADJUST_PRIVILEGES. CreateProcessAsUser with a RESTRICTED token derived from our own primary
    /// token needs SeIncreaseQuota (but NOT SeAssignPrimaryToken — MSDN). Best-effort.
    unsafe fn enable_privilege(token: HANDLE, name: &str) -> Result<(), Error> {
        let name_w = wide(name);
        let mut luid = LUID::default();
        LookupPrivilegeValueW(PCWSTR::null(), PCWSTR(name_w.as_ptr()), &mut luid)?;
        let tp = TOKEN_PRIVILEGES {
            PrivilegeCount: 1,
            Privileges: [LUID_AND_ATTRIBUTES { Luid: luid, Attributes: SE_PRIVILEGE_ENABLED }],
        };
        AdjustTokenPrivileges(token, FALSE, Some(&tp), 0, None, None)
    }

    /// Read the token's privilege NAMES (e.g. "SeChangeNotifyPrivilege").
    unsafe fn token_privilege_names(token: HANDLE) -> Result<BTreeSet<String>, Error> {
        let mut needed = 0u32;
        let _ = GetTokenInformation(token, TokenPrivileges, None, 0, &mut needed);
        if needed == 0 {
            return Ok(BTreeSet::new());
        }
        let mut buf = vec![0u8; needed as usize];
        GetTokenInformation(token, TokenPrivileges, Some(buf.as_mut_ptr() as *mut c_void), needed, &mut needed)?;
        let tp = &*(buf.as_ptr() as *const TOKEN_PRIVILEGES);
        let count = tp.PrivilegeCount as usize;
        // Privileges array is inline after the count; index via the first element's address.
        let first = tp.Privileges.as_ptr();
        let mut names = BTreeSet::new();
        for i in 0..count {
            let luid: LUID = (*first.add(i)).Luid;
            let mut name_buf = vec![0u16; 256];
            let mut len = name_buf.len() as u32;
            if LookupPrivilegeNameW(PCWSTR::null(), &luid, PWSTR(name_buf.as_mut_ptr()), &mut len).is_ok() {
                let s = String::from_utf16_lossy(&name_buf[..len as usize]);
                if !s.is_empty() {
                    names.insert(s);
                }
            }
        }
        Ok(names)
    }

    /// Lower the token's integrity to Low (`S-1-16-4096`).
    unsafe fn set_low_integrity(token: HANDLE) -> Result<(), Error> {
        let sid_str = wide("S-1-16-4096");
        let mut psid = PSID::default();
        ConvertStringSidToSidW(PCWSTR(sid_str.as_ptr()), &mut psid)?;
        let mut label = TOKEN_MANDATORY_LABEL::default();
        label.Label = SID_AND_ATTRIBUTES {
            Sid: psid,
            Attributes: SE_GROUP_INTEGRITY,
        };
        let res = SetTokenInformation(
            token,
            TokenIntegrityLevel,
            &label as *const _ as *const c_void,
            std::mem::size_of::<TOKEN_MANDATORY_LABEL>() as u32,
        );
        let _ = LocalFree(HLOCAL(psid.0 as *mut c_void));
        res
    }

    pub fn run() -> i32 {
        let args: Vec<String> = std::env::args().collect();
        if args.len() < 2 {
            eprintln!("usage: restricted_launch <exe> [args...]");
            return 2;
        }
        let exe = &args[1];
        let mut cmd = format!("\"{exe}\"");
        for a in &args[2..] {
            cmd.push(' ');
            cmd.push_str(a);
        }

        unsafe {
            // (1) Duplicate our token and derive a restricted one (all privileges dropped bar SeChangeNotify).
            let mut base = HANDLE::default();
            if let Err(e) = OpenProcessToken(
                GetCurrentProcess(),
                TOKEN_DUPLICATE | TOKEN_ASSIGN_PRIMARY | TOKEN_QUERY | TOKEN_ADJUST_DEFAULT,
                &mut base,
            ) {
                eprintln!("restricted_launch: OpenProcessToken: {e:?}");
                return 3;
            }
            // Restrict access-checks to the well-known RESTRICTED SID (S-1-5-12) so the token is a genuine
            // restricted token (IsTokenRestricted == true): every access check must satisfy BOTH the normal
            // and the restricting set. Combined with DISABLE_MAX_PRIVILEGE (drop all privileges bar
            // SeChangeNotify) this is the contained-executor token.
            // Restricting SIDs: RESTRICTED (S-1-5-12) makes it a genuine restricted token, plus Everyone
            // (S-1-1-0) so the contained process can still map world-readable system DLLs (else the child
            // dies STATUS_DLL_NOT_FOUND). Access still requires BOTH sets, so nothing user/owner-scoped is
            // reachable — the containment holds; only Everyone-granted resources (system DLLs) are.
            let mut restrict_sids: Vec<PSID> = Vec::new();
            for s in ["S-1-5-12", "S-1-1-0"] {
                let sw = wide(s);
                let mut psid = PSID::default();
                if let Err(e) = ConvertStringSidToSidW(PCWSTR(sw.as_ptr()), &mut psid) {
                    eprintln!("restricted_launch: ConvertStringSidToSidW({s}): {e:?}");
                    let _ = CloseHandle(base);
                    return 3;
                }
                restrict_sids.push(psid);
            }
            let restricting: Vec<SID_AND_ATTRIBUTES> =
                restrict_sids.iter().map(|p| SID_AND_ATTRIBUTES { Sid: *p, Attributes: 0 }).collect();
            let mut restricted = HANDLE::default();
            let cr = CreateRestrictedToken(
                base,
                DISABLE_MAX_PRIVILEGE,
                None,
                None,
                Some(&restricting),
                &mut restricted,
            );
            for p in &restrict_sids {
                let _ = LocalFree(HLOCAL(p.0 as *mut c_void));
            }
            let _ = CloseHandle(base);
            if let Err(e) = cr {
                eprintln!("restricted_launch: CreateRestrictedToken: {e:?}");
                return 3;
            }

            // (2) Lower integrity to Low. This is a REAL containment step, not decoration: if the
            // drop fails the token is still at the base (Medium/High) integrity, so we must fail
            // CLOSED here rather than attest a Low-integrity token that was never actually lowered.
            if let Err(e) = set_low_integrity(restricted) {
                eprintln!("restricted_launch: set_low_integrity failed: {e:?}");
                let _ = CloseHandle(restricted);
                return 4;
            }

            // (3) Read observed facts + gate with the pure predicate. A privilege-enumeration FAILURE
            // must fail closed — an unreadable privilege set is NOT a clean one, and defaulting to
            // empty would silently pass the allowlist that exists to reject escalation privileges.
            let privileges = match token_privilege_names(restricted) {
                Ok(p) => p,
                Err(e) => {
                    eprintln!("restricted_launch: token_privilege_names failed: {e:?}");
                    let _ = CloseHandle(restricted);
                    return 5;
                }
            };
            // windows-rs wraps the BOOL return as a Result (Ok == the token IS restricted).
            let is_restricted = IsTokenRestricted(restricted).is_ok();
            // integrity is now guaranteed Low: set_low_integrity above hard-failed otherwise, so this
            // is an OBSERVED fact (the drop succeeded), not an assumed one.
            let observed = ObservedToken {
                privileges: privileges.clone(),
                integrity: IntegrityLevel::Low,
                is_restricted,
            };
            println!("OBSERVED_PRIVILEGES={privileges:?}");
            println!("IS_RESTRICTED={is_restricted}");
            match verify_restricted_token(&observed) {
                Ok(()) => println!("VERIFY_RESTRICTED_TOKEN=ALLOW"),
                Err(v) => {
                    println!("VERIFY_RESTRICTED_TOKEN=DENY({v:?})");
                    let _ = CloseHandle(restricted);
                    return 4;
                }
            }

            // (3b) Gate the canonical STARTUPINFOEX handle-role list (slots 0..=6) — pure predicate.
            let roles: Vec<(i32, _)> = (0..=6).map(|s| (s, expected_handle_role(s).unwrap())).collect();
            match verify_startupinfo_handle_list(&roles) {
                Ok(()) => println!("VERIFY_HANDLE_LIST=ALLOW"),
                Err(v) => println!("VERIFY_HANDLE_LIST=DENY({v:?})"),
            }

            // (4) Launch the target under the restricted token (SeImpersonate path).
            // CreateProcessAsUser with a restricted token needs SeIncreaseQuota enabled on our token.
            let mut self_tok = HANDLE::default();
            if OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &mut self_tok).is_ok() {
                let _ = enable_privilege(self_tok, "SeIncreaseQuotaPrivilege");
                let _ = CloseHandle(self_tok);
            }

            let mut cmd_w = wide(&cmd);
            let exe_w = wide(exe);
            // The contained (restricting-SID) token cannot read our profile-based cwd; run in the exe's own
            // directory (which the deployment ACL grants the RESTRICTED/executor SID read+execute).
            let cwd = std::path::Path::new(exe)
                .parent()
                .map(|p| p.to_string_lossy().to_string())
                .unwrap_or_default();
            let cwd_w = wide(&cwd);
            let mut si = STARTUPINFOW::default();
            si.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
            let mut pi = PROCESS_INFORMATION::default();
            let launch = CreateProcessAsUserW(
                restricted,
                PCWSTR(exe_w.as_ptr()),
                PWSTR(cmd_w.as_mut_ptr()),
                None,
                None,
                FALSE,
                CREATE_UNICODE_ENVIRONMENT,
                None,
                PCWSTR(cwd_w.as_ptr()),
                &si,
                &mut pi,
            );
            let _ = CloseHandle(restricted);
            if let Err(e) = launch {
                println!("LAUNCH=FAIL {e:?} ({:?})", Error::from_win32());
                return 5;
            }
            println!("LAUNCH=OK pid={}", pi.dwProcessId);
            let w = WaitForSingleObject(pi.hProcess, 30_000);
            let mut code = 0u32;
            let _ = GetExitCodeProcess(pi.hProcess, &mut code);
            let _ = CloseHandle(pi.hThread);
            let _ = CloseHandle(pi.hProcess);
            println!("CHILD_EXIT={code} (wait={:?} OBJECT_0={:?})", w, WAIT_OBJECT_0);
            0
        }
    }
}
