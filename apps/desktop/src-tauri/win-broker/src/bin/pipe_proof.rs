//! Windows broker machine-proof — cross-account named-pipe peer-SID authentication (§0.W.4).
//!
//! This is the Windows analogue of the Linux `engine/ci/isolation_proof.sh`: it proves the peer-auth gate
//! works across REAL distinct OS service principals (not same-user threads). Run as two processes under two
//! different service accounts:
//!
//!   pipe_proof server <pipe> <allowed-broker-sid>   # creates a NULL-DACL pipe, authenticates the connecting
//!                                                    # client's SID, gates it as the challenge-authority pipe
//!                                                    # (allows ONLY the broker SID), prints the verdict.
//!   pipe_proof client <pipe>                         # connects + writes a byte + reads the server ack.
//!
//! The pipe uses a NULL DACL (everyone may CONNECT) so a different service account can reach it — exactly like
//! the Linux 0777 socket. The trust boundary is the peer-SID auth (SO_PEERCRED equivalent), NOT the DACL: the
//! server reads the *kernel-attested* client SID via ImpersonateNamedPipeClient and checks the allowlist.
//!
//! On non-Windows this binary is an inert stub so the workspace still builds on the Linux CI runner.

#[cfg(not(windows))]
fn main() {
    eprintln!("pipe_proof is Windows-only");
    std::process::exit(2);
}

#[cfg(windows)]
fn main() {
    std::process::exit(win::run());
}

#[cfg(windows)]
mod win {
    use brops_core::windows_broker::{authorize_pipe_peer, Pipe, ServiceSids};
    use brops_win_broker::syscall::{authenticate_pipe_client_sid, connect_result_ok, pipe_path_wide};
    use std::ffi::c_void;
    use windows::core::{Error, PCWSTR};
    use windows::Win32::Foundation::{CloseHandle, GENERIC_READ, GENERIC_WRITE, HANDLE};
    use windows::Win32::Security::{
        InitializeSecurityDescriptor, SetSecurityDescriptorDacl, PSECURITY_DESCRIPTOR,
        SECURITY_ATTRIBUTES, SECURITY_DESCRIPTOR,
    };
    use windows::Win32::Storage::FileSystem::{
        CreateFileW, ReadFile, WriteFile, FILE_FLAGS_AND_ATTRIBUTES, FILE_SHARE_MODE, OPEN_EXISTING,
        PIPE_ACCESS_DUPLEX,
    };
    use windows::Win32::System::Pipes::{
        ConnectNamedPipe, CreateNamedPipeW, PIPE_READMODE_BYTE, PIPE_TYPE_BYTE, PIPE_WAIT,
    };
    use windows::Win32::System::SystemServices::SECURITY_DESCRIPTOR_REVISION;

    fn out(line: &str) {
        println!("{line}");
    }

    pub fn run() -> i32 {
        let args: Vec<String> = std::env::args().collect();
        if args.len() < 3 {
            out("PROOF_ERROR=usage: pipe_proof <server|client> <pipe> [allowed-broker-sid]");
            return 2;
        }
        match args[1].as_str() {
            "server" if args.len() >= 4 => server(&args[2], &args[3]),
            "client" => client(&args[2]),
            _ => {
                out("PROOF_ERROR=bad-args");
                2
            }
        }
    }

