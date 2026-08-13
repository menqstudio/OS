"""The PRE-ACCEPT chunked input upload — rev-30 §2.4 + §4.10(a), §4.10(b), §4.10(c).

The signed challenge commits only *digests* of the three desktop-originated inputs. Before
the turn can execute, the exact **raw** bytes have to reach the supervisor's protected
store — and the only party able to carry them is the sidecar, which §2.4 declares
compromised-in-scope. This module is the surface that lets an untrusted courier deliver
bytes the supervisor can prove it was already promised:

  * §4.10(a) ``brops.governed-staging-open.v1`` opens ONE upload session per
    ``(challenge_handle, artifact)``, and only for a digest the verified challenge
    committed to and a length inside that artifact's ceiling;
  * §4.10(b) ``brops.governed-staging-chunk.v1`` accepts the chunks in exact order, each
    an immutable ``<seq>.chunk`` file, each of a length the protocol — not the sender —
    determines;
  * §4.10(c) ``brops.governed-staging-final.v1`` re-reads those files from byte zero,
    re-hashes them, refuses anything the challenge did not authorize, and publishes.

What this grants, and what it deliberately cannot
--------------------------------------------------
Nothing here mints an ``execution_attempt_id``, reads an acceptance clock, consumes the
challenge nonce, issues a lease, or creates an acceptance row. Uploading three artifacts
moves a turn from "admitted to upload" to "its inputs are on disk and match the
signature". §5 acceptance is a later, separate authority; §4.10(d) — the message that
consumes an ``INPUTS_READY`` row and asks for execution — is a separate ordered piece and
lives in ``governed_evidence_request``, where it only READS this state. The reachable end
state of everything below is a ``governed_turn_staging`` row in ``INPUTS_READY`` and three
blobs in the store.

Where the guarantees actually live
-----------------------------------
Not here. The DDL in ``supervisor_ledger.sql`` refuses a session that is born non-empty,
a cursor that advances by anything other than exactly one recorded chunk, a chunk recorded
anywhere but at the cursor, a recorded chunk that is later re-described, a published input
handle that is not the digest the signed challenge committed to, and an ``INPUTS_READY``
turn missing any of the three. This module takes the write lock and drives those edges; it
is not the thing that forbids them. That distinction is the point: a future writer that
never calls these functions still cannot declare a finished upload having uploaded nothing.

Three sender-controlled quantities, and why each is bounded twice
-----------------------------------------------------------------
A compromised sidecar chooses the chunk bytes, the chunk count and the number of sessions.
Each is bounded by an arithmetic rule rather than a policy hope:

  * **length** — a chunk is not sender-sized. It MUST be exactly
    ``min(184320, declared_len - byte_count)``, so a 1-byte-chunk flood is
    ``nondeterministic_chunk`` on its first message (§2.4 P1-3, the Track E amplification);
  * **count** — that rule makes ``n_chunks = ceil(declared_len / 184320)`` a function of
    the declaration, so a session is hard-capped at 46 chunks and a turn at 49 files;
  * **space** — ``declared_len`` is charged against the per-install byte quota at OPEN,
    before any byte arrives, so the reservation binds rather than the arrival.

Only the Python standard library is used. Every clock is an injected ``now_ms``.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
import secrets
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

import governed_staging_ledger as staging
from brops_evidence_store import (
    atomic_link_or_create,
    fsync_dir,
    harden_private_dir,
)
from brops_protocol import (
    MAX_FRAME_BYTES,
    ProtocolError,
    decode_base64url,
    encode_frame,
)
from governed_supervisor import SupervisorError
from governed_turn_open import MAX_OPEN_FRAME_BYTES, OPEN_PROTOCOL, peer_is_sidecar
from governed_turn_open import refused as open_refused

# ---------------------------------------------------------------------------
# Wire constants (§2.4 / §4.10(a)(b)(c), LOCKED literals)
# ---------------------------------------------------------------------------

STAGING_OPEN_PROTOCOL = "brops.governed-staging-open.v1"
STAGING_OPEN_RESULT_PROTOCOL = "brops.governed-staging-open-result.v1"
STAGING_CHUNK_PROTOCOL = "brops.governed-staging-chunk.v1"
STAGING_CHUNK_RESULT_PROTOCOL = "brops.governed-staging-chunk-result.v1"
STAGING_FINAL_PROTOCOL = "brops.governed-staging-final.v1"
STAGING_FINAL_RESULT_PROTOCOL = "brops.governed-staging-final-result.v1"

#: §4.10(b) P1-4: the DECODED chunk cap, 180 KiB. Chosen so that
#: ``4*ceil(184320/3) = 245760`` base64url bytes plus the chunk envelope still fits the
#: 262144 frame body with ≥ 16 KiB of headroom.
MAX_STAGING_CHUNK_BYTES = 184320

#: §2.4/§4.10(b): the two caps are checked INDEPENDENTLY and both fail closed. 184321
#: decoded bytes still produce a frame that fits, and must be refused on the decoded cap;
#: a 256 KiB decoded chunk encodes to 349528 bytes and must be refused on the frame cap
#: before it is decoded at all.
MAX_STAGING_CHUNK_FRAME_BYTES = MAX_FRAME_BYTES

#: §4.10(a)/§4.10(c): "Frame ≤ 4 KiB" for the two control messages.
MAX_STAGING_CONTROL_FRAME_BYTES = 4096

#: §2.4 per-artifact ceilings (LOCKED). ``system``/``history`` match the desktop's real
#: ``ai.rs`` caps; ``generation_config`` is the governed-family ceiling on
#: ``JCS(generation_config_object)``, new to the 3b-1B object form. ``policy_bundle`` is
#: absent because a sidecar may never upload policy at all (§2.4 policy authority).
ARTIFACT_CEILINGS = {
    "system": 262144,
    "history": 8388608,
    "generation_config": 65536,
}

#: §2.4: the total a sidecar may upload for one turn.
MAX_TURN_UPLOAD_BYTES = sum(ARTIFACT_CEILINGS.values())

#: §2.1/§4.1: all ids ≤ 128. A ``staging_session_id`` is additionally required to be
#: base64url-shaped, because it names a directory — see :func:`_session_dir`.
MAX_ID_LEN = 128

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

STATUS_OPENED = "opened"
STATUS_ACK = "ack"
STATUS_PUBLISHED = "published"
STATUS_REFUSED = "refused"

# ---- The three CLOSED refusal sets -------------------------------------------------
REFUSE_PEER_DENIED = "peer_denied"
REFUSE_MALFORMED = "malformed"
REFUSE_RETRY_CONFLICT = "retry_conflict"
REFUSE_SESSION_CORRUPT = "session_corrupt"

# §4.10(a)
REFUSE_NO_STAGING_ROW = "no_staging_row"
REFUSE_ARTIFACT_INVALID = "artifact_invalid"
REFUSE_DIGEST_MISMATCH = "digest_mismatch"
REFUSE_OVERSIZE = "oversize"
REFUSE_QUOTA_SESSIONS = "quota_sessions"
REFUSE_QUOTA_BYTES = "quota_bytes"

# §4.10(b)
REFUSE_SESSION_UNKNOWN = "session_unknown"
REFUSE_SEQ_MISMATCH = "seq_mismatch"
REFUSE_OVERSIZE_CHUNK = "oversize_chunk"
REFUSE_OVERSIZE_FRAME = "oversize_frame"
REFUSE_OVER_DECLARED = "over_declared"
REFUSE_NONDETERMINISTIC_CHUNK = "nondeterministic_chunk"
REFUSE_TOO_MANY_CHUNKS = "too_many_chunks"

# §4.10(c)
REFUSE_LEN_MISMATCH = "len_mismatch"
REFUSE_SHA_MISMATCH = "sha_mismatch"
REFUSE_HANDLE_NOT_CHALLENGE = "handle_not_challenge"
REFUSE_PUBLISH_DIVERGENT = "publish_divergent"

STAGING_OPEN_REFUSAL_REASONS: Tuple[str, ...] = (
    REFUSE_PEER_DENIED, REFUSE_NO_STAGING_ROW, REFUSE_ARTIFACT_INVALID,
    REFUSE_DIGEST_MISMATCH, REFUSE_OVERSIZE, REFUSE_RETRY_CONFLICT,
    REFUSE_QUOTA_SESSIONS, REFUSE_QUOTA_BYTES, REFUSE_SESSION_CORRUPT, REFUSE_MALFORMED,
)

STAGING_CHUNK_REFUSAL_REASONS: Tuple[str, ...] = (
    REFUSE_SESSION_UNKNOWN, REFUSE_SEQ_MISMATCH, REFUSE_RETRY_CONFLICT,
    REFUSE_OVERSIZE_CHUNK, REFUSE_OVERSIZE_FRAME, REFUSE_OVER_DECLARED,
    REFUSE_NONDETERMINISTIC_CHUNK, REFUSE_TOO_MANY_CHUNKS, REFUSE_SESSION_CORRUPT,
    REFUSE_MALFORMED,
)

STAGING_FINAL_REFUSAL_REASONS: Tuple[str, ...] = (
    REFUSE_SESSION_UNKNOWN, REFUSE_SEQ_MISMATCH, REFUSE_LEN_MISMATCH,
    REFUSE_SHA_MISMATCH, REFUSE_HANDLE_NOT_CHALLENGE, REFUSE_PUBLISH_DIVERGENT,
    REFUSE_RETRY_CONFLICT, REFUSE_SESSION_CORRUPT, REFUSE_MALFORMED,
)

#: §4.10(b) and §4.10(c) have no ``peer_denied`` in their published reason sets, but the
#: peer check still runs first on every message — a non-sidecar peer never reaches a
#: handler through the front door (it is refused in the transport), and a handler called
#: directly answers with the shape it is allowed to speak. The two protocols express that
#: as ``malformed``: a message from a principal that may not send it is not a message.
_CHUNK_PEER_DENIED = REFUSE_MALFORMED
_FINAL_PEER_DENIED = REFUSE_MALFORMED

#: The exhaustive request field sets. Anything else — most pointedly an
#: ``execution_attempt_id``, a ``lease_id`` or a ``receipt_id`` — is ``malformed`` before
#: any side effect, the same P1-5 door §4.10(a0) closes.
STAGING_OPEN_REQUEST_FIELDS: Tuple[str, ...] = (
    "protocol", "install_id", "challenge_handle", "request_nonce",
    "artifact", "declared_len", "declared_sha256",
)
STAGING_CHUNK_REQUEST_FIELDS: Tuple[str, ...] = (
    "protocol", "staging_session_id", "seq", "bytes_b64",
)
STAGING_FINAL_REQUEST_FIELDS: Tuple[str, ...] = (
    "protocol", "staging_session_id", "seq",
)

#: Every protocol the SIDECAR principal may send, with the frame-body cap the design fixes
#: for it and the reason each answers an over-cap frame with. The sidecar's transport read
#: bound has to be the largest of these (a chunk is 240 KiB of base64url), so the tighter
#: per-protocol bounds are re-applied here, on the exact bytes that arrived, rather than
#: silently widening every message to the chunk cap.
SIDECAR_FRAME_CAPS: Dict[str, int] = {
    OPEN_PROTOCOL: MAX_OPEN_FRAME_BYTES,
    STAGING_OPEN_PROTOCOL: MAX_STAGING_CONTROL_FRAME_BYTES,
    STAGING_CHUNK_PROTOCOL: MAX_STAGING_CHUNK_FRAME_BYTES,
    STAGING_FINAL_PROTOCOL: MAX_STAGING_CONTROL_FRAME_BYTES,
}

#: The largest frame any sidecar protocol may carry — the transport read bound.
MAX_SIDECAR_FRAME_BYTES = max(SIDECAR_FRAME_CAPS.values())


class _Refuse(Exception):
    """Internal control flow: a typed refusal reason. Never escapes this module."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------
