"""Run the REAL engine verifiers against the REAL output of `brops-provision`.

This is the byte-compatibility proof. A Rust test that asserts Rust's own encoding
round-trips proves nothing about the thing that has to accept it, so nothing here
re-implements anything: it imports `engine/runtime/bro_signature.py`,
`engine/runtime/bro_policy.py` and `engine/tools/bro_deploy_preflight.py` and makes
them judge the files the Rust provisioner wrote. Every signature is Ed25519 over
`bro_signature.canonical_bytes(payload)`, so one byte of divergence in key ordering,
separators, escaping or integer formatting is a signature that does not verify.

    python verify_provisioning.py <trust-dir> <engine-root>

Exits 0 with a per-check log on success; non-zero with the failing check named.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile

CHECKS: list[str] = []


def ok(message: str) -> None:
    CHECKS.append(message)
    print(f"  PASS  {message}")


def fail(message: str) -> None:
    print(f"  FAIL  {message}", file=sys.stderr)
    raise SystemExit(1)


def require(condition: bool, message: str) -> None:
    if condition:
        ok(message)
    else:
        fail(message)


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    trust = pathlib.Path(argv[1]).resolve()
    anchor = pathlib.Path(argv[2]).resolve()
    engine = pathlib.Path(argv[3]).resolve()

    sys.path.insert(0, str(engine / "runtime"))
    sys.path.insert(0, str(engine / "tools"))

    # The registry, the pin and the floor all live in the ANCHOR now. This proof runs against
    # the UNSEALED mint (see `python_verifier.rs`), so the acknowledgement below is still
    # needed here and is still honest: THIS directory really is one the running account can
    # write. What the acknowledgement is no longer needed for is production, which is proved
    # separately, with it unset, in `audit-signer/tests/anchor_end_to_end.py`.
    registry_root = anchor / "registry"
    pin_file = anchor / "operator-root.pub"
    floor_file = anchor / "registry-min"
    session_file = trust / "artifacts" / "conductor-session.json"

    # The engine resolves its anchor and its anti-rollback floor from the environment,
    # and refuses an anchor the reading account can rewrite unless the deployment says
    # out loud that it has no second principal. A single-user desktop has none — this is
    # the acknowledgement the provisioned posture depends on, exercised for real rather
    # than asserted in a comment.
    os.environ["BRO_OPERATOR_ROOT_PUBKEY_FILE"] = str(pin_file)
    os.environ["BRO_OPERATOR_REGISTRY_MIN_FILE"] = str(floor_file)
    # Declared through the FILE form. The raw variable is honoured only under `BRO_ENV=ci`
    # now (this harness deliberately pops BRO_ENV two lines down), because ungated it handed
    # the short-circuit for every custody rule in the runtime to anyone who could set this
    # process's environment — the very adversary the pin exists to stop.
    _ack = anchor / "self-owned-acknowledgement"
    _ack.write_text("acknowledged", encoding="utf-8")
    os.environ["BRO_OPERATOR_ROOT_PIN_SELF_OWNED_FILE"] = str(_ack)
    os.environ.pop("BRO_OPERATOR_ROOT_PIN_SELF_OWNED", None)
    os.environ.pop("BRO_OPERATOR_ROOT_PUBKEY", None)
    os.environ.pop("BRO_OPERATOR_REGISTRY_MIN", None)
    os.environ.pop("BRO_ENV", None)

    import bro_signature
    from bro_audit_log import ANCHOR_AUTHORITIES
    from bro_signature import (
        ACTIVE,
        ARTIFACT_AUTHORITY,
        AUDIT_ANCHOR,
        AUTHORITY_TYPES,
        CONTROL_ROOM,
        EVIDENCE_FLOOR,
        OPERATOR,
        SignatureError,
        canonical_bytes,
        load_trusted_keys,
        resolve_operator_root_pin,
        verify_artifact,
    )

    print("== the operator-root pin, resolved the way production resolves it ==")
    pin = resolve_operator_root_pin(env=os.environ, root=registry_root)
    require(pin == pin_file.read_text(encoding="utf-8").strip(),
            "BRO_OPERATOR_ROOT_PUBKEY_FILE resolves to the minted operator-root public key")

    print("== the trusted-key registry, verified by bro_signature.load_trusted_keys ==")
    # No injected pin: this is the full production path — external anchor, production
    # binding, anti-rollback floor, per-entry parsing.
    keys = load_trusted_keys(root=registry_root, env=os.environ)
    ok("load_trusted_keys accepted the Rust-signed registry "
       "(Ed25519 over bro_signature.canonical_bytes: byte-for-byte agreement)")

    require(any(k.authority_type == OPERATOR and k.public_key == pin for k in keys.values()),
            "the registry contains the operator-root key it is signed by")

    print("== O-2: the operator-root PRIVATE half is nowhere on disk, by enumeration ==")
    # Asked of the filesystem, not of the code that writes it: every file under the trust
    # directory is read whole and every 32-byte window and every 64-character hex run in it
    # is tried AS AN ED25519 SEED. A seed that moved to a differently named file, a temp
    # file or a log line would still be found. A check for `keys/operator-root.json` would
    # not.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    def derives(seed: bytes, public_hex: str) -> bool:
        try:
            return (Ed25519PrivateKey.from_private_bytes(seed)
                    .public_key().public_bytes_raw().hex() == public_hex)
        except Exception:  # noqa: BLE001 - any 32 bytes are a valid seed; be defensive
            return False

    def find_seed(public_hex: str):
        for path in sorted(trust.rglob("*")):
            if not path.is_file():
                continue
            raw = path.read_bytes()
            for offset in range(0, max(0, len(raw) - 31)):
                if derives(raw[offset:offset + 32], public_hex):
                    return path
            text = raw.decode("utf-8", "replace")
            for start in range(0, max(0, len(text) - 63)):
                run = text[start:start + 64]
                if all(c in "0123456789abcdefABCDEF" for c in run) and derives(
                        bytes.fromhex(run), public_hex):
                    return path
        return None

    # The control first: the same search DOES find a key that is really there, so a null
    # result for the root cannot be the search being broken.
    a_retained = json.loads((trust / "keys" / "issuer.json").read_text(encoding="utf-8"))
    require(find_seed(a_retained["public_key"]) is not None,
            "the seed search finds a private half the store really holds")
    where = find_seed(pin)
    require(where is None,
            f"NO file under {trust} carries a seed deriving the PINNED operator-root public "
            f"key: it was generated in memory, signed the registry and the conductor "
            f"session, and was destroyed before provisioning returned (found {where})")
    require(not (trust / "keys" / "operator-root.json").exists(),
            "and there is no keys/operator-root.json at all")

    print("== the registry the engine reads still NAMES the operator root, publicly ==")
    require(any(k.authority_type == OPERATOR and k.public_key == pin for k in keys.values()),
            "load_trusted_keys refuses a registry that does not contain its own signer, so "
            "the PUBLIC half must still be there — and it is, which is what makes the "
            "destroyed private half a reduction rather than a break")

    print("== O-4 / O-5: the delegated authorities the root handed its routine work to ==")
    for authority, artifact in ((CONTROL_ROOM, "control-room-command"),
                                (EVIDENCE_FLOOR, "evidence-floor-anchor")):
        require(ARTIFACT_AUTHORITY[artifact] == authority,
                f"the REAL bro_signature binds {artifact} to {authority}")
        require(ARTIFACT_AUTHORITY[artifact] != OPERATOR,
                f"and NOT to operator-root — otherwise the root would have to survive for "
                f"{artifact} to be usable at all")
        held = [k for k in keys.values() if k.authority_type == authority]
        require(len(held) == 1, f"the store holds exactly one {authority} key")
        require(held[0].allowed_artifact_types == (artifact,),
                f"granted exactly {artifact} and nothing else: {held[0].allowed_artifact_types}")
        require((trust / "keys" / f"{authority}.json").is_file(),
                f"and its private half IS retained — this is work the app may keep doing")
    require(CONTROL_ROOM != EVIDENCE_FLOOR,
            "the two delegations are separate authorities: one key that could do both would "
            "be strictly more powerful than either")
    operator_key = next(k for k in keys.values() if k.authority_type == OPERATOR)
    for artifact in ("control-room-command", "evidence-floor-anchor"):
        require(artifact not in operator_key.allowed_artifact_types,
                f"the operator root is not granted {artifact}, so the delegation is a move "
                "and not a copy")

    print("== O-2: the anchor authority is ABSENT from the store, on the filesystem ==")
    # Asked of the directory, not of the code that writes it. `provision()` writes one
    # `<authority>.json` per authority it mints, each carrying BOTH halves; the check is
    # that no file in there — whatever it is named — carries a private key whose entry
    # claims an authority `bro_audit_log.ANCHOR_AUTHORITIES` would accept.
    key_files = sorted((trust / "keys").glob("*.json"))
    require(bool(key_files), f"there are key files to enumerate in {trust / 'keys'}")
    anchor_capable = []
    for path in key_files:
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry.get("authority_type") in ANCHOR_AUTHORITIES and entry.get("private_key"):
            anchor_capable.append(path.name)
    print(f"  NOTE  minted private halves: {[p.name for p in key_files]}")
    require(not anchor_capable,
            f"NO private half in the app's own trust store is anchor-capable "
            f"(found {anchor_capable})")
    require(not (trust / "keys" / f"{AUDIT_ANCHOR}.json").exists(),
            f"provision() did not write a {AUDIT_ANCHOR}.json at all")
    # And the registry the engine reads carries no anchor-capable key either: this store was
    # provisioned with no anchor argument at all. On a real Windows install the signer
    # service has already started and published its PUBLIC half, and
    # `provision_with_anchor` admits it WHILE THE REGISTRY IS BEING SIGNED — there is no
    # later step, because the operator root is destroyed before provisioning returns and the
    # registry can never be amended. A store minted without one, like this one, simply has
    # no audit anchor, and every keyed verify() of a ledger fails closed.
    require(not [k for k in keys.values() if k.authority_type in ANCHOR_AUTHORITIES],
            "a registry provisioned with no anchor argument names no anchor key, and no key "
            "in this store could add one afterwards")

    print("== the authority list came from the engine, not from a guess ==")
    # O-2. The anchor authority is the ONE the provisioner must NOT mint: `bro_audit_log`
    # accepts nothing else for an audit head, and a private half in the app's own store
    # would put the ledger's writer back in possession of a key that anchors it. So the
    # expected set is every authority the engine knows MINUS that one, and its absence is
    # checked separately and on the filesystem below.
    require(ANCHOR_AUTHORITIES == (AUDIT_ANCHOR,),
            f"bro_audit_log accepts exactly one anchor authority ({ANCHOR_AUTHORITIES})")
    provisionable = set(AUTHORITY_TYPES) - {AUDIT_ANCHOR}
    minted = {k.authority_type for k in keys.values()}
    require(minted == provisionable,
            f"one key per bro_signature.AUTHORITY_TYPES except the anchor authority "
            f"({sorted(provisionable)})")
    for key in keys.values():
        expected = tuple(sorted(a for a, required in ARTIFACT_AUTHORITY.items()
                                if required == key.authority_type))
        require(key.allowed_artifact_types == expected,
                f"the {key.authority_type} key is granted exactly the artifact types "
                f"bro_signature.ARTIFACT_AUTHORITY binds to it")
        require(key.status == ACTIVE, f"the {key.authority_type} key is active")

    print("== the expiry decision, checked against the engine's own window logic ==")
    far_future = 4_102_444_800  # 2100-01-01Z
    operator_key = next(k for k in keys.values() if k.authority_type == OPERATOR)
    require(all(k.not_before_epoch == 0 for k in keys.values()),
            "every key is valid from the epoch, so a backwards clock correction cannot "
            "make the deployment refuse itself")
    session_document = load(session_file)
    verify_artifact(session_document, "conductor-session", keys, now=far_future)
    ok("an artifact still verifies in the year 2100 — nothing will ever ask the owner to renew")
    try:
        verify_artifact(session_document, "conductor-session", keys,
                        now=operator_key.not_after_epoch)
        fail("the key window is not enforced at all")
    except SignatureError:
        ok("the window IS enforced; it simply ends at 9999-12-31Z")

    print("== O-3: the conductor-session artifact, through bro_policy's real verifier ==")
    payload = verify_artifact(session_document, "conductor-session", keys)
    require(payload["agent_id"] == "bro-000" and payload["role"] == "bro",
            "the artifact binds the canonical conductor identity")

    # `verify_conductor_session_token` reads the registry from `<root>/config/` AND the
    # requirement flag from `<root>/.bro/policy.json`, so the full path is exercised
    # against a root that carries both. This is also what proves the honest gap: the
    # registry has to BE at the engine root for the engine to see it.
    from bro_policy import State, verify_conductor_session_token

    staged_root = pathlib.Path(tempfile.mkdtemp(prefix="brops-o3-root-"))
    try:
        (staged_root / "config").mkdir(parents=True)
        shutil.copyfile(registry_root / "config" / "trusted-keys.json",
                        staged_root / "config" / "trusted-keys.json")
        (staged_root / ".bro").mkdir(parents=True)
        (staged_root / ".bro" / "policy.json").write_text(
            json.dumps({"require_conductor_session_token": True}), encoding="utf-8")

        os.environ["BRO_CONDUCTOR_SESSION_TOKEN"] = str(session_file)
        state = State(mode="work", role=payload["role"], session_id=payload["session_id"],
                      agent_id=payload["agent_id"])
        accepted, note = verify_conductor_session_token(state, root=staged_root)
        require(accepted, f"verify_conductor_session_token accepted the minted token: {note}")

        wrong = State(mode="work", role=payload["role"], session_id="not-this-session",
                      agent_id=payload["agent_id"])
        refused, why = verify_conductor_session_token(wrong, root=staged_root)
        require(not refused,
                f"a token bound to another session is still refused: {why}")
    finally:
        shutil.rmtree(staged_root, ignore_errors=True)
        os.environ.pop("BRO_CONDUCTOR_SESSION_TOKEN", None)

    print("== O-5: an evidence-floor-anchor minted by the same Rust signer ==")
    anchor_file = trust / "artifacts" / "test-floor-anchor.json"
    if not anchor_file.is_file():
        fail(f"the harness did not mint a floor anchor at {anchor_file}")
    anchor = verify_artifact(load(anchor_file), "evidence-floor-anchor", keys)
    require(isinstance(anchor.get("head_sequence"), int) and anchor["head_sequence"] >= 1,
            "the anchor carries the positive head_sequence bro_completion._signed_floor_anchor "
            "requires")
    require(anchor["key_id"] == next(
        k.key_id for k in keys.values() if k.authority_type == EVIDENCE_FLOOR),
        "verify_artifact accepted a Rust-signed evidence-floor-anchor under the DELEGATED "
        "evidence-floor authority — the operator root that would have signed it before is "
        "gone, and the artifact still verifies")

    print("== O-4: a control-room-command minted by the same Rust signer ==")
    command_file = trust / "artifacts" / "test-control-room-command.json"
    if not command_file.is_file():
        fail(f"the harness did not mint a control-room command at {command_file}")
    command_document = load(command_file)
    command_payload = verify_artifact(command_document, "control-room-command", keys)
    require(command_payload["key_id"] == next(
        k.key_id for k in keys.values() if k.authority_type == CONTROL_ROOM),
        "verify_artifact accepted it under the delegated control-room authority")

    # The acceptance is not the whole claim. The artifact has to survive the thing that
    # CONSUMES it, which binds it to one command and refuses a replay against another.
    from bro_control_room_api import ACTOR_PROVEN_PER_COMMAND, ControlRoomAPIError

    class _Runtime:
        evidence_keys = keys

    class _API:
        pass

    from bro_control_room_api import ControlRoomAPIV1
    api = ControlRoomAPIV1.__new__(ControlRoomAPIV1)
    api.runtime = _Runtime()
    this_command = {"command_id": command_payload["command_id"],
                    "task_id": command_payload["task_id"],
                    "command": command_payload["command"]}
    proof = api._prove_command_actor(("owner", "owner-gev"), command_document, this_command)
    require(proof["identity_basis"] == ACTOR_PROVEN_PER_COMMAND,
            "the REAL _prove_command_actor accepts it as a per-command owner proof")

    other_command = dict(this_command, command_id="cmd-somebody-elses")
    try:
        api._prove_command_actor(("owner", "owner-gev"), command_document, other_command)
        fail("the artifact authorised a DIFFERENT command — it is a session credential "
             "wearing another name")
    except ControlRoomAPIError as exc:
        require("different command" in str(exc),
                f"and refuses it against another command: {exc}")

    print("== and the delegation did not become a blanket grant, in both directions ==")
    # The strongest key the store has — the operator root that signed this very registry —
    # presented for each delegated artifact. Refused BY AUTHORITY, which is exactly what
    # makes destroying it cost O-4 and O-5 nothing.
    for artifact, sample in (("control-room-command", command_payload),
                             ("evidence-floor-anchor", load(anchor_file)["payload"]
                              if (trust / "artifacts" / "test-floor-anchor.json").is_file()
                              else None)):
        if sample is None:
            continue
        impostor = dict(sample)
        impostor["key_id"] = operator_key.key_id
        try:
            verify_artifact({"payload": impostor, "signature": "00" * 64}, artifact, keys)
            fail(f"the operator root was accepted for {artifact}")
        except SignatureError as exc:
            require(f"({OPERATOR}) may not sign {artifact}" in str(exc),
                    f"the operator root may not sign {artifact}: {exc}")
    # And neither delegate may reach the other's artifact, or the registry.
    for authority, forbidden in ((CONTROL_ROOM, "evidence-floor-anchor"),
                                 (EVIDENCE_FLOOR, "control-room-command"),
                                 (CONTROL_ROOM, "trusted-key-registry"),
                                 (EVIDENCE_FLOOR, "conductor-session")):
        key = next(k for k in keys.values() if k.authority_type == authority)
        try:
            verify_artifact(
                {"payload": {"artifact_type": forbidden, "key_id": key.key_id},
                 "signature": "00" * 64}, forbidden, keys)
            fail(f"the {authority} key was accepted for {forbidden}")
        except SignatureError as exc:
            require(f"({authority}) may not sign {forbidden}" in str(exc),
                    f"the {authority} key may not sign {forbidden}: {exc}")

    print("== the canonical bytes themselves, compared directly ==")
    registry_document = load(registry_root / "config" / "trusted-keys.json")
    rebuilt = canonical_bytes(registry_document["payload"])
    require(len(rebuilt) > 0 and rebuilt[0:1] == b"{",
            "bro_signature.canonical_bytes re-serialises the registry payload")
    bad = dict(registry_document["payload"])
    bad["issued_at_epoch"] = int(bad["issued_at_epoch"]) + 1
    try:
        bro_signature.verify_detached(bad, registry_document["signature"], pin)
        fail("a one-field change to the payload still verified — the signature is not "
             "actually bound to these bytes")
    except SignatureError:
        ok("changing one integer in the payload breaks the signature, so the Rust bytes "
           "and the Python bytes really are the same bytes")

    print("== the whole deployment posture, through bro_deploy_preflight ==")
    from bro_deploy_preflight import preflight

    failures = preflight(env=os.environ, root=registry_root)
    require(not failures,
            "bro_deploy_preflight reports a hardened posture: file-pinned anchor, "
            "authenticating registry, recovery authority present, builder/verifier keys "
            "bound to agent identities"
            + ("" if not failures else f" — got {failures}"))

    print(f"\nGREEN: {len(CHECKS)} checks passed against the real engine verifiers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
