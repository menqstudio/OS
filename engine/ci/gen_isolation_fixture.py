"""Wave 3b-1 — generate the fixture the Linux isolation-proof job provisions (audit P0-1).

Writes, under the base dir passed as argv[1]:
  signerkeys/brops-receipt-signer.json      — the receipt-signing private key (owner-only)
  attkeys/brops-supervisor-attestation.json — the supervisor-attestation private key
  att-pub                                   — the attestation PUBLIC key (hex)
  registry/config/trusted-keys.json         — a signed trusted-key registry
  operator-pin                              — the operator-root public key (hex) for the pin

Run as the CI (login) user BEFORE ownership is tightened; the shell script then chowns the
private-key dirs to the service principals so the login user can no longer read them.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runtime"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from broctl import build_registry, generate_key


def _raw():
    p = Ed25519PrivateKey.generate()
    priv = p.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    ).hex()
    pub = p.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()
    return priv, pub


def main(base: str) -> int:
    root = pathlib.Path(base)
    sig_priv, _ = _raw()
    att_priv, att_pub = _raw()
    (root / "signerkeys" / "brops-receipt-signer.json").write_text(
        json.dumps({"key_id": "rk", "private_key": sig_priv})
    )
    (root / "attkeys" / "brops-supervisor-attestation.json").write_text(
        json.dumps({"key_id": "sup-att-1", "private_key": att_priv})
    )
    (root / "att-pub").write_text(att_pub)

    # A signed registry so the supervisor service can start (load_trusted_keys).
    keys = [generate_key(a, f"dev-{a}", False) for a in ("operator-root", "issuer", "evidence-recorder")]
    (root / "registry" / "config" / "trusted-keys.json").write_text(
        json.dumps(build_registry(keys, 1, 10_000_000_000))
    )
    operator_pub = next(k for k in keys if k["authority_type"] == "operator-root")["public_key"]
    (root / "operator-pin").write_text(operator_pub)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
