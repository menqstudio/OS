"""Wave 3b — the framed, bounded, strict IPC codec for the signer/supervisor boundary
(design §1.9, §4; audit P1-4).

Every message on the supervisor↔signer (and sidecar↔supervisor) local IPC is a single
**length-prefixed frame**: a `u32` big-endian byte count followed by exactly that many
UTF-8 JSON bytes, capped at 256 KiB. Decoding is **strict**: duplicate keys are rejected,
the top level must be an object, and (per message type) unknown fields are rejected via
the contract JSON Schema. Large inputs never travel inline — they are content-addressed
handles (design §1.9), so 256 KiB is a hard ceiling, not a tunable.

This replaces the previous `json.loads(stdin.read())` seam, which had no framing, no
bound, and no strict/duplicate-key/unknown-field/base64url validation.
"""

from __future__ import annotations

import json
import re
import struct
from typing import Any, BinaryIO

# One fixed whole-frame cap (design §1.9, P1-3). Applies to every message, both directions.
MAX_FRAME_BYTES = 256 * 1024
_LENGTH_PREFIX = 4  # u32 big-endian

_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]*$")


class ProtocolError(Exception):
    """A framing / strict-decode / schema failure — always fail-closed."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise ProtocolError(f"duplicate key in frame: {key!r}")
        seen[key] = value
    return seen


def strict_loads(raw: bytes) -> dict[str, Any]:
    """Decode one frame body as strict JSON: UTF-8, ≤ cap, object top level, no duplicate
    keys. (Per-message unknown-field rejection is done by `validate` against a schema.)"""
    if len(raw) > MAX_FRAME_BYTES:
        raise ProtocolError(f"frame body is {len(raw)} bytes, over the {MAX_FRAME_BYTES} cap")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"frame is not valid UTF-8: {exc}")
    try:
        obj = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"frame is not valid JSON: {exc}")
    if not isinstance(obj, dict):
        raise ProtocolError("frame top level must be a JSON object")
    return obj


def encode_frame(obj: dict[str, Any]) -> bytes:
    """Serialize one object as a length-prefixed frame (compact UTF-8 JSON)."""
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise ProtocolError(f"frame body is {len(body)} bytes, over the {MAX_FRAME_BYTES} cap")
    return struct.pack(">I", len(body)) + body


def _read_exactly(stream: BinaryIO, n: int) -> bytes:
    """Read exactly `n` bytes or fail (never a short read)."""
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            raise ProtocolError(f"unexpected EOF: wanted {n} bytes, short by {remaining}")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream: BinaryIO) -> dict[str, Any]:
    """Read one length-prefixed frame from a binary stream and strict-decode it. The
    declared length is bound-checked BEFORE any body bytes are read, so a hostile prefix
    can never make us allocate/read more than the cap."""
    header = _read_exactly(stream, _LENGTH_PREFIX)
    (length,) = struct.unpack(">I", header)
    if length > MAX_FRAME_BYTES:
        raise ProtocolError(f"declared frame length {length} is over the {MAX_FRAME_BYTES} cap")
    body = _read_exactly(stream, length)
    return strict_loads(body)


def write_frame(stream: BinaryIO, obj: dict[str, Any]) -> None:
    stream.write(encode_frame(obj))
    stream.flush()


def is_base64url(value: Any) -> bool:
    """True iff `value` is a base64url (no-padding) string. Runtime validation for wire
    signature/envelope fields (design §4)."""
    return isinstance(value, str) and bool(_B64URL_RE.match(value))


def validate(obj: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate a decoded frame against its contract JSON Schema (unknown-field rejection
    via `additionalProperties: false`, types, required, const tags). Fail-closed."""
    try:
        import jsonschema
    except Exception as exc:  # pragma: no cover — jsonschema is a pinned CI dep
        raise ProtocolError(f"schema validator unavailable: {exc}")
    try:
        jsonschema.validate(obj, schema)
    except jsonschema.ValidationError as exc:
        raise ProtocolError(f"frame does not match its contract: {exc.message}")
