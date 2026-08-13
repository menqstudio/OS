"""Wave 3b — content-addressed, append-only protected evidence store (design §4.0).

Large run artifacts (`system`, `history`, `output`, `containment_evidence`, the policy
bundle) are NOT carried inline over the signer IPC — they are published here by the
supervisor and read back by the signer **by handle**, keeping the IPC frame fixed and
small (design §1.9, P1-3). A **handle** is the artifact's lowercase-hex SHA-256 over its
exact bytes; content-addressing makes tampering detectable — the signer refuses unless
`sha256(bytes) == handle` (design §1.3, §1.5).

Atomic publish algorithm (design §4.0, P1-5), removing the signer's partial-read/TOCTOU
window:
  1. write to a temp file in the same directory (private, O_EXCL);
  2. flush + fsync the file (and fsync the directory after the rename);
  3. verify size + recompute sha256 to get the digest;
  4. atomic exclusive publish — link into place under the digest name; an existing
     identical digest is success (idempotent), any other outcome is an error;
  5. the caller builds/attests evidence only AFTER publish returns the handle;
  6. artifacts are retained until the receipt flow terminates + a retention policy
     elapses (retention/GC is out of this module's scope — it never deletes).

Store custody (design §4.0): the directory is created owner-only (0700 on POSIX; the
equivalent PROTECTED owner/SYSTEM/Administrators DACL on Windows) so only the supervisor +
signer identities (which run as the store owner) can read/write it; it is never the
sidecar/desktop login identity's to read. This module reuses the same "refuse a
group/other-accessible dir" discipline as `broctl._require_private_key_dir`.

Both halves of that used to sit inside `if os.name == "posix"`, so on Windows the store was
created with whatever it inherited — under a volume root or `C:\\ProgramData` that includes
`BUILTIN\\Users` — and nothing checked it afterwards. A rule that returns early on a platform
is indistinguishable from no rule, and this one was guarding exactly the identity the design
says must never reach the store. The Windows equivalent is now implemented rather than
skipped (`bro_custody.windows_make_private_directory` /
`bro_custody.windows_refuse_world_accessible`), and a platform that is neither POSIX nor
Windows REFUSES instead of returning.
"""

from __future__ import annotations

import errno
import os
import pathlib
import stat
import tempfile

from bro_custody import (
    platform_name,
    windows_make_private_directory,
    windows_refuse_world_accessible,
)
from brops_canonical import sha256_hex


class EvidenceStoreError(Exception):
    """A publish/read integrity failure — always fail-closed."""


# errnos that mean "this volume can't hardlink" (fall back to O_EXCL create), as opposed
# to a real I/O failure that must propagate. EEXIST is handled separately (idempotent).
_HARDLINK_UNSUPPORTED = frozenset(
    e for e in (
        getattr(errno, "EPERM", None),
        getattr(errno, "EXDEV", None),
        getattr(errno, "EMLINK", None),
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "EACCES", None),
    ) if e is not None
)


def _hardlink_unsupported(exc: OSError) -> bool:
    return os.name == "nt" or exc.errno in _HARDLINK_UNSUPPORTED


#: What the refusals call this directory, so a reader knows which path to fix.
_STORE = "the evidence store dir"


def posix_forbidden_mode(allow_group: bool) -> int:
    """The POSIX permission bits a directory under this policy may NOT carry.

    A pure function, deliberately: the rule it states is the whole difference between the
    evidence store's custody and §2.4 staging custody, and expressing it inline inside a
    ``platform_name() == "posix"`` branch made it unreachable — and therefore untestable —
    on any non-POSIX host. A rule that cannot be exercised is indistinguishable from a rule
    that is not there, which is exactly how this module once shipped a Windows branch that
    checked nothing.

    ``allow_group=True``  -> other is forbidden (the store is shared with the signer group).
    ``allow_group=False`` -> group AND other are forbidden (§2.4: staging is supervisor-only,
    the sidecar and executor have no read at all).
    """
    return stat.S_IRWXO if allow_group else (stat.S_IRWXO | stat.S_IRWXG)


def harden_private_dir(directory: pathlib.Path, *, allow_group: bool = True) -> pathlib.Path:
    """Public entry point for :func:`_harden_dir` — the ONE implementation of "create this
    directory privately, or prove an existing one is not reachable by identities that must
    not reach it".

    ``allow_group=True`` is the evidence store's own policy (a shared group of two dedicated
    principals). ``allow_group=False`` is the STRICTER policy rev-30 §2.4 requires of the
    staging root and every ``session_dir``: those are supervisor-only, with the sidecar and
    executor holding *no read at all*, so a group-readable staging dir is a real weakening
    and not merely an unused permission.

    The parameter exists so the second caller can state a different policy instead of growing
    a second copy of the create/validate logic — which is how this repository acquired
    duplicate custody machinery before.
    """
    return _harden_dir(directory, allow_group=allow_group)