# Replies
# ---------------------------------------------------------------------------


def _checked(reason: str, closed_set: Tuple[str, ...], protocol: str) -> str:
    """A refusal carrying an off-contract reason is worse than one carrying a wrong reason:
    the §4.10(h) diagnostic routing table (**NOT IMPLEMENTED** — a later ordered piece)
    maps reasons to Blocks BY NAME, so an unmapped string would fall through to whatever
    the default happens to be. Fail loudly here, while the set is still checkable."""
    if reason not in closed_set:
        raise SupervisorError(
            "refusal reason %r is not in the %s closed set" % (reason, protocol)
        )
    return reason


def staging_opened(staging_session_id: str, next_seq: int) -> Dict[str, Any]:
    return {
        "protocol": STAGING_OPEN_RESULT_PROTOCOL,
        "status": STATUS_OPENED,
        "staging_session_id": staging_session_id,
        "next_seq": next_seq,
    }


def staging_open_refused(reason: str) -> Dict[str, Any]:
    return {
        "protocol": STAGING_OPEN_RESULT_PROTOCOL,
        "status": STATUS_REFUSED,
        "reason": _checked(reason, STAGING_OPEN_REFUSAL_REASONS, STAGING_OPEN_PROTOCOL),
    }


def chunk_ack(next_seq: int) -> Dict[str, Any]:
    """§4.10(b) discriminated union: ``status:"ack"`` carries ``reason == null`` and the
    current durable cursor. The cursor is present in BOTH arms so a sender that lost a
    reply always learns where the supervisor actually is."""
    return {
        "protocol": STAGING_CHUNK_RESULT_PROTOCOL,
        "status": STATUS_ACK,
        "next_seq": next_seq,
        "reason": None,
    }


def chunk_refused(reason: str, next_seq: int) -> Dict[str, Any]:
    return {
        "protocol": STAGING_CHUNK_RESULT_PROTOCOL,
        "status": STATUS_REFUSED,
        "next_seq": next_seq,
        "reason": _checked(reason, STAGING_CHUNK_REFUSAL_REASONS, STAGING_CHUNK_PROTOCOL),
    }


def final_published(artifact: str, handle: str, inputs_ready: bool) -> Dict[str, Any]:
    return {
        "protocol": STAGING_FINAL_RESULT_PROTOCOL,
        "status": STATUS_PUBLISHED,
        "artifact": artifact,
        "handle": handle,
        "inputs_ready": inputs_ready,
    }


def final_refused(reason: str) -> Dict[str, Any]:
    return {
        "protocol": STAGING_FINAL_RESULT_PROTOCOL,
        "status": STATUS_REFUSED,
        "reason": _checked(reason, STAGING_FINAL_REFUSAL_REASONS, STAGING_FINAL_PROTOCOL),
    }


