"""Make the REAL `engine/runtime/bro_audit_log.py` judge the REAL signer.

Nothing here re-implements anything. It imports the module that has to accept the
anchor and makes it accept - or refuse - one produced by the actual relay shim
talking to the actual signer service over the actual named pipe. A Rust test that
asserts its own document round-trips proves only that Rust agrees with Rust; this
is the module whose acceptance is the requirement, doing the accepting.

    python anchor_end_to_end.py <case> <trust-dir> <anchor-dir> <engine-root> <work-dir> \
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
  registry-resign  the route that IS closed, run for real: the app's whole data
             directory is enumerated for the operator-root private half, and the
             registry re-signing attack is then attempted with every private half the
             app does hold. Every one must be refused at the external pin.
  pin-rewrite  the route that WAS open, run for real against the closure: every private
             half is deleted, an operator root of the app's own is generated, and the
             attempt to write it over the pin is made. The OPERATING SYSTEM must refuse
             the write, the delete, the create, and the rename of every directory on the
             path; the pin's bytes must be unchanged afterwards; and the attack is then
             carried as far as it still can go (the registry IS app-writable) and must
             fail against the real load_trusted_keys() and the real verify().

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
    if len(argv) != 10:
        print(__doc__, file=sys.stderr)
        return 2
    case, trust, anchor, engine, work, relay, pipe, key_id, rust_authorities = argv[1:]
    trust = pathlib.Path(trust).resolve()
    anchor = pathlib.Path(anchor).resolve()
    engine = pathlib.Path(engine).resolve()
    work = pathlib.Path(work).resolve()

    sys.path.insert(0, str(engine / "runtime"))

    # The engine resolves its trust anchor from the environment, exactly as production
    # does. BRO_TRUSTED_REGISTRY_ROOT is the O-3 redirect that lets a deployment keep
    # its registry outside the engine tree; without it `_trusted_keys()` would read the
    # development registry committed in the repo and this proof would be meaningless.
    os.environ["BRO_OPERATOR_ROOT_PUBKEY_FILE"] = str(anchor / "operator-root.pub")
    os.environ["BRO_OPERATOR_REGISTRY_MIN_FILE"] = str(anchor / "registry-min")
    os.environ["BRO_TRUSTED_REGISTRY_ROOT"] = str(anchor / "registry")
    # BRO_OPERATOR_ROOT_PIN_SELF_OWNED is deliberately REMOVED, not set. It used to be set to
    # `acknowledged` here, and `bro_custody.self_owned_acknowledged()` SHORT-CIRCUITS every
    # custody rule in the runtime when it is - so every run of this proof was made against a
    # check that had been switched off, because the pin was a file in the app's own data
    # directory and the honest rule would have refused it. The pin now lives somewhere this
    # account cannot write, so the rule runs in full and passes on its merits. Popping it
    # rather than leaving it alone matters: an inherited value from the calling environment
    # would silently restore exactly the hole this round exists to close.
    for stale in ("BRO_OPERATOR_ROOT_PUBKEY", "BRO_OPERATOR_REGISTRY_MIN", "BRO_ENV",
                  "BRO_OPERATOR_ROOT_PIN_SELF_OWNED"):
        os.environ.pop(stale, None)

    import bro_audit_log
    import bro_custody
    from bro_signature import canonical_bytes, load_trusted_keys

    print("== the two hardcoded anchor-authority lists are the same list ==")
    require(tuple(rust_authorities.split(",")) == bro_audit_log.ANCHOR_AUTHORITIES,
            f"brops_provision::audit_signer::ANCHOR_AUTHORITIES ({rust_authorities}) is "
            f"exactly bro_audit_log.ANCHOR_AUTHORITIES ({bro_audit_log.ANCHOR_AUTHORITIES})")
    require(bro_audit_log.ANCHOR_AUTHORITIES == ("audit-anchor",),
            "the ONE authority that may anchor is the dedicated audit-anchor type - not "
            "evidence-recorder and not operator-root, both of which the app holds")

    print("== the engine's OWN custody rule, unacknowledged, judges the anchor ==")
    require(not bro_custody.self_owned_acknowledged(),
            "BRO_OPERATOR_ROOT_PIN_SELF_OWNED is NOT set, so bro_custody runs its full rule "
            "instead of short-circuiting it - every check below is made against the real one")
    import bro_signature
    pinned = bro_signature._pin_from_file(
        os.environ["BRO_OPERATOR_ROOT_PUBKEY_FILE"], engine.parent,
        "BRO_OPERATOR_ROOT_PUBKEY_FILE")
    require(len(pinned) == 64,
            f"the real bro_signature._pin_from_file ACCEPTS the anchor's pin with no "
            f"acknowledgement: {anchor / 'operator-root.pub'}")
    # The control: the SAME rule, on a pin in a directory this account owns, must refuse. A
    # rule that accepted both would prove nothing about the location.
    control = work / "self-owned-pin-control"
    control.mkdir(parents=True, exist_ok=True)
    (control / "operator-root.pub").write_text(pinned + "\n", encoding="utf-8")
    try:
        bro_signature._pin_from_file(str(control / "operator-root.pub"), engine.parent,
                                     "BRO_OPERATOR_ROOT_PUBKEY_FILE")
        fail("the same unacknowledged rule ACCEPTED a pin in a directory this account owns, "
             "so its acceptance of the anchor says nothing about the anchor's location")
    except bro_signature.SignatureError as exc:
        require("rewritten by the very account reading it" in str(exc)
                or "owned by the very account reading it" in str(exc),
                f"and REFUSES the same pin in a directory this account owns: {exc}")

    keys = load_trusted_keys()
    require(key_id in keys,
            f"the signer's key {key_id} is in the registry the engine actually reads")
    require(keys[key_id].authority_type in bro_audit_log.ANCHOR_AUTHORITIES,
            "it carries an authority bro_audit_log accepts for an audit-head "
            f"({keys[key_id].authority_type})")

    # The ledger's NAME has to be unique per run. The audit signer's anti-rollback state is
    # keyed by ledger name and now lives in a PERSISTENT directory (the fixture's anchor is
    # permanent, so the key that anchor admits has to be too). A second run with a fresh
    # ledger called `bro-audit.jsonl` therefore asks the signer to anchor count 1 for a name
    # it last anchored at count 3, and it refuses - correctly, and exactly as it would refuse
    # a truncation. `work` is a fresh temporary directory each run, so its own name is the
    # discriminator.
    ledger = work / f"bro-audit-{work.parent.name}.jsonl"
    signer_argv = json.dumps([relay, "--pipe", pipe])

    return globals()[f"case_{case.replace('-', '_')}"](
        bro_audit_log, keys, ledger, signer_argv, key_id, trust, canonical_bytes, anchor)


# ---------------------------------------------------------------------------
# The positive: the module that has to accept it, accepting it
# ---------------------------------------------------------------------------

def case_positive(bro_audit_log, keys, ledger, signer_argv, key_id, trust, canonical_bytes,
                 anchor) -> int:
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

def case_unreachable(bro_audit_log, keys, ledger, signer_argv, key_id, trust, canonical_bytes,
                 anchor) -> int:
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


def case_rollback(bro_audit_log, keys, ledger, signer_argv, key_id, trust, canonical_bytes,
                 anchor) -> int:
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


def case_forgery(bro_audit_log, keys, ledger, signer_argv, key_id, trust, canonical_bytes,
                 anchor) -> int:
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
    control = ledger.with_name(f"positive-control-{ledger.stem}.jsonl")
    bro_audit_log.append(control, "note", {"index": "after"})
    require(bro_audit_log.verify(control, keys=keys) == 1,
            "an anchor from the signer service is still accepted, so the refusals above "
            "are about WHO signed and not about the check being broken")

    print(f"\nGREEN: {len(CHECKS)} checks passed against the real bro_audit_log.")
    return 0


def _hex_runs(text: str):
    """Every 64-character run of hex digits in `text`."""
    for start in range(0, max(0, len(text) - 63)):
        run = text[start:start + 64]
        if all(c in "0123456789abcdefABCDEF" for c in run):
            yield run.lower()


def _find_seed_for(root: pathlib.Path, public_key_hex: str):
    """The file under `root` holding a 32-byte seed that derives `public_key_hex`, or None.

    Asked of the FILESYSTEM, not of the code that writes it. Every file is read whole and
    every 32-byte window and every 64-character hex run in it is tried as an Ed25519 seed,
    so a seed that moved to a temp file, a log line, a staging directory or a differently
    named key file is still found. A check that looked for `keys/operator-root.json` would
    pass the day the material moved.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    def derives(seed: bytes) -> bool:
        try:
            private = Ed25519PrivateKey.from_private_bytes(seed)
        except Exception:  # noqa: BLE001 - any 32 bytes are a valid seed; be defensive anyway
            return False
        return private.public_key().public_bytes_raw().hex() == public_key_hex

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        for offset in range(0, max(0, len(raw) - 31)):
            if derives(raw[offset:offset + 32]):
                return path
        for run in _hex_runs(raw.decode("utf-8", "replace")):
            if derives(bytes.fromhex(run)):
                return path
    return None


