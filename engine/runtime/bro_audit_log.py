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
signature comes from a signing command the DEPLOYMENT installs and names in
``BRO_AUDIT_ANCHOR_SIGNER`` (no person holds, mints or exports its key - the
signer service mints its own on first start), which lives outside this engine, runs under a
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
(1) It does not defend against a party who can make the deployment's signing command sign
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
writer does not hold - one held by another principal (under PR #78 a separate service
account the install provisions, never a person). The
acknowledgement ``BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged`` is exactly a
deployment saying it has no such separation to offer.

THE APPEND LOCK (T-156). ``append()`` is one critical section - read the chain, derive
``seq`` and ``prev_hash`` from its tail, append the record, replace the head, anchor - and
it runs under an exclusive lock the KERNEL owns: ``flock`` on POSIX, a byte-range lock on
Windows, held on a descriptor of ``<ledger>.append-lock`` beside the ledger for the whole
section. The lock is the kernel's record that this descriptor holds it; the FILE is only
something to hold it on, is never unlinked, and its existence means nothing.

What the lock guarantees. Two writers that both take it never interleave, across threads
and across processes, so the chain cannot fork. The wait is bounded by ``_LOCK_TIMEOUT``
and fails CLOSED: a LIVE holder that never releases makes the append refuse with
``AuditLockUnavailable``; it never proceeds unlocked and it never waits forever. A
platform or filesystem that offers no such lock, a lock path that is a symbolic link, and
a lock path that is not a regular file are refused the same way, before anything is
written.

THE ONE THING THAT WAS REFUSED AND IS NOW ACCEPTED. The lock used to be a lock FILE
created with ``O_CREAT|O_EXCL``. A holder that died left the file behind, and from then
on every append was refused until a person deleted it by hand - every allow that records
to this ledger became a deny. Now: a holder that DIES while holding the lock does not
strand the ledger. The kernel releases the lock with the process and the next append
succeeds. The old refusal protected nothing (the dead holder is not writing), it only
denied service. Every refusal that protects the ledger's CONTENT is kept, and one was
added - see (b) below.

WHAT A DEAD WRITER CAN LEAVE BEHIND, and the rule for each. ``append()`` writes in a fixed
order - the record line (the record and its newline written together, then fsync), then
the head (temp file, then an atomic rename), then the anchor - so a writer killed inside
the section leaves exactly one of:
  (a) nothing written. The next append proceeds.
  (b) a TORN record: part of a line and no newline after it. ``read_all`` - so ``verify()``
      and ``append()`` both - REFUSE with ``AuditTornTail``. Nothing repairs it: the bytes
      stay exactly as they are until an operator has looked, because dropping a partial
      record silently is dropping a record. ``append()`` also refuses, by the same name, a
      ledger whose last byte is not a newline even when that last line parses: appending to
      it would fuse two records into one unparsable line and destroy both (it did, before
      this change). That is the added refusal.
  (c) a COMPLETE record whose head never landed: the chain is exactly one correctly linked
      record longer than the head describes. (Head-without-record cannot happen: the record
      is on disk before the head is replaced.) ``verify()`` REFUSES it, as it always has,
      and now names it ``AuditHeadBehind`` instead of calling it a truncation, which it is
      not. The record is KEPT. ``append()`` checks the head under the lock (see below) and
      lets exactly this state through: it derives the new head from the chain it read, so
      the next append rolls the head forward over the dead writer's record, and ``verify()``
      passes again with that record in the chain. That is the whole recovery rule, and it
      drops nothing.
  (d) record and head written, anchor not (custody configured). Every keyed ``verify()``
      refuses until the next append re-anchors - unchanged, and stated at the call site.
