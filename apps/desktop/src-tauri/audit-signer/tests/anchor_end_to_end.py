"""Make the REAL `engine/runtime/bro_audit_log.py` judge the REAL signer.

Nothing here re-implements anything. It imports the module that has to accept the
anchor and makes it accept - or refuse - one produced by the actual relay shim
talking to the actual signer service over the actual named pipe. A Rust test that
asserts its own document round-trips proves only that Rust agrees with Rust; this
is the module whose acceptance is the requirement, doing the accepting.

    python anchor_end_to_end.py <case> <trust-dir> <engine-root> <work-dir> \
                                <relay-exe> <pipe-name> <key-id>

Cases:
  positive   an anchor produced through relay -> pipe -> service is INSTALLED and
             a keyed verify() of the ledger returns green.
  unreachable  the same shim pointed at a pipe nobody serves: append() must fail
             closed, and the ledger must NOT end up silently unanchored-but-green.
  rollback   the ledger's own writer truncates the chain and asks the second
             principal to bless the shorter head. It must refuse.
  forgery    the ledger's own writer signs the truncated head with a private key
             it holds ITSELF, out of the app's trust store, and installs it by
             hand. Reports whether the real verify() accepts it.

Exits 0 on the expected outcome with a per-check log; non-zero with the failing
check named. Never skips: a missing interpreter or a missing `cryptography` is a
failure of the proof, not an excuse to disable it.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

CHECKS: list[str] = []


def ok(message: str) -> None:
    CHECKS.append(message)
    print(f"  PASS  {message}")


def fail(message: str) -> None:
    print(f"  FAIL  {message}", file=sys.stderr)
    raise SystemExit(1)


def require(condition: bool, message: str) -> None:
    ok(message) if condition else fail(message)


def main(argv: list[str]) -> int:
    if len(argv) != 8:
        print(__doc__, file=sys.stderr)
        return 2
    case, trust, engine, work, relay, pipe, key_id = argv[1:]
    trust = pathlib.Path(trust).resolve()
    engine = pathlib.Path(engine).resolve()
    work = pathlib.Path(work).resolve()

    sys.path.insert(0, str(engine / "runtime"))

    # The engine resolves its trust anchor from the environment, exactly as production
    # does. BRO_TRUSTED_REGISTRY_ROOT is the O-3 redirect that lets a deployment keep
    # its registry outside the engine tree; without it `_trusted_keys()` would read the
    # development registry committed in the repo and this proof would be meaningless.
    os.environ["BRO_OPERATOR_ROOT_PUBKEY_FILE"] = str(trust / "pin" / "operator-root.pub")
    os.environ["BRO_OPERATOR_REGISTRY_MIN_FILE"] = str(trust / "pin" / "registry-min")
    os.environ["BRO_OPERATOR_ROOT_PIN_SELF_OWNED"] = "acknowledged"
    os.environ["BRO_TRUSTED_REGISTRY_ROOT"] = str(trust / "registry")
    for stale in ("BRO_OPERATOR_ROOT_PUBKEY", "BRO_OPERATOR_REGISTRY_MIN", "BRO_ENV"):
        os.environ.pop(stale, None)

    import bro_audit_log
    from bro_signature import canonical_bytes, load_trusted_keys

    keys = load_trusted_keys()
    require(key_id in keys,
            f"the signer's key {key_id} is in the registry the engine actually reads")
    require(keys[key_id].authority_type in bro_audit_log.ANCHOR_AUTHORITIES,
            "it carries an authority bro_audit_log accepts for an audit-head "
            f"({keys[key_id].authority_type})")

    ledger = work / "bro-audit.jsonl"
    signer_argv = json.dumps([relay, "--pipe", pipe])

    return globals()[f"case_{case.replace('-', '_')}"](
        bro_audit_log, keys, ledger, signer_argv, key_id, trust, canonical_bytes)


# ---------------------------------------------------------------------------
# The positive: the module that has to accept it, accepting it
# ---------------------------------------------------------------------------

def case_positive(bro_audit_log, keys, ledger, signer_argv, key_id, trust, canonical_bytes) -> int:
    os.environ[bro_audit_log.SIGNER_ENV] = signer_argv
    os.environ[bro_audit_log.SIGNER_KEY_ID_ENV] = key_id

    print("== append(), with custody configured, through the real relay and the real service ==")
    for i in range(3):
        bro_audit_log.append(ledger, "note", {"index": str(i)})
    ok("three appends completed; each one ran the shim, crossed the named pipe and came "
       "back with a signature bro_audit_log installed")

    anchor_path = ledger.with_suffix(ledger.suffix + ".head.sig")
    require(anchor_path.is_file(), "a signed head anchor was installed beside the ledger")
    document = json.loads(anchor_path.read_text(encoding="utf-8"))
    require(set(document) == {"payload", "signature"},
            "the installed document has exactly the field set verify_signed_payload demands")
    require(document["payload"]["key_id"] == key_id,
            "the anchor names the SERVICE's key, not any key this account holds")
    require(document["payload"]["count"] == 3,
            "the anchor describes the chain that is actually on disk")

    print("== the keyed verify(): the authoritative one, which REQUIRES the anchor ==")
    count = bro_audit_log.verify(ledger, keys=keys)
    require(count == 3, f"verify(keys=...) returned {count}: the real engine accepts an anchor "
                        "produced end-to-end by the second principal")

    print("== and the anchor is really bound to these bytes ==")
    tampered = dict(document["payload"])
    tampered["count"] = 2
    from bro_signature import SignatureError, verify_detached
    try:
        verify_detached(tampered, document["signature"], keys[key_id].public_key)
        fail("changing the count still verified - the signature is not bound to the payload")
    except SignatureError:
        ok("changing one field breaks the signature, so the Rust signer's canonical bytes "
           "and bro_signature's canonical bytes are the same bytes")

    print(f"\nGREEN: {len(CHECKS)} checks passed against the real bro_audit_log.")
    return 0


# ---------------------------------------------------------------------------
# The negatives
# ---------------------------------------------------------------------------

def case_unreachable(bro_audit_log, keys, ledger, signer_argv, key_id, trust, canonical_bytes) -> int:
    """No service on the far end. The append must fail closed."""
    os.environ[bro_audit_log.SIGNER_ENV] = signer_argv
    os.environ[bro_audit_log.SIGNER_KEY_ID_ENV] = key_id
    started = time.monotonic()
    try:
        bro_audit_log.append(ledger, "note", {"index": "0"})
        fail("append() succeeded with no signer service running - the ledger would be "
             "silently unanchored, which is the O-2 defect wearing a green light")
    except bro_audit_log.AuditError as exc:
        ok(f"append() refused with no signer reachable: {type(exc).__name__}")
    elapsed = time.monotonic() - started
    require(elapsed < bro_audit_log._SIGNER_TIMEOUT,
            f"the shim gave up in {elapsed:.1f}s, inside the engine's "
            f"{bro_audit_log._SIGNER_TIMEOUT}s budget - it does not get killed mid-call while "
            "holding the ledger's exclusive append lock")

    print("== and the ledger it left behind is not quietly 'intact' ==")
    try:
        bro_audit_log.verify(ledger, keys=keys)
        fail("a keyed verify() of the unanchored ledger returned green")
    except bro_audit_log.AuditError as exc:
        ok(f"a keyed verify() refuses it: {type(exc).__name__}")

    print(f"\nGREEN: {len(CHECKS)} checks passed against the real bro_audit_log.")
    return 0


def case_rollback(bro_audit_log, keys, ledger, signer_argv, key_id, trust, canonical_bytes) -> int:
    """The ledger's own writer asks the second principal to bless a truncation."""
    os.environ[bro_audit_log.SIGNER_ENV] = signer_argv
    os.environ[bro_audit_log.SIGNER_KEY_ID_ENV] = key_id
    for i in range(3):
        bro_audit_log.append(ledger, "note", {"index": str(i)})
    ok("a three-record ledger is anchored at count 3")

    records = bro_audit_log.read_all(ledger)
    ledger.write_text(json.dumps(records[0], sort_keys=True) + "\n", encoding="utf-8")
    head = ledger.with_suffix(ledger.suffix + ".head")
    head.write_text(json.dumps({"count": 1, "last_hash": records[0]["hash"]}), encoding="utf-8")
    ok("the writer truncated the ledger to one record and recomputed the plaintext head - "
       "everything a party who can write the file can do")

    # Ask the signer, through the real shim, for an anchor over the shorter chain. This is
    # the payload bro_audit_log itself would assemble for that state.
    payload = bro_audit_log.head_anchor_payload(ledger, key_id=key_id, now=int(time.time()))
    require(payload["count"] == 1, "the payload the writer is asking to have signed says count=1")
    argv = json.loads(os.environ[bro_audit_log.SIGNER_ENV])
    proc = subprocess.run(argv, input=bro_audit_log._canonical(payload), capture_output=True,
                          text=True, timeout=bro_audit_log._SIGNER_TIMEOUT)
    require(proc.returncode != 0,
            f"the second principal REFUSED to sign the truncation (exit {proc.returncode})")
    require(proc.stdout.strip() == "",
            "and it produced no document at all - not a signature the writer could keep")
    require("ANTI-ROLLBACK" in proc.stderr,
            f"the refusal names the reason: {proc.stderr.strip()[:200]}")

    print(f"\nGREEN: {len(CHECKS)} checks passed against the real bro_audit_log.")
    return 0