#: protocol -> the builder that answers an over-cap frame, and with what reason. Only
#: §4.10(b) has an ``oversize_frame`` in its closed set; the other three say ``malformed``,
#: because inventing a reason outside a published set is exactly what :func:`_checked`
#: exists to stop.
_OVER_FRAME_REPLY: Dict[str, Callable[[], Dict[str, Any]]] = {
    OPEN_PROTOCOL: lambda: open_refused(REFUSE_MALFORMED),
    STAGING_OPEN_PROTOCOL: lambda: staging_open_refused(REFUSE_MALFORMED),
    STAGING_CHUNK_PROTOCOL: lambda: chunk_refused(REFUSE_OVERSIZE_FRAME, 0),
    STAGING_FINAL_PROTOCOL: lambda: final_refused(REFUSE_MALFORMED),
}


def frame_cap_refusal(protocol: Any, frame_len: int) -> Optional[Dict[str, Any]]:
    """The per-protocol frame bound, applied to the bytes that actually arrived.

    Returns the refusal reply, or ``None`` if the frame is within its protocol's cap. An
    unknown protocol returns ``None`` — deciding whether the sidecar may send it at all is
    the front door's job, not this table's, and answering "no" twice in two vocabularies
    would be worse than answering once.
    """
    cap = SIDECAR_FRAME_CAPS.get(protocol)
    if cap is None or frame_len <= cap:
        return None
    return _OVER_FRAME_REPLY[protocol]()


# ---------------------------------------------------------------------------
# Shape validation
# ---------------------------------------------------------------------------


def _require_mapping(request: Any) -> Mapping[str, Any]:
    if not isinstance(request, Mapping):
        raise _Refuse(REFUSE_MALFORMED, "request must be a JSON object")
    return request


def _require_exact_request(request: Any, protocol: str,
                           fields: Tuple[str, ...]) -> Mapping[str, Any]:
    request = _require_mapping(request)
    keys = set(request.keys())
    extra = keys - set(fields)
    if extra:
        raise _Refuse(REFUSE_MALFORMED, "unexpected field(s) %s" % sorted(extra))
    missing = set(fields) - keys
    if missing:
        raise _Refuse(REFUSE_MALFORMED, "missing field(s) %s" % sorted(missing))
    if request["protocol"] != protocol:
        raise _Refuse(REFUSE_MALFORMED, "unexpected protocol %r" % (request["protocol"],))
    return request


def _require_id(request: Mapping[str, Any], field: str) -> str:
    value = request[field]
    if not isinstance(value, str) or not (0 < len(value) <= MAX_ID_LEN):
        raise _Refuse(REFUSE_MALFORMED, "%s must be a 1..128 char string" % field)
    return value


def _require_int(request: Mapping[str, Any], field: str) -> int:
    value = request[field]
    if not isinstance(value, int) or isinstance(value, bool):
        raise _Refuse(REFUSE_MALFORMED, "%s must be an integer" % field)
    return value


def _require_sha256(request: Mapping[str, Any], field: str) -> str:
    value = request[field]
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise _Refuse(REFUSE_MALFORMED, "%s must be lowercase 64-hex" % field)
    return value


def _require_frame_fits(request: Mapping[str, Any], protocol: str, reason: str) -> None:
    """The FRAME cap, checked on the compact serialization of the decoded request.

    ``encode_frame`` is reused rather than a length being estimated, so this bound is the
    same one the transport applies and cannot drift from it. It runs BEFORE ``bytes_b64``
    is decoded, which is the ordering §2.4 fixes: an oversized serialized frame is refused
    on the frame cap without the decoder ever being handed the payload.

    **Only §4.10(b) calls this, and that is deliberate.** §4.10(a) and §4.10(c) have
    EXHAUSTIVE shapes in which every field is a ≤128-char id, a 64-hex digest, a
    closed-set artifact name or a bounded integer — so their largest legal request is a few
    hundred bytes and a handler-level frame check for them could never fire: the shape check
    refuses first, always, with the same verdict. Shipping it anyway would be a check that
    reads as protection while protecting nothing, and mutation testing found exactly that
    (deleting it changed no test). What DOES bound their frames is the shape itself, proved
    arithmetically in the tests, plus the front door's ``frame_cap_refusal`` — which sees the
    raw bytes and so can refuse padding the decoder would have discarded. §4.10(b) is
    different in kind: ``bytes_b64`` is legitimately 240 KiB, so there this is the only thing
    standing between the sender and an unbounded body.
    """
    try:
        encode_frame(dict(request))
    except ProtocolError:
        raise _Refuse(reason, "serialized frame exceeds the %s cap" % protocol)
    except (TypeError, ValueError) as exc:
        # A body that will not serialize at all is not an oversize frame, it is not a
        # frame. Saying "oversize" about it would be a wrong answer in a closed set.
        raise _Refuse(REFUSE_MALFORMED, "request is not JSON-serializable: %s" % exc)


# ---------------------------------------------------------------------------
# Session directories and immutable chunk files
# ---------------------------------------------------------------------------


def _validate_session_id(staging_session_id: str) -> str:
    """A session id NAMES A DIRECTORY, so its charset is a filesystem question, not a
    cosmetic one. base64url only: no separator, no ``..``, no absolute path, no NUL — a
    minted id could otherwise place ``session_dir`` anywhere the supervisor can write.

    A violation is a SUPERVISOR fault, not a peer refusal: ids are minted here and never
    read off the wire for creation, so an invalid one means the injected minter is wrong.
    """
    if not isinstance(staging_session_id, str) or not _SESSION_ID_RE.match(staging_session_id):
        raise SupervisorError("minted staging_session_id is not base64url-shaped")
    return staging_session_id


def mint_session_id() -> str:
    """256 bits of ``secrets`` entropy, base64url, 43 chars.

    §4.10(a) asks only for "an opaque string ≤128", and within the design's threat model a
    guessable id would gain an attacker nothing — the sidecar is the only principal that
    may send these messages, so it can only guess its own sessions. It is unguessable
    anyway because the cost is zero and the property survives a future caller the design
    does not have yet.
    """
    return secrets.token_urlsafe(32)


def _session_dir(staging_root: pathlib.Path, staging_session_id: str) -> pathlib.Path:
    return pathlib.Path(staging_root) / _validate_session_id(staging_session_id)


def _ensure_session_dir(session_dir: pathlib.Path) -> pathlib.Path:
    """Create (or re-validate) the 0700 supervisor-only ``session_dir``.

    ``allow_group=False`` is the §2.4 requirement and NOT the evidence store's default: the
    store is shared with the signer through a group, staging is shared with nobody — "the
    sidecar/executor have no read". Reusing the store's one hardening implementation with a
    stricter policy argument is the alternative to a second copy of it.
    """
    return harden_private_dir(pathlib.Path(session_dir), allow_group=False)


def _chunk_path(session_dir: pathlib.Path, seq: int) -> pathlib.Path:
    return pathlib.Path(session_dir) / ("%d.chunk" % seq)


