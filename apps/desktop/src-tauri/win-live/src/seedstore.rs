//! DPAPI custody for the live-kit principal seeds (closes the "seeds are plaintext hex at rest" audit note).
//!
//! A seed at rest is EITHER a legacy 64-char ASCII-hex file (Linux CI / in-process proof), OR a per-user
//! DPAPI blob bound to the OWNING service account's master key. `config::read_seed` detects which by content,
//! so config paths and the server bins are unchanged. A seed sealed by `CryptProtectData` (per-user scope, no
//! `CRYPTPROTECT_LOCAL_MACHINE`) can be recovered ONLY by the account that sealed it — so a login user (or a
//! sibling principal) who copies the SEALED BLOB cannot decrypt it.
//!
//! Read that claim precisely, because it was previously written as though it covered the whole life of the
//! seed (remediation audit, P1). The seal is applied on FIRST READ. Between provisioning and that read the
//! seed is plaintext hex on disk, and `attest.seed` + `signer.seed` are the two production keys
//! `verify_and_accept` checks — so in that window the boundary is not cryptographic at all, and anyone who
//! can read the file can sign anything the chain will then accept. `win_provision::write_seed` closes the
//! window by restricting each seed to its owning account before anything can read it, which also makes the
//! trust-on-first-use binding correct by construction: the owning account is the only one that CAN read it.
//! The cryptographic boundary is what remains AFTER that, not what protects the seed before it.
//!
//! DPAPI-NG `SID=` was rejected: its protector needs the AD DS KDS root key, which does not exist on a
//! standalone/workgroup box (this deployment uses local accounts). Classic per-user DPAPI is the right fit.

#![cfg(windows)]

use std::ffi::c_void;

use windows::core::PCWSTR;
use windows::Win32::Foundation::{LocalFree, HLOCAL};
use windows::Win32::Security::Cryptography::{
    CryptProtectData, CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
};

/// App-scoped secondary entropy (constant, not secret): separates OUR blobs from any other DPAPI blob of the
/// same account; supplied identically on protect + unprotect.
const ENTROPY: &[u8] = b"brops-live-seed-v1";

fn entropy_blob() -> CRYPT_INTEGER_BLOB {
    CRYPT_INTEGER_BLOB { cbData: ENTROPY.len() as u32, pbData: ENTROPY.as_ptr() as *mut u8 }
}

/// Seal a raw 32-byte seed to the CURRENT account (per-user scope). Must run AS the owning account with its
/// profile loaded (true for a scheduled-task / service logon).
pub fn dpapi_seal(seed: &[u8; 32]) -> Result<Vec<u8>, String> {
    unsafe {
        let input = CRYPT_INTEGER_BLOB { cbData: 32, pbData: seed.as_ptr() as *mut u8 };
        let ent = entropy_blob();
        let mut out = CRYPT_INTEGER_BLOB::default();
        CryptProtectData(
            &input,
            PCWSTR::null(),
            Some(&ent),
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut out,
        )
        .map_err(|e| format!("CryptProtectData: {e:?}"))?;
        let blob = std::slice::from_raw_parts(out.pbData, out.cbData as usize).to_vec();
        let _ = LocalFree(HLOCAL(out.pbData as *mut c_void));
        Ok(blob)
    }
}

/// Unseal a DPAPI blob back to the 32-byte seed. Succeeds ONLY when running as the account that sealed it
/// (its master key). Scrubs the plaintext DPAPI output before freeing it.
pub fn dpapi_unseal(blob: &[u8]) -> Result<[u8; 32], String> {
    unsafe {
        let input = CRYPT_INTEGER_BLOB { cbData: blob.len() as u32, pbData: blob.as_ptr() as *mut u8 };
        let ent = entropy_blob();
        let mut out = CRYPT_INTEGER_BLOB::default();
        CryptUnprotectData(
            &input,
            None,
            Some(&ent),
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut out,
        )
        .map_err(|e| format!("CryptUnprotectData (wrong account / tampered?): {e:?}"))?;
        let n = out.cbData as usize;
        let mut seed = [0u8; 32];
        let ok = n == 32;
        if ok {
            std::ptr::copy_nonoverlapping(out.pbData, seed.as_mut_ptr(), 32);
        }
        std::ptr::write_bytes(out.pbData, 0, n); // scrub plaintext
        let _ = LocalFree(HLOCAL(out.pbData as *mut c_void));
        if ok {
            Ok(seed)
        } else {
            Err(format!("unsealed seed wrong length: {n}"))
        }
    }
}

/// A DPAPI blob is `DWORD dwVersion (0x00000001)` followed by the provider GUID
/// {df9d8cd0-1501-11d1-8c7a-00c04fc297eb} in little-endian wire order — i.e. the GUID sits at OFFSET 4, after
/// the version DWORD. Used to distinguish a sealed blob from a legacy plaintext-hex seed file.
pub fn looks_sealed(bytes: &[u8]) -> bool {
    const GUID_LE: [u8; 16] = [
        0xD0, 0x8C, 0x9D, 0xDF, 0x01, 0x15, 0xD1, 0x11, 0x8C, 0x7A, 0x00, 0xC0, 0x4F, 0xC2, 0x97, 0xEB,
    ];
    bytes.len() >= 20 && bytes[4..20] == GUID_LE
}

#[cfg(test)]
mod tests {
    use super::*;

    // DPAPI seal -> detect -> unseal round-trips to the same seed on the CURRENT account.
    #[test]
    fn dpapi_seal_unseal_roundtrip_and_detection() {
        let seed = [7u8; 32];
        let blob = dpapi_seal(&seed).expect("CryptProtectData");
        assert!(looks_sealed(&blob), "a real DPAPI blob must be detected as sealed");
        assert!(!looks_sealed(b"0011223344556677001122334455667700112233445566770011223344556677"),
            "a 64-char plaintext-hex seed must NOT look sealed");
        assert_eq!(dpapi_unseal(&blob).expect("CryptUnprotectData"), seed, "unseal recovers the seed");
    }
}
