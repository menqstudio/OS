"""Ed25519 key + signature helpers for the LIVE governed-turn kit (Wave 3b).

Thin wrappers over ``cryptography``'s Ed25519 (the pinned engine CI dependency) with the EXACT transport
encodings the Rust broker + the three Python services agree on:

  * ``sign_b64url`` / ``verify_b64url`` — base64url WITHOUT padding, the §4.1/§4.2 ``*_b64`` convention the
    Rust broker decodes with ``URL_SAFE_NO_PAD`` (the isolated-signer envelope signature, the supervisor
    attestation signature, and the challenge signature all use this).
  * ``sign_b64std`` — standard base64 WITH padding, the encoding ``key_manifest::verify_manifest`` decodes
    the root manifest signature with (``base64::STANDARD``).

Private keys never leave the process that owns them; only public keys (hex) + detached signatures cross a
boundary. Raw 32-byte key material is the interchange form (``public_key_hex`` is ``pub_raw().hex()``, which
``key_manifest.rs`` / ``governed_verification.rs`` decode to the raw 32-byte Ed25519 verifying key).
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def gen_private() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def priv_raw(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )


def pub_raw(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def pub_hex(key: Ed25519PrivateKey) -> str:
    return pub_raw(key).hex()


def load_private(raw: bytes) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(raw)


def load_public_hex(hex_str: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(hex_str))


def _unb64url(sig_b64: str) -> bytes:
    pad = "=" * (-len(sig_b64) % 4)
    return base64.urlsafe_b64decode(sig_b64 + pad)


def sign_b64url(priv: Ed25519PrivateKey, message: bytes) -> str:
    """base64url WITHOUT padding of the 64-byte Ed25519 signature (URL_SAFE_NO_PAD)."""
    return base64.urlsafe_b64encode(priv.sign(message)).rstrip(b"=").decode("ascii")


def sign_b64std(priv: Ed25519PrivateKey, message: bytes) -> str:
    """standard base64 WITH padding (base64::STANDARD) — the root manifest signature encoding."""
    return base64.b64encode(priv.sign(message)).decode("ascii")


def verify_b64url(pub: Ed25519PublicKey, message: bytes, sig_b64: str) -> bool:
    """True iff the base64url-nopad signature verifies; never raises on a bad signature (fail-closed)."""
    try:
        pub.verify(_unb64url(sig_b64), message)
        return True
    except Exception:
        return False