def _write_immutable_chunk(session_dir: pathlib.Path, seq: int, data: bytes) -> bool:
    """§2.4 steps 3-6: O_EXCL temp -> fsync -> ``os.link`` into the immutable
    ``<seq>.chunk`` -> fsync the dir. Returns True if the bytes now on disk are byte-
    identical to ``data`` (a fresh write, or an EEXIST replay/adopt), False if a DIFFERENT
    ``<seq>.chunk`` is already there.

    EEXIST is not an error here and not silently a success either. It is the §2.4
    restart-recovery rule (a): a durable chunk file with no DB row means a crash between
    the dir fsync and the commit, and a byte-identical retry ADOPTS it — the caller re-runs
    the transaction and ACKs — while a conflicting re-send is ``retry_conflict``.

    ``os.link``/``O_EXCL`` is the frozen create-if-absent primitive the design names, taken
    from ``brops_evidence_store`` rather than rewritten; it is emphatically not a rename.
    """
    directory = pathlib.Path(session_dir)
    target = _chunk_path(directory, seq)
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".part")
    tmp = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        if os.name == "posix":
            os.chmod(tmp, 0o600)
        created = atomic_link_or_create(tmp, target, data)
        fsync_dir(directory)
        if created:
            return True
        return target.read_bytes() == data
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _read_durable_chunk(session_dir: Any, seq: int, chunk_sha256: str) -> Optional[bytes]:
    """The immutable ``<seq>.chunk``, or ``None`` if it is missing, unreadable, or no
    longer hashes to the digest recorded for it.

    ``None`` is the §2.4 recovery rule (b) trigger, and the caller's only correct response
    is to make the session ``SESSION_CORRUPT``. It is never "re-upload it": the recorded
    cursor already counted those bytes, so re-accepting different ones at a seq the session
    has moved past would let the final digest cover bytes the ACKed prefix never contained.
    """
    path = _chunk_path(pathlib.Path(session_dir), seq)
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if hashlib.sha256(data).hexdigest() != chunk_sha256:
        return None
    return data


# ---------------------------------------------------------------------------
# §4.10(a) — brops.governed-staging-open.v1
# ---------------------------------------------------------------------------


def handle_staging_open(
    request: Any,
    *,
    peer_uid: Any,
    allowed_sidecar_uid: Any,
    conn: Any,
    staging_root: Any,
    mint_id: Callable[[], str] = mint_session_id,
) -> Dict[str, Any]:
    """Serve one ``brops.governed-staging-open.v1`` and return the §4.10(a) reply.

    The session is opened against the ALREADY-VERIFIED challenge: this message never
    carries a document, a signature or a digest the supervisor has not already committed
    to. ``declared_sha256`` must equal the ``*_sha256`` the signature-verified challenge
    fixed for this artifact, so the *content* of a legal upload is decided before the first
    chunk exists and the sender's only remaining freedom is how many bytes it claims to be
    sending — itself bounded by the artifact's ceiling.

    It creates NO row of its own beyond the session: the ``governed_turn_staging`` row must
    already exist in ``UPLOADING`` (that was §4.10(a0)), and a missing one is
    ``no_staging_row`` rather than an implicit creation.
    """
    if conn is None:
        raise SupervisorError("governed-staging-open requires a durable ledger connection")
    try:
        if not peer_is_sidecar(peer_uid, allowed_sidecar_uid):
            raise _Refuse(REFUSE_PEER_DENIED, "peer uid is not the sidecar principal")

        request = _require_exact_request(
            request, STAGING_OPEN_PROTOCOL, STAGING_OPEN_REQUEST_FIELDS
        )
        install_id = _require_id(request, "install_id")
        request_nonce = _require_id(request, "request_nonce")
        challenge_handle = _require_sha256(request, "challenge_handle")
        declared_sha256 = _require_sha256(request, "declared_sha256")
        declared_len = _require_int(request, "declared_len")

        artifact = request["artifact"]
        if not isinstance(artifact, str):
            raise _Refuse(REFUSE_MALFORMED, "artifact must be a string")
        if artifact not in staging.STAGING_ARTIFACTS:
            # `policy_bundle` lands exactly here (§2.4 policy authority): the challenge has
            # no `policy_bundle_sha256`, so there is nothing to bind a sidecar-supplied
            # policy against, and policy must not traverse the untrusted sidecar at all.
            raise _Refuse(REFUSE_ARTIFACT_INVALID, "artifact %r is not uploadable" % (artifact,))
        if declared_len < 0:
            raise _Refuse(REFUSE_MALFORMED, "declared_len must be >= 0")

        # The turn must already have been opened, and the row must be the one this request
        # names on ALL THREE identity fields — a challenge_handle that belongs to a
        # different nonce or install is not this turn.
        row = staging.load_staging(conn, install_id, request_nonce)
        if (row is None
                or row["challenge_handle"] != challenge_handle
                or row["state"] != staging.UPLOADING):
            raise _Refuse(REFUSE_NO_STAGING_ROW, "no UPLOADING staging row for this turn")

        if row[staging.ARTIFACT_DIGEST_COLUMN[artifact]] != declared_sha256:
            raise _Refuse(
                REFUSE_DIGEST_MISMATCH,
                "declared_sha256 is not the challenge's committed digest for %s" % artifact,
            )
        if declared_len > ARTIFACT_CEILINGS[artifact]:
            raise _Refuse(REFUSE_OVERSIZE, "declared_len exceeds the %s ceiling" % artifact)

        session_id = _validate_session_id(mint_id())
        session_dir = _session_dir(pathlib.Path(staging_root), session_id)
        try:
            outcome, session = staging.open_session(
                conn,
                staging.NewSession(
                    staging_session_id=session_id,
                    challenge_handle=challenge_handle,
                    artifact=artifact,
                    declared_len=declared_len,
                    declared_sha256=declared_sha256,
                    session_dir=str(session_dir),
                ),
            )
        except staging.SessionCorrupt:
            raise _Refuse(REFUSE_SESSION_CORRUPT, "session is SESSION_CORRUPT")
        except staging.SessionQuotaExceeded as exc:
            raise _Refuse(exc.reason, str(exc))
        except staging.Conflict:
            raise _Refuse(REFUSE_RETRY_CONFLICT, "session declares different bytes")
        except staging.NotFound:
            raise _Refuse(REFUSE_NO_STAGING_ROW, "staging row vanished under the open")
        except staging.LedgerError as exc:
            raise SupervisorError("staging session ledger fault: %s" % exc)

        # The directory is created AFTER the row commits, and only when this call created
        # the row. Creating it first would leave an orphan 0700 dir behind every idempotent
        # re-open; a crash between the commit and the mkdir is harmless because the chunk
        # path hardens the directory again before it writes.
        if outcome == staging.CREATED:
            _ensure_session_dir(pathlib.Path(session["session_dir"]))

        # ALWAYS from the stored row: an idempotent re-open must re-emit the ORIGINAL
        # session id and the CURRENT cursor, never the id just minted.
        return staging_opened(session["staging_session_id"], session["next_seq"])
    except _Refuse as refusal:
        return staging_open_refused(refusal.reason)


# ---------------------------------------------------------------------------
# §4.10(b) — brops.governed-staging-chunk.v1
# ---------------------------------------------------------------------------


