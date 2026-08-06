//! Windows named-pipe transport for the live kit (the AF_UNIX + SO_PEERCRED analogue). A server creates a
//! pipe with a RESTRICTIVE DACL (see [`crate::pipe_acl`]), then authenticates the connecting client's
//! KERNEL-ATTESTED SID via `ImpersonateNamedPipeClient` (reusing the proven
//! `brops_win_broker::syscall::authenticate_pipe_client_sid`) and gates it against the allowed broker SID.
//! Requests/replies are the SAME 4-byte-big-endian length-prefixed frames the pure chain speaks
//! (`brops_core::ipc_framing`). The client side implements the broker's `HopConn`/`HopConnector`, so the
//! SAME `GovernedChain` that passed the in-process proof runs unchanged over real pipes.
//!
//! ## The DACL is part of the boundary (audit R3 — it used to be NULL)
//!
//! This transport previously created every pipe with a **NULL DACL**, justified as "the trust boundary is
//! the peer SID, never the DACL". That reasoning covers who may CONNECT and not who may CREATE: a NULL
//! DACL grants everyone `FILE_ALL_ACCESS`, which includes `FILE_CREATE_PIPE_INSTANCE`, so any local
//! principal could stand up a SECOND instance of the trusted pipe name at any time and collect the next
//! connection. `FILE_FLAG_FIRST_PIPE_INSTANCE` only fails a create when an instance already exists, so it
//! stopped a squatter who arrived first and did nothing about one arriving later — under a NULL DACL,
//! anyone could arrive later. The flag protected nothing.
//!
//! Three things changed together, and all three are needed:
//!
//! 1. The pipe is created with the explicit DACL from [`crate::pipe_acl::pipe_dacl_plan`]: server
//!    principal + SYSTEM + Administrators full, the provisioned broker SID read/write **without**
//!    `FILE_CREATE_PIPE_INSTANCE`, everyone else absent (and so denied). A failure to build that
//!    descriptor ABORTS the server — there is no NULL-DACL fallback.
//! 2. The server never lets go of the name: the successor instance is created BEFORE the serving instance
//!    is closed, so there is no window in which the pipe name is unowned and a squatter could take it.
//!    `FILE_FLAG_FIRST_PIPE_INSTANCE` is used for the FIRST create only, and its failure now aborts the
//!    process instead of spinning in a retry loop.
//! 3. The client requests [`crate::pipe_acl::PIPE_CLIENT_ACCESS_MASK`] instead of
//!    `GENERIC_READ | GENERIC_WRITE`, because the named-pipe generic mapping expands `GENERIC_WRITE` to
//!    include `FILE_APPEND_DATA` — the same bit as `FILE_CREATE_PIPE_INSTANCE` — which the DACL now
//!    withholds.
//!
//! Every CLIENT connect also passes `SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION` (a server we connect
//! to can only *identify* us, never obtain an impersonation token to act AS the broker). The peer-SID gate
//! remains the primary boundary; these remove the transport preconditions for defeating it.
//!
//! **Honest limitation:** in a SAME-ACCOUNT deployment the broker is the server principal, so it keeps full
//! control and the create-instance restriction buys nothing against it. `run_server` says so on stderr
//! rather than letting the log imply cross-account containment it does not have.

#![cfg(windows)]

use std::ffi::c_void;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use brops_broker::chain_hops::{HopConn, HopError, Principal};
use brops_core::ipc_framing::{encode_frame, LENGTH_PREFIX_BYTES, MAX_FRAME_PAYLOAD_BYTES};
use brops_win_broker::syscall::{
    authenticate_pipe_client_sid, connect_result_ok, current_process_user_sid, pipe_path_wide,
};

use crate::pipe_acl::{self, PIPE_CLIENT_ACCESS_MASK};
use crate::servers::DispatchCore;

