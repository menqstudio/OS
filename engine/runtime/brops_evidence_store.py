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

import os
import pathlib
import stat
import tempfile

from brops_canonical import sha256_hex


class EvidenceStoreError(Exception):
    """A publish/read integrity failure — always fail-closed."""


def _harden_dir(directory: pathlib.Path) -> pathlib.Path:
    """Create (0700) or validate the store dir. On POSIX, refuse a pre-existing
    group/other-accessible dir rather than silently re-permissioning it."""
    resolved = directory.expanduser().resolve()
    if not resolved.exists():
        resolved.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(resolved, 0o700)
    elif not resolved.is_dir():
        raise EvidenceStoreError(f"evidence store path is not a directory: {resolved}")
    elif os.name == "posix":
        mode = resolved.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise EvidenceStoreError(
                f"evidence store dir {resolved} is group/other-accessible; refusing"
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

            # 4. atomic exclusive publish. os.link is atomic + fails EEXIST if the digest
            # is already present (idempotent success after a content re-check).
            try:
                os.link(tmp, target)
            except FileExistsError:
                existing = target.read_bytes()
                if sha256_hex(existing) != handle:
                    raise EvidenceStoreError(
                        f"content-address collision at {handle}: stored bytes differ"
                    )
            except (OSError, NotImplementedError):
                # Filesystems without hardlink support (e.g. some Windows setups): fall
                # back to a not-exists guard, then atomic replace. Content-addressing
                # keeps this safe — identical digest ⇒ identical bytes.
                if not target.exists():
                    os.replace(tmp, target)
                    tmp_consumed = True
        finally:
            if not tmp_consumed:
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass
        _fsync_dir(self.root)
        return handle

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
