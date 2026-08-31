"""**Floor Writer** — the only principal permitted to mutate the per-task anti-rollback floor.

# The defect this closes

``bro_completion``'s evidence-head floor asked two things of the directory holding its marks
and the two had **no intersection**: ``_refuse_self_owned_floor`` demands a directory the
policed account cannot write, and ``_advance_head_floor`` wrote the mark *in that same
account's process*. The only satisfiable posture was
``BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged``, which short-circuits **every** custody rule
in the runtime rather than only this one. That is Owner decision **1b** and roadmap §I, and the
design is ``docs/design/FLOOR_WRITER_SERVICE_DESIGN.md`` (PR #112, merged; Architect design
audit completed; five rulings issued; **this implementation is not Architect-approved**).

# What the Architect ruled, and what each ruling forced here

**R1 — the floor stays PER-TASK.** The authoritative state keeps ``{task_id}.floor.json`` and
the ``_index.json`` roster, byte-shape unchanged, in protected custody belonging to the
Supervisor security domain. It is **NOT** merged into the supervisor's per-install
``evidence-head-sequence.json`` ceiling: those two counters live in different sequence domains,
and unifying them refuses every second task in a deployment with ``EvidenceFork`` — the reason
``bro_completion._head_floor_dir`` documents at length, established by running it.
*"Supervisor custody domain"* says who OWNS and PROTECTS the state; *"Floor Writer principal"*
says who may MUTATE it. Those are different sentences and both are true.

**R2 — authority is not reachability.** A caller is authorized by an authenticated peer
principal (``SO_PEERCRED`` uid, the same primitive ``governed_supervisor_server`` uses),
a served scope binding (``install_id``), and a bound protocol version — never by being able to
open the socket. Every request is validated exhaustively: an unknown field is a refusal, not
something dropped.

**R3 — a distinct runtime principal.** Not a helper of the completion process and not a helper
of the supervisor. It has independent authority to mutate protected anti-rollback state, so it
is named as its own principal in the architecture documents.

**R4 — independent custody, fail closed.** The store is refused unless the writer owns it and
the CALLER cannot write it. Unavailable, unreachable, unauthenticated, unparseable, corrupt,
out-of-scope, wrong protocol — every one of them is a refusal, and the caller may not report a
governed completion trusted or committed on any of them.

**R5 — monotonic, atomic, and idempotency that says so.**
``new > current`` advances and returns ``advanced``; ``new == current`` mutates nothing and
returns ``already_committed``, which is a different word on the wire on purpose; ``new <
current`` is refused and mutates nothing. Before this, an equal head was a silent ``return``
that a caller could not distinguish from a fresh advancement.

# Linux only, and it says so rather than pretending

Peer authentication is ``SO_PEERCRED``. There is no equivalent-strength mechanism wired for
Windows or macOS here, so on those platforms this service **refuses to start and refuses to
serve**. A fake-equivalent — trusting a path, a token file, or a parent process — would be a
weaker security property wearing the same name, which is worse than an unsupported platform
that stops. When a Windows transport with the same property exists, it gets its own module and
its own audit; it does not get this one's docstring.

# The critical section is compare + write + EVIDENCE

The advisory lock is held across the comparison, the authoritative write **and the construction
of the response**. Building the evidence after releasing the lock would let the response
describe a floor another writer had already moved: the number would be true when read and false
when sent, which is precisely the TOCTOU the lock exists to remove.

# Crash and restart, chosen rather than inherited

The roster is enrolled BEFORE the mark is renamed into place. A crash between them therefore
leaves a task the roster knows and no mark, which ``bro_completion._load_head_floor`` already
treats as a removed mark and refuses. That direction is deliberate and it has a cost, stated
here rather than discovered later: an interrupted advance leaves that task refusing until an
operator restores it. The other order — mark first — would let the same crash silently drop a
roster entry, which is a security property degrading quietly. Fail closed is the repository's
rule and this is what it costs.
"""

from __future__ import annotations

import errno
import json
import os
import pathlib
import re
import socket
import stat
import sys
import threading
from typing import Any, Dict, Mapping, Optional, Tuple