use windows::core::{Error, PCWSTR};
use windows::Win32::Foundation::{CloseHandle, LocalFree, HANDLE, HLOCAL};
use windows::Win32::Security::Authorization::ConvertStringSidToSidW;
use windows::Win32::Security::{
    AddAccessAllowedAce, InitializeAcl, InitializeSecurityDescriptor, SetSecurityDescriptorDacl, ACL,
    ACL_REVISION, PSECURITY_DESCRIPTOR, PSID, SECURITY_ATTRIBUTES, SECURITY_DESCRIPTOR,
};
use windows::Win32::Storage::FileSystem::{
    CreateFileW, FlushFileBuffers, ReadFile, WriteFile, FILE_FLAG_FIRST_PIPE_INSTANCE, FILE_SHARE_MODE,
    OPEN_EXISTING, PIPE_ACCESS_DUPLEX, SECURITY_IDENTIFICATION, SECURITY_SQOS_PRESENT,
};
use windows::Win32::System::Pipes::{
    ConnectNamedPipe, CreateNamedPipeW, DisconnectNamedPipe, PIPE_READMODE_BYTE, PIPE_TYPE_BYTE,
    PIPE_UNLIMITED_INSTANCES, PIPE_WAIT,
};
use windows::Win32::System::SystemServices::SECURITY_DESCRIPTOR_REVISION;

const PIPE_BUF: u32 = 8192;

/// `SECURITY_MAX_SID_SIZE`: the largest a SID can be, used to size the ACL buffer generously rather than
/// calling `GetLengthSid` per entry. Over-allocating an ACL is harmless; under-allocating is not.
const MAX_SID_BYTES: usize = 68;

fn now_ms() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
}

/// A live security descriptor built from a [`crate::pipe_acl::PipeDacl`] plan. Owns the ACL buffer and the
/// `LocalAlloc`'d SIDs it references, so the descriptor stays valid for as long as the server serves.
///
/// There is deliberately NO constructor that yields a permissive descriptor: the only way to obtain one of
/// these is through `pipe_dacl_plan`, which refuses malformed and world SIDs.
struct PipeSecurity {
    /// Backing store for the ACL; the descriptor points into it.
    acl: Vec<u8>,
    /// `LocalAlloc`'d SIDs referenced by the ACEs — freed on drop, after the descriptor is gone.
    sids: Vec<PSID>,
    /// Boxed so its address is stable across moves of this struct.
    sd: Box<SECURITY_DESCRIPTOR>,
    /// Whether the broker shares the server's principal (same-account deployment) — reported, not hidden.
    broker_is_server_principal: bool,
}

impl PipeSecurity {
    fn build(server_sid: &str, allowed_broker_sid: &str) -> Result<PipeSecurity, String> {
        let plan = pipe_acl::pipe_dacl_plan(server_sid, allowed_broker_sid)?;
        let mut sids: Vec<PSID> = Vec::with_capacity(plan.aces.len());
        unsafe {
            for ace in &plan.aces {
                let wide: Vec<u16> = ace.sid.encode_utf16().chain(std::iter::once(0)).collect();
                let mut psid = PSID::default();
                if ConvertStringSidToSidW(PCWSTR(wide.as_ptr()), &mut psid).is_err() {
                    for s in &sids {
                        let _ = LocalFree(HLOCAL(s.0));
                    }
                    return Err(format!("ConvertStringSidToSidW failed for {}", ace.sid));
                }
                sids.push(psid);
            }

            let acl_len = std::mem::size_of::<ACL>()
                + plan.aces.len() * (std::mem::size_of::<u32>() * 3 + MAX_SID_BYTES);
            let mut acl = vec![0u8; acl_len];
            let pacl = acl.as_mut_ptr() as *mut ACL;
            if InitializeAcl(pacl, acl_len as u32, ACL_REVISION).is_err() {
                for s in &sids {
                    let _ = LocalFree(HLOCAL(s.0));
                }
                return Err(format!("InitializeAcl: {:?}", Error::from_win32()));
            }
            for (ace, psid) in plan.aces.iter().zip(sids.iter()) {
                if AddAccessAllowedAce(pacl, ACL_REVISION, ace.mask, *psid).is_err() {
                    for s in &sids {
                        let _ = LocalFree(HLOCAL(s.0));
                    }
                    return Err(format!("AddAccessAllowedAce({}): {:?}", ace.sid, Error::from_win32()));
                }
            }

            let mut sd = Box::new(SECURITY_DESCRIPTOR::default());
            let psd = PSECURITY_DESCRIPTOR(sd.as_mut() as *mut SECURITY_DESCRIPTOR as *mut c_void);
            if InitializeSecurityDescriptor(psd, SECURITY_DESCRIPTOR_REVISION).is_err() {
                for s in &sids {
                    let _ = LocalFree(HLOCAL(s.0));
                }
                return Err(format!("InitializeSecurityDescriptor: {:?}", Error::from_win32()));
            }
            // `true` = a DACL IS present. Passing `None` here is the NULL-DACL bug this replaced.
            if SetSecurityDescriptorDacl(psd, true, Some(acl.as_ptr() as *const ACL), false).is_err() {
                for s in &sids {
                    let _ = LocalFree(HLOCAL(s.0));
                }
                return Err(format!("SetSecurityDescriptorDacl: {:?}", Error::from_win32()));
            }
            Ok(PipeSecurity {
                acl,
                sids,
                sd,
                broker_is_server_principal: plan.broker_is_server_principal,
            })
        }
    }