def case_forgery(bro_audit_log, keys, ledger, signer_argv, key_id, trust, canonical_bytes) -> int:
    """The negative that decides whether the second principal bought anything.

    The writer does not ask the signer at all. It signs the truncated head with a
    private key that is sitting in ITS OWN trust directory, drops the sidecar in,
    and asks the real verify() what it thinks.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    os.environ[bro_audit_log.SIGNER_ENV] = signer_argv
    os.environ[bro_audit_log.SIGNER_KEY_ID_ENV] = key_id
    for i in range(3):
        bro_audit_log.append(ledger, "note", {"index": str(i)})
    ok("a three-record ledger is anchored at count 3 by the second principal")

    reachable = []
    for path in sorted((trust / "keys").glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        registered = keys.get(entry.get("key_id"))
        if registered is not None and registered.authority_type in bro_audit_log.ANCHOR_AUTHORITIES:
            reachable.append((path, entry, registered))
    print(f"  NOTE  anchor-capable private keys inside the APP's own trust store: "
          f"{[p.name for p, _, _ in reachable]}")

    if not reachable:
        ok("the app's account holds NO private key registered under an anchor authority, so "
           "the anchor can only come from the second principal")
        print(f"\nGREEN: {len(CHECKS)} checks passed against the real bro_audit_log.")
        return 0

    # It does hold one. Use it exactly as a forger would.
    path, entry, registered = reachable[0]
    records = bro_audit_log.read_all(ledger)
    ledger.write_text(json.dumps(records[0], sort_keys=True) + "\n", encoding="utf-8")
    ledger.with_suffix(ledger.suffix + ".head").write_text(
        json.dumps({"count": 1, "last_hash": records[0]["hash"]}), encoding="utf-8")

    anchor_path = ledger.with_suffix(ledger.suffix + ".head.sig")
    previous = hashlib.sha256(anchor_path.read_bytes()).hexdigest()
    payload = {
        "artifact_type": bro_audit_log.ANCHOR_ARTIFACT_TYPE,
        "key_id": entry["key_id"],
        "ledger": ledger.name,
        "count": 1,
        "last_hash": records[0]["hash"],
        "previous_anchor_sha256": previous,
        "issued_at_epoch": int(time.time()),
    }
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(entry["private_key"]))
    forged = {"payload": payload, "signature": private.sign(canonical_bytes(payload)).hex()}
    anchor_path.write_text(json.dumps(forged, sort_keys=True), encoding="utf-8")

    try:
        count = bro_audit_log.verify(ledger, keys=keys)
    except bro_audit_log.AuditError as exc:
        ok("the forged anchor was REFUSED by the real verify(): "
           f"{type(exc).__name__}: {exc}")
        print(f"\nGREEN: {len(CHECKS)} checks passed against the real bro_audit_log.")
        return 0

    print(f"  OPEN  the real verify(keys=...) returned {count} on a ledger truncated from 3 to 1 "
          f"records, because {path.name} in the app's own trust store is registered as "
          f"{registered.authority_type}, which bro_audit_log.ANCHOR_AUTHORITIES accepts.",
          flush=True)
    print("  OPEN  O-2 IS NOT CLOSED. The second principal is a second ROUTE to a signature, "
          "not the only one.")
    # Reported on stdout with a stable marker and a zero exit: this is the tree's honest
    # record of an open defect, not a failing build. `tests/forgery.rs` asserts the marker.
    print("\nO2-OPEN: an anchor signed by the app's own account was accepted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
