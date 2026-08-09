"""Append-only, hash-chained audit ledger (Execution Surface kind=recorder).

P3 auditability: a human-readable JSONL ledger that sits BESIDE the cryptographic
marker mechanisms (nonce/lease/release), never replacing them. Every record links
to the previous by hash; a sidecar head file records the count and last hash so a
tail truncation is detectable, not just mid-chain tampering.

Machine-local by contract: the ledger path is supplied by the caller and MUST live
outside the repository (enforced here) so task-specific / sensitive runtime state is
never committed to Git. All payload strings are secret-redacted before they are
written (composes with L15).

The hash chain alone cannot resist the party that writes the ledger: whoever can
append can also drop records, recompute the chain and rewrite the plaintext
``.head`` sidecar, and an unkeyed ``verify()`` stays green. The authority against
that forger is an Ed25519 head ANCHOR, mirroring how ``bro_evidence`` anchors its
``evidence-head``: an external anchor authority signs a payload naming the ledger,
its record count and its tail hash, and ``verify(path, keys=...)`` refuses any chain
that does not reproduce that signed head exactly.

WHO SIGNS (custody). This module holds no private key and cannot sign - an
enforcement point that could sign is an enforcement point that could forge. The
signature comes from an OWNER-PROVIDED signing command named by
``BRO_AUDIT_ANCHOR_SIGNER``, which lives outside this engine, runs under a
principal that cannot write the ledger, and holds the private half of the
``BRO_AUDIT_ANCHOR_KEY_ID`` key registered under the dedicated ``audit-anchor``
authority - a type this repository never mints, so its private half can only be
held by that separate principal. ``append()`` assembles the payload itself, hands it to
that command, and REFUSES any returned document whose payload is not identical to
the one it assembled, does not verify against the operator-pinned trusted key
registry, or disagrees with the chain on disk. No seed is compiled in and none is
invented: with no custody configured the ledger is honestly UNANCHORED, which every
keyed ``verify()`` reports as its own distinct refusal (``AuditAnchorMissing``) -
never as "intact", and never confused with tampering (a plain ``AuditError``).

WHAT THIS BUYS, EXACTLY. A party who can write the ledger file can no longer drop
records, recompute the chain, rewrite the plaintext ``.head`` and have ``verify()``
report intact - it cannot produce the signature. That claim is only worth as much as
the custody of the anchor key, which is why ``ANCHOR_AUTHORITIES`` names ONE dedicated
authority (see the comment on it): while it named ``evidence-recorder`` and
``operator-root``, a deployment that provisions its own trust material at install held
both private halves in the ledger writer's own store, and the writer could simply sign
a fresh anchor for the truncation it had just made.

WHAT IT STILL DOES NOT BUY. Two things, both named rather than left to be discovered.
(1) It does not defend against a party who can make the owner's signing command sign
arbitrary heads; that boundary belongs to the signer's custody, which is required to run
as a separate principal and to REFUSE any anchor whose count is below the last one it
signed. ``previous_anchor_sha256`` is carried in the payload so such a signer can chain
its own decisions, and a count rollback is additionally refused here on install (defence
in depth only - a writer that drops the sidecar in directly walks past it).
(2) It does not defend against a party that holds the key the TRUSTED-KEY REGISTRY is
signed with. ``verify_signed_payload`` resolves the anchor's ``key_id`` through
``bro_signature.load_trusted_keys``; whoever holds the operator root can add an
``audit-anchor`` key of their own to that registry, re-sign it, raise the anti-rollback
floor, and anchor anything. On a deployment where the application provisions its own
trust root, that party IS the ledger's writer, and no authority list in this module can
separate a principal from itself. It is closed only by an operator root the ledger's
writer does not hold - an offline root, or one held by another principal. The
acknowledgement ``BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged`` is exactly a
deployment saying it has no such separation to offer.

Pure standard library on the append hot path when no custody is configured;
``bro_signature`` and the signing subprocess are reached only when anchoring is
provisioned or a caller supplies trusted keys.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import time

from bro_secrets import redact_mapping

GENESIS = "0" * 64
# The anchor's artifact type is deliberately NOT a bro_signature.ARTIFACT_AUTHORITY
# type: verify_artifact rejects unknown artifact types and checks the payload's own
# artifact_type field, so a signed audit head can never be replayed as a registry
# artifact (lease, receipt, evidence head, ...) and no registry artifact can be
# presented as an audit head.
ANCHOR_ARTIFACT_TYPE = "audit-head"
# The ONE authority whose keys may anchor an audit head, named here and nowhere else.
#
# HARDCODED ON PURPOSE, and deliberately not grantable. ``audit-head`` is in
# ``broctl.OUT_OF_REGISTRY_ARTIFACTS``, so no registry entry can name it in its own
# ``allowed_artifact_types``; the binding is carried by the authority TYPE instead, and
# that type is compared against this literal. A party who can rewrite the trusted-key
# registry therefore still cannot hand anybody the right to sign this ledger's own head -
# it would have to change this line, in the engine, which is the tree the deployment
# mounts read-only.
#
# WHY IT IS ONE NAME AND NOT THREE. It used to read
# ``("evidence-recorder", "operator-root")``, on the premise that the ledger's writer held
# neither. That premise died when the desktop app began minting its own trust material at
# install: ``brops_provision::provision()`` writes a private half for EVERY authority it
# knows into ``<app_data>/trust/keys/``, which the app's own account owns - so the ledger's
# writer held both anchor-capable halves, could truncate the chain, recompute it, sign a
# fresh anchor with a key it already had, and a keyed ``verify()`` returned green. The
# anchor authority is now a type nothing in this repository mints: the signer principal
# (a Windows service under its own virtual account, or a separate uid on POSIX) mints its
# own seed and publishes only the PUBLIC half for registration. ``operator-root`` keeps
# minting conductor sessions and evidence-floor anchors; it simply may no longer speak for
# the audit log's head, which is the separation this ledger's whole anchor mechanism is for.
#
# An offline-operator deployment is NOT excluded by this: an operator who really is offline
# mints an ``audit-anchor`` keypair on the offline machine exactly as they mint the operator
# root, registers the public half, and signs heads out of band through
# ``head_anchor_payload``/``attach_head_anchor``. What changed is that the anchor's custody
# is now its own fact, instead of riding on a key the deployment needs online for other work.
ANCHOR_AUTHORITY = "audit-anchor"
ANCHOR_AUTHORITIES = (ANCHOR_AUTHORITY,)
# The anchor payload's EXACT field set. Checked as an exact set, not a subset, so a
# signing command cannot smuggle extra fields into a document the verifier then
# treats as authoritative, and cannot omit one the chain check relies on.
ANCHOR_PAYLOAD_FIELDS = frozenset({
    "artifact_type", "key_id", "ledger", "count", "last_hash",
    "previous_anchor_sha256", "issued_at_epoch",
})
# Owner-provided custody. Deliberately two variables: a path with no key id (or a
# key id with no path) is a HALF-configuration and is refused loudly rather than
# silently degrading to an unanchored ledger.
SIGNER_ENV = "BRO_AUDIT_ANCHOR_SIGNER"
SIGNER_KEY_ID_ENV = "BRO_AUDIT_ANCHOR_KEY_ID"
# The signer runs inside the ledger's exclusive append lock (the anchor must
# describe the chain exactly as written, with no interleaved writer), so a wedged
# signer must surface rather than starve other writers past their lock timeout.
_SIGNER_TIMEOUT = 10.0
_ENGINE_ROOT = pathlib.Path(__file__).resolve().parents[1]
# Bound on how long a writer waits for the exclusive append lock before failing
# closed. Appends are short (read tail, hash, append one line, replace head), so a
# wait longer than this means a crashed or wedged holder - surfaced, never ignored.
_LOCK_TIMEOUT = 10.0
_LOCK_POLL = 0.01

CUSTODY_REFUSAL = (
    "Audit-head anchor custody is NOT configured. No signing key is compiled into "
    "this engine and none will be invented: an anchor signed with a key the "
    "ledger's own writer can reach proves nothing. The OWNER must provide, from "
    "outside this repository:\n"
    "  1. " + SIGNER_ENV + " - an absolute path to a signing command (or a JSON "
    "argv array whose first element is that path). It reads one canonical "
    "audit-head payload as JSON on stdin and writes a "
    "{payload, signature} JSON document on stdout. It MUST run under a principal "
    "that cannot write the audit ledger, it MUST NOT live inside this engine, and "
    "it MUST refuse to sign an anchor whose count is lower than the last one it "
    "signed (anti-rollback).\n"
    "  2. " + SIGNER_KEY_ID_ENV + " - the key id that command signs with, "
    "registered in the operator-pinned trusted-key registry under the "
    "'audit-anchor' authority - a type nothing in this repository mints, so the "
    "only party that can hold its private half is the signer principal itself. "
    "'evidence-recorder' and 'operator-root' are NOT accepted here: a deployment "
    "that provisions its own trust material holds both of those, and an anchor "
    "signed with a key the ledger's writer holds proves nothing. The private half "
    "never enters this process."
)


class AuditError(ValueError):
    """Raised on a broken/tampered/truncated audit chain (fail-closed)."""


class AuditAnchorMissing(AuditError):
    """The ledger carries NO signed head anchor.

    A distinct fact from tampering: "unanchored" says the integrity of this ledger
    was never established, and the action it calls for is provisioning custody.
    "Tampered" (plain AuditError) says an established integrity claim was broken,
    and the action it calls for is incident response. Collapsing them would lose
    the one that gets acted on, so they are separate types - both refusals.
    """


class AuditAnchorCustodyMissing(AuditError):
    """Anchor-signing custody is absent or half-configured; the owner must supply it."""


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _record_hash(prev_hash: str, body: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(body)).encode("utf-8")).hexdigest()


def _head_path(path: pathlib.Path) -> pathlib.Path:
    return path.with_suffix(path.suffix + ".head")


def _lock_path(path: pathlib.Path) -> pathlib.Path:
    return path.with_suffix(path.suffix + ".lock")


def _anchor_path(path: pathlib.Path) -> pathlib.Path:
    return path.with_suffix(path.suffix + ".head.sig")


def _acquire_lock(path: pathlib.Path) -> int:
    """Take an exclusive, cross-process append lock via an O_EXCL lock file.

    O_CREAT|O_EXCL is atomic on POSIX and Windows alike, so exactly one writer holds
    the lock at a time - the ledger's read-modify-write (compute seq/prev_hash from
    the tail, append, replace head) can never interleave and fork the chain. A holder
    that crashes leaves the lock file behind; the next writer waits out the bounded
    timeout and then fails closed, which is the audit ledger's contract."""
    lock = _lock_path(path)
    deadline = time.monotonic() + _LOCK_TIMEOUT
    while True:
        try:
            return os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass  # another writer holds the lock
        except PermissionError:
            # Windows raises PermissionError (not FileExistsError) when the lock file is
            # in the delete-pending window between a releaser's close and its unlink;
            # that is simply "held right now", so retry rather than propagate. A
            # genuinely unwritable directory still resolves to the bounded AuditError.
            pass
        if time.monotonic() >= deadline:
            raise AuditError(f"audit ledger lock not acquired within {_LOCK_TIMEOUT}s: {lock}")
        time.sleep(_LOCK_POLL)