This is about a writer that DIES. A machine that loses power can lose more (neither the
head's temp file nor the directory entry is fsynced), and nothing is claimed about that.

What the lock does NOT guarantee. It is ADVISORY: a process that does not take it is not
excluded, and a party who can write the ledger's directory can remove or replace the lock
file under a holder. That was equally true of the lock file, which the same party could
simply delete. It is an agreement between honest writers and nothing more - it is NOT an
integrity control, and it changes nothing about O-2: the ledger is still not tamper-evident
against its own writer wherever anchor custody is unconfigured.

APPEND LOOKS BEFORE IT WRITES (the Architect's audit of T-156, finding F-05). Under the
lock, before anything is written, ``append()`` walks the chain it is about to extend and
checks the plaintext head against it - the same two functions ``verify()`` runs,
``_check_chain`` and ``_check_head``. A chain with a broken link or a rewritten record, a
head that describes a longer or a different chain, and records with no head at all are
refused (``AuditTruncated`` for the head cases) and nothing is written. Until this it did
not look: an append onto a ledger that had been cut short wrote one more record and a
fresh head that agreed with the shortened chain, and from then on only a signed anchor
could tell. The one state let through is (c) above, because the append is its repair.
WHAT THIS IS NOT: it reads the PLAINTEXT head, which the ledger's own writer can rewrite
together with the chain. It turns an accidental or partial truncation into a refusal; it
does not make the ledger tamper-evident against that writer. That is still the anchor's
job and still O-2.

THE FORK DEFENCE, exactly. The at-fork hook closes the lock descriptors a ``fork()`` COPIED
into the child. A descriptor handed to another process any other way - sent over a Unix
socket, or made inheritable on purpose and passed through an exec - is a second holder of
the same open file description, the hook never sees it, and the lock stays held until
that process closes it or dies. Nothing in this engine does that; it is named because the
defence is against ``fork()`` and not against descriptor passing in general.

A LEFTOVER ``<ledger>.lock`` from the old scheme is not a lock here. It is never read,
trusted or deleted - its existence was the whole defect, and this process did not create
it. An operator may remove it.

Pure standard library on the append hot path when no custody is configured;
``bro_signature`` and the signing subprocess are reached only when anchoring is
provisioned or a caller supplies trusted keys.
"""
from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import pathlib
import stat
import subprocess
import time
from typing import Iterator

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
# Deployment-provided custody (installed and configured by the install, never held by
# a person). Deliberately two variables: a path with no key id (or a
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
# wait longer than this means a LIVE holder that is wedged - surfaced, never ignored
# and never waited on forever. (This said "a crashed or wedged holder". A crashed holder
# no longer holds anything: the kernel released its lock when it died.) The value is the
# one this module already had, and it matches `_SIGNER_TIMEOUT`: the longest thing a
# healthy holder does inside the section is wait for the signer.
_LOCK_TIMEOUT = 10.0
_LOCK_POLL = 0.01
# The file the lock is held ON, beside the ledger. Deliberately NOT the old scheme's
# `<ledger>.lock`: that name's EXISTENCE used to mean "held", an operator's remedy for a
# stranded ledger was to delete it, and deleting the file a kernel lock is held on lets a
# second writer lock a fresh inode while the first still holds the old one.
_LOCK_SUFFIX = ".append-lock"
# Where the Windows lock sits: one byte far past any content. The same offset, for the
# same reason, as `bro_approval_requests._LOCK_OFFSET`; a test holds the two equal.
_LOCK_OFFSET = 0x4000_0000

CUSTODY_REFUSAL = (
    "Audit-head anchor custody is NOT configured. No signing key is compiled into "
    "this engine and none will be invented: an anchor signed with a key the "
    "ledger's own writer can reach proves nothing. The DEPLOYMENT must provide, from "
    "outside this repository (an install step, not a key any person holds):\n"
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


class AuditMalformed(AuditError):
    """The bytes are not a ledger at all: not UTF-8, a record that is not an object or lacks a
    chain field, a head that will not parse.

    An ``AuditError`` -- so ``verify()``'s "Raises AuditError on any break" holds and a caller
    that catches only that (``bro_backup``) gets a verdict instead of a traceback -- but its
    own subclass, because the difference is one a reader acts on. A broken LINK is a chain
    that was written and then altered; a malformed SHAPE is content the reader cannot account
    for at all, which ``bro_monitor`` reports as *unreadable* rather than as a chain that
    failed to verify. Before this class existed those shapes escaped as raw ``KeyError`` /
    ``AttributeError`` / ``JSONDecodeError``, and the monitor told them apart by catching
    exactly those.
    """


class AuditAnchorCustodyMissing(AuditError):
    """Anchor-signing custody is absent or half-configured; the deployment must supply it."""


class AuditLockUnavailable(AuditError):
    """The append lock could not be taken, so NOTHING was written.

    A live holder that did not release within ``_LOCK_TIMEOUT``, a lock path that is a
    symbolic link or not a regular file, or a platform with no kernel lock to offer. An
    ``AuditError``, so every caller that fails closed on one still does; its own type so a
    reader can tell "the ledger is busy or cannot be locked" from "the ledger is broken".
    """


class AuditTornTail(AuditError):
    """The ledger does not end at a record boundary: a writer died mid-record.

    Refused by ``read_all`` (so by ``verify()`` and ``append()`` alike) and never repaired
    here - the partial bytes are what was being written, and removing them silently is
    removing a record.
    """


class AuditTruncated(AuditError):
    """The plaintext head describes a longer or a different chain than the ledger holds, or
    the ledger has records and no head: what a ledger cut short looks like.

    `verify()` has always refused this, as a plain `AuditError` with the same words. It has
    its own name since the Architect's audit of T-156 (finding F-05), because `append()` now
    refuses it too and a caller needs to tell it from a lock that could not be taken. Nothing
    repairs it: the records the head still counts are gone, and writing a fresh head over
    the gap is how a truncation stops being visible.
    """


class AuditHeadBehind(AuditError):
    """The chain is exactly one correctly linked record LONGER than the head describes.

    The state a writer killed between its record and its head leaves. Still a refusal - a
    head that does not describe the chain verifies nothing - but not a truncation, which is
    what it used to be reported as. Nothing is missing; the next ``append()`` writes a head
    that covers the record. The shape is what a crash leaves, not proof that one happened:
    a head rolled back by one, or deleted from a one-record ledger, looks the same.
    """


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _record_hash(prev_hash: str, body: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(body)).encode("utf-8")).hexdigest()


def _head_path(path: pathlib.Path) -> pathlib.Path:
    return path.with_suffix(path.suffix + ".head")


def _lock_path(path: pathlib.Path) -> pathlib.Path:
    return path.with_suffix(path.suffix + _LOCK_SUFFIX)


def _anchor_path(path: pathlib.Path) -> pathlib.Path:
    return path.with_suffix(path.suffix + ".head.sig")


def _platform_name() -> str:
    return os.name


# Descriptors this process currently holds the append lock on. `flock` belongs to the open
# file DESCRIPTION, and a fork()ed child shares its parent's descriptions: a child forked
# while a thread is inside `append()` would keep the lock alive after the parent died,
# which is exactly the stranding this lock exists to end. So the child closes its copies.
# Closing them does NOT release the parent's lock (the parent's own descriptor still refers
# to the description); it only stops the child from being a second owner of it. A child
# that goes on to exec never needed this: Python opens descriptors close-on-exec, so the
# signing command this module runs inside the section does not inherit the lock either.
_held_lock_fds: set[int] = set()


def _drop_inherited_locks() -> None:
    for fd in list(_held_lock_fds):
        try:
            os.close(fd)
        except OSError:
            pass
    _held_lock_fds.clear()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_drop_inherited_locks)


def _open_lock_file(lock: pathlib.Path) -> int:
    """Open (creating if absent) the file the lock is held on, WITHOUT following a symlink.

    A symlink at the lock path lets whoever planted it choose the inode this writer locks -
    one nobody else contends on, so two writers each "hold the lock" - and `O_CREAT` through
    a dangling one creates a file wherever it points. `O_NOFOLLOW` makes the kernel refuse
    in the same call that opens. Windows has no such flag, so there the path is checked
    first; that leaves a window between the check and the open, and it is what that
    platform offers. Mode 0600, as the old lock file was - so a ledger several accounts
    append to needs this file's mode set once by whoever provisions it; it is never
    unlinked, so the mode stays.
    """
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags = os.O_RDWR | os.O_CREAT | nofollow | getattr(os, "O_BINARY", 0)
    symlinked = (
        f"the audit ledger's lock path is a symbolic link, and a lock taken through one is "
        f"a lock on whatever its author chose: {lock}. Nothing was written.")
    if not nofollow and os.path.islink(lock):
        raise AuditLockUnavailable(symlinked)
    try:
        fd = os.open(lock, flags, 0o600)
    except OSError as exc:
        if nofollow and exc.errno in (errno.ELOOP, errno.EMLINK):
            raise AuditLockUnavailable(symlinked) from exc
        raise AuditLockUnavailable(
            f"the audit ledger's lock file cannot be opened, so the append cannot be "
            f"serialized and nothing was written: {lock}: {exc}") from exc
    try:
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
    except OSError:
        regular = False
    if not regular:
        os.close(fd)
        raise AuditLockUnavailable(
            f"the audit ledger's lock path is not a regular file: {lock}. Nothing was written.")
    return fd


def _try_lock(fd: int) -> bool:
    """ONE non-blocking attempt. True: this descriptor holds the lock. False: another does.

    Non-blocking on both platforms, so the wait is `_append_lock`'s bounded loop and not
    the kernel's unbounded one: a blocking `flock` behind a live holder that never releases
    waits forever, and waiting forever is not failing closed, it is a hang.
    """
    if _platform_name() == "posix":
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True
    if _platform_name() == "nt":
        import msvcrt

        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    raise AuditLockUnavailable(
        f"this runtime has no way to serialize two audit-ledger writers on "
        f"{_platform_name()}, and an unserialized append forks the chain. Nothing was written.")


def _is_still_the_lock_file(fd: int, lock: pathlib.Path) -> bool:
    """True when the path still names the inode this descriptor has locked.

    A waiter opens the lock file and then waits. If the file is removed and recreated in
    that time, the waiter ends up holding a lock on an inode nobody else will ever open
    while new writers contend on the new one - two holders at once. Compared AFTER the lock
    is taken, so the answer cannot go stale between the check and the hold. POSIX only: a
    file this process has open cannot be removed or replaced on Windows.
    """
    if _platform_name() != "posix":
        return True
    try:
        on_disk = os.stat(lock, follow_symlinks=False)
        mine = os.fstat(fd)
    except OSError:
        return False
    return (on_disk.st_dev, on_disk.st_ino) == (mine.st_dev, mine.st_ino)


def _close_lock(fd: int) -> None:
    """Release and close. Closing alone releases on both platforms; the explicit unlock is
    there because Windows promises release-on-close only "eventually"."""
    try:
        if _platform_name() == "posix":
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        elif _platform_name() == "nt":
            import msvcrt

            # No seek: nothing reads or writes this descriptor, so it is still positioned
            # at `_LOCK_OFFSET`, where `_try_lock` put it.
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    finally:
        os.close(fd)


@contextlib.contextmanager
def _append_lock(path: pathlib.Path) -> Iterator[None]:
    """Hold the ledger's exclusive append lock for the body, or refuse having written nothing.

    The ledger's read-modify-write (derive seq/prev_hash from the tail, append, replace the
    head) must never interleave: two writers that both read N records both write record N,
    and the chain forks. The lock is an ADVISORY kernel lock held on a descriptor - the
    shape `bro_approval_requests._write_lock` has, for the reason `bro_completion` gives
    for its floor: the kernel drops it when the holder dies, so a crash cannot leave the
    ledger permanently unwritable. Unlike those two it has a deadline on POSIX as well,
    because a LIVE holder can wedge (the signing command runs inside this section) and an
    audit append that hangs takes the hook that called it down with it.

    Raises `AuditLockUnavailable` when the lock is not acquired within `_LOCK_TIMEOUT`.
    It never yields without holding the lock.
    """
    lock = _lock_path(path)
    deadline = time.monotonic() + _LOCK_TIMEOUT
    held = False
    fd = _open_lock_file(lock)
    try:
        while True:
            try:
                acquired = _try_lock(fd)
            except OSError as exc:
                raise AuditLockUnavailable(
                    f"the audit ledger's lock cannot be taken on {lock}: {exc}. "
                    "Nothing was written.") from exc
            if acquired and _is_still_the_lock_file(fd, lock):
                break
            if time.monotonic() >= deadline:
                raise AuditLockUnavailable(
                    f"audit ledger lock not acquired within {_LOCK_TIMEOUT}s: {lock}. A live "
                    "writer holds it and has not released; refusing rather than appending "
                    "unlocked. Nothing was written.")
            if acquired:
                # Locked an inode the path no longer names. Let go of it and contend on the
                # file that is there now; the deadline above still bounds the whole wait.
                stale, fd = fd, -1
                _close_lock(stale)
                fd = _open_lock_file(lock)
            else:
                time.sleep(_LOCK_POLL)
        _held_lock_fds.add(fd)
        held = True
        yield
    finally:
        if not held:
            if fd >= 0:
                os.close(fd)
        elif fd in _held_lock_fds:
            # (Absent only in a fork()ed child, whose copy `_drop_inherited_locks` closed.)
            _held_lock_fds.discard(fd)
            _close_lock(fd)


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
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        # Same rule as the per-line decode below: bytes that are not UTF-8 are a broken
        # ledger, and a broken ledger is an AuditError, not a raw ValueError subclass.
        raise AuditMalformed(f"audit ledger is not UTF-8: {exc}") from exc
    lines = text.splitlines()
    # `append()` writes a record and its newline together, under the lock, so the only line
    # that can lack its newline is the LAST one, and only when its writer died mid-write.
    unterminated = bool(text) and not text.endswith("\n")
    for index, line in enumerate(lines):
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                if unterminated and index == len(lines) - 1:
                    # Named apart from a corrupt line in the middle of the chain, because
                    # the remedy differs: this is a write that never finished, not a
                    # record that was altered. Refused either way, and never trimmed.
                    raise AuditTornTail(
                        f"audit ledger ends in a torn record: the last line is not a "
                        f"complete record and has no newline, which is what a writer "
                        f"killed mid-write leaves. It is refused, not repaired - removing "
                        f"the partial bytes would be dropping a record: {exc}") from exc
                # A corrupt line is a broken ledger; verify() documents AuditError, so
                # a tampered record must not surface as a raw JSONDecodeError callers
                # that catch only AuditError would miss.
                raise AuditError(f"unparsable audit record: {exc}") from exc
    return records


def _refuse_unterminated_tail(p: pathlib.Path) -> None:
    """Refuse to append to a ledger whose last byte is not a newline.

    `read_all` has already refused a last line that does not parse. This is the other half:
    a last line that DOES parse but lost its newline (the write was cut one byte short).
    Appending to it writes the new record onto the same line, and one line holding two
    objects is unparsable - the append would destroy the record before it and itself, and
    the ledger would refuse every read from then on. Read as bytes: text mode would hide
    whether the file ends `\\n` or `\\r\\n`, and either is a boundary.
    """
    try:
        with p.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:
                return
            fh.seek(-1, os.SEEK_END)
            last = fh.read(1)
    except FileNotFoundError:
        return
    if last != b"\n":
        raise AuditTornTail(
            f"audit ledger does not end at a record boundary (its last byte is not a "
            f"newline), which is what a writer killed mid-write leaves: {p.name}. Appending "
            f"would fuse this record onto the one before it and make both unparsable; "
            f"refusing, and repairing nothing.")


# ---------------------------------------------------------------------------
# Anchor custody - deployment-provided, never compiled in
# ---------------------------------------------------------------------------

def anchor_custody_configured(env=None) -> bool:
    """True when the deployment has configured anchor custody at all.

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
    """Resolve the deployment-provided (signing argv, key id), or refuse by name.

    Never falls back to any built-in key: the refusal names both variables and
    states exactly what the deployment must provide.
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
    """Build the audit-head payload a party OUTSIDE this process signs.

    The out-of-band path. No person holds an ``audit-anchor`` key (PR #78): the only
    party that can sign this payload is the separate signer service. This module
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
    # another writer has already extended. The lock is the kernel's, so a writer that
    # dies in here releases it; what it can leave on disk, and the rule for each state,
    # is in the module docstring.
    with _append_lock(p):
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
        # A torn tail left by a writer that died mid-record refuses here, before anything
        # is written: `read_all` for a last line that does not parse, the check after it
        # for one that parses but lost its newline.
        existing = read_all(p)
        _refuse_unterminated_tail(p)
        # The chain this append is about to extend is checked as `verify()` checks it, under
        # the lock, before anything is written (the Architect's audit of T-156, F-05). Until
        # then `append()` never looked: onto a ledger cut short it wrote one more record and
        # a head that agreed with the shortened chain, and the truncation was gone for every
        # reader that had no signed anchor. One state is let through, because this append is
        # its repair: a head exactly one record behind (`AuditHeadBehind`).
        _check_chain(existing)
        try:
            _check_head(p, existing)
        except AuditHeadBehind:
            pass
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
        # that verify() would read as a truncation. A writer killed between the fsync
        # above and the rename below leaves a complete record the head does not cover
        # (`AuditHeadBehind`); this head is derived from the chain as read, never from
        # the old head, so the next append's rename is what covers that record.
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


_HEAD_BEHIND = (
    "audit ledger head is one record behind the chain: the chain holds one complete, "
    "correctly linked record the head does not describe. This is the state a writer killed "
    "between its record and its head leaves - nothing is missing, so it is not a truncation "
    "- and it is refused all the same, because a head that does not describe the chain "
    "verifies nothing. The next append() writes a head that covers the record.")


def _head_is_one_behind(count, last_hash, records: list) -> bool:
    """True when the head describes exactly the chain as it stood ONE record ago.

    Called only after the chain walk in `verify()` has passed, so every record here is an
    object whose `hash` was recomputed. Both halves are required: a head whose count is one
    short but whose hash is not the previous record's is not this state, it is a head that
    describes some other chain, and it keeps its old name.
    """
    if not records or type(count) is not int or count != len(records) - 1:
        return False
    return last_hash == (records[-2]["hash"] if len(records) >= 2 else GENESIS)


def _check_chain(records: list) -> None:
    """Walk the chain: sequence, linkage and every record's hash. Raises AuditError.

    One walk for `verify()` and for `append()`. They were one loop inside `verify()` until
    T-156's audit: `append()` extended whatever it read, so a chain that was already broken
    grew by one well-formed record and a fresh head.
    """
    prev_hash = GENESIS
    for i, rec in enumerate(records):
        # EVERY malformed shape is an AuditError (its `AuditMalformed` subclass), as the
        # docstring promises. A line that parses
        # as JSON but is not an object (`[1,2]`) raised AttributeError from `.get`, and a record
        # missing `kind` or `payload` raised KeyError from the subscript below -- both escaped
        # callers that catch AuditError and nothing else (`engine/tools/bro_backup.py`). It was
        # still a refusal; it was a traceback instead of a verdict.
        if not isinstance(rec, dict):
            raise AuditMalformed(f"audit ledger record at index {i} is not an object")
        if rec.get("seq") != i:
            raise AuditError(f"audit ledger sequence break at index {i}")
        if rec.get("prev_hash") != prev_hash:
            raise AuditError(f"audit ledger linkage break at seq {i}")
        missing = [k for k in ("seq", "prev_hash", "kind", "payload") if k not in rec]
        if missing:
            raise AuditMalformed(f"audit ledger record at seq {i} is missing {missing}")
        body = {k: rec[k] for k in ("seq", "prev_hash", "kind", "payload")}
        if _record_hash(prev_hash, body) != rec.get("hash"):
            raise AuditError(f"audit ledger record tampered at seq {i}")
        prev_hash = rec["hash"]


def _check_head(p: pathlib.Path, records: list) -> None:
    """Refuse a plaintext head that does not describe `records`. Raises AuditError.

    ``AuditHeadBehind`` for the one state a writer killed between its record and its head
    leaves; ``AuditTruncated`` for a head that describes a longer or a different chain, or
    for records with no head at all - which is what a ledger cut short looks like.
    """
    head_file = _head_path(p)
    if head_file.exists():
        try:
            head = json.loads(head_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:   # JSONDecodeError and UnicodeDecodeError both
            raise AuditMalformed(f"unreadable audit head: {exc}") from exc
        if not isinstance(head, dict):
            raise AuditMalformed("audit head is not an object")
        if head.get("count") != len(records):
            if _head_is_one_behind(head.get("count"), head.get("last_hash"), records):
                raise AuditHeadBehind(_HEAD_BEHIND)
            raise AuditTruncated("audit ledger truncated: head count disagrees with chain length")
        if head.get("last_hash") != (records[-1]["hash"] if records else GENESIS):
            raise AuditTruncated("audit ledger truncated: head hash disagrees with chain tail")
    elif records:
        # No head at all is the head of an empty ledger: count 0, tail GENESIS.
        if _head_is_one_behind(0, GENESIS, records):
            raise AuditHeadBehind(_HEAD_BEHIND)
        raise AuditTruncated("audit ledger has records but no head anchor")


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

    Returns the record count. Raises AuditError on any break - including the two states a
    writer that died mid-append leaves, each under its own subclass so the reader knows
    what happened: ``AuditTornTail`` (a partial last record) and ``AuditHeadBehind`` (a
    complete last record the head does not cover). Neither is accepted and neither is
    repaired here; the module docstring gives the rule for each.
    """
    p = pathlib.Path(path)
    records = read_all(p)
    _check_chain(records)
    _check_head(p, records)
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