    /// `SECURITY_ATTRIBUTES` pointing at this descriptor. Built on demand so no raw self-reference is
    /// stored in the struct.
    fn attributes(&mut self) -> SECURITY_ATTRIBUTES {
        SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: self.sd.as_mut() as *mut SECURITY_DESCRIPTOR as *mut c_void,
            bInheritHandle: false.into(),
        }
    }
}

impl Drop for PipeSecurity {
    fn drop(&mut self) {
        unsafe {
            for s in &self.sids {
                let _ = LocalFree(HLOCAL(s.0));
            }
        }
        self.acl.clear();
    }
}

/// Read exactly `buf.len()` bytes from the pipe, or Err on EOF/short read.
unsafe fn read_exact(h: HANDLE, buf: &mut [u8]) -> Result<(), ()> {
    let mut got = 0usize;
    while got < buf.len() {
        let mut n = 0u32;
        ReadFile(h, Some(&mut buf[got..]), Some(&mut n), None).map_err(|_| ())?;
        if n == 0 {
            return Err(());
        }
        got += n as usize;
    }
    Ok(())
}

/// Write all bytes to the pipe.
unsafe fn write_all(h: HANDLE, mut buf: &[u8]) -> Result<(), ()> {
    while !buf.is_empty() {
        let mut n = 0u32;
        WriteFile(h, Some(buf), Some(&mut n), None).map_err(|_| ())?;
        if n == 0 {
            return Err(());
        }
        buf = &buf[n as usize..];
    }
    Ok(())
}

/// Read one length-prefixed frame's PAYLOAD (bounded by the shared cap).
unsafe fn read_frame_payload(h: HANDLE) -> Result<Vec<u8>, ()> {
    let mut prefix = [0u8; LENGTH_PREFIX_BYTES];
    read_exact(h, &mut prefix)?;
    let declared = u32::from_be_bytes(prefix) as usize;
    if declared == 0 || declared > MAX_FRAME_PAYLOAD_BYTES {
        return Err(());
    }
    let mut body = vec![0u8; declared];
    read_exact(h, &mut body)?;
    Ok(body)
}

/// Write a payload as one length-prefixed frame.
unsafe fn write_frame(h: HANDLE, payload: &[u8]) -> Result<(), ()> {
    let frame = encode_frame(payload).map_err(|_| ())?;
    write_all(h, &frame)
}

// =================================================================================================
// Server
// =================================================================================================

