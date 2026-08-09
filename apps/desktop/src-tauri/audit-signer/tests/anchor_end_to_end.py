"""Make the REAL `engine/runtime/bro_audit_log.py` judge the REAL signer.

Nothing here re-implements anything. It imports the module that has to accept the
anchor and makes it accept - or refuse - one produced by the actual relay shim
talking to the actual signer service over the actual named pipe. A Rust test that
asserts its own document round-trips proves only that Rust agrees with Rust; this
is the module whose acceptance is the requirement, doing the accepting.

    python anchor_end_to_end.py <case> <trust-dir> <engine-root> <work-dir> \
                                <relay-exe> <pipe-name> <key-id> <rust-anchor-authorities>

Cases:
  positive   an anchor produced through relay -> pipe -> service is INSTALLED and
             a keyed verify() of the ledger returns green.
  unreachable  the same shim pointed at a pipe nobody serves: append() must fail
             closed, and the ledger must NOT end up silently unanchored-but-green.
  rollback   the ledger's own writer truncates the chain and asks the second
             principal to bless the shorter head. It must refuse.
  forgery    the ledger's own writer signs the truncated head with EVERY private key
             it holds ITSELF, out of the app's trust store, and installs each by hand.
             The real verify() must REFUSE every one of them, naming the authority.
  registry-resign  the residual route, run for real: the app re-signs the trusted-key
             registry with the operator-root private half provision() leaves it,
             introduces an audit-anchor key of its own, and anchors the truncation
             with that. Reports what the real verify() does.

The last argument is `brops_provision::audit_signer::ANCHOR_AUTHORITIES`, comma
separated. It is a mirror of a hardcoded Python tuple, so every case asserts the two
are identical before doing anything else - a mirror that can drift silently is a
second source of truth.

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
    if len(argv) != 9:
        print(__doc__, file=sys.stderr)
        return 2
    case, trust, engine, work, relay, pipe, key_id, rust_authorities = argv[1:]
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

    print("== the two hardcoded anchor-authority lists are the same list ==")
    require(tuple(rust_authorities.split(",")) == bro_audit_log.ANCHOR_AUTHORITIES,
            f"brops_provision::audit_signer::ANCHOR_AUTHORITIES ({rust_authorities}) is "
            f"exactly bro_audit_log.ANCHOR_AUTHORITIES ({bro_audit_log.ANCHOR_AUTHORITIES})")
    require(bro_audit_log.ANCHOR_AUTHORITIES == ("audit-anchor",),
            "the ONE authority that may anchor is the dedicated audit-anchor type - not "
            "evidence-recorder and not operator-root, both of which the app holds")

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


def _forge_anchor(bro_audit_log, ledger, private_key_hex, key_id, canonical_bytes, *, count=1):
    """Truncate the ledger to `count` records and install a self-signed head for it.

    Everything a party who can write the ledger file can do, and nothing more: the
    records are dropped, the plaintext `.head` that `append()` itself maintains is
    recomputed, and the `.head.sig` sidecar is written directly - which also walks
    straight past `_check_anchor_monotonic`, the install-side rollback check the
    module documents as defence in depth precisely because a writer can do this.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    records = bro_audit_log.read_all(ledger)
    kept = records[:count]
    ledger.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in kept),
                      encoding="utf-8")
    tail = kept[-1]["hash"] if kept else bro_audit_log.GENESIS
    ledger.with_suffix(ledger.suffix + ".head").write_text(
        json.dumps({"count": len(kept), "last_hash": tail}), encoding="utf-8")

    anchor_path = ledger.with_suffix(ledger.suffix + ".head.sig")
    previous = (hashlib.sha256(anchor_path.read_bytes()).hexdigest()
                if anchor_path.exists() else None)
    payload = {
        "artifact_type": bro_audit_log.ANCHOR_ARTIFACT_TYPE,
        "key_id": key_id,
        "ledger": ledger.name,
        "count": len(kept),
        "last_hash": tail,
        "previous_anchor_sha256": previous,
        "issued_at_epoch": int(time.time()),
    }
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    forged = {"payload": payload, "signature": private.sign(canonical_bytes(payload)).hex()}
    anchor_path.write_text(json.dumps(forged, sort_keys=True), encoding="utf-8")
    return payload