from bro_contracts import canonical_json_sha256
from governed_supervisor_server import (
    CONNECTION_BUDGET_S,
    MAX_FRAME_BYTES,
    ServerError,
    SocketPeerConn,
    read_frame,
    read_peercred_uid,
    write_frame,
)

#: The wire contract. A request that does not carry this exact string is refused before any
#: state is read: R2 makes protocol/version binding part of authority, not a courtesy.
FLOOR_PROTOCOL = "bridge.floor-advance.v1"

#: The one operation. A closed set, like the supervisor's: a sixth op there is a schema change
#: and a review, and the same rule applies to a second op here.
OP_ADVANCE_FLOOR = "advance-floor"

#: The exhaustive request shape. Unknown fields are refused rather than ignored — a caller
#: still speaking an older dialect must not believe its extra field was honoured.
_REQUEST_FIELDS = ("protocol", "install_id", "task_id", "head_sequence", "evidence_head_sha256")

#: Outcomes. Two successes that a reader must never confuse (R5).
OUTCOME_ADVANCED = "advanced"
OUTCOME_ALREADY_COMMITTED = "already_committed"

REFUSE_UNAUTHENTICATED = "unauthenticated_peer"
REFUSE_UNAUTHORIZED = "unauthorized_principal"
REFUSE_SCOPE_MISMATCH = "scope_mismatch"
REFUSE_PROTOCOL = "unsupported_protocol"
REFUSE_MALFORMED = "malformed_request"
REFUSE_ROLLBACK = "floor_rollback_refused"
REFUSE_CUSTODY = "custody_unsatisfied"
REFUSE_STATE_UNREADABLE = "authoritative_state_unreadable"
REFUSE_PLATFORM = "platform_unsupported"
#: Client-side: the writer could not be reached at all. Distinct from a refusal it issued,
#: because "it said no" and "it never answered" are different facts about a deployment.
REFUSE_UNREACHABLE = "floor_writer_unreachable"
#: Client-side: an answer arrived and did not bind to the request that produced it.
REFUSE_UNVERIFIED_REPLY = "reply_binding_unverified"

_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
#: A task id is an identifier, not a path. The floor's file name is derived from it, so a value
#: carrying a separator or a traversal segment could address a file outside the store — the one
#: input that turns a bounded write into an arbitrary one.
_TASK_ID = re.compile(r"\A[A-Za-z0-9._-]{1,128}\Z")
_INSTALL_ID = re.compile(r"\A[A-Za-z0-9._:-]{1,128}\Z")

#: Same file name the policed process already locks, so a deployment migrating to this service
#: does not end up with two lock regimes over one directory during the transition.
_FLOOR_LOCK = "_index.json.lock"
_FLOOR_INDEX = "_index.json"