def _release_lock(fd: int, path: pathlib.Path) -> None:
    try:
        os.close(fd)
    finally:
        try:
            os.unlink(_lock_path(path))
        except OSError:
            pass


def _assert_external(path: pathlib.Path, root: pathlib.Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return
    raise AuditError(f"audit ledger must live outside the repository: {path}")


def read_all(path: pathlib.Path) -> list[dict]:
    p = pathlib.Path(path)
    if not p.exists():
        return []
    records = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                # A corrupt line is a broken ledger; verify() documents AuditError, so
                # a tampered record must not surface as a raw JSONDecodeError callers
                # that catch only AuditError would miss.
                raise AuditError(f"unparsable audit record: {exc}") from exc
    return records


# ---------------------------------------------------------------------------
# Anchor custody - owner-provided, never compiled in
# ---------------------------------------------------------------------------

def anchor_custody_configured(env=None) -> bool:
    """True when the owner has named anchor custody at all.

    Either variable counts: a half-configuration must reach ``anchor_custody`` and
    become a loud refusal, not silently leave the ledger unanchored because of a
    typo in one variable name.
    """
    source = os.environ if env is None else env
    return bool((source.get(SIGNER_ENV) or "").strip()) or \
        bool((source.get(SIGNER_KEY_ID_ENV) or "").strip())


def _signer_argv(raw: str) -> list[str]:
    if raw.startswith("["):
        try:
            argv = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuditAnchorCustodyMissing(
                f"{SIGNER_ENV} looks like a JSON argv array but does not parse: {exc}") from exc
        if not (isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv)):
            raise AuditAnchorCustodyMissing(
                f"{SIGNER_ENV} as a JSON array must be a non-empty array of strings")
    else:
        argv = [raw]
    executable = pathlib.Path(argv[0])
    if not executable.is_absolute():
        raise AuditAnchorCustodyMissing(
            f"{SIGNER_ENV} must be an absolute path, got {argv[0]!r}")
    resolved = executable.resolve()
    if not resolved.is_file():
        raise AuditAnchorCustodyMissing(
            f"{SIGNER_ENV} does not name an existing file: {resolved}")
    # A signing command inside the engine is reachable by whatever can write the
    # ledger, so its signature proves nothing. Refuse it by name rather than ship a
    # protection that only reads as one.
    try:
        resolved.relative_to(_ENGINE_ROOT)
    except ValueError:
        pass
    else:
        raise AuditAnchorCustodyMissing(
            f"the audit-head signing command must not live inside this engine: {resolved}. "
            "A key the engine can reach is a key the ledger's own writer can reach, and "
            "an anchor it signs proves nothing.")
    return [str(resolved)] + [str(a) for a in argv[1:]]


