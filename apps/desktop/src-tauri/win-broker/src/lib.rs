//! Wave 3b-1B — Windows (§0.W) governed-execution broker: the REAL winapi syscall layer over the pure,
//! host-independent predicates in [`brops_core::windows_broker`]. This crate supplies the concrete Windows
//! mechanisms the pure logic only *models*; the first mechanism landed here is the named-pipe peer-SID
//! authentication — the Windows equivalent of the Linux `AF_UNIX` + `SO_PEERCRED` UID allowlist (§0.W.4).
//!
//! On any non-Windows host this crate compiles to nothing but a re-export of the pure predicates, so the
//! whole workspace still builds and tests on the Linux CI runner. The real winapi paths + their integration
//! tests are `#[cfg(windows)]` and run on a Windows CI runner.
//!
//! **This does NOT flip the Windows governed gate.** `platform_governed_execution_supported()` stays `false`
//! on Windows: only the peer-auth primitive has a real syscall implementation here; the remaining §0.1
//! primitives (image Authenticode via `WinVerifyTrust`, `CreateProcessAsUser` with a restricted token +
//! STARTUPINFOEX handle list, CNG key custody) and the full dedicated-service-SID machine-proof are still
//! unbuilt. Governed turns remain fail-closed on Windows.

pub use brops_core::windows_broker;

/// Re-exported pure verifiers so callers depend on one Windows-broker crate.
pub use brops_core::windows_broker::{
    authorize_pipe_peer, verify_distinct_principals, Pipe, ServiceSids, Sid, WindowsBrokerViolation,
};

#[cfg(windows)]
pub mod syscall {
    //! Real winapi named-pipe peer-SID authentication (§0.W.4). The server, once a client has connected and
    //! written, impersonates the client, reads the impersonation token's user SID, and reverts — then the
    //! caller gates that SID with [`brops_core::windows_broker::authorize_pipe_peer`]. Mirrors the Linux
    //! server reading `SO_PEERCRED` and checking the UID allowlist.

    use brops_core::windows_broker::Sid;
    use std::ffi::c_void;
    use windows::core::{Error, PWSTR};
    use windows::Win32::Foundation::{
        CloseHandle, LocalFree, ERROR_PIPE_CONNECTED, HANDLE, HLOCAL, TRUE,
    };
    use windows::Win32::Security::Authorization::ConvertSidToStringSidW;
    use windows::Win32::Security::{
        GetTokenInformation, RevertToSelf, TokenUser, TOKEN_QUERY, TOKEN_USER,
    };
    use windows::Win32::Security::WinTrust::{
        WinVerifyTrust, WINTRUST_ACTION_GENERIC_VERIFY_V2, WINTRUST_DATA, WINTRUST_DATA_0,
        WINTRUST_FILE_INFO, WTD_CHOICE_FILE, WTD_REVOKE_NONE, WTD_STATEACTION_CLOSE,
        WTD_STATEACTION_VERIFY, WTD_UI_NONE,
    };
    use windows::Win32::System::Pipes::ImpersonateNamedPipeClient;
    use windows::Win32::System::Threading::{
        GetCurrentProcess, GetCurrentThread, OpenProcessToken, OpenThreadToken,
    };
    use windows::core::PCWSTR;
    use windows::Win32::Foundation::HWND;

    /// Convert a token handle's user SID to its canonical string form (`S-1-5-...`).
    unsafe fn token_user_sid(token: HANDLE) -> Result<Sid, Error> {
        // Sizing call: TokenUser returns a variable-length TOKEN_USER; the first call reports the length.
        let mut needed = 0u32;
        let _ = GetTokenInformation(token, TokenUser, None, 0, &mut needed);
        if needed == 0 {
            return Err(Error::from_win32());
        }
        let mut buf = vec![0u8; needed as usize];
        GetTokenInformation(
            token,
            TokenUser,
            Some(buf.as_mut_ptr() as *mut c_void),
            needed,
            &mut needed,
        )?;
        let tu = &*(buf.as_ptr() as *const TOKEN_USER);
        let mut wide = PWSTR::null();
        ConvertSidToStringSidW(tu.User.Sid, &mut wide)?;
        let s = wide.to_string().map_err(|_| Error::from_win32())?;
        // ConvertSidToStringSidW allocates via LocalAlloc; free it.
        let _ = LocalFree(HLOCAL(wide.0 as *mut c_void));
        Ok(s)
    }