def expected_chunk_len(declared_len: int, byte_count: int) -> int:
    """§2.4 P1-3, LOCKED: the chunk length is NOT sender-chosen.

    Every chunk is exactly ``min(184320, declared_len - byte_count)``, so all chunks are a
    full 184320 except the final remainder. That single rule is what bounds cardinality:
    ``n_chunks`` becomes ``ceil(declared_len / 184320)``, a function of the declaration, so
    a compromised sidecar cannot turn one 8 MiB artifact into eight million one-byte
    messages.
    """
    return min(MAX_STAGING_CHUNK_BYTES, declared_len - byte_count)


def n_chunks(declared_len: int) -> int:
    """``ceil(declared_len / 184320)`` — and 0 for the zero-byte artifact, which sends NO
    chunk message at all and goes straight to §4.10(c)."""
    return (declared_len + MAX_STAGING_CHUNK_BYTES - 1) // MAX_STAGING_CHUNK_BYTES


def handle_staging_chunk(
    request: Any,
    *,
    peer_uid: Any,
    allowed_sidecar_uid: Any,
    conn: Any,
) -> Dict[str, Any]:
    """Serve one ``brops.governed-staging-chunk.v1`` and return the §4.10(b) reply.

    The whole message reduces to the single canonical order predicate (P1-2, LOCKED — the
    old collapsed "seq != next_seq ⇒ refuse" is deleted):

      * ``seq == next_seq`` — validate the deterministic length, persist the immutable
        ``<seq>.chunk``, advance the cursor, and ACK **only after the DB commit**;
      * ``seq < next_seq`` and byte-identical to the durable chunk — idempotent ACK at the
        current cursor, nothing re-appended, ``byte_count`` unchanged;
      * ``seq < next_seq`` and different — ``retry_conflict``;
      * ``seq > next_seq`` — ``seq_mismatch``, a true gap.

    ACK-after-commit is the ordering that matters. ACKing before the commit would let a
    crash lose a chunk the sender believes was accepted, and the sender would then send
    ``seq+1`` into a supervisor still at ``seq`` — a gap nothing could reconcile, because
    the immutable-file rule means the missing bytes can never be back-filled.
    """
    if conn is None:
        raise SupervisorError("governed-staging-chunk requires a durable ledger connection")
    next_seq = 0
    try:
        if not peer_is_sidecar(peer_uid, allowed_sidecar_uid):
            raise _Refuse(_CHUNK_PEER_DENIED, "peer uid is not the sidecar principal")

        # FRAME cap first, on the serialization, before the payload is decoded (§2.4).
        _require_frame_fits(_require_mapping(request), STAGING_CHUNK_PROTOCOL, REFUSE_OVERSIZE_FRAME)
        request = _require_exact_request(
            request, STAGING_CHUNK_PROTOCOL, STAGING_CHUNK_REQUEST_FIELDS
        )
        session_id = _require_id(request, "staging_session_id")
        seq = _require_int(request, "seq")
        if seq < 0:
            raise _Refuse(REFUSE_MALFORMED, "seq must be >= 0")
        if seq >= staging.MAX_STAGING_CHUNKS:
            raise _Refuse(REFUSE_TOO_MANY_CHUNKS, "seq %d is past the 46-chunk cap" % seq)
        if not isinstance(request["bytes_b64"], str):
            raise _Refuse(REFUSE_MALFORMED, "bytes_b64 must be a string")
        try:
            data = decode_base64url(request["bytes_b64"])
        except ProtocolError as exc:
            raise _Refuse(REFUSE_MALFORMED, "bytes_b64 is not canonical base64url: %s" % exc)
        # DECODED cap, checked independently of the frame cap: 184321 bytes still fit a
        # frame and must die here anyway.
        if len(data) > MAX_STAGING_CHUNK_BYTES:
            raise _Refuse(REFUSE_OVERSIZE_CHUNK, "decoded chunk exceeds 184320 bytes")

        session = staging.load_session(conn, session_id)
        if session is None:
            raise _Refuse(REFUSE_SESSION_UNKNOWN, "no such staging session")
        next_seq = session["next_seq"]
        if session["state"] == staging.SESSION_CORRUPT:
            raise _Refuse(REFUSE_SESSION_CORRUPT, "session is SESSION_CORRUPT")

        if seq > next_seq:
            raise _Refuse(REFUSE_SEQ_MISMATCH, "seq %d is past the cursor %d" % (seq, next_seq))
        if seq < next_seq:
            return _replay_chunk(conn, session, seq, data)

        # ---- seq == next_seq: the only path that may write -----------------------
        if session["state"] != staging.SESSION_UPLOADING:
            # An ARTIFACT_READY session's cursor is final; nothing may be appended to a
            # published artifact.
            raise _Refuse(REFUSE_SEQ_MISMATCH, "session is not accepting chunks")
        # There is deliberately NO second `next_seq >= MAX_STAGING_CHUNKS` guard here. On
        # this branch `seq == next_seq`, and `seq >= 46` was already refused
        # `too_many_chunks` above — so a guard here could never fire from any request, and
        # an unreachable check reads as protection while protecting nothing. The floor that
        # does hold regardless of this code is the `next_seq <= 46` SQL CHECK.
        declared_len = session["declared_len"]
        byte_count = session["byte_count"]
        if byte_count + len(data) > declared_len:
            raise _Refuse(REFUSE_OVER_DECLARED, "chunk would exceed declared_len")
        if len(data) != expected_chunk_len(declared_len, byte_count):
            raise _Refuse(
                REFUSE_NONDETERMINISTIC_CHUNK,
                "chunk_len %d is not the deterministic length" % len(data),
            )

        session_dir = _ensure_session_dir(pathlib.Path(session["session_dir"]))
        if not _write_immutable_chunk(session_dir, seq, data):
            # A DIFFERENT <seq>.chunk is already durable. §2.4 recovery rule (a): the
            # byte-identical retry adopts, a conflicting re-send does not.
            raise _Refuse(REFUSE_RETRY_CONFLICT, "a different chunk is already durable at this seq")

        try:
            advanced = staging.record_chunk(
                conn, session_id, seq, hashlib.sha256(data).hexdigest(), len(data)
            )
        except staging.SessionCorrupt:
            raise _Refuse(REFUSE_SESSION_CORRUPT, "session is SESSION_CORRUPT")
        except (staging.Conflict, staging.IllegalTransition):
            raise _Refuse(REFUSE_RETRY_CONFLICT, "cursor moved under this chunk")
        except staging.NotFound:
            raise _Refuse(REFUSE_SESSION_UNKNOWN, "session vanished under this chunk")
        except staging.LedgerError as exc:
            raise SupervisorError("staging chunk ledger fault: %s" % exc)

        return chunk_ack(advanced["next_seq"])
    except _Refuse as refusal:
        return chunk_refused(refusal.reason, next_seq)


def _replay_chunk(conn: Any, session: Any, seq: int, data: bytes) -> Dict[str, Any]:
    """``seq < next_seq``: a chunk the supervisor already counted.

    The comparison is against the DURABLE FILE, re-hashed, not against the recorded digest
    alone. Checking only the digest would let a session whose bytes had rotted under it
    keep ACKing replays and then fail — or worse, publish — at final; §2.4 recovery rule
    (b) says the answer to a missing or mismatched chunk file is a terminal
    ``SESSION_CORRUPT`` session, never a repair.
    """
    session_id = session["staging_session_id"]
    next_seq = session["next_seq"]
    recorded = staging.load_chunk(conn, session_id, seq)
    if recorded is None:
        staging.mark_session_corrupt(conn, session_id)
        raise _Refuse(REFUSE_SESSION_CORRUPT, "no recorded chunk below the cursor")
    durable = _read_durable_chunk(session["session_dir"], seq, recorded["chunk_sha256"])
    if durable is None:
        staging.mark_session_corrupt(conn, session_id)
        raise _Refuse(REFUSE_SESSION_CORRUPT, "durable chunk is missing or does not re-hash")
    if durable != data:
        raise _Refuse(REFUSE_RETRY_CONFLICT, "re-sent bytes differ from the accepted chunk")
    return chunk_ack(next_seq)