/// Serve `core` on `pipe_name` forever: one connection at a time, each a single framed request → framed
/// reply. Every connection's client SID is authenticated and MUST equal `allowed_peer_sid` (the broker), or
/// the request is refused before dispatch — the peer-SID trust boundary. Never returns (killed by the proof
/// harness).
pub fn run_server(pipe_name: &str, allowed_peer_sid: &str, core: &dyn DispatchCore) -> ! {
    let wide = pipe_path_wide(pipe_name);

    // The server's own principal is one of the DACL's full-control trustees; it is read from the process
    // token, never from config, so a config-writing adversary cannot nominate the pipe's owner.
    let server_sid = match current_process_user_sid() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("win-live server[{pipe_name}]: cannot read own SID ({e:?}); refusing to serve");
            std::process::exit(9);
        }
    };
    let mut security = match PipeSecurity::build(&server_sid, allowed_peer_sid) {
        Ok(s) => s,
        Err(why) => {
            // No NULL-DACL fallback. A pipe we cannot restrict is a pipe anyone can instantiate.
            eprintln!("win-live server[{pipe_name}]: cannot build a restrictive pipe DACL: {why}");
            eprintln!("win-live server[{pipe_name}]: refusing to serve on an unrestricted pipe");
            std::process::exit(9);
        }
    };
    if security.broker_is_server_principal {
        // Say it out loud: this deployment does not get the create-instance restriction.
        eprintln!(
            "win-live server[{pipe_name}]: WARNING same-account deployment — the broker SID IS this \
             server's principal, so it retains FILE_CREATE_PIPE_INSTANCE. Pipe-squat resistance requires \
             distinct service accounts (see CROSS_ACCOUNT_PROOF.md)."
        );
    }
    let sa = security.attributes();

    // `first` selects FILE_FLAG_FIRST_PIPE_INSTANCE. It is meaningful ONLY on the very first create: it
    // fails if any instance of the name already exists, which is the fail-closed detection of a squatter
    // who got there before us. Afterwards we always hold an instance, so no one else can create one (the
    // DACL withholds FILE_CREATE_PIPE_INSTANCE from every non-TCB principal) and the flag would only stop
    // US from making our own successor.
    let create = |first: bool| -> Result<HANDLE, Error> {
        let flags = if first {
            PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE
        } else {
            PIPE_ACCESS_DUPLEX
        };
        unsafe {
            let h = CreateNamedPipeW(
                PCWSTR(wide.as_ptr()),
                flags,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                PIPE_UNLIMITED_INSTANCES,
                PIPE_BUF,
                PIPE_BUF,
                0,
                Some(&sa as *const SECURITY_ATTRIBUTES),
            );
            if h.is_invalid() {
                Err(Error::from_win32())
            } else {
                Ok(h)
            }
        }
    };

    let mut current = match create(true) {
        Ok(h) => h,
        Err(e) => {
            // Previously this printed and `continue`d, spinning forever and re-trying until the squatter
            // released the name — i.e. it eventually coexisted with whatever created the name first. A
            // trusted pipe name we could not create first is a compromised transport; stop.
            eprintln!(
                "win-live server[{pipe_name}]: CreateNamedPipeW(FIRST_PIPE_INSTANCE) failed: {e:?}"
            );
            eprintln!(
                "win-live server[{pipe_name}]: the pipe name already exists — another process holds it. \
                 Refusing to serve rather than coexist with a squatter."
            );
            std::process::exit(9);
        }
    };

    loop {
        unsafe {
            if connect_result_ok(ConnectNamedPipe(current, None)).is_ok() {
                // Read the client's framed request (also gives us a client context to impersonate).
                let reply: Value = match read_frame_payload(current) {
                    Ok(payload) => {
                        let sid = authenticate_pipe_client_sid(current).ok();
                        let allowed = sid.as_deref() == Some(allowed_peer_sid);
                        if !allowed {
                            json!({ "ok": false, "reason": "peer_denied", "peer_sid": sid })
                        } else {
                            match serde_json::from_slice::<Value>(&payload) {
                                Ok(req) => core.handle(&req, now_ms()),
                                Err(_) => json!({ "ok": false, "reason": "malformed" }),
                            }
                        }
                    }
                    Err(()) => json!({ "ok": false, "reason": "read_error" }),
                };
                if let Ok(bytes) = serde_json::to_vec(&reply) {
                    let _ = write_frame(current, &bytes);
                }
                let _ = FlushFileBuffers(current);
            }

            // Stand the successor up BEFORE releasing this instance, so the pipe name is never unowned.
            // Closing first and re-creating (what this loop used to do) leaves a window in which any local
            // principal can create the name and inherit every subsequent connection — the window
            // FILE_FLAG_FIRST_PIPE_INSTANCE cannot close, because by then it is the squatter who is first.
            let mut next = None;
            for _ in 0..200 {
                match create(false) {
                    Ok(h) => {
                        next = Some(h);
                        break;
                    }
                    Err(_) => std::thread::sleep(std::time::Duration::from_millis(5)),
                }
            }
            let Some(next) = next else {
                eprintln!(
                    "win-live server[{pipe_name}]: cannot create a successor pipe instance; stopping \
                     rather than releasing the pipe name to whoever creates it next"
                );
                std::process::exit(9);
            };
            let _ = DisconnectNamedPipe(current);
            let _ = CloseHandle(current);
            current = next;
        }
    }
}

// =================================================================================================
// Client
// =================================================================================================