    /// Build a SECURITY_ATTRIBUTES carrying a NULL DACL (grants everyone access) so a client under a different
    /// service account can CONNECT. The descriptor is owned by the caller for the pipe's lifetime.
    unsafe fn null_dacl_sa(sd: &mut SECURITY_DESCRIPTOR) -> SECURITY_ATTRIBUTES {
        let psd = PSECURITY_DESCRIPTOR(sd as *mut _ as *mut c_void);
        let _ = InitializeSecurityDescriptor(psd, SECURITY_DESCRIPTOR_REVISION);
        // present=TRUE, dacl=NULL, defaulted=FALSE  => NULL DACL => everyone allowed.
        let _ = SetSecurityDescriptorDacl(psd, true, None, false);
        SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: psd.0,
            bInheritHandle: false.into(),
        }
    }

    fn server(pipe: &str, allowed_broker_sid: &str) -> i32 {
        let wide = pipe_path_wide(pipe);
        unsafe {
            let mut sd = SECURITY_DESCRIPTOR::default();
            let sa = null_dacl_sa(&mut sd);
            let h = CreateNamedPipeW(
                PCWSTR(wide.as_ptr()),
                PIPE_ACCESS_DUPLEX,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                1,
                4096,
                4096,
                0,
                Some(&sa as *const SECURITY_ATTRIBUTES),
            );
            if h.is_invalid() {
                out(&format!("PROOF_ERROR=CreateNamedPipeW: {:?}", Error::from_win32()));
                return 1;
            }
            if let Err(e) = connect_result_ok(ConnectNamedPipe(h, None)) {
                out(&format!("PROOF_ERROR=ConnectNamedPipe: {e:?}"));
                let _ = CloseHandle(h);
                return 1;
            }
            let mut b = [0u8; 1];
            let mut read = 0u32;
            if ReadFile(h, Some(&mut b), Some(&mut read), None).is_err() {
                out(&format!("PROOF_ERROR=ReadFile: {:?}", Error::from_win32()));
                let _ = CloseHandle(h);
                return 1;
            }
            let client_sid = match authenticate_pipe_client_sid(h) {
                Ok(s) => s,
                Err(e) => {
                    out(&format!("PROOF_ERROR=authenticate: {e:?}"));
                    let _ = CloseHandle(h);
                    return 1;
                }
            };
            // Gate the REAL kernel-attested client SID as the challenge-authority pipe (allows ONLY broker).
            let sids = ServiceSids {
                login: "S-1-0-0".into(),
                broker: allowed_broker_sid.to_string(),
                authority: "S-1-0-0-a".into(),
                sidecar: "S-1-0-0-c".into(),
                supervisor: "S-1-0-0-s".into(),
                recorder: "S-1-0-0-r".into(),
                executor: "S-1-0-0-e".into(),
                signer: "S-1-0-0-g".into(),
            };
            let verdict = match authorize_pipe_peer(Pipe::ChallengeAuthority, &client_sid, &sids) {
                Ok(()) => "ALLOW",
                Err(_) => "DENY",
            };
            out(&format!("CLIENT_SID={client_sid}"));
            out(&format!("VERDICT={verdict}"));
            // Ack so the client stays connected until we've authenticated (removes any close-race).
            let mut wrote = 0u32;
            let _ = WriteFile(h, Some(b"y"), Some(&mut wrote), None);
            let _ = CloseHandle(h);
            0
        }
    }

    fn client(pipe: &str) -> i32 {
        let wide = pipe_path_wide(pipe);
        unsafe {
            // Retry until the server pipe exists.
            let mut handle: Option<HANDLE> = None;
            for _ in 0..3000 {
                if let Ok(h) = CreateFileW(
                    PCWSTR(wide.as_ptr()),
                    (GENERIC_READ | GENERIC_WRITE).0,
                    FILE_SHARE_MODE(0),
                    None,
                    OPEN_EXISTING,
                    FILE_FLAGS_AND_ATTRIBUTES(0),
                    None,
                ) {
                    handle = Some(h);
                    break;
                }
                std::thread::sleep(std::time::Duration::from_millis(5));
            }
            let h = match handle {
                Some(h) => h,
                None => {
                    out(&format!("PROOF_ERROR=client CreateFileW: {:?}", Error::from_win32()));
                    return 1;
                }
            };
            let mut wrote = 0u32;
            let _ = WriteFile(h, Some(b"x"), Some(&mut wrote), None);
            let mut ack = [0u8; 1];
            let mut ackread = 0u32;
            let _ = ReadFile(h, Some(&mut ack), Some(&mut ackread), None);
            let _ = CloseHandle(h);
            out("CLIENT_DONE=1");
            0
        }
    }
}