# ---------------------------------------------------------------------------
# §4.10(c) — brops.governed-staging-final.v1
# ---------------------------------------------------------------------------


def handle_staging_final(
    request: Any,
    *,
    peer_uid: Any,
    allowed_sidecar_uid: Any,
    conn: Any,
    publish_artifact: Callable[[bytes], str],
    clock_ms: Callable[[], int],
) -> Dict[str, Any]:
    """Serve one ``brops.governed-staging-final.v1`` and return the §4.10(c) reply.

    Assembly re-reads the immutable ``<seq>.chunk`` files in strict order and recomputes
    SHA-256 **and** length **from byte zero**. No stored incremental hash is consulted,
    because §2.4 P0-1 is right that a finalized SHA-256 digest is not a resumable internal
    hash state — trusting one across a restart would mean trusting a value no later read
    could contradict.

    Then three assertions, in this order, and only then a publish:

      1. the assembled length equals ``declared_len``   (else ``len_mismatch``);
      2. the recomputed digest equals ``declared_sha256`` (else ``sha_mismatch``);
      3. the recomputed digest equals the digest the SIGNED CHALLENGE committed to for
         this artifact, re-read from the turn now (else ``handle_not_challenge``) — the
         supervisor never publishes bytes the challenge did not authorize.

    Assertion 3 is redundant with §4.10(a)'s ``digest_mismatch`` gate on the happy path,
    and that is the intent: it is re-checked against durable state at the moment of
    publication rather than trusted from a check made at open, and the same equality is
    ALSO enforced by a trigger when the handle is recorded, so three independent things
    must fail together for an unauthorized artifact to be bound to a turn.
    """
    if conn is None:
        raise SupervisorError("governed-staging-final requires a durable ledger connection")
    if not callable(publish_artifact):
        raise SupervisorError("publish_artifact must be callable")
    try:
        if not peer_is_sidecar(peer_uid, allowed_sidecar_uid):
            raise _Refuse(_FINAL_PEER_DENIED, "peer uid is not the sidecar principal")

        request = _require_exact_request(
            request, STAGING_FINAL_PROTOCOL, STAGING_FINAL_REQUEST_FIELDS
        )
        session_id = _require_id(request, "staging_session_id")
        seq = _require_int(request, "seq")
        if seq < 0:
            raise _Refuse(REFUSE_MALFORMED, "seq must be >= 0")

        session = staging.load_session(conn, session_id)
        if session is None:
            raise _Refuse(REFUSE_SESSION_UNKNOWN, "no such staging session")
        if session["state"] == staging.SESSION_CORRUPT:
            raise _Refuse(REFUSE_SESSION_CORRUPT, "session is SESSION_CORRUPT")

        turn = staging.load_staging_by_handle(conn, session["challenge_handle"])
        if turn is None:
            raise _Refuse(REFUSE_SESSION_UNKNOWN, "the session's turn is gone")
        artifact = session["artifact"]

        if session["state"] == staging.ARTIFACT_READY:
            # §4.10(c) idempotent final: the SAME reply, rebuilt from the recorded handle,
            # so a lost reply is safe. A retry naming a different cursor is not that retry.
            if seq != session["next_seq"]:
                raise _Refuse(REFUSE_RETRY_CONFLICT, "final retry names a different cursor")
            return final_published(
                artifact, session["published_handle"], _inputs_ready(turn)
            )

        if seq != session["next_seq"]:
            raise _Refuse(
                REFUSE_SEQ_MISMATCH,
                "final seq %d is not the cursor %d" % (seq, session["next_seq"]),
            )

        assembled = _assemble(conn, session)
        declared_len = session["declared_len"]
        if len(assembled) != declared_len:
            raise _Refuse(REFUSE_LEN_MISMATCH, "assembled %d != declared %d"
                          % (len(assembled), declared_len))
        recomputed = hashlib.sha256(assembled).hexdigest()
        if recomputed != session["declared_sha256"]:
            raise _Refuse(REFUSE_SHA_MISMATCH, "assembled bytes do not match declared_sha256")
        if recomputed != turn[staging.ARTIFACT_DIGEST_COLUMN[artifact]]:
            raise _Refuse(REFUSE_HANDLE_NOT_CHALLENGE,
                          "assembled digest is not the challenge's committed digest")

        try:
            handle = publish_artifact(assembled)
        except Exception:
            # The store's own divergent-refuse: an existing object at this handle whose
            # bytes do not hash to it. Fail closed rather than record a handle that does
            # not resolve to the bytes just assembled.
            raise _Refuse(REFUSE_PUBLISH_DIVERGENT, "store refused the publish")
        if not isinstance(handle, str) or handle.lower() != recomputed:
            raise _Refuse(REFUSE_HANDLE_NOT_CHALLENGE,
                          "the store returned a handle that is not the assembled digest")

        now_ms = clock_ms()
        if not isinstance(now_ms, int) or isinstance(now_ms, bool):
            raise SupervisorError("clock_ms must return an int (epoch ms)")
        try:
            _session, inputs_ready = staging.finalize_session(conn, session_id, handle, now_ms)
        except staging.SessionCorrupt:
            raise _Refuse(REFUSE_SESSION_CORRUPT, "session is SESSION_CORRUPT")
        except (staging.Conflict, staging.IllegalTransition):
            raise _Refuse(REFUSE_RETRY_CONFLICT, "session moved under this final")
        except staging.NotFound:
            raise _Refuse(REFUSE_SESSION_UNKNOWN, "session vanished under this final")
        except staging.LedgerError as exc:
            raise SupervisorError("staging final ledger fault: %s" % exc)

        return final_published(artifact, handle, inputs_ready)
    except _Refuse as refusal:
        return final_refused(refusal.reason)


def _inputs_ready(turn: Any) -> bool:
    return all(turn[staging.ARTIFACT_HANDLE_COLUMN[a]] is not None
               for a in staging.STAGING_ARTIFACTS)


def _assemble(conn: Any, session: Any) -> bytes:
    """Read ``<seq>.chunk`` for ``0 .. next_seq-1`` in strict order into one bounded buffer.

    The buffer is bounded by construction and not by hope: the cursor cannot exceed 46, a
    chunk cannot exceed 184320 decoded bytes, and ``byte_count <= declared_len <= 8 MiB``
    is a CHECK constraint — so the worst case here is the 8 MiB history artifact, the same
    bound §4.10(f) puts on the desktop's reassembly buffer.

    A missing chunk row cannot occur (the gapless trigger), and a missing or mismatched
    chunk FILE is §2.4 recovery rule (b): the session becomes terminally ``SESSION_CORRUPT``
    and nothing is ever published from it.
    """
    session_id = session["staging_session_id"]
    parts = bytearray()
    for seq in range(session["next_seq"]):
        recorded = staging.load_chunk(conn, session_id, seq)
        if recorded is None:
            staging.mark_session_corrupt(conn, session_id)
            raise _Refuse(REFUSE_SESSION_CORRUPT, "chunk %d has no recorded digest" % seq)
        durable = _read_durable_chunk(session["session_dir"], seq, recorded["chunk_sha256"])
        if durable is None:
            staging.mark_session_corrupt(conn, session_id)
            raise _Refuse(REFUSE_SESSION_CORRUPT,
                          "chunk %d is missing or does not re-hash" % seq)
        parts.extend(durable)
    return bytes(parts)