def _harden_dir(directory: pathlib.Path, *, allow_group: bool = True) -> pathlib.Path:
    """Create the dir privately, or validate that an existing one is not world-reachable.

    A *group*-accessible dir is allowed when ``allow_group`` is set, and for the evidence
    store it is allowed on purpose: the store is shared by the two dedicated principals (the
    supervisor writes, the signer reads) via a shared group (design §4.0), so it may be
    group-readable — but NEVER world-accessible, and never reachable by the sidecar/desktop
    login identity. (The private-key dirs stay strictly owner-only; so does rev-30 §2.4
    staging, which passes ``allow_group=False``.)

    Both platforms answer the same two questions, and neither may decline to answer:

    * creation — POSIX ``chmod 0700``; Windows a PROTECTED DACL granting only OWNER RIGHTS,
      SYSTEM and Administrators, because ``mkdir`` there takes no mode and a new directory
      simply inherits whatever its parent grants. The operator opts a second principal in
      afterwards, on either platform.
    * validation — POSIX refuses ``mode & S_IRWXO``; Windows refuses an access-allowed ACE
      for any principal that means "anyone who can log on" (Everyone, Authenticated Users,
      INTERACTIVE, BUILTIN\\Users, …). Read access counts on both, which is the point: the
      store's contents are the evidence, not merely the ability to change it.

    A platform that is neither refuses. There is no honest third answer here — the store's
    whole custody claim is a statement about who the operating system lets in, and a runtime
    that cannot ask the question cannot make the claim.
    """
    resolved = directory.expanduser().resolve()
    if not resolved.exists():
        resolved.mkdir(parents=True, exist_ok=True)
        if platform_name() == "posix":
            os.chmod(resolved, 0o700)  # created owner-only; operator opts into a group
        elif platform_name() == "nt":
            windows_make_private_directory(resolved, _STORE, EvidenceStoreError)
        else:
            raise _unsupported_platform(resolved)
    elif not resolved.is_dir():
        raise EvidenceStoreError(f"evidence store path is not a directory: {resolved}")
    elif platform_name() == "posix":
        mode = resolved.stat().st_mode
        forbidden = posix_forbidden_mode(allow_group)
        if mode & forbidden:
            reach = "world-accessible" if mode & stat.S_IRWXO else "group-accessible"
            raise EvidenceStoreError(
                f"evidence store dir {resolved} is {reach}; refusing"
            )
    elif platform_name() == "nt":
        windows_refuse_world_accessible(resolved, _STORE, EvidenceStoreError)
    else:
        raise _unsupported_platform(resolved)
    return resolved


def _unsupported_platform(resolved: pathlib.Path) -> EvidenceStoreError:
    return EvidenceStoreError(
        f"evidence store custody cannot be established on {platform_name()}: this runtime has no "
        f"way to create {resolved} privately or to ask who may reach it, and an unchecked store "
        "is not a protected store"
    )