    /// The user SID of the current process (used to know the expected peer SID in same-user tests / to resolve
    /// the broker's own identity).
    pub fn current_process_user_sid() -> Result<Sid, Error> {
        unsafe {
            let mut token = HANDLE::default();
            OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token)?;
            let sid = token_user_sid(token);
            let _ = CloseHandle(token);
            sid
        }
    }

    /// Authenticate the client connected to a named-pipe server handle: impersonate the client, read the
    /// impersonation token's user SID, then revert. The pipe MUST already have a connected client that has
    /// written at least one byte (so a client context exists to impersonate). Returns the client's SID string.
    pub fn authenticate_pipe_client_sid(pipe: HANDLE) -> Result<Sid, Error> {
        unsafe {
            ImpersonateNamedPipeClient(pipe)?;
            // OpenAsSelf = TRUE: open the impersonation token using the process security context, so the
            // impersonated identity cannot itself deny the open.
            let mut token = HANDLE::default();
            let opened = OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, TRUE, &mut token);
            // Always revert before propagating any error, so the thread never stays impersonated.
            let revert = RevertToSelf();
            opened?;
            revert?;
            let sid = token_user_sid(token);
            let _ = CloseHandle(token);
            sid
        }
    }

    /// Build a `\\.\pipe\...` name as a NUL-terminated UTF-16 buffer.
    pub fn pipe_path_wide(name: &str) -> Vec<u16> {
        format!(r"\\.\pipe\{name}").encode_utf16().chain(std::iter::once(0)).collect()
    }

    /// Non-fatal helper: treat `ERROR_PIPE_CONNECTED` (a client that connected between CreateNamedPipe and
    /// ConnectNamedPipe) as success, per the Win32 named-pipe contract.
    pub fn connect_result_ok(r: Result<(), Error>) -> Result<(), Error> {
        match r {
            Ok(()) => Ok(()),
            Err(e) if e.code() == ERROR_PIPE_CONNECTED.to_hresult() => Ok(()),
            Err(e) => Err(e),
        }
    }

    /// §0.W image-integrity primitive: does the file at `path` carry a VALID embedded Authenticode
    /// signature? This is the real `WinVerifyTrust` (`WINTRUST_ACTION_GENERIC_VERIFY_V2`) backing the
    /// `authenticode_valid` field the pure [`brops_core::windows_broker::verify_image`] mandates — the
    /// Windows analogue of the Linux TCB re-hash + signature floor (§2.5/§2.7). Fail-closed: any status
    /// other than `S_OK` (unsigned = `TRUST_E_NOSIGNATURE`, tampered = `TRUST_E_BAD_DIGEST`, untrusted
    /// root, etc.) returns `false`. `WTD_UI_NONE` (never prompts) + `WTD_REVOKE_NONE` (offline-deterministic;
    /// revocation is enforced separately via the manifest, not a network CRL fetch during a launch gate).
    pub fn image_authenticode_valid(path: &str) -> bool {
        let wpath: Vec<u16> = path.encode_utf16().chain(std::iter::once(0)).collect();
        unsafe {
            let mut file_info = WINTRUST_FILE_INFO {
                cbStruct: std::mem::size_of::<WINTRUST_FILE_INFO>() as u32,
                pcwszFilePath: PCWSTR(wpath.as_ptr()),
                hFile: HANDLE::default(),
                pgKnownSubject: std::ptr::null_mut(),
            };
            // WINTRUST_DATA is a plain #[repr(C)] POD (no Default derive); zero it, then set the fields
            // that select file-based, no-UI, offline verification.
            let mut wtd: WINTRUST_DATA = std::mem::zeroed();
            wtd.cbStruct = std::mem::size_of::<WINTRUST_DATA>() as u32;
            wtd.dwUIChoice = WTD_UI_NONE;
            wtd.fdwRevocationChecks = WTD_REVOKE_NONE;
            wtd.dwUnionChoice = WTD_CHOICE_FILE;
            wtd.Anonymous = WINTRUST_DATA_0 { pFile: &mut file_info as *mut WINTRUST_FILE_INFO };
            wtd.dwStateAction = WTD_STATEACTION_VERIFY;
            let mut action = WINTRUST_ACTION_GENERIC_VERIFY_V2;
            let status =
                WinVerifyTrust(HWND::default(), &mut action, &mut wtd as *mut _ as *mut std::ffi::c_void);
            // Always release the state data regardless of the verdict.
            wtd.dwStateAction = WTD_STATEACTION_CLOSE;
            let _ =
                WinVerifyTrust(HWND::default(), &mut action, &mut wtd as *mut _ as *mut std::ffi::c_void);
            status == 0
        }
    }
}