/// Open a client handle to a named pipe, retrying briefly until the server instance exists.
fn open_client(pipe_name: &str) -> Result<HANDLE, ()> {
    let wide = pipe_path_wide(pipe_name);
    for _ in 0..3000 {
        let h = unsafe {
            CreateFileW(
                PCWSTR(wide.as_ptr()),
                // NOT `GENERIC_READ | GENERIC_WRITE`: the named-pipe generic mapping expands GENERIC_WRITE
                // to include FILE_APPEND_DATA, whose bit value IS FILE_CREATE_PIPE_INSTANCE. The server's
                // DACL deliberately withholds that bit from the broker, so a generic request would be
                // denied — and "fixing" the denial by granting 0x4 would hand the squat right straight
                // back. Request exactly the duplex-I/O rights the framed transport uses.
                PIPE_CLIENT_ACCESS_MASK,
                FILE_SHARE_MODE(0),
                None,
                OPEN_EXISTING,
                // SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION (audit P0, broker impersonation): pin the
                // impersonation level the SERVER we connect to may obtain to *Identification* only. Without
                // this, a named-pipe client defaults to SecurityImpersonation, so a rogue server that squatted
                // the pipe name could `ImpersonateNamedPipeClient` and act AS the broker (relaying a
                // broker-SID token onward to the signer/authority and passing their peer-SID gate). An
                // identification-level token cannot be used to open another pipe as the broker, closing the
                // relay. The kernel-attested server-side SID gate still only needs to READ our SID.
                SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION,
                None,
            )
        };
        if let Ok(h) = h {
            return Ok(h);
        }
        std::thread::sleep(std::time::Duration::from_millis(3));
    }
    Err(())
}

/// A single live named-pipe connection as a broker [`HopConn`].
pub struct WindowsHopConn {
    handle: HANDLE,
}
impl HopConn for WindowsHopConn {
    fn send_all(&mut self, frame: &[u8]) -> Result<(), HopError> {
        // `frame` is already length-prefixed by `hop_roundtrip`; write it verbatim.
        unsafe { write_all(self.handle, frame).map_err(|_| HopError::Io) }
    }
    fn recv_all(&mut self) -> Result<Vec<u8>, HopError> {
        let payload = unsafe { read_frame_payload(self.handle).map_err(|_| HopError::Io)? };
        // Return the reply framed, matching the Unix transport's contract for `decode_one`.
        encode_frame(&payload).map_err(HopError::from)
    }
}
impl Drop for WindowsHopConn {
    fn drop(&mut self) {
        unsafe {
            let _ = CloseHandle(self.handle);
        }
    }
}

/// The broker's named-pipe connector: one fresh connection per hop, routed by [`Principal`].
pub struct WindowsHopConnector {
    pub authority_pipe: String,
    pub supervisor_pipe: String,
    pub signer_pipe: String,
}
impl brops_broker::chain_executor::HopConnector for WindowsHopConnector {
    fn connect(&self, principal: Principal) -> Result<Box<dyn HopConn>, HopError> {
        let name = match principal {
            Principal::ChallengeAuthority => &self.authority_pipe,
            Principal::Supervisor => &self.supervisor_pipe,
            Principal::IsolatedSigner => &self.signer_pipe,
        };
        let handle = open_client(name).map_err(|_| HopError::Unavailable)?;
        Ok(Box::new(WindowsHopConn { handle }))
    }
}

/// One framed request→reply roundtrip to a pipe (used by the execution's `attest-run` hop to the supervisor).
pub fn hop_once(pipe_name: &str, req: &Value) -> Result<Value, ()> {
    let handle = open_client(pipe_name)?;
    let result = (|| unsafe {
        let bytes = serde_json::to_vec(req).map_err(|_| ())?;
        write_frame(handle, &bytes)?;
        let payload = read_frame_payload(handle)?;
        serde_json::from_slice::<Value>(&payload).map_err(|_| ())
    })();
    unsafe {
        let _ = CloseHandle(handle);
    }
    result
}

// =================================================================================================
// Windows-only read-back test
// =================================================================================================
//
// These run on a Windows host only, so they are NOT covered by the Linux CI runner — the pure DACL plan
// in `crate::pipe_acl` is what CI guards. This test is the end-to-end half: it creates a real pipe with
// the real `PipeSecurity` and reads the descriptor back off the kernel object, so it fails if anyone
// restores the NULL DACL (which the pure tests, by themselves, could not detect).
#[cfg(test)]
mod win_pipe_tests {
    use super::*;
    use crate::pipe_acl::{create_instance_grantees, dacl_is_open, world_grantees, PipeAce};
    use windows::core::PWSTR;
    use windows::Win32::Foundation::ERROR_SUCCESS;
    use windows::Win32::Security::Authorization::{ConvertSidToStringSidW, GetSecurityInfo, SE_KERNEL_OBJECT};
    use windows::Win32::Security::{
        AclSizeInformation, GetAce, GetAclInformation, ACCESS_ALLOWED_ACE, ACE_HEADER,
        ACL_SIZE_INFORMATION, DACL_SECURITY_INFORMATION,
    };
    use windows::Win32::System::SystemServices::ACCESS_ALLOWED_ACE_TYPE;
    use windows::Win32::System::Threading::GetCurrentProcessId;

