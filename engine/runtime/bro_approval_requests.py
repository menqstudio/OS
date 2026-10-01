"""The desktop asks, the engine records, and nothing here decides. `T-021b`.

WHY THIS IS ITS OWN MODULE. `bro_control_room_api.py` opens by stating what it is:
"Nothing here decides anything. No approval is granted, no verdict is issued, no state is
written." That property is worth more than the convenience of putting a write beside a read,
so the write lives here, in a file whose own header says what it does write and what it
cannot change.

WHAT IT WRITES. One line, appended to a hash-chained log, saying that a document arrived. Not
a state transition -- the approval queue the cockpit reads is DERIVED state
(`bro_control_room_api._governance_approval_queue`: "a pending approval IS a task whose latest
transition parked it in an approval state"), so nothing written here can move a task. The
artifact that moves one is `control-room-command.schema.json`, which carries `key_id` and a
detached Ed25519 signature the engine verifies. That is the whole separation: the desktop
cannot mint that, and a record of an ask is not an ask being granted.

THE FIVE OBLIGATIONS this module exists to discharge, fixed by
`docs/design/T-021_SCHEMA_AUDIT.md` BEFORE it was written, for the reason
`docs/OWNER_ACTION_REQUIRED.md` gives about the invariants above them: so the test is not
designed by whoever is trying to pass it.

  O-1  a repeated `request_id` is recorded as a DUPLICATE ask, never as a second decision,
       and the reply says which
  O-2  a request whose `expected_task_state` disagrees with what the engine holds is refused
       BY NAME, so a stale cockpit cannot ask about a task that has moved on
  O-3  `requested_at_epoch` is recorded as CLAIMED, beside the engine's own receive time
  O-4  `evidence_refs` resolve only inside the engine's own store; an unresolvable ref is
       refused by name rather than fetched
  O-5  the caller reads through the framed readers (`brops_protocol.MAX_FRAME_BYTES`), which
       is the transport's obligation and is asserted where the transport is wired

FAIL-CLOSED ON ITS OWN VALIDATOR. The schema is the single source
(`contracts/approval-request.schema.json`, vendored byte-identical into `engine/schemas/`), so
this module validates against that file rather than restating its rules in code, where the two
would drift. If `jsonschema` is not importable it REFUSES and says so: "I could not check" and
"it is fine" are different answers, and a request path that accepts a document it could not
validate is the shape this repository refuses.

REFUSALS ARE DOCUMENTS, NOT EXCEPTIONS. The caller is a request/reply transport that must
always emit a reply, and an exception there would surface as "the engine is unreachable" --
reporting a transport failure for the engine refusing with a reason worth reading. Same rule,
and same shape, as the governance read's refusals. A refusal carries no `recorded` key at all,
so "I did not record this" cannot be read as "recorded, and it changed nothing".
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pathlib
import time
from typing import Any, Callable, Iterator, Mapping

#: The wire contract. Held as literals here AND in the bridge, with a test asserting the two are
#: equal, exactly as `brops.governance-read.v1` is -- the bridge has to be able to refuse when this
#: module cannot even be imported, which is precisely when its constants are out of reach.
APPROVAL_REQUEST_PROTOCOL = "brops.approval-request.v1"
APPROVAL_REQUEST_OP = "approval.request"

#: Reply protocol. A DIFFERENT name from the request's, because a reply that reused it could be
#: replayed back into this function as a request.
APPROVAL_REPLY_PROTOCOL = "brops.approval-request-reply.v1"

#: The log, inside the runtime's own state directory. One file, append-only, hash-chained.
LOG_NAME = "approval-requests.jsonl"

SCHEMA_REL = ("schemas", "approval-request.schema.json")


#: Where the Windows writer lock sits: one byte far past any content. A byte-range lock is
#: MANDATORY there, so locking byte 0 of the log would stop this module's own reads of it;
#: a byte nobody reads serializes writers and blocks nothing. (POSIX locks the whole file
#: advisorily and needs no offset.)
_LOCK_OFFSET = 0x4000_0000

#: How long a Windows writer waits for that byte before refusing. (POSIX `flock` blocks in
#: the kernel and is released when the holder exits, so it needs no deadline.)
_LOCK_TIMEOUT_SECONDS = 10


class ApprovalRequestError(Exception):
    """Raised only for a programming error in a caller, never for a bad request."""


class _LogUnlockable(Exception):
    """The log could not be locked for writing. `record` turns this into a refusal."""


def _platform_name() -> str:
    return os.name


@contextlib.contextmanager
def _write_lock(path: pathlib.Path) -> Iterator[Any]:
    """Hold the log exclusively across verify-read-append, and yield the handle to append to.

    `record` reads the whole log, derives `sequence` and `previous_sha256` from what it read,
    and only then appends. Unlocked, two asks arriving together both read N lines and both
    write line N+1 chained to line N: the chain forks, `verify_chain` fails from then on, and
    every later ask is refused until the file is repaired by hand. The lock makes
    read-derive-append one step.

    It is taken on the log file ITSELF, not on a lock file beside it: the only thing this
    module writes is that log, and a test holds it to that. An advisory lock rather than an
    `O_EXCL` lock file for the reason `bro_completion._floor_write_lock` gives — the kernel
    drops it when the holder dies, so a crash cannot leave the log permanently unwritable.

    A platform with neither primitive REFUSES: an unserialized append is the defect.
    """
    with open(path, "ab", buffering=0) as handle:
        if _platform_name() == "posix":
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield handle
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        elif _platform_name() == "nt":
            import msvcrt

            # LK_NBLCK in a short loop rather than LK_LOCK, which sleeps a whole second
            # between its ten attempts: the lock is held for one append. A writer that
            # still cannot take it must not proceed unlocked.
            deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
            while True:
                os.lseek(handle.fileno(), _LOCK_OFFSET, os.SEEK_SET)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise _LogUnlockable(f"another writer holds it ({exc})") from exc
                    time.sleep(0.01)
            try:
                yield handle
            finally:
                os.lseek(handle.fileno(), _LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            raise _LogUnlockable(
                f"this runtime has no way to serialize two writers on {_platform_name()}")


def _sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _refusal(request: Any, reason: str) -> dict[str, Any]:
    """The engine refusing, in a document with no field that could read as success.

    Note what is absent: no `recorded`, no `sequence`, no `entry_sha256`. A consumer reaching for
    any of them finds nothing to read rather than a falsy value to believe.
    """
    return {
        "protocol": APPROVAL_REPLY_PROTOCOL,
        "schema": 1,
        "ok": False,
        "op": APPROVAL_REQUEST_OP,
        "request_id": request.get("request_id") if isinstance(request, dict) else None,
        "reason": reason,
    }


class ApprovalRequestLog:
    """The append-only record of asks that arrived, and the only thing this path writes.

    Every input the caller cannot be trusted to compute is passed in as a seam rather than read
    from a runtime this module would then depend on:

      `task_states`  what the engine holds, per task id. O-2 is decided against this mapping.
      `evidence_has` whether the engine's own store holds a ref. O-4 is decided by this callable.
      `now_epoch`    the engine's clock, supplied by the caller that owns it. O-3 records it
                     beside the requester's claim and never instead of it.
    """

    def __init__(self, state_dir: pathlib.Path, engine_root: pathlib.Path):
        self.state_dir = pathlib.Path(state_dir)
        self.engine_root = pathlib.Path(engine_root)

    # -- the log ---------------------------------------------------------------------------
    @property
    def path(self) -> pathlib.Path:
        return self.state_dir / LOG_NAME

    def entries(self) -> list[dict[str, Any]]:
        """Every recorded line, in order. A malformed line raises rather than being skipped."""
        if not self.path.exists():
            return []
        out = []
        for n, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ApprovalRequestError(f"{self.path}:{n} is not a JSON object: {exc}") from exc
        return out

    def chain_head(self) -> str:
        entries = self.entries()
        return entries[-1]["entry_sha256"] if entries else ""

    def verify_chain(self) -> None:
        """Re-derive every link. Raises on the first break, naming the line."""
        prev = ""
        for n, entry in enumerate(self.entries(), 1):
            if entry.get("previous_sha256") != prev:
                raise ApprovalRequestError(
                    f"{self.path}:{n} says previous_sha256={entry.get('previous_sha256')!r}, "
                    f"the line before hashes to {prev!r}")
            body = {k: v for k, v in entry.items() if k != "entry_sha256"}
            if entry.get("entry_sha256") != _sha256(body):
                raise ApprovalRequestError(f"{self.path}:{n} does not hash to its own digest")
            prev = entry["entry_sha256"]

    # -- validation ------------------------------------------------------------------------
    def _schema(self) -> dict[str, Any]:
        return json.loads((self.engine_root.joinpath(*SCHEMA_REL)).read_text(encoding="utf-8"))

    def _schema_errors(self, request: Any) -> list[str] | None:
        """Schema errors, or None when the validator itself is unavailable."""
        try:
            import jsonschema
        except ImportError:
            return None
        schema = self._schema()
        cls = jsonschema.validators.validator_for(schema)
        cls.check_schema(schema)
        return [e.message for e in cls(schema).iter_errors(request)]

    # -- the entry point -------------------------------------------------------------------
    def record(self, request: Any, *, now_epoch: int,
               task_states: Mapping[str, str],
               evidence_has: Callable[[str], bool] | None = None) -> dict[str, Any]:
        """Record one ask, or refuse it. Always returns a reply document."""
        if not isinstance(request, dict):
            return _refusal({}, "an approval request must be a JSON object")

        errors = self._schema_errors(request)
        if errors is None:
            return _refusal(request,
                            "this engine cannot validate an approval request: the `jsonschema` "
                            "dependency is not importable, and a request path that accepts a "
                            "document it could not check is worse than one that refuses")
        if errors:
            return _refusal(request, "the request does not satisfy "
                                     f"approval-request.schema.json: {'; '.join(sorted(errors))}")

        task_id = request["task_id"]
        if task_id not in task_states:
            return _refusal(request, f"the engine has no task {task_id!r}, so there is nothing to "
                                     f"ask about")

        held = task_states[task_id]
        if held != request["expected_task_state"]:
            # O-2. Named on both sides, because "refused" without the two states is a refusal the
            # reader cannot act on.
            return _refusal(request, f"task {task_id!r} is in state {held!r} and the request "
                                     f"expects {request['expected_task_state']!r}; a stale ask is "
                                     f"refused rather than recorded against a task that moved on")

        refs = list(request.get("evidence_refs") or [])
        if refs:
            if evidence_has is None:
                return _refusal(request, "this engine cannot resolve evidence references, so a "
                                         "request carrying them is refused rather than recorded "
                                         "with refs nobody checked")
            missing = [r for r in refs if not evidence_has(r)]
            if missing:
                # O-4. Resolved inside the engine's own store; never fetched.
                return _refusal(request, "the engine's evidence store does not hold "
                                         f"{', '.join(repr(m) for m in sorted(missing))}; a "
                                         f"reference is resolved inside this engine or refused")

        self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            with _write_lock(self.path) as handle:
                try:
                    self.verify_chain()
                    recorded = self.entries()              # read once: the log is the same file
                except ApprovalRequestError as exc:
                    # A log that does not verify is not this caller's programming error and
                    # not a bad request: it is the engine unable to say what came before, and
                    # the rule at the top of this file is that a refusal is a document.
                    return _refusal(request, "the engine's approval-request log does not "
                                             f"verify, so nothing can be appended to it: {exc}")
                previous = recorded[-1]["entry_sha256"] if recorded else ""
                duplicate = request["request_id"] in {
                    e["request"]["request_id"] for e in recorded}                       # O-1

                body = {
                    "sequence": len(recorded) + 1,
                    "previous_sha256": previous,
                    "received_at_epoch": int(now_epoch),   # O-3, the engine's own clock
                    "claimed_at_epoch": int(request["requested_at_epoch"]),
                    "duplicate": duplicate,
                    "requester_authenticated": False,
                    "task_state_when_received": held,
                    "request": request,
                }
                entry = dict(body, entry_sha256=_sha256(body))
                line = json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
                handle.write(line.encode("utf-8"))
        except _LogUnlockable as exc:
            return _refusal(request, "the engine's approval-request log cannot be locked for "
                                     f"writing, and an unserialized append forks its chain: {exc}")

        return {
            "protocol": APPROVAL_REPLY_PROTOCOL,
            "schema": 1,
            "ok": True,
            "op": APPROVAL_REQUEST_OP,
            "request_id": request["request_id"],
            "recorded": True,
            "duplicate": duplicate,
            "sequence": entry["sequence"],
            "entry_sha256": entry["entry_sha256"],
            "chain_head_sha256": entry["entry_sha256"],
            "requester_authenticated": False,
            "task_state_when_received": held,
            # The sentence that keeps a reply from being read as a decision. There is deliberately
            # no `granted`, `disposition`, `verdict` or `state` field to read instead of it.
            "adjudicated": False,
            "note": ("recorded, not adjudicated: only a signed owner control-room command decides, "
                     "and this engine has not been asked to issue one"),
        }