# ---------------------------------------------------------------------------
# §2.4 — the sweep, filesystem half
# ---------------------------------------------------------------------------

#: The prefix/suffix ``_write_immutable_chunk`` gives its ``mkstemp`` temp, and therefore the
#: exact shape §2.4 means by "orphan ``.tmp-*.part``". Derived from the writer rather than
#: re-typed: a sweep that hunted a pattern the writer no longer produces would report zero
#: orphans forever and read as healthy.
TEMP_CHUNK_PREFIX = ".tmp-"
TEMP_CHUNK_SUFFIX = ".part"


@dataclass(frozen=True)
class StagingSweep:
    """One pass of the §2.4 sweep, in numbers — including what it could NOT reclaim.

    ``failures`` exists because the alternative is a sweep that stops at the first bad path
    and silently stops meeting its SLA for every session behind it. One unreadable directory
    must not hold the whole install's quota hostage, and it must not disappear either.
    """

    rows: int
    sessions: int
    dirs_removed: int
    orphan_dirs_removed: int
    temps_removed: int
    failures: Tuple[str, ...] = ()

    def as_detail(self) -> Dict[str, Any]:
        return {"rows": self.rows, "sessions": self.sessions,
                "dirs_removed": self.dirs_removed,
                "orphan_dirs_removed": self.orphan_dirs_removed,
                "temps_removed": self.temps_removed,
                "failures": list(self.failures)}


def _remove_session_tree(staging_root: pathlib.Path, session_dir: Any) -> int:
    """Unlink one ``session_dir`` and every flat file in it. Returns the files removed.

    Two containment rules, both refusals rather than best-effort:

      * the directory MUST be a direct child of ``staging_root`` whose name is a valid
        session id — the same predicate ``_session_dir`` used to build it, so a stored path
        that could send this anywhere else is a supervisor fault and is refused, not walked;
      * it is NOT a recursive delete. A session directory holds flat ``<seq>.chunk`` and
        ``.tmp-*.part`` files and nothing else, so a subdirectory inside one means something
        this sweep does not understand put it there. It is left, named, and reported.

    A sweep is the one component whose whole job is deletion; it is worth it being unable to
    express a deletion outside the tree it owns.
    """
    directory = pathlib.Path(session_dir)
    if directory.parent != staging_root or not _SESSION_ID_RE.match(directory.name):
        raise SupervisorError(
            "refusing to sweep %s: not a session directory under %s" % (directory, staging_root)
        )
    removed = 0
    for entry in sorted(directory.iterdir()):
        if entry.is_dir() and not entry.is_symlink():
            raise SupervisorError("refusing to sweep %s: it holds a subdirectory" % directory)
        entry.unlink()
        removed += 1
    directory.rmdir()
    return removed


def _sweep_orphan_temps(session_dir: pathlib.Path, now_ms: int) -> int:
    """Unlink the ``.tmp-*.part`` files of a LIVE session that no write can still own.

    §2.4 names orphan temps separately from the whole-``session_dir`` unlink, so they are
    collected inside surviving sessions too — but an age bound is what makes that safe. A
    temp is only orphaned once no in-flight ``_write_immutable_chunk`` could still be holding
    it, and unlinking one that IS held would break that chunk's ``os.link`` for no reason.

    ``STAGING_CLEANUP_DEADLINE_MS`` is the bound, and it is not arbitrary: a session's whole
    life is bounded by the 30 s challenge TTL, so a temp older than the two-sweep cleanup
    deadline cannot belong to a live write — its session is already past sweeping.
    """
    removed = 0
    for entry in sorted(session_dir.iterdir()):
        name = entry.name
        if not (name.startswith(TEMP_CHUNK_PREFIX) and name.endswith(TEMP_CHUNK_SUFFIX)):
            continue
        if entry.is_dir() and not entry.is_symlink():
            continue
        age_ms = now_ms - int(entry.stat().st_mtime * 1000)
        if age_ms < staging.STAGING_CLEANUP_DEADLINE_MS:
            continue
        entry.unlink()
        removed += 1
    return removed


def sweep_staging(conn: Any, staging_root: Any, now_ms: int) -> StagingSweep:
    """One §2.4 sweep pass: reclaim every expired turn's row, sessions, chunks and bytes.

    This is the mechanism the §2.4 session and byte quotas are written against — "a provable
    completion SLA so the per-install byte/file quotas can rely on expired rows being gone" —
    and until 2026-08-13 it did not exist in this tree, which is what made an install support
    exactly two completing governed turns for the life of the deployment.

    The order is the ledger first (:func:`governed_staging_ledger.sweep_expired_staging`,
    which commits the DELETE and hands back the directories the rows named), then the
    filesystem. A crash between them leaves directories with no row, and the SAME pass that
    would have removed them collects them next time as orphans — so the staging root converges
    on "exactly the directories of sessions that still exist" from either side of a crash.

    What it will not do: touch the published store (it never learns a store path), consume a
    challenge nonce (see the ledger half), remove a LIVE turn's row, session or directory, or
    delete anything outside ``staging_root``.
    """
    root = pathlib.Path(staging_root)
    if not root.is_dir():
        raise SupervisorError("staging root is not a directory: %s" % root)

    swept = staging.sweep_expired_staging(conn, now_ms)

    failures = []
    dirs_removed = 0
    for session_dir in swept.session_dirs:
        try:
            _remove_session_tree(root, session_dir)
            dirs_removed += 1
        except FileNotFoundError:
            # The row named a directory that is not there: a crash between the row commit
            # and the mkdir, or a previous pass that got this far. Reclaimed either way.
            dirs_removed += 1
        except (SupervisorError, OSError) as exc:
            failures.append("%s: %s" % (session_dir, exc))

    # Everything still on disk that no surviving session names. This is the half that
    # survives a crash in the middle of the pass above, and the half that collects a
    # directory whose row was deleted by a cascade rather than by name.
    live_dirs = {
        pathlib.Path(row["session_dir"]).name
        for row in conn.execute(
            "SELECT session_dir FROM governed_turn_staging_session"
        ).fetchall()
    }
    orphan_dirs_removed = 0
    temps_removed = 0
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.is_symlink():
            # The supervisor's private 0700 root holds session directories. Anything else is
            # not this sweep's to delete, and is reported rather than removed or ignored.
            failures.append("%s: not a session directory" % entry)
            continue
        try:
            if entry.name in live_dirs:
                temps_removed += _sweep_orphan_temps(entry, now_ms)
                continue
            _remove_session_tree(root, entry)
            orphan_dirs_removed += 1
        except (SupervisorError, OSError) as exc:
            failures.append("%s: %s" % (entry, exc))

    return StagingSweep(
        rows=swept.rows_deleted,
        sessions=len(swept.sessions),
        dirs_removed=dirs_removed,
        orphan_dirs_removed=orphan_dirs_removed,
        temps_removed=temps_removed,
        failures=tuple(failures),
    )