#[cfg(all(test, windows))]
mod win_tests {
    use super::syscall::*;
    use brops_core::windows_broker::{authorize_pipe_peer, Pipe, ServiceSids, WindowsBrokerViolation};
    use std::thread;
    use windows::core::{Error, PCWSTR};
    use windows::Win32::Foundation::{CloseHandle, GENERIC_READ, GENERIC_WRITE, HANDLE};
    use windows::Win32::Storage::FileSystem::{
        CreateFileW, ReadFile, WriteFile, FILE_FLAGS_AND_ATTRIBUTES, FILE_SHARE_MODE, OPEN_EXISTING,
        PIPE_ACCESS_DUPLEX,
    };
    use windows::Win32::System::Pipes::{
        ConnectNamedPipe, CreateNamedPipeW, PIPE_READMODE_BYTE, PIPE_TYPE_BYTE, PIPE_WAIT,
    };
    use windows::Win32::System::Threading::GetCurrentProcessId;

    // A ServiceSids where a chosen SID stands in for one role; the others are placeholders (distinct).
    fn sids_with(broker: &str) -> ServiceSids {
        ServiceSids {
            login: "S-1-0-0-login".into(),
            broker: broker.into(),
            authority: "S-1-0-0-authority".into(),
            sidecar: "S-1-0-0-sidecar".into(),
            supervisor: "S-1-0-0-supervisor".into(),
            recorder: "S-1-0-0-recorder".into(),
            executor: "S-1-0-0-executor".into(),
            signer: "S-1-0-0-signer".into(),
        }
    }

