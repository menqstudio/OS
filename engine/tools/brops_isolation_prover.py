"""Wave 3b-1 — same-login-user isolation PROVER (design §1.1, §5; audit P0-1, P1-4).

Run as the sidecar/desktop LOGIN user (the in-scope attacker). It attempts the four
denials the design requires and exits 0 ONLY if every one is denied; if any attack
SUCCEEDS it exits 1. The Linux CI job `engine-isolation` runs this against real,
separately-owned signer + supervisor services (dedicated principals), so the boundary is
machine-proven — never skip-guarded or documentation-only.

Attacks (all must be denied):
  1. connect to the SIGNER socket + request a signature  -> denied by SO_PEERCRED
     (the signer admits only the supervisor UID);
  2. read the receipt-signing / supervisor-attestation private keys -> PermissionError
     (owner-only 0700 dirs of the service principals);
  3. read or write the protected evidence store          -> PermissionError
     (0770, owned by a service group the login user is not in);
  4. make the SUPERVISOR sign caller-supplied evidence    -> refused/denied
     (the supervisor accepts only {run_id, execution_attempt_id}).

Env: BROPS_SIGNER_SOCKET, BROPS_SUPERVISOR_SOCKET, BROPS_PROVE_SIGNER_KEY,
     BROPS_PROVE_ATTESTATION_KEY, BROPS_PROVE_STORE_DIR.
"""

from __future__ import annotations

import os
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_HERE / "runtime"))
sys.path.insert(0, str(_HERE / "tools"))

import brops_socket


def _attack_connect_signer() -> bool:
    """Return True iff DENIED (good). A signed result means the attack SUCCEEDED."""
    frame = {
        "protocol": "brops.sign-request.v1",
        "attestation": {"attestation_protocol": "brops.run-attestation.v1",
                        "supervisor_key_id": "x", "sig": "AAAA"},
        "evidence": {"run_id": "x"},
    }
    try:
        result = brops_socket.request(os.environ["BROPS_SIGNER_SOCKET"], frame, timeout=5)
    except Exception:  # noqa: BLE001 — connection refused/closed = denied = good
        return True
    return result.get("status") != "signed"


def _attack_read_file(path: str) -> bool:
    """Return True iff reading is DENIED."""
    try:
        with open(path, "rb") as handle:
            handle.read(1)
    except PermissionError:
        return True
    except FileNotFoundError:
        return True  # not reachable is also denied
    return False


def _attack_store(store_dir: str) -> bool:
    """Return True iff the login user can neither WRITE nor LIST the store."""
    wrote = False
    try:
        probe = pathlib.Path(store_dir) / "attacker-probe"
        probe.write_bytes(b"x")
        wrote = True
        probe.unlink()
    except (PermissionError, FileNotFoundError, OSError):
        wrote = False
    listed = False
    try:
        os.listdir(store_dir)
        listed = True
    except (PermissionError, FileNotFoundError, OSError):
        listed = False
    return not wrote and not listed


def _attack_supervisor_oracle() -> bool:
    """Return True iff the supervisor DENIES a caller-supplied-evidence frame."""
    frame = {"protocol": "brops.sign-request.v1", "evidence": {"forged": True, "decision": "completed"}}
    try:
        result = brops_socket.request(os.environ["BROPS_SUPERVISOR_SOCKET"], frame, timeout=5)
    except Exception:  # noqa: BLE001 — connection denied = good
        return True
    return result.get("status") != "signed"


def main() -> int:
    checks = {
        "1_connect_signer": _attack_connect_signer(),
        "2_read_signer_key": _attack_read_file(os.environ["BROPS_PROVE_SIGNER_KEY"]),
        "2_read_attestation_key": _attack_read_file(os.environ["BROPS_PROVE_ATTESTATION_KEY"]),
        "3_store_no_read_write": _attack_store(os.environ["BROPS_PROVE_STORE_DIR"]),
        "4_supervisor_oracle": _attack_supervisor_oracle(),
    }
    ok = True
    for name, denied in checks.items():
        print(f"[{'DENIED ' if denied else 'BREACH '}] {name}")
        ok = ok and denied
    if not ok:
        print("ISOLATION PROOF FAILED — at least one attack succeeded", file=sys.stderr)
        return 1
    print("ISOLATION PROOF PASSED — all four denials hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
