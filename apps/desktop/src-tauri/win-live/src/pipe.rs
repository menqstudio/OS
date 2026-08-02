//! Windows named-pipe transport for the live kit (the AF_UNIX + SO_PEERCRED analogue). A server creates a
//! NULL-DACL pipe (everyone may CONNECT — like the Linux 0777 socket), then authenticates the connecting
//! client's KERNEL-ATTESTED SID via `ImpersonateNamedPipeClient` (reusing the proven
//! `brops_win_broker::syscall::authenticate_pipe_client_sid`) and gates it against the allowed broker SID —
//! the trust boundary is the peer SID, never the DACL. Requests/replies are the SAME 4-byte-big-endian
//! length-prefixed frames the pure chain speaks (`brops_core::ipc_framing`). The client side implements the
//! broker's `HopConn`/`HopConnector`, so the SAME `GovernedChain` that passed the in-process proof runs
//! unchanged over real pipes.

#![cfg(windows)]

use std::ffi::c_void;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use brops_broker::chain_hops::{HopConn, HopError, Principal};
use brops_core::ipc_framing::{encode_frame, LENGTH_PREFIX_BYTES, MAX_FRAME_PAYLOAD_BYTES};
use brops_win_broker::syscall::{authenticate_pipe_client_sid, connect_result_ok, pipe_path_wide};

use crate::servers::DispatchCore;

use windows::core::{Error, PCWSTR};
use windows::Win32::Foundation::{CloseHandle, GENERIC_READ, GENERIC_WRITE, HANDLE};
use windows::Win32::Security::{
    InitializeSecurityDescriptor, SetSecurityDescriptorDacl, PSECURITY_DESCRIPTOR, SECURITY_ATTRIBUTES,
    SECURITY_DESCRIPTOR,
};
use windows::Win32::Storage::FileSystem::{
    CreateFileW, FlushFileBuffers, ReadFile, WriteFile, FILE_FLAGS_AND_ATTRIBUTES, FILE_SHARE_MODE,
    OPEN_EXISTING, PIPE_ACCESS_DUPLEX,
};
use windows::Win32::System::Pipes::{
    ConnectNamedPipe, CreateNamedPipeW, DisconnectNamedPipe, PIPE_READMODE_BYTE, PIPE_TYPE_BYTE,
    PIPE_UNLIMITED_INSTANCES, PIPE_WAIT,
};
use windows::Win32::System::SystemServices::SECURITY_DESCRIPTOR_REVISION;

const PIPE_BUF: u32 = 8192;

fn now_ms() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
}

/// A NULL-DACL SECURITY_ATTRIBUTES (everyone may connect); peer identity is enforced by SID auth, not the ACL.
unsafe fn null_dacl_sa(sd: &mut SECURITY_DESCRIPTOR) -> SECURITY_ATTRIBUTES {
    let psd = PSECURITY_DESCRIPTOR(sd as *mut _ as *mut c_void);
    let _ = InitializeSecurityDescriptor(psd, SECURITY_DESCRIPTOR_REVISION);
    let _ = SetSecurityDescriptorDacl(psd, true, None, false);
    SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: psd.0,
        bInheritHandle: false.into(),
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
    loop {
        unsafe {
            let mut sd = SECURITY_DESCRIPTOR::default();
            let sa = null_dacl_sa(&mut sd);
            let h = CreateNamedPipeW(
                PCWSTR(wide.as_ptr()),
                PIPE_ACCESS_DUPLEX,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                PIPE_UNLIMITED_INSTANCES,
                PIPE_BUF,
                PIPE_BUF,
                0,
                Some(&sa as *const SECURITY_ATTRIBUTES),
            );
            if h.is_invalid() {
                eprintln!("win-live server[{pipe_name}]: CreateNamedPipeW: {:?}", Error::from_win32());
                continue;
            }
            if connect_result_ok(ConnectNamedPipe(h, None)).is_err() {
                let _ = CloseHandle(h);
                continue;
            }
            // Read the client's framed request (also gives us a client context to impersonate).
            let reply: Value = match read_frame_payload(h) {
                Ok(payload) => {
                    let sid = authenticate_pipe_client_sid(h).ok();
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
                let _ = write_frame(h, &bytes);
            }
            let _ = FlushFileBuffers(h);
            let _ = DisconnectNamedPipe(h);
            let _ = CloseHandle(h);
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
                (GENERIC_READ | GENERIC_WRITE).0,
                FILE_SHARE_MODE(0),
                None,
                OPEN_EXISTING,
                FILE_FLAGS_AND_ATTRIBUTES(0),
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
