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

Store custody (design §4.0): the directory is created owner-only (0700 on POSIX) so only
the supervisor + signer identities (which run as the store owner) can read/write it; it
is never the sidecar/desktop login identity's to read. This module reuses the same
"refuse a group/other-accessible dir" discipline as `broctl._require_private_key_dir`.
"""

from __future__ import annotations

import errno
import os
import pathlib
import stat
import tempfile

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


def _harden_dir(directory: pathlib.Path) -> pathlib.Path:
    """Create (0700) or validate the store dir. On POSIX, refuse an **other-accessible**
    dir. A *group*-accessible dir is allowed on purpose: the store is shared by the two
    dedicated principals (the supervisor writes, the signer reads) via a shared group
    (design §4.0), so it may be group-readable — but NEVER world-accessible, and never
    reachable by the sidecar/desktop login identity. (The private-key dirs stay strictly
    owner-only; only this shared store permits a group.)"""
    resolved = directory.expanduser().resolve()
    if not resolved.exists():
        resolved.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(resolved, 0o700)  # created owner-only; operator opts into a group
    elif not resolved.is_dir():
        raise EvidenceStoreError(f"evidence store path is not a directory: {resolved}")
    elif os.name == "posix":
        mode = resolved.stat().st_mode
        if mode & stat.S_IRWXO:
            raise EvidenceStoreError(
                f"evidence store dir {resolved} is world-accessible; refusing"
            )
    return resolved


def _fsync_dir(directory: pathlib.Path) -> None:
    """Best-effort directory fsync (POSIX). No-op where a dir fd can't be fsync'd."""
    if os.name != "posix":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


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
                os.chmod(tmp, 0o600)

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
        consumed (must not be unlinked by the caller). Idempotent on EEXIST."""
        try:
            os.link(tmp, target)  # atomic create-if-absent (POSIX + NTFS)
            return False  # tmp still present; caller unlinks it
        except FileExistsError:
            self._verify_idempotent(target, handle)
            return False
        except OSError as exc:
            # Distinguish "hardlinks unsupported here" (fall back) from a real error.
            if not _hardlink_unsupported(exc):
                raise
        # Hardlink-unsupported fallback (e.g. some Windows / FAT volumes): atomically
        # CREATE the target itself with O_EXCL — still create-if-absent, no clobber, no
        # check-then-act. A crash mid-write leaves a partial target, which `read()`
        # rejects (sha mismatch) — fail-closed, never a silent bad artifact.
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            self._verify_idempotent(target, handle)
            return False
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        return False

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
