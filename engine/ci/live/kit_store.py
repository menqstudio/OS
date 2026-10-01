"""The file-backed half of the live kits' protected store, written ONCE.

Three kit runners each carried their own copy of this until 2026-10-01:

  * ``run_supervisor.py``        -- ``read_run_evidence`` and ``publish_artifact``, closures in ``main``;
  * ``run_ladder_supervisor.py`` -- the same two again, plus ``Store.read``;
  * ``run_signer.py``            -- ``FileArtifactStore.read_verified``.

The copies had already drifted in the one place it matters: the ladder supervisor refused a blob
over :data:`MAX_BLOB_BYTES`, and the live signer read whatever size was on disk into memory before
hashing it. A bound two of three readers apply is a bound the store does not have.

What is here is the I/O and nothing else. Each caller keeps its own refusal vocabulary -- the
supervisor seams answer ``None``, the ladder raises ``LadderError``, the signer raises
``SignerError`` -- so the exception class is injected, as ``brops_socket.read_peercred_uid`` does
for the same reason. Only the Python standard library is used.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Optional

#: The recorder's evidence chain for one run. Bounded so a hostile file cannot exhaust the reader.
MAX_EVIDENCE_BYTES = 1 << 20

#: A store blob larger than this is refused rather than read into memory. The three staged
#: artifacts are capped by §2.4 (8 MiB for `history`, the largest), and the executor's reply and
#: containment report are smaller still.
MAX_BLOB_BYTES = 16 << 20

_HEX = frozenset("0123456789abcdef")


def is_handle(value: Any) -> bool:
    """A store handle is a 64-char LOWERCASE hex content address, and nothing else reaches a path."""
    return isinstance(value, str) and len(value) == 64 and all(c in _HEX for c in value)


def read_run_evidence(evidence_dir: str, attempt: Any,
                      max_bytes: int = MAX_EVIDENCE_BYTES) -> Optional[bytes]:
    """The RECORDER's evidence chain for ``attempt``, or ``None`` (audit F-01).

    Read from the recorder's OWN directory, which no caller can write. The attempt id reaches the
    filesystem, so it must not be able to escape the directory: it is a supervisor-minted id, and
    the supervisor still does not get to assume its own inputs. Absent, unreadable and oversize
    are all ``None`` -- the seam's contract is "the bytes, or nothing".
    """
    if not isinstance(attempt, str) or not attempt \
            or not all(c.isalnum() or c in "-_" for c in attempt):
        return None
    path = os.path.join(evidence_dir, attempt + ".evidence.json")
    try:
        with open(path, "rb") as fh:
            data = fh.read(max_bytes + 1)
    except OSError:
        return None
    if len(data) > max_bytes:
        return None
    return data


def publish_blob(store_dir: str, data: bytes) -> str:
    """Publish ``data`` under its content address and return the 64-hex handle.

    Atomic-by-rename and idempotent: the content address IS the filename, so republishing
    identical bytes is a no-op and no other bytes can claim that name. 0644 because a different
    uid (the signer) reads the blob by handle.
    """
    handle = hashlib.sha256(data).hexdigest()
    final = os.path.join(store_dir, handle)
    if not os.path.exists(final):
        tmp = final + ".tmp-%d" % os.getpid()
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, final)
        try:
            os.chmod(final, 0o644)
        except OSError:
            pass
    return handle


def read_blob(store_dir: str, handle: Any, *, error: type,
              max_bytes: int = MAX_BLOB_BYTES) -> bytes:
    """The bytes ``handle`` names, re-verified: ``sha256(bytes) == handle`` on EVERY read.

    That re-hash is what makes a handle safe to accept from a durable row or an attested
    evidence object: the bytes it names cannot have been swapped for others under the same
    address. Raises ``error`` for a value that is not a handle, a blob over ``max_bytes`` (read
    as ``max_bytes + 1`` and refused, never slurped whole) and a blob whose digest is not its
    name. A handle that names nothing raises ``FileNotFoundError``: "absent" is the one outcome
    the callers treat differently, so it is left to them.
    """
    if not is_handle(handle):
        raise error("not a 64-hex content address: %r" % (handle,))
    with open(os.path.join(store_dir, handle), "rb") as fh:
        data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise error("store blob %s exceeds %d bytes" % (handle, max_bytes))
    if hashlib.sha256(data).hexdigest() != handle:
        raise error("store corruption: blob digest != handle %s" % handle)
    return data