def anchor_custody(env=None) -> tuple[list[str], str]:
    """Resolve the owner-provided (signing argv, key id), or refuse by name.

    Never falls back to any built-in key: the refusal names both variables and
    states exactly what the owner must provide.
    """
    source = os.environ if env is None else env
    signer_raw = (source.get(SIGNER_ENV) or "").strip()
    key_id = (source.get(SIGNER_KEY_ID_ENV) or "").strip()
    missing = [name for name, value in ((SIGNER_ENV, signer_raw),
                                        (SIGNER_KEY_ID_ENV, key_id)) if not value]
    if missing:
        raise AuditAnchorCustodyMissing(f"{' and '.join(missing)} not set. {CUSTODY_REFUSAL}")
    return _signer_argv(signer_raw), key_id


def _trusted_keys():
    """The operator-pinned trusted key registry, or a fail-closed refusal.

    ``append`` needs it to VERIFY what the signing command returned before that
    document is installed as this ledger's anchor: an unverified anchor would be an
    integrity claim nobody checked.
    """
    from bro_signature import SignatureError, load_trusted_keys
    try:
        return load_trusted_keys()
    except SignatureError as exc:
        raise AuditError(
            "audit-head anchor custody is configured but the operator-pinned trusted "
            "key registry cannot be loaded, so a returned anchor could not be "
            f"verified before installation: {exc}") from exc