def case_forgery(bro_audit_log, keys, ledger, signer_argv, key_id, trust, canonical_bytes) -> int:
    """The negative that decides whether the second principal bought anything.

    The writer does not ask the signer at all. It signs a truncated head with each
    private key sitting in ITS OWN trust directory, drops the sidecar in, and asks the
    real verify() what it thinks. Every one must be refused, and refused for the
    AUTHORITY - not for the chain, which the forger has made self-consistent.

    This case used to end by printing `O2-OPEN` and exiting 0, because two of those keys
    (`evidence-recorder` and `operator-root`) were anchor authorities. They no longer are.
    """
    os.environ[bro_audit_log.SIGNER_ENV] = signer_argv
    os.environ[bro_audit_log.SIGNER_KEY_ID_ENV] = key_id
    for i in range(3):
        bro_audit_log.append(ledger, "note", {"index": str(i)})
    ok("a three-record ledger is anchored at count 3 by the second principal")

    print("== what the app's own account actually holds, enumerated on the filesystem ==")
    held = []
    for path in sorted((trust / "keys").glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry.get("private_key"):
            held.append((path, entry))
    require(bool(held), f"there are minted private halves to enumerate in {trust / 'keys'}")
    print(f"  NOTE  private halves in the APP's own trust store: "
          f"{ {p.name: e['authority_type'] for p, e in held} }")

    anchor_capable = [p.name for p, e in held
                      if e["authority_type"] in bro_audit_log.ANCHOR_AUTHORITIES]
    require(not anchor_capable,
            f"NONE of them carries an authority bro_audit_log accepts for an audit head "
            f"(found {anchor_capable})")
    require(not (trust / "keys" / "audit-anchor.json").exists(),
            "provision() wrote no audit-anchor key file at all - the seed for the one "
            "authority that can anchor is minted by the signer service, under its own account")

    print("== and every one of them is REFUSED when it tries to anchor anyway ==")
    for path, entry in held:
        registered = keys.get(entry["key_id"])
        if registered is None:
            continue  # not in the registry the engine reads; nothing to refuse by authority
        _forge_anchor(bro_audit_log, ledger, entry["private_key"], entry["key_id"],
                      canonical_bytes)
        # The chain, the plaintext head and the anchor all agree with each other, so an
        # unkeyed verify() is happy - which is exactly why the keyed one has to not be.
        require(bro_audit_log.verify(ledger) == 1,
                f"[{path.name}] the truncated ledger is internally self-consistent, so "
                "nothing but the authority can be the reason for a refusal")
        try:
            count = bro_audit_log.verify(ledger, keys=keys)
        except bro_audit_log.AuditError as exc:
            message = str(exc)
            require(f"({registered.authority_type}) may not sign audit-head" in message,
                    f"[{path.name}] REFUSED, naming the authority as the reason: {message}")
            require("audit-anchor" in message,
                    f"[{path.name}] and naming what would be required instead")
            continue
        fail(f"[{path.name}] the real verify(keys=...) returned {count} on a ledger truncated "
             f"from 3 to 1 records, anchored with a {registered.authority_type} private half "
             f"the app itself holds. O-2 IS NOT CLOSED.")

    print("== the honest positive control: the service's key still anchors ==")
    # A negative suite with no positive control cannot tell "the authority check works"
    # from "everything is refused now". A FRESH ledger name, because the signer's own
    # anti-rollback floor is keyed by ledger name and it has already signed count 3 for
    # the one above - which is the property `case_rollback` proves, not this one.
    control = ledger.with_name("positive-control.jsonl")
    bro_audit_log.append(control, "note", {"index": "after"})
    require(bro_audit_log.verify(control, keys=keys) == 1,
            "an anchor from the signer service is still accepted, so the refusals above "
            "are about WHO signed and not about the check being broken")

    print(f"\nGREEN: {len(CHECKS)} checks passed against the real bro_audit_log.")
    return 0


def case_registry_resign(bro_audit_log, keys, ledger, signer_argv, key_id, trust,
                         canonical_bytes) -> int:
    """The route narrowing the authority does NOT close, run for real rather than argued.

    `verify_signed_payload` resolves the anchor's key through
    `bro_signature.load_trusted_keys`, i.e. through the operator-signed trusted-key
    registry. `provision()` leaves the `operator-root` PRIVATE half in the app's own trust
    directory, and that key is what the registry is signed with. So the app can mint a
    keypair, register it under `audit-anchor`, re-sign the registry, raise the
    anti-rollback floor it also owns, and anchor whatever head it likes.

    Nothing in `bro_audit_log` can reach this: the module's trust root is the registry, and
    on a self-provisioned deployment the registry's signer is the ledger's writer. It is
    closed only by an operator root the app does not hold.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from bro_signature import load_trusted_keys

    os.environ[bro_audit_log.SIGNER_ENV] = signer_argv
    os.environ[bro_audit_log.SIGNER_KEY_ID_ENV] = key_id
    for i in range(3):
        bro_audit_log.append(ledger, "note", {"index": str(i)})
    ok("a three-record ledger is anchored at count 3 by the second principal")

    operator_file = trust / "keys" / "operator-root.json"
    require(operator_file.is_file(),
            "provision() left the operator-root PRIVATE half in the app's own trust store")
    operator = json.loads(operator_file.read_text(encoding="utf-8"))
    require(bool(operator.get("private_key")),
            "and it really is the private half, not a published record")

    # Mint the attacker's own anchor key and register it, exactly as register_anchor_key
    # does for the service - with the app's own operator root doing the signing.
    rogue = Ed25519PrivateKey.generate()
    rogue_public = rogue.public_key().public_bytes_raw().hex()
    rogue_id = "audit-anchor-rogue"

    registry_path = trust / "registry" / "config" / "trusted-keys.json"
    document = json.loads(registry_path.read_text(encoding="utf-8"))
    payload = document["payload"]
    payload["registry_version"] = int(payload.get("registry_version", 1)) + 1
    payload["keys"] = sorted(payload["keys"] + [{
        "key_id": rogue_id,
        "public_key": rogue_public,
        "authority_type": "audit-anchor",
        "allowed_artifact_types": [],
        "not_before_epoch": 0,
        "not_after_epoch": 253_402_300_799,
        "status": "active",
        "issued_by": operator["key_id"],
    }], key=lambda e: e["key_id"])
    signer = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(operator["private_key"]))
    registry_path.write_text(json.dumps(
        {"payload": payload, "signature": signer.sign(canonical_bytes(payload)).hex()},
        sort_keys=True), encoding="utf-8")
    # The anti-rollback floor is a file in the app's own trust store too.
    (trust / "pin" / "registry-min").write_text(
        f"{payload['registry_version']}\n", encoding="utf-8")
    ok("the app re-signed the trusted-key registry with the operator root it holds, adding "
       "an audit-anchor key of its own, and raised the anti-rollback floor to match")

    reloaded = load_trusted_keys()
    require(rogue_id in reloaded,
            "the engine's own load_trusted_keys accepts the re-signed registry - external "
            "pin, production binding, rollback floor and all")
    require(reloaded[rogue_id].authority_type == "audit-anchor",
            "and resolves the rogue key under the one authority that may anchor")

    _forge_anchor(bro_audit_log, ledger, rogue.private_bytes_raw().hex(), rogue_id,
                  canonical_bytes)
    try:
        count = bro_audit_log.verify(ledger, keys=reloaded)
    except bro_audit_log.AuditError as exc:
        print(f"  NOTE  the real verify() refused it: {type(exc).__name__}: {exc}")
        print("\nO2-RESIDUAL-GONE: re-signing the registry no longer buys an accepted "
              "anchor. Something now binds the anchor key beyond the registry - find it, "
              "and replace this case and its Rust assertion with the inverse.")
        return 0

    print(f"  OPEN  the real verify(keys=...) returned {count} on a ledger truncated from 3 "
          "to 1 records. The anchor was signed by a key the app minted for itself minutes "
          "ago, admitted to the registry by the operator-root private half "
          "brops_provision::provision() wrote into the app's own trust directory.")
    print("  OPEN  Narrowing ANCHOR_AUTHORITIES closed the DIRECT route (a provisioned "
          "anchor-capable key). It cannot close this one: bro_audit_log's trust root is the "
          "registry, and on a self-provisioned deployment the registry's signer IS the "
          "ledger's writer. Closing it needs an operator root the app does not hold.")
    print("\nO2-RESIDUAL-OPERATOR-ROOT: the app re-signed the registry and anchored a "
          "truncation with a key of its own.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