    /// Read the DACL actually attached to a kernel object: `(dacl_present, allow_aces)`.
    unsafe fn handle_dacl(h: HANDLE) -> Option<(bool, Vec<PipeAce>)> {
        let mut dacl: *mut ACL = std::ptr::null_mut();
        let mut psd = PSECURITY_DESCRIPTOR::default();
        let rc = GetSecurityInfo(
            h,
            SE_KERNEL_OBJECT,
            DACL_SECURITY_INFORMATION,
            None,
            None,
            Some(&mut dacl),
            None,
            Some(&mut psd),
        );
        if rc != ERROR_SUCCESS {
            return None;
        }
        let present = !dacl.is_null();
        let mut aces = Vec::new();
        if present {
            let mut info = ACL_SIZE_INFORMATION::default();
            if GetAclInformation(
                dacl,
                &mut info as *mut _ as *mut c_void,
                std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
                AclSizeInformation,
            )
            .is_ok()
            {
                for i in 0..info.AceCount {
                    let mut pace: *mut c_void = std::ptr::null_mut();
                    if GetAce(dacl, i, &mut pace).is_err() || pace.is_null() {
                        continue;
                    }
                    let hdr = &*(pace as *const ACE_HEADER);
                    if hdr.AceType as u32 != ACCESS_ALLOWED_ACE_TYPE {
                        continue;
                    }
                    let ace = &*(pace as *const ACCESS_ALLOWED_ACE);
                    let mut wide = PWSTR::null();
                    if ConvertSidToStringSidW(PSID(&ace.SidStart as *const u32 as *mut c_void), &mut wide)
                        .is_ok()
                    {
                        if let Ok(s) = wide.to_string() {
                            aces.push(PipeAce { sid: s, mask: ace.Mask });
                        }
                        let _ = LocalFree(HLOCAL(wide.0 as *mut c_void));
                    }
                }
            }
        }
        if !psd.is_invalid() {
            let _ = LocalFree(HLOCAL(psd.0));
        }
        Some((present, aces))
    }

    #[test]
    fn a_created_pipe_carries_a_restrictive_dacl_not_a_null_one() {
        let me = current_process_user_sid().expect("own SID");
        // A broker SID that is deliberately NOT this process, so the plan takes the cross-account shape.
        let broker = "S-1-5-21-424242-424242-424242-4444";
        let mut sec = PipeSecurity::build(&me, broker).expect("build restrictive descriptor");
        assert!(!sec.broker_is_server_principal);
        let sa = sec.attributes();
        let name = format!("brops-dacl-readback-{}", unsafe { GetCurrentProcessId() });
        let wide = pipe_path_wide(&name);
        let h = unsafe {
            CreateNamedPipeW(
                PCWSTR(wide.as_ptr()),
                PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                PIPE_UNLIMITED_INSTANCES,
                PIPE_BUF,
                PIPE_BUF,
                0,
                Some(&sa as *const SECURITY_ATTRIBUTES),
            )
        };
        assert!(!h.is_invalid(), "CreateNamedPipeW: {:?}", Error::from_win32());

        let (present, aces) = unsafe { handle_dacl(h) }.expect("read back the pipe DACL");
        unsafe {
            let _ = CloseHandle(h);
        }

        // The finding, asserted against the live kernel object rather than a plan.
        assert!(present, "the pipe must NOT have a NULL DACL");
        assert!(!dacl_is_open(present, &aces), "pipe descriptor is open: {aces:?}");
        assert!(world_grantees(&aces).is_empty(), "world SID on the pipe: {aces:?}");
        let creators = create_instance_grantees(&aces);
        assert!(
            !creators.contains(&broker),
            "the broker must not be able to create pipe instances: {creators:?}"
        );
        let broker_ace = aces.iter().find(|a| a.sid == broker).expect("broker ACE present");
        assert_eq!(broker_ace.mask, PIPE_CLIENT_ACCESS_MASK);
    }

    #[test]
    fn a_world_broker_sid_aborts_descriptor_construction() {
        // Fail-closed: there is no code path from a bad broker SID to a permissive pipe.
        let me = current_process_user_sid().expect("own SID");
        assert!(PipeSecurity::build(&me, "S-1-1-0").is_err());
        assert!(PipeSecurity::build(&me, "").is_err());
    }
}
