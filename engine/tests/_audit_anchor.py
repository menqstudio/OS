"""Test helper: stand in for the OWNER who provisions audit-head anchor custody.

``bro_audit_log.append`` attaches an Ed25519-signed head anchor and every keyed
``verify()`` requires one. The engine holds no private key and no seed is compiled
in: the signature comes from a command named by ``BRO_AUDIT_ANCHOR_SIGNER`` that
lives outside the engine and signs with ``BRO_AUDIT_ANCHOR_KEY_ID``, whose registry
entry must carry the dedicated ``audit-anchor`` authority - the only one
``bro_audit_log.ANCHOR_AUTHORITIES`` accepts. In production
that command is the owner's, under separate custody. In tests this helper plays
that role: it mints ephemeral keys, writes an operator-signed trusted-key registry,
and drops a signing SCRIPT into the test's temp directory (outside the engine, so
the runtime's own "the signer must not live inside this engine" refusal is
satisfied honestly rather than bypassed).

The script also implements the anti-rollback the runtime REQUIRES of a real signer:
it remembers the highest count it has signed for a ledger and refuses to sign a
lower one, so tests can prove the rollback path as well as the happy path.

Not a test module (no ``test_`` prefix), so unittest discovery ignores it.
"""
import json
import pathlib
import sys
import tempfile
import time
from unittest.mock import patch

import bro_signature
from broctl import build_registry, generate_key

# append() anchors with the real clock (an operator reading the ledger wants the
# real issue time), so the ephemeral registry's validity window must cover NOW —
# a fixed historical epoch would make every key "expired" against wall time.
NOW = int(time.time())
YEAR = 365 * 24 * 60 * 60
# The registry the runtime verifies against carries all three on purpose. `audit-anchor`
# is the only one `bro_audit_log.ANCHOR_AUTHORITIES` accepts and is what the signing
# script holds; `operator-root` signs the registry itself; `evidence-recorder` is kept
# precisely so tests can present a VALID signature from a key the ledger's writer would
# hold on a self-provisioned deployment and prove the anchor check refuses it by
# authority. Dropping it would delete the negative that closes O-2.
ANCHOR_AUTHORITY = "audit-anchor"
AUTHORITIES = ("operator-root", "evidence-recorder", ANCHOR_AUTHORITY)

# The owner's signing command, as a standalone script. It reads one canonical
# audit-head payload on stdin and writes {"payload": ..., "signature": ...} on
# stdout, signing the bytes it was given and nothing else.
_SIGNER_SOURCE = '''\
import json
import pathlib
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PRIVATE_KEY_HEX = {private!r}
FLOOR_PATH = pathlib.Path({floor!r})
REFUSE_ALL = {refuse_all!r}
SIGN_DIFFERENT_PAYLOAD = {sign_different!r}

payload = json.loads(sys.stdin.read())

if REFUSE_ALL:
    sys.stderr.write("signer refuses: standing in for a signer under separate custody")
    raise SystemExit(3)

# Anti-rollback, which the runtime requires of a real signer: never sign a head
# describing fewer records than one already signed for this ledger.
floor = {{}}
if FLOOR_PATH.exists():
    floor = json.loads(FLOOR_PATH.read_text(encoding="utf-8"))
ledger = payload.get("ledger")
if int(payload.get("count", -1)) < int(floor.get(ledger, -1)):
    sys.stderr.write("signer refuses: audit-head count is below one already signed")
    raise SystemExit(4)
floor[ledger] = max(int(payload.get("count", 0)), int(floor.get(ledger, 0)))
FLOOR_PATH.write_text(json.dumps(floor), encoding="utf-8")

if SIGN_DIFFERENT_PAYLOAD:
    payload = dict(payload, count=0, last_hash="0" * 64)

canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")
signature = Ed25519PrivateKey.from_private_bytes(
    bytes.fromhex(PRIVATE_KEY_HEX)).sign(canonical).hex()
json.dump({{"payload": payload, "signature": signature}}, sys.stdout)
'''