def sweep_forever(*, conn: Any, staging_root: Any, clock_ms: Callable[[], int], stop: Any,
                  interval_ms: int = staging.STAGING_SWEEP_INTERVAL_MS,
                  on_pass: Optional[Callable[[Any], None]] = None) -> int:
    """§2.4's "background sweep (plus a startup pass)": sweep, wait, repeat. Returns passes.

    The startup pass is not a special case — it is the first iteration, which is why it
    cannot be forgotten by a deployment that starts the loop.

    ``stop`` is any object with ``wait(seconds) -> bool`` (``threading.Event`` is the one the
    deployment passes), so the schedule is drivable in a test without a clock or a thread.
    This function creates no thread itself: WHERE the sweep runs is a deployment decision and
    belongs to the process that owns the supervisor's lifetime.

    A pass that raises does not end the loop. The SLA is the reason: one bad pass must not
    silently retire the only thing that returns staging quota, and the fault has to reach
    ``on_pass`` where the deployment logs it.
    """
    if interval_ms <= 0:
        raise SupervisorError("staging sweep interval must be positive")
    passes = 0
    while True:
        try:
            report: Any = sweep_staging(conn, staging_root, clock_ms())
        except Exception as exc:  # noqa: BLE001 — reported, never fatal to the schedule
            report = StagingSweep(rows=0, sessions=0, dirs_removed=0, orphan_dirs_removed=0,
                                  temps_removed=0, failures=("sweep pass failed: %s" % exc,))
        passes += 1
        if on_pass is not None:
            on_pass(report)
        if stop.wait(interval_ms / 1000.0):
            return passes


# ---------------------------------------------------------------------------
# The supervisor-side binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StagingService:
    """The §4.10(a)(b)(c) binding: the sidecar UID this supervisor serves, the 0700 staging
    root it owns, and the store publish seam.

    Like ``OpenService``, it is also the fail-closed switch. A supervisor constructed
    WITHOUT one serves no staging message at all — not because staging is optional, but
    because a supervisor that has not been told who the sidecar is or where its private
    staging root lives cannot honestly accept a byte on either's behalf.
    """

    allowed_sidecar_uid: int
    staging_root: Any
    publish_artifact: Callable[[bytes], str]
    mint_id: Callable[[], str] = mint_session_id

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_sidecar_uid, int) or isinstance(self.allowed_sidecar_uid, bool):
            raise SupervisorError("StagingService.allowed_sidecar_uid must be an int uid")
        if not callable(self.publish_artifact):
            raise SupervisorError("StagingService.publish_artifact must be callable")
        if not callable(self.mint_id):
            raise SupervisorError("StagingService.mint_id must be callable")

    def handle(self, request: Any, *, peer_uid: Any, conn: Any,
               clock_ms: Callable[[], int]) -> Dict[str, Any]:
        protocol = request.get("protocol") if isinstance(request, Mapping) else None
        if protocol == STAGING_OPEN_PROTOCOL:
            return handle_staging_open(
                request, peer_uid=peer_uid, allowed_sidecar_uid=self.allowed_sidecar_uid,
                conn=conn, staging_root=self.staging_root, mint_id=self.mint_id,
            )
        if protocol == STAGING_CHUNK_PROTOCOL:
            return handle_staging_chunk(
                request, peer_uid=peer_uid, allowed_sidecar_uid=self.allowed_sidecar_uid,
                conn=conn,
            )
        if protocol == STAGING_FINAL_PROTOCOL:
            return handle_staging_final(
                request, peer_uid=peer_uid, allowed_sidecar_uid=self.allowed_sidecar_uid,
                conn=conn, publish_artifact=self.publish_artifact, clock_ms=clock_ms,
            )
        raise SupervisorError("not a staging protocol: %r" % (protocol,))


#: The three protocols :class:`StagingService` serves. The front door routes on this set,
#: so admitting staging widens the sidecar's door by exactly these names.
STAGING_PROTOCOLS: Tuple[str, ...] = (
    STAGING_OPEN_PROTOCOL,
    STAGING_CHUNK_PROTOCOL,
    STAGING_FINAL_PROTOCOL,
)


__all__ = [
    "ARTIFACT_CEILINGS",
    "MAX_SIDECAR_FRAME_BYTES",
    "MAX_STAGING_CHUNK_BYTES",
    "MAX_STAGING_CHUNK_FRAME_BYTES",
    "MAX_STAGING_CONTROL_FRAME_BYTES",
    "MAX_TURN_UPLOAD_BYTES",
    "REFUSE_ARTIFACT_INVALID",
    "REFUSE_DIGEST_MISMATCH",
    "REFUSE_HANDLE_NOT_CHALLENGE",
    "REFUSE_LEN_MISMATCH",
    "REFUSE_MALFORMED",
    "REFUSE_NONDETERMINISTIC_CHUNK",
    "REFUSE_NO_STAGING_ROW",
    "REFUSE_OVERSIZE",
    "REFUSE_OVERSIZE_CHUNK",
    "REFUSE_OVERSIZE_FRAME",
    "REFUSE_OVER_DECLARED",
    "REFUSE_PEER_DENIED",
    "REFUSE_PUBLISH_DIVERGENT",
    "REFUSE_QUOTA_BYTES",
    "REFUSE_QUOTA_SESSIONS",
    "REFUSE_RETRY_CONFLICT",
    "REFUSE_SEQ_MISMATCH",
    "REFUSE_SESSION_CORRUPT",
    "REFUSE_SESSION_UNKNOWN",
    "REFUSE_SHA_MISMATCH",
    "REFUSE_TOO_MANY_CHUNKS",
    "SIDECAR_FRAME_CAPS",
    "STAGING_CHUNK_PROTOCOL",
    "STAGING_CHUNK_REFUSAL_REASONS",
    "STAGING_CHUNK_REQUEST_FIELDS",
    "STAGING_CHUNK_RESULT_PROTOCOL",
    "STAGING_FINAL_PROTOCOL",
    "STAGING_FINAL_REFUSAL_REASONS",
    "STAGING_FINAL_REQUEST_FIELDS",
    "STAGING_FINAL_RESULT_PROTOCOL",
    "STAGING_OPEN_PROTOCOL",
    "STAGING_OPEN_REFUSAL_REASONS",
    "STAGING_OPEN_REQUEST_FIELDS",
    "STAGING_OPEN_RESULT_PROTOCOL",
    "STAGING_PROTOCOLS",
    "STATUS_ACK",
    "STATUS_OPENED",
    "STATUS_PUBLISHED",
    "STATUS_REFUSED",
    "StagingService",
    "StagingSweep",
    "TEMP_CHUNK_PREFIX",
    "TEMP_CHUNK_SUFFIX",
    "chunk_ack",
    "chunk_refused",
    "expected_chunk_len",
    "final_published",
    "final_refused",
    "frame_cap_refusal",
    "handle_staging_chunk",
    "handle_staging_final",
    "handle_staging_open",
    "mint_session_id",
    "n_chunks",
    "staging_open_refused",
    "staging_opened",
    "sweep_forever",
    "sweep_staging",
]