def _is_sha256_hex(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _anchor_sha256(p: pathlib.Path) -> str | None:
    """Digest of the anchor being superseded, so the owner's signing command can
    chain its own decisions and refuse a rollback past one it already signed."""
    try:
        return hashlib.sha256(_anchor_path(p).read_bytes()).hexdigest()
    except OSError:
        return None


def _anchor_payload(p: pathlib.Path, *, key_id: str, count: int,
                    last_hash: str, now) -> dict:
    return {
        "artifact_type": ANCHOR_ARTIFACT_TYPE,
        "key_id": key_id,
        "ledger": p.name,
        "count": count,
        "last_hash": last_hash,
        "previous_anchor_sha256": _anchor_sha256(p),
        "issued_at_epoch": int(now),
    }


def _sign_anchor(argv: list[str], payload: dict) -> dict:
    """Hand the assembled payload to the owner's signing command and take back a
    signed document - refusing anything that is not a signature over EXACTLY the
    payload this ledger assembled."""
    try:
        proc = subprocess.run(argv, input=_canonical(payload), capture_output=True,
                              text=True, timeout=_SIGNER_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuditError(
            f"audit-head signing command failed to run ({argv[0]}): {exc}") from exc
    if proc.returncode != 0:
        raise AuditError(
            f"audit-head signing command refused (exit {proc.returncode}): "
            f"{(proc.stderr or '').strip()[:400]}")
    try:
        document = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AuditError(
            f"audit-head signing command did not return a signed document: {exc}") from exc
    if not isinstance(document, dict) or document.get("payload") != payload:
        # The signing command signs what the ledger says its head is, or nothing.
        # Without this it could return a signature over a shorter chain it preferred
        # and the install path would verify that signature happily.
        raise AuditError(
            "audit-head signing command returned a signature over a DIFFERENT payload "
            "than the one this ledger assembled")
    return document


def head_anchor_payload(path, *, key_id: str, now: int) -> dict:
    """Build the audit-head payload an EXTERNAL recorder/operator signs.

    The out-of-band path, for an operator anchoring a ledger by hand. This module
    never signs - the returned payload leaves the process, is signed by the
    ``audit-anchor`` authority, and comes back through ``attach_head_anchor``. The
    chain is structurally verified first so an anchor is never minted over an
    already-broken ledger.
    """
    p = pathlib.Path(path)
    count = verify(p)
    records = read_all(p)
    return _anchor_payload(p, key_id=key_id, count=count,
                           last_hash=records[-1]["hash"] if records else GENESIS, now=now)


def attach_head_anchor(path, document: dict, keys: dict, *, now: int | None = None) -> dict:
    """Install a signed head anchor beside the ledger, verifying it first.

    The document must verify against the trusted registry AND describe the ledger's
    current chain exactly - a stale or foreign anchor is refused rather than stored.
    """
    return _install_anchor(pathlib.Path(path), document, keys, now=now)


def _install_anchor(p: pathlib.Path, document: dict, keys: dict, *,
                    now: int | None = None) -> dict:
    payload = verify_signed_payload(document, ANCHOR_ARTIFACT_TYPE, keys,
                                    authorities=ANCHOR_AUTHORITIES, now=now)
    _check_anchor_against_chain(p, payload)
    _check_anchor_monotonic(p, payload)
    anchor = _anchor_path(p)
    tmp = anchor.with_suffix(anchor.suffix + ".tmp")
    tmp.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    os.replace(tmp, anchor)
    return payload


def _check_anchor_monotonic(p: pathlib.Path, payload: dict) -> None:
    """Refuse to replace an installed anchor with one describing a SHORTER chain.

    Defence in depth only - the authoritative anti-rollback lives in the owner's
    signing command, which must refuse to sign a lower count at all. This side can
    still be bypassed by a writer who drops the sidecar in directly, so it is never
    presented as the guarantee.
    """
    anchor = _anchor_path(p)
    if not anchor.exists():
        return
    try:
        installed = json.loads(anchor.read_text(encoding="utf-8"))["payload"]["count"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, IndexError) as exc:
        raise AuditError(
            f"the installed audit head anchor is unreadable; refusing to replace it: {exc}") from exc
    if not isinstance(installed, int) or isinstance(installed, bool):
        raise AuditError("the installed audit head anchor has no integer count; "
                         "refusing to replace it")
    if payload["count"] < installed:
        raise AuditError(
            f"audit head anchor rollback refused: new count {payload['count']} is below "
            f"the installed anchor's {installed}")


def verify_signed_payload(document, artifact_type: str, keys: dict, *,
                          authorities, now: int | None = None) -> dict:
    """Verify an out-of-registry signed document against the trusted key registry.

    ``keys`` is the registry loaded by ``bro_signature.load_trusted_keys`` (anchored
    to the external operator pin); the raw signature check is
    ``bro_signature.verify_detached`` itself. Key policy mirrors
    ``bro_signature.verify_artifact`` - known key id, active status, validity
    window - with the artifact binding enforced by ``authorities`` (the artifact
    types here are intentionally unknown to the registry, so per-key
    ``allowed_artifact_types`` cannot name them; the authority type carries the
    binding instead). Raises AuditError; never returns an unverified payload.
    """
    # Lazy import: the append hot path stays pure standard library; only a caller
    # that supplies trusted keys pays for the cryptography dependency.
    from bro_signature import SignatureError, verify_detached

    if not isinstance(document, dict) or set(document) != {"payload", "signature"}:
        raise AuditError(f"signed {artifact_type} must contain payload and signature only")
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise AuditError(f"signed {artifact_type} payload must be an object")
    if payload.get("artifact_type") != artifact_type:
        raise AuditError(
            f"document claims to be {payload.get('artifact_type')!r} but was "
            f"verified as {artifact_type!r}")
    key_id = payload.get("key_id")
    if not isinstance(key_id, str) or key_id not in keys:
        raise AuditError(f"unknown signing key: {key_id!r}")
    key = keys[key_id]
    if key.status != "active":
        raise AuditError(f"key {key_id} is {key.status}")
    if key.authority_type not in authorities:
        raise AuditError(
            f"key {key_id} ({key.authority_type}) may not sign {artifact_type}; "
            f"requires one of {sorted(authorities)}")
    moment = int(time.time()) if now is None else now
    if moment < key.not_before_epoch:
        raise AuditError(f"key {key_id} is not valid yet")
    if moment >= key.not_after_epoch:
        raise AuditError(f"key {key_id} expired at {key.not_after_epoch}")
    try:
        verify_detached(payload, document["signature"], key.public_key)
    except SignatureError as exc:
        raise AuditError(f"signed {artifact_type} signature RED: {exc}") from exc
    return payload


def _check_anchor_against_chain(p: pathlib.Path, payload: dict) -> None:
    # Exact field set, not a subset: an anchor carrying fields the verifier does not
    # check is an anchor whose meaning the signer, not the verifier, decided.
    if set(payload) != set(ANCHOR_PAYLOAD_FIELDS):
        raise AuditError(
            "audit head anchor payload has the wrong field set; unexpected="
            f"{sorted(set(payload) - set(ANCHOR_PAYLOAD_FIELDS))} missing="
            f"{sorted(set(ANCHOR_PAYLOAD_FIELDS) - set(payload))}")
    records = read_all(p)
    if payload.get("ledger") != p.name:
        raise AuditError("audit head anchor names a different ledger")
    count = payload.get("count")
    if not isinstance(count, int) or isinstance(count, bool):
        raise AuditError("audit head anchor count is not an integer")
    if count != len(records):
        raise AuditError("audit head anchor count disagrees with chain length")
    tail = records[-1]["hash"] if records else GENESIS
    if payload.get("last_hash") != tail:
        raise AuditError("audit head anchor hash disagrees with chain tail")
    previous = payload.get("previous_anchor_sha256")
    if previous is not None and not _is_sha256_hex(previous):
        raise AuditError("audit head anchor previous_anchor_sha256 is neither null "
                         "nor a sha256 hex digest")


def append(path, kind: str, payload: dict, *, repo_root: pathlib.Path | None = None) -> dict:
    p = pathlib.Path(path)
    if repo_root is not None:
        _assert_external(p, repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    # The whole read-modify-write is one critical section: two writers that both read
    # the tail before either appended would compute the same seq/prev_hash and fork
    # the chain. The lock serialises them; the tail is re-read inside it. Anchoring
    # happens inside the same section so the signed head can never describe a chain
    # another writer has already extended.
    lock_fd = _acquire_lock(p)
    try:
        configured = anchor_custody_configured()
        if not configured and _anchor_path(p).exists():
            # Silently appending past an installed anchor would strand it and turn
            # every later keyed verify() into a tamper report on an honest ledger.
            # Refuse before writing anything.
            raise AuditAnchorCustodyMissing(
                f"{p.name} carries a signed head anchor but no anchor custody is "
                f"configured, so this append could not be anchored and would strand "
                f"it. {CUSTODY_REFUSAL}")
        signer_argv = anchor_key_id = trusted = None
        if configured:
            # Resolve custody and the verification registry BEFORE writing, so a
            # misconfiguration refuses without leaving an unanchorable record behind.
            signer_argv, anchor_key_id = anchor_custody()
            trusted = _trusted_keys()
        existing = read_all(p)
        prev_hash = existing[-1]["hash"] if existing else GENESIS
        seq = existing[-1]["seq"] + 1 if existing else 0
        body = {"seq": seq, "prev_hash": prev_hash, "kind": kind, "payload": redact_mapping(payload)}
        record = dict(body)
        record["hash"] = _record_hash(prev_hash, body)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        # Replace the head atomically so a crash mid-write can never leave a torn head
        # that verify() would read as a truncation.
        head = _head_path(p)
        tmp = head.with_suffix(head.suffix + ".tmp")
        tmp.write_text(json.dumps({"count": seq + 1, "last_hash": record["hash"]}), encoding="utf-8")
        os.replace(tmp, head)
        if configured:
            # Fail-closed: if signing or installation raises, the record stays (the
            # ledger is append-only) but the anchor is now stale, so every keyed
            # verify() refuses this ledger until an operator re-anchors it. A
            # silently unanchored append would be the O-2 defect all over again.
            document = _sign_anchor(
                signer_argv,
                _anchor_payload(p, key_id=anchor_key_id, count=seq + 1,
                                last_hash=record["hash"], now=time.time()))
            _install_anchor(p, document, trusted)
        return record
    finally:
        _release_lock(lock_fd, p)


def verify(path, *, keys: dict | None = None, now: int | None = None) -> int:
    """Walk the chain, proving linkage, hashes and (via the head) no tail truncation.

    With ``keys`` (the operator-pinned trusted key registry) the check is
    authoritative: a signed head anchor from the ``audit-anchor`` authority is
    REQUIRED and the chain must reproduce it exactly, so a writer that drops
    records, recomputes the chain and rewrites the plaintext ``.head`` still fails
    (it cannot re-sign the anchor). A ledger that exists but carries no anchor is
    refused as ``AuditAnchorMissing`` - a different fact from tampering, raised as
    its own type so an operator can act on the one that actually applies. Without
    ``keys`` the check is structural only - sufficient against corruption, not
    against the ledger's own writer.

    Returns the record count. Raises AuditError on any break.
    """
    p = pathlib.Path(path)
    records = read_all(p)
    prev_hash = GENESIS
    for i, rec in enumerate(records):
        if rec.get("seq") != i:
            raise AuditError(f"audit ledger sequence break at index {i}")
        if rec.get("prev_hash") != prev_hash:
            raise AuditError(f"audit ledger linkage break at seq {i}")
        body = {k: rec[k] for k in ("seq", "prev_hash", "kind", "payload")}
        if _record_hash(prev_hash, body) != rec.get("hash"):
            raise AuditError(f"audit ledger record tampered at seq {i}")
        prev_hash = rec["hash"]
    head_file = _head_path(p)
    if head_file.exists():
        head = json.loads(head_file.read_text(encoding="utf-8"))
        if head.get("count") != len(records):
            raise AuditError("audit ledger truncated: head count disagrees with chain length")
        if head.get("last_hash") != (records[-1]["hash"] if records else GENESIS):
            raise AuditError("audit ledger truncated: head hash disagrees with chain tail")
    elif records:
        raise AuditError("audit ledger has records but no head anchor")
    if keys is not None:
        anchor_file = _anchor_path(p)
        if not anchor_file.exists():
            # Keyed on the ledger FILE, not on the record count: a ledger emptied to
            # zero records with its sidecars deleted must not verify as a clean
            # "return 0". Only a ledger that was never created has nothing to anchor.
            if p.exists():
                raise AuditAnchorMissing(
                    f"{p.name} has no signed head anchor (.head.sig): this ledger is "
                    f"UNANCHORED - its integrity was never established, which is a "
                    f"different fact from tampering. A self-hashed head cannot resist "
                    f"the party that writes the log, so this verification refuses "
                    f"rather than reporting the chain intact. {CUSTODY_REFUSAL}")
            return 0
        try:
            document = json.loads(anchor_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuditError(f"unreadable audit head anchor: {exc}") from exc
        payload = verify_signed_payload(document, ANCHOR_ARTIFACT_TYPE, keys,
                                        authorities=ANCHOR_AUTHORITIES, now=now)
        _check_anchor_against_chain(p, payload)
    return len(records)