    #[test]
    fn named_pipe_server_authenticates_the_real_client_sid_and_gates_it() {
        // A same-process client connects to the server pipe; both run as this test's user, so the SID the
        // server reads MUST equal this process's user SID. That proves the winapi impersonation path is real
        // (not stubbed), and the pure allowlist then ACCEPTS a matching policy and DENIES a mismatching one.
        let me = current_process_user_sid().expect("own SID");
        let name = format!("brops-peerauth-test-{}", unsafe { GetCurrentProcessId() });
        let wide = pipe_path_wide(&name);

        let server = {
            let wide = wide.clone();
            thread::spawn(move || unsafe {
                let pipe = CreateNamedPipeW(
                    PCWSTR(wide.as_ptr()),
                    PIPE_ACCESS_DUPLEX,
                    PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                    1,
                    4096,
                    4096,
                    0,
                    None,
                );
                assert!(!pipe.is_invalid(), "CreateNamedPipeW failed: {:?}", Error::from_win32());
                connect_result_ok(ConnectNamedPipe(pipe, None)).expect("ConnectNamedPipe");
                // Read the client's byte first so a client context exists to impersonate.
                let mut b = [0u8; 1];
                let mut read = 0u32;
                ReadFile(pipe, Some(&mut b), Some(&mut read), None).expect("ReadFile");
                let sid = authenticate_pipe_client_sid(pipe).expect("authenticate client SID");
                let _ = CloseHandle(pipe);
                sid
            })
        };

        // Give the server a moment to create the pipe, then connect + write one byte.
        // (No sleep primitive dependency: retry CreateFileW until the pipe exists.)
        let client_wide = wide.clone();
        let mut opened: Option<HANDLE> = None;
        for _ in 0..2000 {
            let h = unsafe {
                CreateFileW(
                    PCWSTR(client_wide.as_ptr()),
                    (GENERIC_READ | GENERIC_WRITE).0,
                    FILE_SHARE_MODE(0),
                    None,
                    OPEN_EXISTING,
                    FILE_FLAGS_AND_ATTRIBUTES(0),
                    None,
                )
            };
            if let Ok(h) = h {
                opened = Some(h);
                break;
            }
            thread::yield_now();
        }
        let client = opened.expect("client CreateFileW eventually connects");
        let mut written = 0u32;
        unsafe {
            WriteFile(client, Some(b"x"), Some(&mut written), None).expect("WriteFile");
            let _ = CloseHandle(client);
        }

        let observed = server.join().expect("server thread");
        assert_eq!(observed, me, "server-observed client SID must equal this process's user SID");

        // The pure allowlist then gates the REAL observed SID: a policy allowing it (as the broker on the
        // challenge-authority pipe) passes; the same SID on the signer pipe (supervisor-only) is denied.
        let sids = sids_with(&observed);
        assert!(authorize_pipe_peer(Pipe::ChallengeAuthority, &observed, &sids).is_ok());
        assert!(matches!(
            authorize_pipe_peer(Pipe::Signer, &observed, &sids),
            Err(WindowsBrokerViolation::PeerNotAllowedOnPipe(Pipe::Signer, _))
        ));
    }

    #[test]
    fn authenticode_rejects_an_unsigned_file() {
        // An arbitrary unsigned file has no embedded Authenticode signature -> WinVerifyTrust returns
        // TRUST_E_NOSIGNATURE (nonzero) -> image_authenticode_valid == false. This is the fail-closed
        // direction (§2.7): an image that is not validly signed must never pass.
        let path = std::env::temp_dir()
            .join(format!("brops-unsigned-{}.bin", unsafe { GetCurrentProcessId() }));
        std::fs::write(&path, b"not a signed PE image").unwrap();
        let valid = image_authenticode_valid(path.to_str().unwrap());
        let _ = std::fs::remove_file(&path);
        assert!(!valid, "an unsigned file MUST fail Authenticode verification (fail-closed)");
    }

    #[test]
    fn authenticode_accepts_an_embedded_signed_binary() {
        // Modern Windows system binaries are CATALOG-signed, which file-based WinVerifyTrust (correctly)
        // rejects — the §0.W broker verifies OUR OWN embedded-signed executor, not catalog-signed OS files.
        // Node.js and Git ship EMBEDDED Authenticode signatures and are preinstalled on both a dev box and
        // the windows-latest CI runner, so at least one is a stable positive fixture proving the verifier
        // distinguishes a valid signature (not merely hardcoded false).
        let candidates = [
            r"C:\Program Files\nodejs\node.exe",
            r"C:\Program Files\Git\cmd\git.exe",
            r"C:\Program Files\Git\bin\git.exe",
        ];
        let found: Vec<&str> = candidates
            .iter()
            .copied()
            .filter(|p| std::path::Path::new(p).exists())
            .collect();
        assert!(!found.is_empty(), "expected an embedded-signed fixture (node/git) present");
        assert!(
            found.iter().any(|p| image_authenticode_valid(p)),
            "at least one embedded-signed fixture must pass Authenticode verification: {found:?}"
        );
    }
}