def _fsync_dir(directory: pathlib.Path) -> None:
    """Best-effort directory fsync (POSIX). No-op where a dir fd can't be fsync'd."""
    if os.name != "posix":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_link_or_create(tmp: pathlib.Path, target: pathlib.Path, data: bytes) -> bool:
    """Create ``target`` exactly once from the already-fsync'd ``tmp``. Returns True if THIS
    call created it, False if it was already there.

    This is the design's named create-if-absent primitive (§2.4: "the exact frozen
    ``brops_evidence_store.py`` ``os.link`` create-if-absent no-overwrite primitive, with the
    ``O_EXCL`` fallback; NOT ``rename`` and NOT ``renameat2``"). ``os.link`` is atomic: it
    creates ``target`` iff it does not exist and raises ``EEXIST`` otherwise, so there is no
    check-then-act race, and a concurrent writer of the same target always loses to ``EEXIST``.

    It was extracted from :meth:`EvidenceStore._atomic_publish` — which now calls it — because
    §2.4 requires the SAME primitive for the immutable ``<seq>.chunk`` files under a
    DIFFERENT idempotency rule: the store re-verifies an existing target against a content
    handle, while staging re-verifies it against the exact bytes the sender re-sent. Returning
    "did I create it?" and leaving the verification to the caller is what lets both share one
    implementation instead of the tree growing a second copy of the EEXIST /
    hardlink-unsupported / ``O_EXCL``-fallback reasoning.

    EEXIST is the ONLY "already present" signal; every other ``OSError`` that is not a
    "this volume cannot hardlink" errno propagates, and is never conflated with it.
    """
    try:
        os.link(tmp, target)  # atomic create-if-absent (POSIX + NTFS)
        return True
    except FileExistsError:
        return False
    except OSError as exc:
        # Distinguish "hardlinks unsupported here" (fall back) from a real error.
        if not _hardlink_unsupported(exc):
            raise
    # Hardlink-unsupported fallback (e.g. some Windows / FAT volumes): atomically CREATE the
    # target itself with O_EXCL — still create-if-absent, no clobber, no check-then-act. A
    # crash mid-write leaves a partial target, which every reader in this design re-hashes
    # and rejects — fail-closed, never a silent bad artifact.
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    except FileExistsError:
        return False
    with os.fdopen(fd, "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    return True


def fsync_dir(directory: pathlib.Path) -> None:
    """Public name for :func:`_fsync_dir` — the directory-durability step §2.4 requires after
    linking each ``<seq>.chunk`` into place, shared rather than re-derived."""
    _fsync_dir(directory)


class EvidenceStore:
    """A content-addressed store rooted at one directory. Handles are hex sha256."""

    def __init__(self, root: os.PathLike[str] | str) -> None:
        self.root = _harden_dir(pathlib.Path(root))

    def _path(self, handle: str) -> pathlib.Path:
        if len(handle) != 64 or any(c not in "0123456789abcdef" for c in handle):
            raise EvidenceStoreError(f"not a valid content handle: {handle!r}")
        return self.root / handle

    def publish(self, data: bytes) -> str:
        """Publish exact bytes; return the content handle (hex sha256). Idempotent — a
        second publish of identical bytes returns the same handle without error."""
        if not isinstance(data, (bytes, bytearray)):
            raise EvidenceStoreError("evidence artifact must be bytes")
        data = bytes(data)

        # 1. temp file in the same dir (O_EXCL via mkstemp), 2. write + fsync.
        fd, tmp_name = tempfile.mkstemp(dir=self.root, prefix=".tmp-", suffix=".part")
        tmp = pathlib.Path(tmp_name)
        tmp_consumed = False  # set once the temp has become the published target
        try:
            with os.fdopen(fd, "wb") as handle_file:
                handle_file.write(data)
                handle_file.flush()
                os.fsync(handle_file.fileno())
            if os.name == "posix":
                # Owner rw + GROUP read (0640): the store is shared by the two dedicated
                # principals via a group (the supervisor writes, the signer reads), so a
                # published artifact must be group-readable — but never world (design §4.0,
                # audit P0-1). No effect on the single-principal case (the group is the
                # owner's own). World stays denied.
                #
                # There is no `elif os.name == "nt"` branch here, and that is not the
                # same omission `_harden_dir` had: a new file on Windows inherits the
                # directory's DACL, and `_harden_dir` has just established (on creation)
                # or verified (on an existing store) that the directory grants nothing to
                # a third-party login identity. The published artifact is covered by the
                # rule rather than exempted from it.
                os.chmod(tmp, 0o640)

            # 3. verify size + recompute sha256 over the bytes actually on disk.
            written = tmp.read_bytes()
            if len(written) != len(data) or written != data:
                raise EvidenceStoreError("evidence artifact changed under us before publish")
            handle = sha256_hex(written)
            target = self._path(handle)

            # 4. atomic exclusive publish via a real create-if-absent primitive — NEVER a
            # check-then-act race (P1-5). `os.link` is atomic: it creates `target` iff it
            # does not exist, and raises EEXIST otherwise. EEXIST is the ONLY "already
            # published" signal (idempotent, content re-checked); every OTHER OSError is a
            # real failure and propagates — never conflated with EEXIST. A concurrent
            # publisher of the same bytes always loses the link race to EEXIST, so there is
            # exactly one target and it is never overwritten.
            tmp_consumed = self._atomic_publish(tmp, target, data, handle)
        finally:
            if not tmp_consumed and tmp.exists():
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass
        _fsync_dir(self.root)
        return handle

    def _atomic_publish(self, tmp: pathlib.Path, target: pathlib.Path, data: bytes, handle: str) -> bool:
        """Create `target` exactly once from the fsync'd temp. Returns True if `tmp` was
        consumed (must not be unlinked by the caller). Idempotent on EEXIST.

        The create-if-absent mechanics live in :func:`atomic_link_or_create`; what stays here
        is this store's OWN idempotency rule — an already-present target must content-address
        to `handle`.
        """
        if not atomic_link_or_create(tmp, target, data):
            self._verify_idempotent(target, handle)
        return False  # tmp still present in both branches; caller unlinks it

    def _verify_idempotent(self, target: pathlib.Path, handle: str) -> None:
        """An already-present digest must content-address to `handle` (a content-address
        collision — astronomically improbable, or a corrupted store — is fail-closed)."""
        existing = target.read_bytes()
        if sha256_hex(existing) != handle:
            raise EvidenceStoreError(f"content-address collision at {handle}: stored bytes differ")

    def has(self, handle: str) -> bool:
        return self._path(handle).exists()

    def read(self, handle: str) -> bytes:
        """Read exact bytes by handle, refusing unless `sha256(bytes) == handle`
        (design §1.3, §1.5). A missing handle or a hash mismatch is fail-closed."""
        path = self._path(handle)
        if not path.exists():
            raise EvidenceStoreError(f"evidence handle not in store: {handle}")
        data = path.read_bytes()
        if sha256_hex(data) != handle:
            raise EvidenceStoreError(f"evidence store corruption: {handle} bytes do not hash to it")
        return data