class FloorWriterError(Exception):
    """A refusal, carrying the TYPED reason it will go on the wire as.

    The first version of this class carried only prose, and ``handle`` recovered the reason by
    matching substrings of the message. Two tests caught it immediately — a rollback and a
    changed-head-at-the-same-sequence both came out as ``malformed_request`` — and the defect is
    worse than the two cases it produced: the wire contract would drift every time somebody
    improved a sentence. The reason is data now, decided where the refusal is decided.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------
# Custody (R4)
# ---------------------------------------------------------------------------


def require_linux(what: str) -> None:
    """Refuse anywhere ``SO_PEERCRED`` is not the authentication primitive.

    Called at bind time AND before serving a connection, because a service that starts on an
    unsupported platform and refuses later has still advertised a socket it cannot police.
    """
    if sys.platform != "linux":
        raise FloorWriterError(
            REFUSE_PLATFORM,
            f"{what}: the Floor Writer authenticates peers with SO_PEERCRED, which requires "
            f"Linux; this platform is {sys.platform!r}. No equivalent-strength mechanism is "
            "wired here, and a weaker one under the same name would be worse than a stop")


def _stat_or_refuse(path: pathlib.Path) -> os.stat_result:
    try:
        return path.lstat()
    except OSError as exc:
        raise FloorWriterError(
            REFUSE_CUSTODY,
            f"cannot stat the authoritative floor store {path}: {exc}") from exc


def require_writer_custody(store: pathlib.Path, caller_uid: int) -> None:
    """The store must be the WRITER's, and the CALLER must not be able to write it.

    Both halves are load-bearing and they are different questions. A store the writer does not
    own is one it cannot promise to be the only mutator of. A store the caller can write makes
    the whole service theatre: the caller would not need to ask.

    Group and other write bits are refused too. "The caller's uid is not the owner" is not the
    property being checked — the property is that nothing but this principal can write, and a
    group-writable directory in a deployment where the caller shares the group satisfies the
    first and violates the second.
    """
    info = _stat_or_refuse(store)
    if not stat.S_ISDIR(info.st_mode):
        raise FloorWriterError(REFUSE_CUSTODY,
                               f"the authoritative floor store {store} is not a directory")
    if info.st_uid != os.geteuid():
        raise FloorWriterError(
            REFUSE_CUSTODY,
            f"the authoritative floor store {store} is owned by uid {info.st_uid}, not by the "
            f"Floor Writer principal (uid {os.geteuid()}): a store this principal does not own "
            "is one it cannot be the only mutator of")
    if info.st_uid == caller_uid:
        raise FloorWriterError(
            REFUSE_CUSTODY,
            f"the authoritative floor store {store} is owned by the CALLING principal "
            f"(uid {caller_uid}); a floor its own subject owns is not a floor")
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise FloorWriterError(
            REFUSE_CUSTODY,
            f"the authoritative floor store {store} is group- or world-writable "
            f"(mode {stat.S_IMODE(info.st_mode):04o}); least privilege means this principal "
            "and no other")


# ---------------------------------------------------------------------------
# Authoritative state
# ---------------------------------------------------------------------------


def _index_path(store: pathlib.Path) -> pathlib.Path:
    return store / _FLOOR_INDEX


def _load_index(store: pathlib.Path) -> set:
    """The roster of tasks that have ever been measured.

    An absent roster is an UNPROVISIONED store, not an empty one. Treating the two the same
    would let deleting one file restart every task's floor at zero, which is the attack the
    roster exists to catch.
    """
    path = _index_path(store)
    if not path.exists():
        raise FloorWriterError(
            REFUSE_STATE_UNREADABLE,
            f"the authoritative floor store {store} has no {_FLOOR_INDEX}: it is unprovisioned, "
            "and an unprovisioned floor is refused rather than started at zero")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        tasks = document["tasks"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise FloorWriterError(
            REFUSE_STATE_UNREADABLE,
            f"the floor roster {path} is unreadable; refusing rather than treating a damaged "
            f"anti-rollback record as absent: {exc}") from exc
    if not isinstance(tasks, list) or any(not isinstance(t, str) for t in tasks):
        raise FloorWriterError(REFUSE_STATE_UNREADABLE,
                               f"the floor roster {path} is not a list of task ids")
    return set(tasks)


def _load_floor(store: pathlib.Path, task_id: str) -> Tuple[int, Optional[str]]:
    """``(head_sequence, evidence_head_sha256)`` for one task, or ``(0, None)`` if genuinely new.

    The refusals mirror ``bro_completion._load_head_floor`` deliberately: the authoritative copy
    and the reader that still consults it must agree about what a damaged record means, or the
    two would disagree about whether a rollback happened.
    """
    known = _load_index(store)
    path = store / f"{task_id}.floor.json"
    if not path.exists():
        if task_id in known:
            raise FloorWriterError(
                REFUSE_STATE_UNREADABLE,
                f"the floor for {task_id} is missing but the roster still names the task: the "
                "mark was removed. Refusing rather than restarting the floor at zero")
        return 0, None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        recorded = record["head_sequence"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise FloorWriterError(
            REFUSE_STATE_UNREADABLE,
            f"the floor for {task_id} is unreadable; refusing rather than treating a damaged "
            f"anti-rollback record as absent: {exc}") from exc
    if isinstance(recorded, bool) or not isinstance(recorded, int) or recorded < 0:
        raise FloorWriterError(
            REFUSE_STATE_UNREADABLE,
            f"the floor for {task_id} is not a non-negative integer: {recorded!r}")
    digest = record.get("evidence_head_sha256") if isinstance(record, dict) else None
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise FloorWriterError(
            REFUSE_STATE_UNREADABLE,
            f"the floor for {task_id} records no signed head digest; a mark that cannot say "
            "which signed head it was taken against is not evidence of anything")
    return recorded, digest


#: In-process exclusion, per store, held UNDER the file lock.
#:
#: This exists because ``fcntl.lockf`` locks are owned by the PROCESS, not the thread: two
#: threads of one process both "acquire" the same lock and neither blocks. A concurrency test
#: found it immediately — eight threads racing one task left the floor at the LAST writer's
#: value, 2, instead of the highest, 12. A lost update, in the one place the whole service
#: exists to prevent.
#:
#: The two locks answer different questions and neither substitutes for the other. The file
#: lock excludes other PROCESSES (a legacy completion still writing, a second writer instance);
#: this one excludes other THREADS of this one. A service whose accept loop is serial does not
#: create the second case today, but "the current loop happens to be serial" is not a property
#: the correctness of an anti-rollback floor should rest on.
_THREAD_LOCKS: Dict[str, "threading.Lock"] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(store: pathlib.Path) -> "threading.Lock":
    key = str(store.resolve())
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[key] = lock
        return lock


class _FloorLock:
    """The whole compare → write → evidence critical section, over BOTH locks.

    An advisory lock on byte 0 of the roster, not a lock FILE: the kernel drops it when the
    holder dies, so a crash mid-advance cannot leave the floor permanently unwritable. An
    ``O_CREAT|O_EXCL`` lock file would, and that is a self-inflicted denial of every future
    completion on the install.

    The thread lock is taken FIRST and released LAST, so the ordering is the same on every
    path and cannot deadlock against itself.
    """

    def __init__(self, store: pathlib.Path) -> None:
        self._path = store / _FLOOR_LOCK
        self._fd: Optional[int] = None
        self._thread_lock = _thread_lock_for(store)

    def __enter__(self) -> "_FloorLock":
        import fcntl

        self._thread_lock.acquire()
        try:
            self._fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.lockf(self._fd, fcntl.LOCK_EX)
        except OSError as exc:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            self._thread_lock.release()
            raise FloorWriterError(
                REFUSE_STATE_UNREADABLE,
                f"cannot take the floor write lock {self._path}: {exc}") from exc
        return self

    def __exit__(self, *exc_info: Any) -> None:
        try:
            if self._fd is not None:
                import fcntl

                try:
                    fcntl.lockf(self._fd, fcntl.LOCK_UN)
                finally:
                    os.close(self._fd)
                    self._fd = None
        finally:
            self._thread_lock.release()


def advance(store: pathlib.Path, install_id: str, task_id: str, head_sequence: int,
            evidence_head_sha256: str, request_sha256: str,
            caller_uid: int) -> Dict[str, Any]:
    """Compare and advance atomically, and build the bound result inside the same lock (R5).

    Returns the response body. Raises :class:`FloorWriterError` for every case that is not an
    authoritatively committed floor — including a rollback attempt, which mutates nothing.
    """
    require_writer_custody(store, caller_uid)
    # Refuse an unprovisioned store BEFORE creating anything in it: the lock file must not
    # become the way an absent floor acquires a file and starts looking provisioned.
    _load_index(store)
    with _FloorLock(store):
        # Read INSIDE the lock. Reading outside it is the defect: the value compared would be
        # one another writer is free to have replaced before this one's rename lands.
        current, current_digest = _load_floor(store, task_id)
        if head_sequence < current:
            raise FloorWriterError(
                REFUSE_ROLLBACK,
                f"floor rollback refused for {task_id}: the authoritative floor is {current} "
                f"and the request asked for {head_sequence}. Nothing was written")
        if head_sequence == current:
            # R5: NOT a fresh advancement, and the wire says so. Bound to the authoritative
            # current state rather than to the request's claim about it.
            if current_digest != evidence_head_sha256:
                raise FloorWriterError(
                    REFUSE_STATE_UNREADABLE,
                    f"the floor for {task_id} stands at {current} against signed head "
                    f"{current_digest}, and this request presents {evidence_head_sha256} for the "
                    "same sequence: a head that changed without advancing is not a replay")
            return _result(OUTCOME_ALREADY_COMMITTED, install_id, task_id, current,
                           current_digest, request_sha256)
        # Enrol in the roster FIRST — see the module docstring on crash order.
        known = _load_index(store)
        if task_id not in known:
            _atomic_write(store, _FLOOR_INDEX, {"tasks": sorted(known | {task_id})})
        _atomic_write(store, f"{task_id}.floor.json",
                      {"task_id": task_id, "head_sequence": head_sequence,
                       "evidence_head_sha256": evidence_head_sha256})
        # Read the committed state back before saying it was committed. The response must
        # describe the file, not the intention: a write that landed differently — a full disk
        # truncating the rename's target, a store swapped underneath — must not be reported as
        # the requested advancement.
        committed, committed_digest = _load_floor(store, task_id)
        if committed != head_sequence or committed_digest != evidence_head_sha256:
            raise FloorWriterError(
                REFUSE_STATE_UNREADABLE,
                f"the floor for {task_id} reads back as {committed}/{committed_digest} after a "
                f"write of {head_sequence}/{evidence_head_sha256}: refusing to report an "
                "advancement that is not what the authoritative state holds")
        return _result(OUTCOME_ADVANCED, install_id, task_id, committed, committed_digest,
                       request_sha256)


def _atomic_write(store: pathlib.Path, name: str, document: Mapping[str, Any]) -> None:
    """Write via a temp file and ``rename``, so a crash cannot leave a truncated record that
    the loader would (correctly) refuse forever. ``fsync`` on the file and the directory: a
    rename that is visible but not durable is exactly the ambiguous committed state this
    service must not produce."""
    final = store / name
    temporary = store / (name + ".tmp")
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, payload.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, final)
        dir_fd = os.open(store, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        raise FloorWriterError(REFUSE_STATE_UNREADABLE,
                               f"cannot record {final}: {exc}") from exc


def _result(outcome: str, install_id: str, task_id: str, floor: int, digest: str,
            request_sha256: str) -> Dict[str, Any]:
    """The bound success evidence (R2, and the Architect's four success criteria).

    * *handled by the authoritative principal* — ``writer_uid`` is this process's effective uid,
      and the caller reads the server's uid independently through ``SO_PEERCRED`` on its own
      side of the same socket. Neither party takes the other's word for who it is.
    * *the intended scope* — ``install_id`` is echoed from a request that was already checked
      against the writer's served scope, so echoing it cannot widen anything.
    * *what was committed* — ``floor`` and ``evidence_head_sha256`` are read back from the
      authoritative state, not copied from the request.
    * *this request instance* — ``request_sha256`` binds the response to the exact canonical
      request bytes, so a response cannot be replayed against a different advancement.

    There is deliberately no ``success: true``. The outcome is a word with two values a reader
    must tell apart, and every field above is a fact rather than an assertion that facts were
    checked.
    """
    body = {
        "protocol": FLOOR_PROTOCOL,
        "op": OP_ADVANCE_FLOOR,
        "outcome": outcome,
        "install_id": install_id,
        "task_id": task_id,
        "floor": floor,
        "evidence_head_sha256": digest,
        "request_sha256": request_sha256,
        "writer_uid": os.geteuid(),
    }
    body["result_sha256"] = canonical_json_sha256(body)
    return body


# ---------------------------------------------------------------------------
# The door (R2)
# ---------------------------------------------------------------------------


def _refusal(reason: str, detail: str) -> Dict[str, Any]:
    return {"protocol": FLOOR_PROTOCOL, "op": OP_ADVANCE_FLOOR, "ok": False,
            "reason": reason, "detail": detail}


def validate_request(request: Any) -> Dict[str, Any]:
    """Exhaustive shape and value validation, before any state is touched.

    Every branch here is reached before the store is opened. A malformed request must not be
    able to cause a read of the authoritative state, let alone a write.
    """
    if not isinstance(request, dict):
        raise FloorWriterError(REFUSE_MALFORMED, "request is not a JSON object")
    allowed = {"op"} | set(_REQUEST_FIELDS)
    extra = set(request.keys()) - allowed
    if extra:
        raise FloorWriterError(REFUSE_MALFORMED,
                               f"request has unexpected field(s) {sorted(extra)}")
    missing = allowed - set(request.keys())
    if missing:
        raise FloorWriterError(REFUSE_MALFORMED,
                               f"request is missing field(s) {sorted(missing)}")
    if request["op"] != OP_ADVANCE_FLOOR:
        raise FloorWriterError(REFUSE_PROTOCOL, f"unknown op {request['op']!r}")
    if request["protocol"] != FLOOR_PROTOCOL:
        raise FloorWriterError(
            REFUSE_PROTOCOL,
            f"unsupported protocol {request['protocol']!r}; this writer speaks "
            f"{FLOOR_PROTOCOL!r} and nothing else")
    task_id = request["task_id"]
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise FloorWriterError(
            REFUSE_MALFORMED,
            "task_id must be an identifier of 1..128 chars from [A-Za-z0-9._-]; the floor's "
            "file name is derived from it, so a separator or a traversal segment would address "
            "a file outside the store")
    install_id = request["install_id"]
    if not isinstance(install_id, str) or not _INSTALL_ID.fullmatch(install_id):
        raise FloorWriterError(REFUSE_MALFORMED,
                               "install_id must be an identifier of 1..128 chars")
    head = request["head_sequence"]
    if isinstance(head, bool) or not isinstance(head, int) or head < 1:
        raise FloorWriterError(
            REFUSE_MALFORMED,
            f"head_sequence must be a positive integer, not {head!r}; sequence 0 is the absence "
            "of a measured head and cannot be advanced to")
    digest = request["evidence_head_sha256"]
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise FloorWriterError(REFUSE_MALFORMED,
                               "evidence_head_sha256 must be 64 lowercase hex characters")
    return request


def request_digest(request: Mapping[str, Any]) -> str:
    """The canonical digest of the request, computed by BOTH ends from the same primitive so
    the binding in the response is checkable rather than asserted."""
    return canonical_json_sha256(dict(request))


def handle(request: Any, *, store: pathlib.Path, served_install_id: str,
           allowed_caller_uids: frozenset, caller_uid: Optional[int]) -> Dict[str, Any]:
    """One request, one verdict. Never raises for a caller's fault: it returns a refusal body.

    ``caller_uid`` is ``None`` when peer authentication could not be performed at all — an
    unsupported platform, or a socket that yielded no credentials. That is refused first,
    because everything below it would otherwise be deciding on an unknown principal.
    """
    try:
        if caller_uid is None:
            return _refusal(REFUSE_UNAUTHENTICATED,
                            "the peer could not be authenticated; no principal, no authority")
        if caller_uid not in allowed_caller_uids:
            # Deliberately does not echo the allowlist: a refusal must not be an oracle for
            # which uid to become.
            return _refusal(REFUSE_UNAUTHORIZED,
                            f"uid {caller_uid} is not permitted to request floor advancement. "
                            "Reaching this socket is not authority")
        validated = validate_request(request)
        if validated["install_id"] != served_install_id:
            return _refusal(REFUSE_SCOPE_MISMATCH,
                            f"this writer serves one install and the request names another; "
                            "a floor advanced under the wrong scope is a floor advanced for "
                            "someone else")
        digest = request_digest(validated)
        return advance(store, validated["install_id"], validated["task_id"],
                       validated["head_sequence"], validated["evidence_head_sha256"],
                       digest, caller_uid)
    except FloorWriterError as exc:
        # The reason travels WITH the refusal. It is never recovered from the prose.
        return _refusal(exc.reason, exc.detail)


def serve_connection(conn: Any, *, store: pathlib.Path, served_install_id: str,
                     allowed_caller_uids: frozenset) -> Dict[str, Any]:
    """Read one framed request, answer it, and return what was sent — for the caller's log and
    for tests, which assert on the same object the peer received."""
    try:
        caller_uid = conn.peer_uid
    except Exception:  # pragma: no cover - a connection that cannot say who it is
        caller_uid = None
    try:
        payload = read_frame(conn, max_bytes=MAX_FRAME_BYTES)
    except (ServerError, OSError) as exc:
        reply = _refusal(REFUSE_MALFORMED, f"unreadable frame: {exc}")
        _try_write(conn, reply)
        return reply
    try:
        request = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        reply = _refusal(REFUSE_MALFORMED, f"request is not UTF-8 JSON: {exc}")
        _try_write(conn, reply)
        return reply
    reply = handle(request, store=store, served_install_id=served_install_id,
                   allowed_caller_uids=allowed_caller_uids, caller_uid=caller_uid)
    _try_write(conn, reply)
    return reply


def _try_write(conn: Any, reply: Mapping[str, Any]) -> None:
    try:
        write_frame(conn, json.dumps(reply, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                    max_bytes=MAX_FRAME_BYTES)
    except (ServerError, OSError):
        # The verdict already happened; a peer that hung up does not un-commit a floor, and it
        # does not get a second decision either.
        pass


def bind(socket_path: pathlib.Path) -> "socket.socket":
    """Bind the AF_UNIX socket, 0700, refusing anywhere peer authentication is unavailable."""
    require_linux("cannot bind the Floor Writer socket")
    try:
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        if socket_path.exists():
            socket_path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(socket_path))
        os.chmod(socket_path, 0o700)
        server.listen(16)
    except OSError as exc:
        raise FloorWriterError(REFUSE_PLATFORM,
                               f"cannot bind {socket_path}: {exc}") from exc
    return server


def serve_forever(server: "socket.socket", *, store: pathlib.Path, served_install_id: str,
                  allowed_caller_uids: frozenset) -> None:  # pragma: no cover - daemon loop
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
            conn = SocketPeerConn(sock)
            serve_connection(conn, store=store, served_install_id=served_install_id,
                             allowed_caller_uids=allowed_caller_uids)
        finally:
            try:
                sock.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# The client the completion path uses
# ---------------------------------------------------------------------------


def request_advance(socket_path: pathlib.Path, install_id: str, task_id: str,
                    head_sequence: int, evidence_head_sha256: str,
                    expected_writer_uid: Optional[int] = None) -> Dict[str, Any]:
    """Ask the Floor Writer to advance, and refuse anything that is not bound proof it did.

    The completion process calls this INSTEAD of writing the mark. Every failure mode —
    no socket, no answer, a refusal, an answer that does not bind to this request — raises,
    and the caller must not report a governed completion trusted on any of them.
    """
    require_linux("cannot request floor advancement")
    request = {
        "op": OP_ADVANCE_FLOOR,
        "protocol": FLOOR_PROTOCOL,
        "install_id": install_id,
        "task_id": task_id,
        "head_sequence": head_sequence,
        "evidence_head_sha256": evidence_head_sha256,
    }
    expected_digest = request_digest(request)
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(CONNECTION_BUDGET_S)
        sock.connect(str(socket_path))
    except OSError as exc:
        raise FloorWriterError(REFUSE_UNREACHABLE,
            f"the Floor Writer at {socket_path} is unreachable: {exc}. The floor cannot be "
            "advanced, so this completion is not trusted") from exc
    try:
        # The caller authenticates the SERVER, not only the reverse: the peer on the other end
        # of this socket must be the principal the deployment says owns the floor.
        served_by = read_peercred_uid(sock)
        if expected_writer_uid is not None and served_by != expected_writer_uid:
            raise FloorWriterError(REFUSE_UNVERIFIED_REPLY,
            f"the socket at {socket_path} is served by uid {served_by}, not by the "
                f"expected Floor Writer principal {expected_writer_uid}")
        conn = SocketPeerConn(sock)
        write_frame(conn, json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                    max_bytes=MAX_FRAME_BYTES)
        payload = read_frame(conn, max_bytes=MAX_FRAME_BYTES)
    except ServerError as exc:
        raise FloorWriterError(REFUSE_UNREACHABLE,
            f"floor advancement exchange failed: {exc}") from exc
    except OSError as exc:
        raise FloorWriterError(REFUSE_UNREACHABLE,
            f"floor advancement exchange failed: {exc}") from exc
    finally:
        try:
            sock.close()
        except OSError:
            pass
    try:
        reply = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise FloorWriterError(REFUSE_UNVERIFIED_REPLY,
            f"the Floor Writer's reply is not UTF-8 JSON: {exc}") from exc
    return verify_reply(reply, request, expected_digest, served_by,
                        expected_writer_uid=expected_writer_uid)


def verify_reply(reply: Any, request: Mapping[str, Any], expected_digest: str,
                 served_by: Optional[int],
                 expected_writer_uid: Optional[int] = None) -> Dict[str, Any]:
    """Check the reply against the request that produced it. Separate from the socket so the
    binding is testable without one, and so every field a caller relies on is checked in one
    named place rather than at the call sites."""
    if not isinstance(reply, dict):
        raise FloorWriterError(REFUSE_UNVERIFIED_REPLY,
            "the Floor Writer's reply is not a JSON object")
    if reply.get("ok") is False:
        raise FloorWriterError(REFUSE_UNVERIFIED_REPLY,
            f"floor advancement refused: {reply.get('reason')}: {reply.get('detail')}")
    body = {k: v for k, v in reply.items() if k != "result_sha256"}
    if reply.get("result_sha256") != canonical_json_sha256(body):
        raise FloorWriterError(REFUSE_UNVERIFIED_REPLY,
            "the Floor Writer's reply does not match its own digest")
    if reply.get("protocol") != FLOOR_PROTOCOL or reply.get("op") != OP_ADVANCE_FLOOR:
        raise FloorWriterError(REFUSE_UNVERIFIED_REPLY,
            "the reply is for a different protocol or operation")
    if reply.get("request_sha256") != expected_digest:
        raise FloorWriterError(REFUSE_UNVERIFIED_REPLY,
            "the reply does not bind to this request: it may be another advancement's answer")
    if reply.get("outcome") not in (OUTCOME_ADVANCED, OUTCOME_ALREADY_COMMITTED):
        raise FloorWriterError(REFUSE_UNVERIFIED_REPLY,
            f"unknown outcome {reply.get('outcome')!r}")
    for field in ("install_id", "task_id"):
        if reply.get(field) != request[field]:
            raise FloorWriterError(REFUSE_UNVERIFIED_REPLY,
            f"the reply's {field} is not the one requested")
    if reply.get("floor") != request["head_sequence"]:
        raise FloorWriterError(REFUSE_UNVERIFIED_REPLY,
            f"the reply reports floor {reply.get('floor')} for a request of "
            f"{request['head_sequence']}: the floor that was committed is not the floor asked for")
    if reply.get("evidence_head_sha256") != request["evidence_head_sha256"]:
        raise FloorWriterError(REFUSE_UNVERIFIED_REPLY,
            "the reply binds a different signed head than the request")
    if expected_writer_uid is not None and reply.get("writer_uid") != expected_writer_uid:
        raise FloorWriterError(REFUSE_UNVERIFIED_REPLY,
            "the reply names a different writer principal than expected")
    if served_by is not None and reply.get("writer_uid") != served_by:
        raise FloorWriterError(REFUSE_UNVERIFIED_REPLY,
            f"the reply claims writer uid {reply.get('writer_uid')} but the socket is served by "
            f"{served_by}: a principal that misreports itself is not one to trust a floor to")
    return reply