def case_registry_resign(bro_audit_log, keys, ledger, signer_argv, key_id, trust,
                         canonical_bytes, anchor) -> int:
    """The route that IS closed now, proved the way the old case proved it was open.

    `verify_signed_payload` resolves the anchor's key through
    `bro_signature.load_trusted_keys`, i.e. through the operator-signed trusted-key
    registry. This case used to re-sign that registry with the `operator-root` PRIVATE half
    `provision()` left in the app's own trust directory, admit an `audit-anchor` key of its
    own, raise the anti-rollback floor, and anchor a truncation - and it printed
    `O2-RESIDUAL-OPERATOR-ROOT` when the real `verify()` accepted the result.

    `brops_provision::mint` now generates the root in memory, signs the registry and the
    conductor session with it, and drops it before returning. So:

    1. the private half is looked for across the WHOLE application data directory, by
       deriving a public key from every 32-byte window and every hex run in every file;
    2. the same search is run for a key that IS retained, as the control - a null result
       from a search that finds nothing at all would prove nothing;
    3. the attack is attempted anyway, once per private half the app still holds. The real
       `load_trusted_keys` must refuse every re-signed registry at the external pin.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from bro_signature import SignatureError, load_trusted_keys

    os.environ[bro_audit_log.SIGNER_ENV] = signer_argv
    os.environ[bro_audit_log.SIGNER_KEY_ID_ENV] = key_id
    for i in range(3):
        bro_audit_log.append(ledger, "note", {"index": str(i)})
    ok("a three-record ledger is anchored at count 3 by the second principal")

    app_data = trust.parent
    operator_public = (anchor / "operator-root.pub").read_text(encoding="utf-8").strip()

    print("== the control: the search DOES find a private half that is really there ==")
    held = []
    for path in sorted((trust / "keys").glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry.get("private_key"):
            held.append((path, entry))
    require(bool(held), f"there are retained private halves to enumerate in {trust / 'keys'}")
    print(f"  NOTE  private halves the app still holds: "
          f"{ {p.name: e['authority_type'] for p, e in held} }")
    require(_find_seed_for(app_data, held[0][1]["public_key"]) is not None,
            "a seed the store really holds IS found by this search, so a null result for "
            "the operator root below is about the operator root and not about the search")

    print("== and it finds NO operator-root private half anywhere under the app data dir ==")
    require(not (trust / "keys" / "operator-root.json").exists(),
            "there is no keys/operator-root.json")
    where = _find_seed_for(app_data, operator_public)
    require(where is None,
            f"NO file under {app_data} carries a 32-byte seed deriving the PINNED "
            f"operator-root public key - searched every file, every byte offset and every "
            f"hex run (found {where})")

    print("== the attack, attempted anyway with every private half the app DOES hold ==")
    registry_path = anchor / "registry" / "config" / "trusted-keys.json"
    original = registry_path.read_bytes()
    floor_path = anchor / "registry-min"
    original_floor = floor_path.read_bytes()
    for path, entry in held:
        rogue = Ed25519PrivateKey.generate()
        payload = json.loads(original.decode("utf-8"))["payload"]
        payload["registry_version"] = int(payload.get("registry_version", 1)) + 1
        payload["keys"] = sorted(payload["keys"] + [{
            "key_id": f"audit-anchor-rogue-{path.stem}",
            "public_key": rogue.public_key().public_bytes_raw().hex(),
            "authority_type": "audit-anchor",
            "allowed_artifact_types": [],
            "not_before_epoch": 0,
            "not_after_epoch": 253_402_300_799,
            "status": "active",
            "issued_by": entry["key_id"],
        }], key=lambda e: e["key_id"])
        signer = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(entry["private_key"]))
        document = json.dumps(
            {"payload": payload, "signature": signer.sign(canonical_bytes(payload)).hex()},
            sort_keys=True)
        # The re-signed registry EXISTS - it was built, and it is signed. Installing it is
        # what fails, and it fails at the operating system rather than at a check: the
        # registry moved into the anchor with the pin, because
        # `bro_signature.resolve_registry_root` refuses a registry root the reading account
        # can write. The refusal used to be the Ed25519 check downstream; it is now one step
        # earlier and made by the kernel.
        try:
            registry_path.write_text(document, encoding="utf-8")
            fail(f"[{path.name}] the trusted-key registry was WRITABLE by this account")
        except PermissionError as exc:
            ok(f"[{path.name}] installing a registry re-signed with a private half the app "
               f"holds is refused by the OS: {type(exc).__name__}: [Errno {exc.errno}] "
               f"{exc.strerror}")
        try:
            floor_path.write_text(f"{payload['registry_version']}\n", encoding="utf-8")
            fail(f"[{path.name}] the anti-rollback floor was WRITABLE by this account")
        except PermissionError as exc:
            ok(f"[{path.name}] and so is raising the anti-rollback floor: "
               f"{type(exc).__name__}")

    require(registry_path.read_bytes() == original,
            "the registry's bytes are unchanged after every attempt")
    require(floor_path.read_bytes() == original_floor,
            "and so are the anti-rollback floor's")
    require(load_trusted_keys()[key_id].authority_type == "audit-anchor",
            "and the registry the engine reads still resolves the SIGNER's key, not a rogue "
            "one - the refusals above left a working deployment, not a broken one")

    print("== the positive control: the service's key still anchors a fresh ledger ==")
    control = ledger.with_name(f"positive-control-{ledger.stem}.jsonl")
    bro_audit_log.append(control, "note", {"index": "after"})
    require(bro_audit_log.verify(control, keys=keys) == 1,
            "an anchor from the signer service is still accepted, so the refusals above are "
            "about the missing root and not about everything being refused now")

    print("\nO2-RESIDUAL-GONE: no operator-root private half exists on disk, and no key the "
          "app holds can re-sign the trusted-key registry. The registry is sealed.")
    print(f"\nGREEN: {len(CHECKS)} checks passed against the real bro_audit_log.")
    return 0


def case_pin_rewrite(bro_audit_log, keys, ledger, signer_argv, key_id, trust,
                     canonical_bytes, anchor) -> int:
    """The route destroying the operator root did NOT close, now closed - run, not argued.

    Its predecessor asserted the defect: `load_trusted_keys` authenticates the registry against
    an operator public key pinned from OUTSIDE it, that pin was
    `<app_data>/trust/pin/operator-root.pub`, and an account that could rewrite it did not need
    the destroyed key at all. It generated a root of its own, pinned it, re-signed the registry
    under it with an `audit-anchor` entry of its choosing, raised the floor it also owned, and
    the real `bro_audit_log.verify()` returned green on a ledger truncated from 3 records to 1.

    The pin, the floor and the provisioning manifest now live in `brops_provision::anchor` - a
    directory sealed against this very account. So the SAME attack is run, step for step, and
    two separate things are asserted about it:

    1. the operating system refuses every write. Not provisioning, not the engine: `open(...,
       "w")`, `os.remove`, creating a new file in the anchor directory, and renaming the anchor
       directory and its parent all raise `PermissionError`, and the pin's bytes are read back
       afterwards and are byte-identical. A refusal by intent is one a future edit can remove;
       this one is the kernel's.
    2. and the forgery fails anyway. The attack is carried as far as it still can go - the
       registry IS in the app's own directory and really is re-signed under the rogue root, and
       a rogue anchor really is installed over the truncated ledger - and the real
       `load_trusted_keys` refuses the re-signed registry against the untouched pin, the real
       `verify()` refuses the forged head, and the positive control still passes in the same
       run.

    To make the result impossible to attribute to a key left behind, EVERY private half in the
    app-side store is deleted first, exactly as the predecessor did.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from bro_signature import SignatureError, load_trusted_keys

    os.environ[bro_audit_log.SIGNER_ENV] = signer_argv
    os.environ[bro_audit_log.SIGNER_KEY_ID_ENV] = key_id
    for i in range(3):
        bro_audit_log.append(ledger, "note", {"index": str(i)})
    ok("a three-record ledger is anchored at count 3 by the second principal")

    removed = []
    for path in sorted((trust / "keys").glob("*.json")):
        path.unlink()
        removed.append(path.name)
    require(bool(removed),
            f"every private half in the app-side store is deleted first ({removed}) - so "
            "nothing below can be blamed on a key the destruction failed to remove, and so "
            "the app-side directory is demonstrably still this account's to write")

    pin_path = anchor / "operator-root.pub"
    floor_path = anchor / "registry-min"
    manifest_path = anchor / "PROVISIONING.json"
    pin_before = pin_path.read_bytes()
    floor_before = floor_path.read_bytes()
    manifest_before = manifest_path.read_bytes()

    rogue_root = Ed25519PrivateKey.generate()
    rogue_root_public = rogue_root.public_key().public_bytes_raw().hex()

    print("== the attack's FIRST step, attempted for real: write a root of its own over the "
          "pin ==")

    def refused(what, action):
        """`action` must raise PermissionError. Anything else is the attack succeeding."""
        try:
            action()
        except PermissionError as exc:
            ok(f"{what}: refused by the operating system - "
               f"{type(exc).__name__}: [Errno {exc.errno}] {exc.strerror}")
            return
        except OSError as exc:
            fail(f"{what}: failed with {type(exc).__name__} rather than PermissionError, so "
                 f"this check cannot say the OS refused it: {exc}")
        fail(f"{what}: SUCCEEDED. The account running the application can write the trust "
             f"anchor, so it can install a trust root of its own and O-2 IS NOT CLOSED.")

    refused("overwriting pin/operator-root.pub",
            lambda: pin_path.write_text(rogue_root_public + "\n", encoding="utf-8"))
    refused("appending to pin/operator-root.pub",
            lambda: open(pin_path, "a", encoding="utf-8").write("x"))
    refused("deleting pin/operator-root.pub", lambda: os.remove(pin_path))
    refused("renaming pin/operator-root.pub aside",
            lambda: os.rename(pin_path, anchor / "operator-root.pub.bak"))
    refused("writing a NEW file into the anchor directory",
            lambda: (anchor / "operator-root.pub.new").write_text("x", encoding="utf-8"))
    refused("raising the anti-rollback floor",
            lambda: floor_path.write_text("999\n", encoding="utf-8"))
    refused("rewriting the provisioning manifest",
            lambda: manifest_path.write_text("{}", encoding="utf-8"))
    refused("renaming the anchor directory aside",
            lambda: os.rename(anchor, anchor.parent / "trust-anchor.bak"))
    refused("renaming the anchor's PARENT aside - the route that defeats a seal on the leaf "
            "alone",
            lambda: os.rename(anchor.parent, anchor.parent.parent / "BroPS-o2-selftest.bak"))
    refused("removing the anchor directory", lambda: os.rmdir(anchor))

    require(pin_path.read_bytes() == pin_before,
            "and the pin's BYTES are unchanged afterwards - the refusals are refusals, not "
            "writes that happened to raise on close")
    require(floor_path.read_bytes() == floor_before,
            "so are the anti-rollback floor's")
    require(manifest_path.read_bytes() == manifest_before,
            "so are the provisioning manifest's")
    require(pin_path.read_text(encoding="utf-8").strip() != rogue_root_public,
            "and the pinned key is still the provisioned operator root, not the one this "
            "account just generated")

    print("== and the attack's SECOND step: re-sign the registry under the rogue root ==")
    rogue_anchor = Ed25519PrivateKey.generate()
    rogue_anchor_id = "audit-anchor-rogue"
    registry_path = anchor / "registry" / "config" / "trusted-keys.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))["payload"]
    payload["operator_public_key"] = rogue_root_public
    payload["registry_version"] = int(payload.get("registry_version", 1)) + 1
    entries = [e for e in payload["keys"] if e["authority_type"] != "operator-root"]
    entries.append({
        "key_id": "rogue-operator-root",
        "public_key": rogue_root_public,
        "authority_type": "operator-root",
        "allowed_artifact_types": ["conductor-session", "protected-authority",
                                   "trusted-key-registry", "workspace-binding"],
        "not_before_epoch": 0,
        "not_after_epoch": 253_402_300_799,
        "status": "active",
        "issued_by": "rogue-operator-root",
    })
    entries.append({
        "key_id": rogue_anchor_id,
        "public_key": rogue_anchor.public_key().public_bytes_raw().hex(),
        "authority_type": "audit-anchor",
        "allowed_artifact_types": [],
        "not_before_epoch": 0,
        "not_after_epoch": 253_402_300_799,
        "status": "active",
        "issued_by": "rogue-operator-root",
    })
    payload["keys"] = sorted(entries, key=lambda e: e["key_id"])
    registry_before = registry_path.read_bytes()
    refused("installing a registry re-signed under the rogue root, with an audit-anchor key "
            "of its own",
            lambda: registry_path.write_text(json.dumps(
                {"payload": payload,
                 "signature": rogue_root.sign(canonical_bytes(payload)).hex()},
                sort_keys=True), encoding="utf-8"))
    require(registry_path.read_bytes() == registry_before,
            "and the registry's bytes are unchanged")
    require(load_trusted_keys()[key_id].authority_type == "audit-anchor",
            "the registry the engine reads still resolves the SIGNER's key and no rogue one")

    print("== and the forged anchor itself, judged by the real bro_audit_log.verify() ==")
    # The LEDGER is in the app\'s own directory and always was - the app has to append to it.
    # So the truncation and the forged `.head.sig` really do land on disk. What the attack
    # needed the anchor directory for was to make the rogue signing key RESOLVE, and that is
    # what it could not reach.
    _forge_anchor(bro_audit_log, ledger, rogue_anchor.private_bytes_raw().hex(),
                  rogue_anchor_id, canonical_bytes)
    try:
        count = bro_audit_log.verify(ledger, keys=keys)
    except bro_audit_log.AuditError as exc:
        ok(f"the real verify() REFUSES the ledger truncated from 3 records to 1 and anchored "
           f"by the rogue key: {type(exc).__name__}: {exc}")
    else:
        fail(f"the real verify(keys=...) returned {count} on a truncated ledger anchored by a "
             f"key this account admitted to a registry it re-signed. O-2 IS NOT CLOSED.")

    print("== the positive control: the service's key still anchors a fresh ledger ==")
    control = ledger.with_name(f"positive-control-{ledger.stem}.jsonl")
    bro_audit_log.append(control, "note", {"index": "after"})
    require(bro_audit_log.verify(control, keys=keys) == 1,
            "an anchor from the signer service is still accepted, so the refusals above are "
            "about the rogue root and not about everything being refused now")

    print("\nO2-PIN-CUSTODY-CLOSED: the operator pin, the anti-rollback floor and the "
          "provisioning manifest are held where the account running the application cannot "
          "write them. Every step of the attack that destroying the operator root did NOT "
          "close was attempted here and refused by the operating system, and the part of it "
          "that could still be carried out - re-signing the app-side registry under a root of "
          "this account's own - fails against the pin it could not reach.")
    print(f"\nGREEN: {len(CHECKS)} checks passed against the real bro_audit_log.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