class AnchorCustody:
    """Handle on the provisioned custody: the registry the runtime verifies against,
    the key id it signs with, and the env the owner would have exported."""

    def __init__(self, keys, trusted, key_id, env, signer_dir):
        self.keys = keys
        self.trusted = trusted
        self.key_id = key_id
        self.env = env
        self.signer_dir = signer_dir

    def sign(self, authority, payload):
        """Sign a payload directly, for tests that need a hand-made document."""
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        canonical = bro_signature.canonical_bytes(payload)
        private = Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(self.keys[authority]["private_key"]))
        return {"payload": payload, "signature": private.sign(canonical).hex()}


def _write_signer(directory: pathlib.Path, private_key_hex: str, *,
                  refuse_all: bool = False, sign_different: bool = False) -> pathlib.Path:
    script = directory / ("signer_refuse.py" if refuse_all else
                          "signer_lying.py" if sign_different else "signer.py")
    script.write_text(_SIGNER_SOURCE.format(
        private=private_key_hex,
        floor=str(directory / "signed-floor.json"),
        refuse_all=refuse_all,
        sign_different=sign_different,
    ), encoding="utf-8")
    return script


def provision(test_case, *, authority=ANCHOR_AUTHORITY) -> AnchorCustody:
    """Provision anchor custody for the lifetime of ``test_case``.

    Patches ``bro_signature.load_trusted_keys`` to the ephemeral registry (the
    runtime imports it lazily, so the patch is seen at call time) and exports the
    two custody variables the owner would set. Everything is torn down on cleanup.
    """
    # Deliberately NOT under the engine: the runtime refuses a signing command that
    # lives inside the repository, and this helper must satisfy that, not dodge it.
    home = pathlib.Path(tempfile.mkdtemp(prefix="bro-anchor-custody-"))
    import shutil
    test_case.addCleanup(shutil.rmtree, home, ignore_errors=True)

    keys = {a: generate_key(a, f"dev-{a}", False) for a in AUTHORITIES}
    registry_root = home / "registry"
    (registry_root / "config").mkdir(parents=True)
    (registry_root / "config" / "trusted-keys.json").write_text(
        json.dumps(build_registry(list(keys.values()), NOW - 3600, YEAR)), encoding="utf-8")
    pin = keys["operator-root"]["public_key"]
    trusted = bro_signature.load_trusted_keys(registry_root, operator_public_key=pin)

    signer = _write_signer(home, keys[authority]["private_key"])
    env = {
        "BRO_AUDIT_ANCHOR_SIGNER": json.dumps([sys.executable, str(signer)]),
        "BRO_AUDIT_ANCHOR_KEY_ID": keys[authority]["key_id"],
    }
    env_patch = patch.dict("os.environ", env)
    env_patch.start()
    test_case.addCleanup(env_patch.stop)

    keys_patch = patch.object(bro_signature, "load_trusted_keys",
                              lambda *a, **k: trusted)
    keys_patch.start()
    test_case.addCleanup(keys_patch.stop)

    return AnchorCustody(keys, trusted, keys[authority]["key_id"], env, home)


def use_variant_signer(test_case, custody: AnchorCustody, *, refuse_all=False,
                       sign_different=False, authority=ANCHOR_AUTHORITY):
    """Point ``BRO_AUDIT_ANCHOR_SIGNER`` at a misbehaving signer for one test."""
    script = _write_signer(custody.signer_dir, custody.keys[authority]["private_key"],
                           refuse_all=refuse_all, sign_different=sign_different)
    patcher = patch.dict("os.environ", {
        "BRO_AUDIT_ANCHOR_SIGNER": json.dumps([sys.executable, str(script)])})
    patcher.start()
    test_case.addCleanup(patcher.stop)


def without_custody(test_case):
    """Remove the two custody variables for the lifetime of ``test_case``."""
    import os
    patcher = patch.dict("os.environ", {})
    patcher.start()
    test_case.addCleanup(patcher.stop)
    os.environ.pop("BRO_AUDIT_ANCHOR_SIGNER", None)
    os.environ.pop("BRO_AUDIT_ANCHOR_KEY_ID", None)
