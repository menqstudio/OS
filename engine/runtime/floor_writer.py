"""**Floor Writer**, FW-1 — the service that owns the per-task anti-rollback floor.

This is the reviewed design, ``docs/design/FLOOR_WRITER_SERVICE_DESIGN.md``, implemented. The
first attempt at this file did not implement it: it invented a protocol name, a refusal
vocabulary, an authorization model and a socket permission model of its own while the reviewed
specification sat in the repository. The Architect's audit of that attempt found seven blocking
defects, and five of them were answers the design already contained. What follows is the design,
not a patch set over the earlier attempt.

# Scope: FW-1 only

Per §6, FW-1 is *"the service, the protocol, the Linux transport, and the client seam"*, and its
stop condition is that **the floor rule does not change** — the same comparisons, the same
refusal meanings, the same two stored fields — because moving the write and changing the rule in
one slice makes a regression indistinguishable from the move.

``scope.pin`` (§4.1) and the start-time scope resolution in the challenge authority and the
supervisor are **FW-3**, which §6 gates on the Architect ratifying the §2.5/§2.6 amendment. This
module refuses ``scope.pin`` as ``unknown_op`` and says so, rather than half-building it. Windows
is **FW-2**; until it lands this service's claim is *"Linux only"*, in those words.

# What the design fixes that the first attempt got wrong

**No ``install_id`` on the wire, and none may be** (§4.1). The scope is the service's own, read
from its TCB-owned config. Accepting it from the caller *"would reproduce A-01 inside the fix"*,
and §7's fifth negative makes a request carrying the field a ``malformed`` refusal rather than
something quietly ignored.

**The server is authenticated by its socket's DIRECTORY** (§1.7), which no other runtime
principal may write, checked through ``bro_custody`` — the same rule §2.5 applies to every TCB
path and its ancestors. The earlier attempt used ``chmod(socket, 0700)`` instead, which is not in
the design and which a two-account measurement showed makes the service unreachable by its own
intended caller: the whole point is two principals, and 0700 admits one.

**The posture is a closed two-state resolver** (§1.4): ``ServiceFloor(endpoint)`` or
``AcknowledgedLocalFloor``, *"no third state and no fallback from the first to the second"*, and
the local posture exists only under the pre-existing
``BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged`` disclosure. That resolver lives in
``bro_completion``; this module's part of it is that every failure here is a refusal, never a
silence a caller could read as "no floor required" (§7 negative 1).

**One writer process, so the cross-process lock disappears** (§1.9). The earlier attempt carried
an ``fcntl`` lock inherited from the policed-process design and then added a thread lock beside it
after a concurrency test found the first one does not exclude threads. Under this topology the
service is the only writer of its own store, so the serialization that remains is in-process and
is the only kind the topology can need.

# One storage-layout amendment, ruled on rather than slipped in

§4.3 lists the store as ``marks/<install_id>/<task_id>.floor.json`` *"plus the roster"* — two
durable objects. Two objects need two renames per advance, and a crash between them leaves a
roster naming a task whose mark is absent: a state that refuses forever and that only a
privileged repair could clear. That is the audit's B5.

The first attempt at fixing it derived the roster from the directory listing. **The Architect
refused that**, correctly: it redefines "roster" to mean "whatever mark files happen to exist",
which is a change to the security semantics rather than to the storage. Roster membership and
floor state are different facts and must stay different facts.

So the **semantics are kept and the physical layout is amended**, which the ruling permits: one
authoritative document per install, ``marks/<install_id>/floor-state.json``, carrying an explicit
``roster`` list AND the per-task floors, committed by ONE atomic rename. A task in the roster
whose floor is missing is still ``mark_removed`` — the detection survives — but no crash can
create that state, because the two facts are written together or not at all. A crash exposes the
complete previous document or the complete new one, and nothing between them.

What this costs, stated rather than discovered later: the whole install's state is one file, so a
corruption that used to lose one task now refuses every task on that install. That is the
fail-closed direction, and under §1.2 the only principal that can corrupt it is the service
itself.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import errno
import socket
import stat
import struct
import sys
import threading
from typing import Any, Dict, Mapping, Optional, Tuple

from bro_custody import posix_rewrite_verdict

#: §4.1. The reviewed wire contract; the version is part of authority, not a courtesy.
FLOOR_PROTOCOL = "brops.floor-writer.v1"

#: §4.1 / §6. FW-1's two operations. ``scope.pin`` is named by the design and belongs to FW-3.
OP_GET = "floor.get"
OP_ADVANCE = "floor.advance"
OP_SCOPE_PIN = "scope.pin"
FW1_OPS = (OP_GET, OP_ADVANCE)

#: §4.1. Exhaustive per op. ``install_id`` is deliberately absent from both, and §7's fifth
#: negative requires a request carrying it to be refused as an unknown key rather than ignored.
_FIELDS = {
    OP_GET: ("protocol", "task_id"),
    OP_ADVANCE: ("protocol", "task_id", "head_sequence", "evidence_head_sha256"),
}

#: §4.2. Outcomes. Two successes a reader must never confuse.
OUTCOME_ADVANCED = "advanced"
OUTCOME_IDEMPOTENT = "idempotent"

#: §4.2, the closed refusal enum, verbatim. A reason outside this set is a bug, and both
#: ``FloorWriterError`` and ``_refusal`` assert membership so one cannot be invented at a call site.
REFUSALS = frozenset({
    "peer_denied", "unknown_op", "malformed", "oversize", "floor_absent", "mark_removed",
    "mark_corrupt", "no_head_digest", "stale_floor", "head_digest_changed", "scope_unavailable",
    "internal",
})

#: §1.7. ONE cap, one number, both directions, defined once. The design fixes it at 4096 after
#: this repository found three framing codecs disagreeing (8192 / 8192 / 512 KiB) with the
#: deployed client capping at 8192 in both directions, making one gate unreachable.
#:
#: §1.7 asks FW-1 to CONFIRM the cap's arithmetic through the real encoder rather than assert it,
#: and it is confirmed: the largest legal advance — a 128-byte task_id, a 64-hex digest and a
#: 64-bit sequence — encodes to 324 bytes, against the design's predicted "well under 512", for
#: 12.6x of headroom. `test_the_cap_is_confirmed_through_the_real_encoder` re-measures it, so the
#: number in this comment cannot drift away from the encoder that produces it.
#:
#: PARTIAL: §1.7 specifies BOTH platforms and this module is the Linux half only. The named-pipe
#: column — `authenticate_pipe_client_sid`, the `pipe_dacl_plan` DACL, the create-successor-before-
#: close rule — is FW-2 and is NOT IMPLEMENTED here. The cap is also defined once per LANGUAGE in
#: the design and pinned by a cross-language drift test; only the Python constant exists, and no
#: such drift test does.
MAX_FLOOR_FRAME_BYTES = 4096
LENGTH_PREFIX_BYTES = 4

#: §1.7. A TOTAL wall-clock budget for one exchange, armed at the first read and never re-armed.
#: A per-recv timeout is not a bound: it restarts on every byte, so a peer dripping one byte per
#: timeout holds a serial loop forever while never once timing out.
CONNECTION_BUDGET_S = 30.0

_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
#: A task id is an identifier, not a path: the mark's file name is derived from it, so a value
#: carrying a separator or a traversal segment would address a file outside the store.
_TASK_ID = re.compile(r"\A[A-Za-z0-9._-]{1,128}\Z")
_INSTALL_ID = re.compile(r"\A[A-Za-z0-9._:-]{1,128}\Z")

#: §4.4. The service's own TCB-owned config. Mirrors ``BROPS_BROKER_CONFIG``'s shape: the variable
#: names a file, and a config that does not parse or whose custody cannot be verified is a refusal
#: to start rather than a degraded start.
ENV_SERVICE_CONFIG = "BROPS_FLOOR_WRITER_CONFIG"


class FloorWriterError(Exception):
    """A refusal carrying the reviewed enum value it goes on the wire as.

    The reason is data, decided where the refusal is decided. An earlier version recovered it by
    matching substrings of the message, and two tests caught that immediately — a rollback and a
    changed-head-at-equal-sequence both came out as the malformed reason.
    """

    def __init__(self, reason: str, detail: str) -> None:
        if reason not in REFUSALS:
            raise AssertionError(
                f"{reason!r} is not in the reviewed refusal enum; §4.2 closes that set and a "
                "thirteenth value is a design change, not a call-site decision")
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------
# §4.4 — the TCB-owned service configuration
# ---------------------------------------------------------------------------


class ServiceConfig:
    """``install_id``, the marks root, the per-op peer allowlist and the provisioning generation.

    Every value the service needs comes from here and none of it from a caller. The policed
    process contributes nothing to this object: that is what makes the scope binding service-side
    (§1.5) rather than a request field the subject chooses (A-01).
    """

    def __init__(self, install_id: str, marks_root: pathlib.Path, socket_path: pathlib.Path,
                 peers: Mapping[str, frozenset], generation: int, source: pathlib.Path) -> None:
        self.install_id = install_id
        self.marks_root = marks_root
        self.socket_path = socket_path
        self.peers = dict(peers)
        self.generation = generation
        self.source = source

    def peers_for(self, op: str) -> frozenset:
        """§1.8. An op is refused if the authenticated peer is not on THAT op's list — not merely
        on the union of them. A ``scope.pin`` peer must not be able to advance a floor, and the
        completion principal must not be able to ask what the pin is."""
        return self.peers.get(op, frozenset())

    @property
    def marks_dir(self) -> pathlib.Path:
        """§4.3. ``marks/<install_id>/`` — the install scoping is INTERNAL, from this config, and
        is what makes "no install_id on the wire" implementable."""
        return self.marks_root / self.install_id


def load_service_config(env: Optional[Mapping[str, str]] = None) -> ServiceConfig:
    """Read and validate the config named by ``BROPS_FLOOR_WRITER_CONFIG``.

    Absent, unreadable, unparseable, incomplete or custody-unverifiable means raise. There is no
    partial start: a service that came up having guessed half its own configuration would be
    advertising a socket whose promises it cannot keep.
    """
    environ = os.environ if env is None else env
    raw = environ.get(ENV_SERVICE_CONFIG)
    if not raw:
        raise FloorWriterError(
            "scope_unavailable",
            f"{ENV_SERVICE_CONFIG} is unset. The Floor Writer's install scope, marks root and "
            "peer allowlist come from its own TCB-owned config and from nowhere else")
    path = pathlib.Path(raw)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FloorWriterError(
            "scope_unavailable", f"cannot read the Floor Writer config {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise FloorWriterError("scope_unavailable",
                               f"the Floor Writer config {path} is not a JSON object")

    install_id = document.get("install_id")
    if not isinstance(install_id, str) or not _INSTALL_ID.fullmatch(install_id):
        raise FloorWriterError(
            "scope_unavailable", f"the Floor Writer config {path} carries no usable install_id")
    marks_root = document.get("marks_root")
    if not isinstance(marks_root, str) or not marks_root:
        raise FloorWriterError(
            "scope_unavailable", f"the Floor Writer config {path} names no marks_root")
    socket_path = document.get("socket_path")
    if not isinstance(socket_path, str) or not socket_path:
        raise FloorWriterError(
            "scope_unavailable",
            f"the Floor Writer config {path} names no socket_path. The endpoint is part of the "
            "service's own configuration: there is no default, because a default would be a way "
            "for a misconfigured deployment to come up looking provisioned")
    generation = document.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise FloorWriterError(
            "scope_unavailable",
            f"the Floor Writer config {path} carries no provisioning generation >= 1. §1.10: the "
            "generation is minted once at provisioning and served with every reply, so a "
            "re-provisioned floor is visibly new rather than silently empty. It is minted by "
            "provision_floor_writer.py — previous + 1, or 1 — into BOTH this config and the "
            "authoritative store, and load_state refuses a store whose generation is not this "
            "one. O-5 stays OPEN either way: nothing here is signed from outside the machine, so "
            "a restore of the whole store, generation included, is still indistinguishable from a "
            "first sighting, exactly as §1.10 itself states")

    peers_doc = document.get("peers")
    if not isinstance(peers_doc, dict) or not peers_doc:
        raise FloorWriterError(
            "scope_unavailable",
            f"the Floor Writer config {path} carries no per-op peer allowlist. §1.8 requires one "
            "list PER OP, not a union: a scope.pin peer must not be able to advance a floor")
    peers: Dict[str, frozenset] = {}
    for op, uids in peers_doc.items():
        if op not in (OP_GET, OP_ADVANCE, OP_SCOPE_PIN):
            raise FloorWriterError(
                "scope_unavailable",
                f"the Floor Writer config {path} lists peers for unknown op {op!r}")
        if not isinstance(uids, list) or not uids:
            raise FloorWriterError(
                "scope_unavailable",
                f"the Floor Writer config {path} gives op {op!r} no peers; an empty list refuses "
                "every caller, which is a misconfiguration rather than a posture")
        checked = set()
        for uid in uids:
            # bool is an int subclass, and a stray True must never masquerade as uid 1 — the
            # isolated_signer_server.peer_is_broker rule, adopted here.
            if isinstance(uid, bool) or not isinstance(uid, int) or uid < 0:
                raise FloorWriterError(
                    "scope_unavailable",
                    f"the Floor Writer config {path} lists {uid!r} as a peer uid for {op!r}")
            checked.add(uid)
        peers[op] = frozenset(checked)
    for op in FW1_OPS:
        if op not in peers:
            raise FloorWriterError(
                "scope_unavailable",
                f"the Floor Writer config {path} gives no peer list for {op!r}, which FW-1 serves")

    return ServiceConfig(install_id, pathlib.Path(marks_root), pathlib.Path(socket_path),
                         peers, generation, path)


# ---------------------------------------------------------------------------
# §1.2 / §1.7 — custody of the state directory and of the socket's directory
# ---------------------------------------------------------------------------


def require_linux(what: str) -> None:
    """§6 FW-2. Peer authentication is ``SO_PEERCRED``; there is no equivalent-strength mechanism
    wired for Windows or macOS here, so this stops rather than approximating. A weaker mechanism
    under the same name would be a security property that reads as equivalent and is not."""
    if sys.platform != "linux":
        raise FloorWriterError(
            "scope_unavailable",
            f"{what}: the Floor Writer authenticates peers with SO_PEERCRED, which requires "
            f"Linux; this platform is {sys.platform!r}. Windows is FW-2 and is not built")


def require_private_directory(directory: pathlib.Path, what: str) -> None:
    """The directory must be this principal's, and writable by nothing else.

    Used for BOTH the marks store (§1.2 — *"the policed account gets no access at all"*) and the
    socket's parent (§1.7 — this IS the server authentication: a directory no other runtime
    principal may write is one in which no other principal can replace the endpoint).

    ``posix_rewrite_verdict`` is the same custody primitive the operator-root pin and the evidence
    floor already use, so this is one contract with one implementation rather than a second
    opinion about what "protected" means.
    """
    try:
        info = directory.lstat()
    except OSError as exc:
        raise FloorWriterError("scope_unavailable",
                               f"cannot stat {what} {directory}: {exc}") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise FloorWriterError("scope_unavailable", f"{what} {directory} is not a directory")
    if info.st_uid != os.geteuid():
        raise FloorWriterError(
            "scope_unavailable",
            f"{what} {directory} is owned by uid {info.st_uid}, not by the Floor Writer principal "
            f"(uid {os.geteuid()}); a directory this principal does not own is one it cannot "
            "promise to be the only writer of")
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise FloorWriterError(
            "scope_unavailable",
            f"{what} {directory} is group- or world-writable (mode "
            f"{stat.S_IMODE(info.st_mode):04o}); least privilege means this principal and no other")
    # `posix_rewrite_verdict` answers "can the process running me rewrite this path?", and it was
    # written for the POLICED account, where owning the path is disqualifying. Here the question
    # is the opposite one: this directory is the Floor Writer's own, so its `owner` and
    # `permission` verdicts describe the INTENDED state, not a defect. Using the primitive
    # wholesale refused the service's own correctly-provisioned directory — found by a real
    # two-account run, not by reading.
    #
    # What is still needed from it is the third vector, and only that one: a parent another
    # principal can write lets them rename this directory aside and put their own in its place,
    # which makes this directory's own mode irrelevant. That is the vector
    # `_refuse_self_owned_floor` names third, and it is what §1.7 means by the endpoint being
    # unreplaceable.
    verdict = posix_rewrite_verdict(directory, info, what, RuntimeError)
    if verdict is not None and verdict.kind == "parent":
        raise FloorWriterError(
            "scope_unavailable",
            f"{what} {directory} fails custody: its parent {verdict.parent} (uid "
            f"{verdict.parent_uid}, mode {verdict.parent_mode:04o}) is writable by another "
            "principal, which can rename the whole directory aside and put its own in its place "
            "regardless of this directory's mode")


# ---------------------------------------------------------------------------
# §4.3, amended — the marks store. ONE document, ONE atomic publish per advance, and the
# roster is a field IN that document. It is never the directory listing: the Architect
# refused a directory-derived roster because it redefines a security fact as a side effect
# of which files happen to exist.
# ---------------------------------------------------------------------------


#: §4.3, amended. ONE authoritative document per install: an explicit roster and the per-task
#: floors, committed together. The name is not ``<task_id>.floor.json`` any more because the
#: coupled state has one commit point now — see the module docstring for the ruling that required
#: it and for what the change costs.
STATE_FILE = "floor-state.json"


def _state_path(config: ServiceConfig) -> pathlib.Path:
    return config.marks_dir / STATE_FILE


def load_state(config: ServiceConfig) -> Dict[str, Any]:
    """The whole authoritative document, validated.

    An absent document is an UNPROVISIONED store, not an empty one: treating them alike would let
    deleting one file restart every task's floor at zero, which is the attack the roster exists to
    catch. §4.2 records that under service custody this reads as self-damage rather than as an
    attack — it still refuses.
    """
    marks = config.marks_dir
    if not marks.is_dir():
        raise FloorWriterError(
            "floor_absent",
            f"the marks directory {marks} does not exist. It is created by the service's own "
            "provisioning, so a floor cannot be bootstrapped by a client")
    path = _state_path(config)
    if not path.exists():
        raise FloorWriterError(
            "floor_absent",
            f"the authoritative floor state {path} does not exist; the store is unprovisioned and "
            "an unprovisioned floor is refused rather than started at zero")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FloorWriterError(
            "mark_corrupt",
            f"the authoritative floor state is unreadable; refusing rather than treating a "
            f"damaged anti-rollback record as absent: {exc}") from exc
    if not isinstance(document, dict):
        raise FloorWriterError("mark_corrupt", "the authoritative floor state is not an object")
    roster = document.get("roster")
    floors = document.get("floors")
    if not isinstance(roster, list) or any(not isinstance(x, str) for x in roster):
        raise FloorWriterError("mark_corrupt", "the roster is not a list of task ids")
    if not isinstance(floors, dict):
        raise FloorWriterError("mark_corrupt", "the floors block is not an object")
    if document.get("install_id") != config.install_id:
        # The document says which install it belongs to, so a store swapped underneath the service
        # is caught rather than served. A-01 in miniature: the scope must not be assumable.
        raise FloorWriterError(
            "mark_corrupt",
            "the authoritative floor state names a different install than this service serves")
    if document.get("generation") != config.generation:
        # §1.10. The generation is minted by provisioning into BOTH the config and the store, so a
        # config re-provisioned over a store that was not is a service reporting `generation: N+1`
        # while serving generation N's floors -- exactly the "visibly new versus silently old"
        # confusion the number exists to remove. The store and the config must name one
        # provisioning or neither is authoritative about which floor a client is looking at.
        raise FloorWriterError(
            "mark_corrupt",
            f"the authoritative floor state carries generation {document.get('generation')!r} and "
            f"this service is configured for generation {config.generation}; a store and a config "
            "from different provisionings cannot both describe the floor a client is told about")
    return document


def read_floor(config: ServiceConfig, task_id: str) -> Tuple[int, Optional[str]]:
    """``(head_sequence, evidence_head_sha256)`` for one task, or ``(0, None)`` if never measured.

    Roster membership is checked SEPARATELY from the floor, because they are different facts: a
    task the roster names whose floor is gone is ``mark_removed``, exactly as it was when they
    were two files. What changed is that no crash can produce that state.
    """
    document = load_state(config)
    roster = set(document["roster"])
    floors = document["floors"]
    record = floors.get(task_id)
    if record is None:
        if task_id in roster:
            raise FloorWriterError(
                "mark_removed",
                f"the roster names {task_id} but its floor is absent: the mark was removed. "
                "Refusing rather than restarting the anti-rollback floor at zero")
        return 0, None
    if not isinstance(record, dict):
        raise FloorWriterError("mark_corrupt", f"the floor for {task_id} is not an object")
    recorded = record.get("head_sequence")
    if isinstance(recorded, bool) or not isinstance(recorded, int) or recorded < 0:
        raise FloorWriterError(
            "mark_corrupt", f"the floor for {task_id} is not a non-negative integer")
    digest = record.get("evidence_head_sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise FloorWriterError(
            "no_head_digest",
            f"the floor for {task_id} records no signed head digest; a mark that cannot say which "
            "signed head it was taken against is not evidence of anything")
    if task_id not in roster:
        # A floor without roster membership is the other half of the same corruption. It cannot
        # be produced by this service, which writes both together.
        raise FloorWriterError(
            "mark_corrupt",
            f"the floor for {task_id} exists but the roster does not name it; the two halves of "
            "the authoritative state disagree")
    return recorded, digest


def commit_state(config: ServiceConfig, document: Mapping[str, Any]) -> None:
    """§4.3's atomic publish, over the WHOLE coupled state, in ONE rename.

    Private temp in the same directory, write, ``fsync``, rename over the document, ``fsync`` the
    directory. A crash exposes the complete previous document or the complete new one. There is no
    second object to fall out of step with this one, so there is no half-state and therefore no
    repair path to design.
    """
    marks = config.marks_dir
    final = _state_path(config)
    temporary = marks / f".{STATE_FILE}.tmp"
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, final)
        dir_fd = os.open(marks, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise FloorWriterError(
            "internal", f"cannot commit the authoritative floor state: {exc}") from exc


def known_tasks(config: ServiceConfig) -> set:
    """The roster, read from the document that declares it — never inferred from what files exist."""
    return set(load_state(config)["roster"])


#: §1.9. ONE writer process, so the cross-process lock disappears. What remains is in-process
#: serialization of load -> compare -> publish -> evidence, which is the only kind this topology
#: can need. A file lock would add no exclusion here and would add a failure mode: ``fcntl.lockf``
#: is owned by the process, not the thread, so it excludes nothing inside one service anyway — a
#: concurrency test proved that on the earlier attempt, where eight threads left the floor at the
#: last writer's value instead of the highest.
_ADVANCE_LOCK = threading.Lock()


def _reply(op: str, config: ServiceConfig, **fields: Any) -> Dict[str, Any]:
    """§4.2. A result carries ``ok: true``, the op, its fields and the provisioning generation."""
    body = {"ok": True, "protocol": FLOOR_PROTOCOL, "op": op, "generation": config.generation}
    body.update(fields)
    return body


def _refusal(reason: str, detail: str) -> Dict[str, Any]:
    """§4.2. A refusal carries ``ok: false`` and NO result field at all, so it cannot be mistaken
    for a result — the ``audit-signer/src/lib.rs:91`` rule, adopted verbatim. The detail is capped
    and carries no path or traceback."""
    if reason not in REFUSALS:
        raise AssertionError(f"{reason!r} is not in the reviewed refusal enum")
    return {"ok": False, "protocol": FLOOR_PROTOCOL, "reason": reason, "detail": detail[:512]}


def do_get(config: ServiceConfig, task_id: str) -> Dict[str, Any]:
    """§1.3. ``floor.get`` exists because ``validate_evidence_chain`` needs a number BEFORE it
    validates the chain. Its answer is never authoritative: a client that ignores it, or lies to
    itself about it, still cannot advance below the floor, because ``floor.advance`` re-checks
    against the store this service owns."""
    current, digest = read_floor(config, task_id)
    return _reply(OP_GET, config, head_sequence=current, evidence_head_sha256=digest,
                  known=task_id in known_tasks(config))


def do_advance(config: ServiceConfig, task_id: str, head_sequence: int,
               digest: str) -> Dict[str, Any]:
    """§1.3's whole load -> compare -> write, and the result built inside the same lock.

    The comparisons are ``bro_completion``'s, unchanged (§6's stop condition): a lower head is
    stale, an equal head with a different signed digest is a head that changed without advancing,
    and an equal head with the same digest is idempotent and writes nothing.

    Roster membership and the floor move in ONE commit. The roster is updated explicitly here —
    it is a fact this service records, not one a reader infers from the filesystem.
    """
    with _ADVANCE_LOCK:
        document = load_state(config)
        roster = list(document["roster"])
        floors = dict(document["floors"])
        current, current_digest = read_floor(config, task_id)
        if head_sequence < current:
            raise FloorWriterError(
                "stale_floor",
                f"the floor for {task_id} stands at {current} and the request asked for "
                f"{head_sequence}. Nothing was written")
        if head_sequence == current:
            if current_digest != digest:
                raise FloorWriterError(
                    "head_digest_changed",
                    f"the floor for {task_id} stands at {current} against one signed head and "
                    "this request presents another for the same sequence: a head that changed "
                    "without advancing has stopped being a high-water mark")
            # §7 negative 4: validate_evidence_chain runs TWICE per completion, so the second call
            # must be idempotent by contract rather than by luck. Exactly once written: this
            # branch commits nothing at all.
            return _reply(OP_ADVANCE, config, outcome=OUTCOME_IDEMPOTENT,
                          head_sequence=current, evidence_head_sha256=current_digest)
        floors[task_id] = {"head_sequence": head_sequence, "evidence_head_sha256": digest}
        if task_id not in roster:
            roster.append(task_id)
        commit_state(config, {"install_id": config.install_id, "generation": config.generation,
                              "roster": sorted(roster), "floors": floors})
        # Read the committed state back before calling it committed: the reply must describe the
        # document on disk, not the intention that produced it.
        committed, committed_digest = read_floor(config, task_id)
        if committed != head_sequence or committed_digest != digest:
            raise FloorWriterError(
                "internal",
                f"the floor for {task_id} does not read back as what was written; refusing to "
                "report an advancement the authoritative state does not hold")
        return _reply(OP_ADVANCE, config, outcome=OUTCOME_ADVANCED,
                      head_sequence=committed, evidence_head_sha256=committed_digest)


# ---------------------------------------------------------------------------
# §4.1 — request validation
# ---------------------------------------------------------------------------


def validate(request: Any) -> Tuple[str, Dict[str, Any]]:
    """Exhaustive shape and value validation before any state is touched.

    §7 negative 5 is the one to read twice: a request carrying ``install_id`` is refused as an
    unknown key. The scope is the service's own, and accepting it on the wire would reproduce
    A-01 inside the fix.
    """
    if not isinstance(request, dict):
        raise FloorWriterError("malformed", "request is not a JSON object")
    op = request.get("op")
    if op == OP_SCOPE_PIN:
        raise FloorWriterError(
            "unknown_op",
            "scope.pin is FW-3 and is not built: §6 gates it on the Architect ratifying the "
            "§2.5/§2.6 amendment. This service serves floor.get and floor.advance")
    if op not in FW1_OPS:
        raise FloorWriterError("unknown_op", f"unknown op {op!r}")
    allowed = {"op"} | set(_FIELDS[op])
    extra = sorted(set(request.keys()) - allowed)
    if extra:
        raise FloorWriterError(
            "malformed",
            f"request has unexpected field(s) {extra}"
            + (". install_id is never on this wire: the scope is the service's own"
               if "install_id" in extra else ""))
    missing = sorted(allowed - set(request.keys()))
    if missing:
        raise FloorWriterError("malformed", f"request is missing field(s) {missing}")
    if request["protocol"] != FLOOR_PROTOCOL:
        raise FloorWriterError(
            "malformed",
            f"unsupported protocol; this service speaks {FLOOR_PROTOCOL!r} and nothing else")
    task_id = request["task_id"]
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise FloorWriterError(
            "malformed",
            "task_id must be 1..128 chars of [A-Za-z0-9._-]; the mark's file name is derived "
            "from it, so a separator or a traversal segment would address a file outside the store")
    if op == OP_ADVANCE:
        head = request["head_sequence"]
        if isinstance(head, bool) or not isinstance(head, int) or head < 1:
            raise FloorWriterError(
                "malformed",
                "head_sequence must be a positive integer; sequence 0 is the absence of a "
                "measured head and cannot be advanced to")
        digest = request["evidence_head_sha256"]
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise FloorWriterError(
                "malformed", "evidence_head_sha256 must be 64 lowercase hex characters")
    return op, request


def handle(request: Any, *, config: ServiceConfig, peer_uid: Optional[int]) -> Dict[str, Any]:
    """One request, one verdict. Never raises for a caller's fault.

    The peer is authorized against the list for the op it actually asked for (§1.8), so being
    admitted for one operation is not admission to another.
    """
    try:
        op, validated = validate(request)
        if peer_uid is None or isinstance(peer_uid, bool) or not isinstance(peer_uid, int):
            return _refusal("peer_denied", "the peer could not be authenticated")
        if peer_uid not in config.peers_for(op):
            # Does not echo the allowlist: a refusal must not be an oracle for which uid to become.
            return _refusal("peer_denied",
                            f"uid {peer_uid} is not permitted to call {op}. Reaching this socket "
                            "is not authority, and admission to one op is not admission to another")
        if op == OP_GET:
            return do_get(config, validated["task_id"])
        return do_advance(config, validated["task_id"], validated["head_sequence"],
                          validated["evidence_head_sha256"])
    except FloorWriterError as exc:
        return _refusal(exc.reason, exc.detail)


# ---------------------------------------------------------------------------
# §1.7 — the Linux transport. The socket's DIRECTORY is the server authentication.
# ---------------------------------------------------------------------------

#: The Architect's standing constraint on the amended layout, kept as code rather than as a
#: remembered intention: a corrupt authoritative document is a REFUSAL, and it is never repaired
#: by rebuilding a roster from whatever files happen to exist. Healing from the directory would
#: reintroduce, through the back door, exactly the directory-derived roster the ruling refused —
#: the explicit roster would stop being the authority the moment it disagreed with the filesystem.
#: There is deliberately no rebuild path in this module. Restoring a damaged store is a
#: provisioning act by the machine administrator, outside this service.
NEVER_HEAL_FROM_DIRECTORY = True

#: §1.7 / B4. The socket's parent is owned by the Floor Writer and **not writable** by anyone
#: else — that is what stops another principal replacing the endpoint, and it is the server
#: authentication the design specifies. The caller needs only to TRAVERSE it, so group execute is
#: granted and group write is not.
#:
#: The **setgid** bit is not decoration. A socket this service binds inherits the service's own
#: primary group, and a process cannot ``chgrp`` a file to a group it is not a member of — so
#: without setgid the endpoint comes up owned ``service:service`` at :data:`SOCKET_MODE` 0770 and
#: the caller, whose only claim is the CALLER group, gets ``other`` = 0 and cannot connect. That
#: is not a theory: a four-account run produced exactly that ``scope_unavailable`` on every probe.
#: setgid makes the directory's group the group of what is created in it, which is the same
#: mechanism `engine/ci/isolation_proof.sh` uses on the protected store (2770).
SOCKET_DIR_MODE = 0o2750
#: The socket itself is group-accessible, because connecting requires write permission on the
#: socket and the caller is a DIFFERENT principal by construction. The first attempt used 0700
#: here; a two-account measurement showed that refuses the service's own intended caller with
#: EACCES, so the service failed closed permanently instead of working. The boundary is the
#: directory, not this mode.
SOCKET_MODE = 0o770


def bind(socket_path: pathlib.Path) -> "socket.socket":
    """Bind the AF_UNIX endpoint, having first proved the directory that holds it is protected.

    Order matters: custody is proved BEFORE the socket exists. A socket that exists is a promise,
    and a service that cannot show its endpoint is unreplaceable must not make one.
    """
    require_linux("cannot bind the Floor Writer socket")
    directory = socket_path.parent
    require_private_directory(directory, "the Floor Writer socket directory")
    try:
        if socket_path.exists():
            socket_path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(socket_path))
        os.chmod(socket_path, SOCKET_MODE)
        server.listen(16)
    except OSError as exc:
        raise FloorWriterError(
            "scope_unavailable", f"cannot bind the Floor Writer endpoint: {exc}") from exc
    return server


def read_peer_uid(sock: "socket.socket") -> int:
    """The connecting peer's uid, from the kernel, captured at accept time.

    ``SO_PEERCRED`` yields ``struct ucred {pid, uid, gid}``, unpacked as ``=III``. Not
    caller-supplied and not spoofable over the wire — the ``isolated_signer_server.py`` shape the
    design names. Off Linux this fails closed so the caller DENIES rather than trusting an
    unauthenticated peer.
    """
    require_linux("cannot authenticate the peer")
    ucred = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("=III"))
    _pid, uid, _gid = struct.unpack("=III", ucred)
    return uid


def _read_frame(sock: "socket.socket") -> bytes:
    """One length-prefixed frame, bounded at :data:`MAX_FLOOR_FRAME_BYTES` (§1.7).

    Fail-closed on a short header, a zero or oversize declared length, and a truncated body. A
    frame at exactly the cap is accepted: §7's eighth negative tests the boundary on both sides of
    the number, so the comparison is strictly greater-than.
    """
    header = _recv_exactly(sock, LENGTH_PREFIX_BYTES)
    if len(header) != LENGTH_PREFIX_BYTES:
        raise FloorWriterError("malformed", "short length prefix")
    length = int.from_bytes(header, "big")
    if length == 0:
        raise FloorWriterError("malformed", "empty frame rejected")
    if length > MAX_FLOOR_FRAME_BYTES:
        raise FloorWriterError(
            "oversize", f"frame length {length} exceeds the bound {MAX_FLOOR_FRAME_BYTES}")
    body = _recv_exactly(sock, length)
    if len(body) != length:
        raise FloorWriterError("malformed", "truncated frame body")
    return body


def _recv_exactly(sock: "socket.socket", n: int) -> bytes:
    chunks = []
    got = 0
    while got < n:
        chunk = sock.recv(n - got)
        if not chunk:
            break
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)


def _write_frame(sock: "socket.socket", payload: bytes) -> None:
    if len(payload) > MAX_FLOOR_FRAME_BYTES:
        raise FloorWriterError("internal", "reply exceeds the frame bound")
    sock.sendall(len(payload).to_bytes(LENGTH_PREFIX_BYTES, "big") + payload)


def serve_connection(sock: "socket.socket", config: ServiceConfig) -> Dict[str, Any]:
    """Authenticate the peer, read one framed request, answer it, and return what was sent.

    §7's seventh negative: an unauthenticated peer is refused **before a frame is read**. The uid
    is taken from the kernel first, and a socket that cannot say who is on the other end never
    gets to send bytes into the parser.
    """
    try:
        peer_uid = read_peer_uid(sock)
    except (FloorWriterError, OSError):
        reply = _refusal("peer_denied", "the peer could not be authenticated")
        _try_send(sock, reply)
        return reply
    try:
        payload = _read_frame(sock)
    except FloorWriterError as exc:
        reply = _refusal(exc.reason, exc.detail)
        _try_send(sock, reply)
        return reply
    except OSError as exc:
        reply = _refusal("malformed", f"unreadable frame: {exc}")
        _try_send(sock, reply)
        return reply
    try:
        request = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        reply = _refusal("malformed", f"request is not UTF-8 JSON: {exc}")
        _try_send(sock, reply)
        return reply
    reply = handle(request, config=config, peer_uid=peer_uid)
    _try_send(sock, reply)
    return reply


def _try_send(sock: "socket.socket", reply: Mapping[str, Any]) -> None:
    try:
        _write_frame(sock, json.dumps(reply, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    except (FloorWriterError, OSError):
        # The verdict already happened. A peer that hung up does not un-commit a floor, and it
        # does not get a second decision either — its retry is answered `idempotent`, which is
        # what §7's fourth negative is for.
        pass


def serve_forever(server: "socket.socket", config: ServiceConfig) -> None:  # pragma: no cover
    """The serial accept loop. §1.9: one writer process, so this loop IS the serialization."""
    require_linux("cannot serve floor advancement")
    while True:
        try:
            sock, _ = server.accept()
        except OSError as exc:
            if exc.errno == errno.EINTR:
                continue
            raise
        try:
            sock.settimeout(CONNECTION_BUDGET_S)
            serve_connection(sock, config)
        finally:
            try:
                sock.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# The client seam the completion process uses (§1.3, §1.4)
# ---------------------------------------------------------------------------


def _exchange(endpoint: pathlib.Path, request: Mapping[str, Any]) -> Dict[str, Any]:
    """One request, one reply, over a fresh connection. Every failure raises.

    §1.4 / §7 negative 1: an unreachable service, a timeout, a malformed reply and a refusal are
    all refusals to the caller, and **none of them may read as "no floor required"**. That
    coercion is the R-06 defect, and it is the constraint the Owner attached to the decision.
    """
    require_linux("cannot reach the Floor Writer")
    payload = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_FLOOR_FRAME_BYTES:
        raise FloorWriterError("oversize", "the request exceeds the frame bound")
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(CONNECTION_BUDGET_S)
        sock.connect(str(endpoint))
    except OSError as exc:
        raise FloorWriterError(
            "scope_unavailable",
            f"the Floor Writer is unreachable ({exc.strerror}). The floor cannot be advanced, so "
            "this completion is not verified — this is NOT 'no floor required'") from exc
    try:
        _write_frame(sock, payload)
        body = _read_frame(sock)
    except (FloorWriterError, OSError) as exc:
        detail = exc.detail if isinstance(exc, FloorWriterError) else str(exc)
        raise FloorWriterError("scope_unavailable",
                               f"the Floor Writer exchange failed: {detail}") from exc
    finally:
        try:
            sock.close()
        except OSError:
            pass
    try:
        reply = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise FloorWriterError(
            "malformed", f"the Floor Writer's reply is not UTF-8 JSON: {exc}") from exc
    if not isinstance(reply, dict):
        raise FloorWriterError("malformed", "the Floor Writer's reply is not a JSON object")
    if reply.get("ok") is not True:
        reason = reply.get("reason")
        raise FloorWriterError(
            reason if reason in REFUSALS else "internal",
            f"the Floor Writer refused: {reason}: {reply.get('detail')}")
    if reply.get("protocol") != FLOOR_PROTOCOL or reply.get("op") != request["op"]:
        raise FloorWriterError(
            "malformed", "the reply is for a different protocol or operation than was asked")
    generation = reply.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise FloorWriterError(
            "malformed",
            "the reply carries no provisioning generation; §1.10 serves one with every reply so a "
            "re-provisioned floor is visibly new rather than silently empty")
    return reply


def client_get(endpoint: pathlib.Path, task_id: str) -> Tuple[int, Optional[str], bool, int]:
    """``(head_sequence, evidence_head_sha256, known, generation)``.

    §1.3: this number is a courtesy. A client that ignores it still cannot advance below the
    floor, because ``floor.advance`` re-checks against the store the service owns.
    """
    reply = _exchange(endpoint, {"op": OP_GET, "protocol": FLOOR_PROTOCOL, "task_id": task_id})
    head = reply.get("head_sequence")
    if isinstance(head, bool) or not isinstance(head, int) or head < 0:
        raise FloorWriterError("malformed", "floor.get returned no usable head_sequence")
    digest = reply.get("evidence_head_sha256")
    if digest is not None and (not isinstance(digest, str) or not _SHA256.fullmatch(digest)):
        raise FloorWriterError("malformed", "floor.get returned a malformed head digest")
    return head, digest, bool(reply.get("known")), reply["generation"]


def client_advance(endpoint: pathlib.Path, task_id: str, head_sequence: int,
                   digest: str) -> Dict[str, Any]:
    """Ask the service to advance, and accept nothing that is not the committed answer.

    The reply must name the floor that was asked for and the head it was taken against; a service
    that answered about something else is not evidence that this advancement happened.
    """
    reply = _exchange(endpoint, {"op": OP_ADVANCE, "protocol": FLOOR_PROTOCOL, "task_id": task_id,
                                 "head_sequence": head_sequence,
                                 "evidence_head_sha256": digest})
    if reply.get("outcome") not in (OUTCOME_ADVANCED, OUTCOME_IDEMPOTENT):
        raise FloorWriterError("malformed", f"unknown outcome {reply.get('outcome')!r}")
    if reply.get("head_sequence") != head_sequence:
        raise FloorWriterError(
            "malformed",
            f"the reply reports floor {reply.get('head_sequence')} for a request of "
            f"{head_sequence}: the committed floor is not the floor asked for")
    if reply.get("evidence_head_sha256") != digest:
        raise FloorWriterError("malformed",
                               "the reply binds a different signed head than the request")
    return reply
