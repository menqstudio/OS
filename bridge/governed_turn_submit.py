"""``bridge.governed-turn-submit.v1`` — the §4.10(g) ingress, and the orchestrator behind it.

This is the hop every other governed piece has been consuming "by assumption". §4.10(a0),
§4.10(a)(b)(c), §4.10(d), §5 and §4.10(e) are the SUPERVISOR's halves; §4.6 is the shape the
outcome takes coming back. None of them had a client. This module is that client: one
one-shot subprocess reads ONE `bridge.governed-turn-submit.v1` frame off `stdin`, drives a
whole governed turn against the supervisor over `brops_socket`, and writes ONE §4.6
`bridge.governed-turn-result.v1` frame to `stdout`.

**§4.10(g) is PARTIAL and this file is one side of it.** The sidecar orchestrator built
here is complete. What is MISSING is a specific piece of the trusted side, and it is worth
naming precisely because much of that side already exists: the renderer's thin
`governed_turn_execute` proxy, the renderer↔broker IPC, the payload-aware idempotency store
and the broker orchestration control flow are all shipped
(`apps/desktop/src-tauri/src/governed_turn.rs`, `core/src/broker_client.rs`,
`core/src/governed_turn_ipc.rs`, `core/src/broker_turns.rs`,
`core/src/broker_orchestrator.rs`). What does not exist ANYWHERE in the tree is the
SUBMIT half: `prepare_governed_turn_v1b` / `PreparedGovernedTurnV1B` /
`GovernedGenerationConfig` / `resolve_governed_generation_config_v1b`, and the internal
`governed_turn_submit_prepared` helper that would build a `bridge.governed-turn-submit.v1`
frame and spawn this subprocess — zero occurrences of any of those five names. The broker's
one production `GovernedExecutor`, `broker/src/chain_executor.rs::ChainExecutor`, spawns
only the recorder and never a sidecar. So nothing in this tree writes a submit frame — see
"NOT WIRED" at the bottom, which says exactly what that costs and what it does not.

What it drives, in this exact order (§4.10(g), §6.1 steps 1-2-3)
----------------------------------------------------------------
1. ONE `brops.governed-turn-open.v1` (§4.10(a0)). It is FIRST and it is not negotiable:
   §4.10(a) requires the `UPLOADING` `governed_turn_staging` row that only turn-open
   creates, so a staging-open sent before it is refused `no_staging_row`.
2. Then, per artifact in the §2.4 order (`system`, `history`, `generation_config`), one
   `brops.governed-staging-open.v1` -> N x `brops.governed-staging-chunk.v1` ->
   one `brops.governed-staging-final.v1`.
3. ONE `brops.governed-evidence-request.v1` (§4.10(d)) — the execute/finalize trigger.
4. The §4.10(e) reply it answers with is re-framed by
   `governed_turn_result_bridge.reframe_turn_result` into §4.6 and returned.

There is no fifth step. §4.10(g) says in as many words that "this submit subprocess pulls
**NO** output": the §4.10(f) `brops.governed-turn-output-read.v1` loop belongs to the
backend, driven later through FRESH one-shot sidecars, and a test here records every frame
this orchestrator writes and asserts no output-read protocol is among them.

The three things this hop is careful NOT to do
-----------------------------------------------
§2.4 declares the sidecar compromised, so the interesting question is never "does it copy
the fields" but "which supervisor verdicts would a well-meaning local check make
unreachable". Three were deliberately not written:

* **The challenge document is forwarded VERBATIM.** `challenge_doc_b64` leaves this process
  as the exact string that arrived. It is decoded ONCE, to read `install_id` and
  `request_nonce` off the payload — the two §4.10(a0) request fields the submit frame does
  not carry — and the decoded value is then thrown away. Re-encoding it would mean the
  bytes §4.10(a0)'s canonicality gate hashes are bytes THIS process chose, which is exactly
  the divergence that gate exists to refuse. `noncanonical` therefore stays reachable
  through this hop, produced by the party entitled to produce it.
* **The three staged digests are NOT compared against the challenge's committed
  `*_sha256`.** This module declares the true digest of the bytes it actually derived and
  lets the supervisor decide. A local pre-check would be a guard masking its neighbour:
  §4.10(a)'s `digest_mismatch` and §4.10(c)'s `handle_not_challenge` would both become
  unreachable through the only client that exists, and §4.10(g)'s own test list REQUIRES
  `handle_not_challenge` to be produced by exactly this path.
* **`inputs_ready` is not asserted after the third final.** §4.10(d) owns that question and
  answers it `no_inputs_ready`. Refusing here would put a verdict outside a closed set.

What IS checked locally, and why each one can fire
---------------------------------------------------
Two disjoint classes, and they are deliberately different exception types (below):

* **Ingress** — the frame on `stdin` is not a §4.10(g) frame, or overflows a §4.10(g) cap.
  §4.10(g): "overflow ⇒ out-of-band ingress error, no frame emitted". The desktop wrote it;
  no supervisor was involved and none is claimed to have been.
* **Transport** — the thing on the other end of the socket did not answer with a §4.10(a0)/
  (a)/(b)/(c)/(d)/(e) reply. That is not a refusal to relay, it is evidence that the peer is
  not the supervisor's handler, and §6.1's out-of-band contract makes it a local failure.

An UPSTREAM refusal is neither, and it is the one place this piece is incomplete — see
`UpstreamRefusal`.

The arithmetic, done first (§4.10(g), and three of the five numbers are load-bearing)
--------------------------------------------------------------------------------------
Every frame this module writes was CONSTRUCTED at its maximum and measured through
`brops_protocol.encode_frame` — the same serializer the transport uses — in
``bridge/tests/test_governed_turn_submit.py``, never estimated here:

* `brops.governed-turn-open.v1` at a full 4096-byte document: **5818** bytes against
  `MAX_OPEN_FRAME_BYTES = 8192`. 2374 spare. It fits, and only just over 1.4x — which is why
  §4.10(g) caps `challenge_doc_b64` at 4096 decoded rather than leaving it open.
* `brops.governed-staging-chunk.v1` at a full 184320-byte chunk: **245982** bytes against
  `MAX_STAGING_CHUNK_FRAME_BYTES = 262144`. 16162 spare. **LOAD-BEARING** — this is the
  bound that decides the chunk stride, and it is 1.06x, not 100x.
* `brops.governed-staging-open.v1` **561** and `-final.v1` **207** against 4096;
  `brops.governed-evidence-request.v1` **426** against 4096. None can fire.
* **Chunk cardinality.** `history` at its 8388608 ceiling is `ceil(8388608/184320)` = **46**
  chunks, seq 0..45 — the whole of `MAX_STAGING_CHUNKS = 46`, against the §4.10(b) cap of
  `seq <= 45`. **LOAD-BEARING**, and it fits with 90112 bytes to spare (46 chunks carry
  8478720; the first `declared_len` needing a 47th is 8478721). It is the tightest bound on
  the ladder, and the one an artifact ceiling cannot be raised past without breaking.
* **Round trips.** A maximum turn is `1 + (1+2+1) + (1+46+1) + (1+1+1) + 1` = **57**
  request/response pairs. The floor is **10**, not the 8 the shape suggests: `n_chunks(0)`
  is 0 so a zero-byte artifact sends no chunk, but only `system` can be empty — an empty
  history canonicalizes to `[]` (2 bytes) and the closed `generation_config` object is at
  least 137, so two of the three artifacts always send one.

And one number that is NOT a fit but a contradiction, recorded rather than resolved:
`ai.rs::governed_sidecar_call` kills this subprocess at a hard **120 s** deadline
(`Duration::from_secs(120)`), while the single §4.10(d) round trip inside it drives §5
acceptance, the §6.1 step-5 contained execution — itself budgeted `EXECUTION_TIMEOUT_MS =
120000` — the recorder chain and an isolated-signer round trip. **The part cannot fit inside
the whole**: a governed turn that uses its full execution budget exceeds the deadline the
tree's only sidecar spawner applies, before the other 56 round trips are counted. That needs
an Architect ruling (a longer deadline for the submit call, or a non-blocking §4.10(d)), not
a number invented here, so the two hop budgets below are named separately and the
contradiction is asserted as a test rather than smoothed over.

One cap this module does NOT write. §4.10(g) caps `JCS(generation_config)` at
`MAX_GENERATION_CONFIG_BYTES = 65536`, and the largest object the §4.10(g) field rules can
express is **349** bytes — every value at its regex maximum. That is a factor of 188, so the
cap could not fire for any accepted input and shipping it would read as protection while
protecting nothing (the class deleted rather than shipped in §4.10(a)/(c)). The number is
pinned by a test instead, so widening a field regex turns it RED. `system` and `history` DO
get their ceilings checked, because both are caller-sized and both can overflow.

NOT WIRED — read this before believing a turn moves
----------------------------------------------------
Nothing in production writes a `bridge.governed-turn-submit.v1` frame. The producer would be
`governed_turn_submit_prepared`, called from the broker's `GovernedExecutor`; the name does
not exist and the one production implementation of that trait spawns the recorder, not a
sidecar. So this branch is reachable only from tests, and the §4.10(f) desktop pull stays
unreachable behind it — its `output_stream_id` can only arrive on the §4.6 frame this module
returns, to a caller that is not there. `config/reachability-declarations.json` names the six
Rust symbols that wait on exactly that.

The supervisor side is also not deployed: `engine/ci/live/run_supervisor.py` constructs no
`OpenService`/`StagingService`/`EvidenceRequestService`/`OutputReadService`, so the live
socket serves none of the five protocols driven here (a test in the engine suite asserts
that absence). What IS proven is the whole ladder against the REAL services, real Ed25519
keys, a real durable ledger and the real isolated signer, in
``engine/tests/test_governed_turn_submit_e2e.py``.

Only the Python standard library is used, and no clock, file or subprocess is touched
anywhere in this file. The one impure thing is the injected `request_supervisor` seam.
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

# The engine's runtime holds every constant, closed reason set and reply builder this hop
# speaks to. Importing them is what keeps the client unable to send a message the supervisor
# can no longer serve, or to accept a reply it can no longer send. Idempotent, and it grants
# this process nothing: a handler needs a ledger connection, a store and a peer uid, and
# this process holds none of the three.
_ENGINE_RUNTIME = pathlib.Path(__file__).resolve().parent.parent / "engine" / "runtime"
if _ENGINE_RUNTIME.is_dir() and str(_ENGINE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_ENGINE_RUNTIME))

import brops_canonical  # noqa: E402
import governed_evidence_request as ger  # noqa: E402
import governed_staging_ledger as staging  # noqa: E402
import governed_staging_upload as gsu  # noqa: E402
import governed_turn_open as gto  # noqa: E402
from brops_protocol import ProtocolError, decode_base64url, strict_loads  # noqa: E402
from governed_turn_result import GOVERNED_TURN_RESULT_PROTOCOL  # noqa: E402
from governed_turn_result_bridge import reframe_turn_result  # noqa: E402

# ---------------------------------------------------------------------------
# Wire constants (§4.10(g), LOCKED literals)
# ---------------------------------------------------------------------------

#: §2.2 gives the ingress its own name and its own schema family, because the frozen
#: `bridge.task-request` (`additionalProperties:false`, no `challenge_doc_b64`, no
#: discriminator) cannot carry a signed challenge document and MUST NOT be extended — the
#: 3b-1A positive control depends on it byte-for-byte. The top-level `protocol` const is the
#: one canonical discriminator in both directions.
BRIDGE_SUBMIT_PROTOCOL = "bridge.governed-turn-submit.v1"

#: The exhaustive top-level field set, `additionalProperties:false`. Six names.
SUBMIT_REQUEST_FIELDS: Tuple[str, ...] = (
    "protocol",
    "task_id",
    "challenge_doc_b64",
    "system",
    "history",
    "generation_config",
)

#: §4.10(g)'s closed `role` enum.
HISTORY_ROLES: Tuple[str, ...] = ("user", "assistant", "system")

#: The exhaustive `history` entry field set.
HISTORY_ENTRY_FIELDS: Tuple[str, ...] = ("role", "content")

#: §2.1/§4.1: every id is ≤ 128. IMPORTED rather than restated — the same literal governs
#: `task_id` here and every id the supervisor's own `_require_id` admits.
MAX_ID_LEN = gsu.MAX_ID_LEN

#: §4.10(g): "decoded ≤ 4096". IMPORTED from §4.10(a0), which is the gate that would
#: otherwise answer `doc_oversize` — checked here so an over-cap document becomes an ingress
#: error instead of an unbuildable 8 KiB frame. `doc_oversize` remains reachable BY NAME in
#: the engine suite from a sender that does not apply this cap, which is precisely the
#: hostile sidecar §4.10(a0) is written against.
MAX_CHALLENGE_DOC_BYTES = gto.MAX_CHALLENGE_DOC_BYTES

#: §4.10(g)'s ingress caps on the two CALLER-SIZED artifacts. DERIVED from §2.4's staging
#: ceilings rather than typed out: an artifact this hop accepted but staging would refuse
#: `oversize` is a turn that dies one message later for a reason the desktop cannot act on.
#: §4.10(g) names `MAX_SYSTEM_BYTES = 262144` and `MAX_CONVERSATION_BYTES = 8388608`; a test
#: asserts these two derivations still equal those literals.
MAX_SYSTEM_BYTES = gsu.ARTIFACT_CEILINGS["system"]
MAX_CONVERSATION_BYTES = gsu.ARTIFACT_CEILINGS["history"]

#: §4.10(g), mirroring the real desktop code (`ai.rs:73,75`, whose literals a test re-reads
#: from that file so the two cannot drift). Both CAN fire and neither is implied by
#: `MAX_CONVERSATION_BYTES`: 1001 one-byte messages canonicalize to ~30 KiB, and a single
#: 1048577-byte message is well inside the 8 MiB conversation cap.
MAX_MESSAGES = 1000
MAX_MESSAGE_BYTES = 1048576

#: The §2.4 upload order. IMPORTED, because §4.10(c) sets `inputs_ready` only when all three
#: handles are recorded and the order is the ledger's, not this client's, to choose.
STAGING_ARTIFACTS: Tuple[str, ...] = staging.STAGING_ARTIFACTS

#: How long ONE control-plane round trip may take. The four control protocols are pure
#: durable-state decisions — a shape check, a CAS, a digest compare, a publish — so 30 s is
#: already generous, and it is the same figure the §4.10(f) hop puts on its one supervisor
#: read for the same reason: a supervisor that accepts and then goes silent must surface as
#: THIS hop's named failure rather than as a killed child the desktop can only call a
#: timeout.
CONTROL_HOP_TIMEOUT_S = 30.0

#: How long the ONE §4.10(d) round trip may take. It is a different number because it is a
#: different kind of wait: §4.10(d) does not answer until §5 acceptance, the §6.1 step-5
#: contained execution (budgeted `EXECUTION_TIMEOUT_MS = 120000`), the recorder chain and the
#: isolated signer have all run. 120 s is the execution budget itself, and it is NOT enough —
#: see the contradiction recorded in the module docstring. It is written as its own constant
#: precisely so the disagreement has a name a reviewer can find.
EXECUTION_HOP_TIMEOUT_S = 120.0

#: `ai.rs::governed_sidecar_call`'s hard deadline on this whole subprocess
#: (`Duration::from_secs(120)`). Recorded here only so the test that compares it with
#: `EXECUTION_HOP_TIMEOUT_S` has a name to compare against; nothing in this module enforces
#: it, because the party that enforces it is the parent process.
SIDECAR_SUBPROCESS_DEADLINE_S = 120.0


# ---------------------------------------------------------------------------
# The three failure kinds — deliberately three types, not one
# ---------------------------------------------------------------------------


class SubmitIngressError(RuntimeError):
    """The frame on `stdin` is not a §4.10(g) frame, or overflows a §4.10(g) cap.

    §4.10(g): an overflow "⇒ out-of-band ingress error, no frame emitted". Nothing was sent
    to a supervisor and nothing is claimed about one. `engine_sidecar._dispatch` turns this
    into the protocol-less `bridge.op.v1` document, which the desktop can only read as the
    out-of-band failure it is.
    """


class SupervisorTransportError(RuntimeError):
    """The peer did not answer with a reply this hop's own protocols can express.

    NOT a refusal. A reply that fails the shape check below is evidence that the thing on the
    other end of the socket is not the supervisor's handler, and §6.1's out-of-band contract
    makes that a local transport failure — the same judgement the §4.10(f) hop records for
    its own leg. Inventing a governed reason to carry it would be this process originating
    the one thing §2.4 forbids it to originate.
    """


class UpstreamRefusal(RuntimeError):
    """A WELL-FORMED internal refusal from one of the five sidecar-driven hops.

    This is a real verdict, decided by the supervisor against its own durable state, and it
    is NOT a `GOVERNED_REFUSAL_REASONS` member — §4.10(h) (**NOT IMPLEMENTED**) keeps the
    per-protocol internal reasons a deliberately disjoint namespace and gives them their own
    carrier, `bridge.governed-turn-diagnostic.v1`, which this tree does not build.

    So the reason is carried here as far as it can honestly go and no further. `stage` and
    `reason` are both members of closed sets IMPORTED from the engine module that publishes
    them, and they are surfaced in the out-of-band refusal's error text. What is MISSING is
    the classifiable frame: without §4.10(h) (**NOT IMPLEMENTED**) a desktop cannot tell this
    apart from a socket failure, and §4.10(h) item 4 says exactly that — a non-diagnostic
    reply is treated as a transport failure. Building the frame now would add a producer with
    no consumer, since the classifier lives in the broker half of §4.10(g) that does not
    exist either.
    """

    def __init__(self, stage: str, reason: str) -> None:
        super().__init__("%s refused the governed turn: %s" % (stage, reason))
        self.stage = stage
        self.reason = reason


#: §4.10(h)'s (**NOT IMPLEMENTED**) Carrier-1 `stage` literals, one per sidecar-driven hop.
#: Named here because `UpstreamRefusal.stage` carries them and a stage outside the set would
#: be this process inventing a routing key.
DIAGNOSTIC_STAGES: Tuple[str, ...] = (
    "governed-turn-open",
    "staging-open",
    "staging-chunk",
    "staging-final",
    ger.DIAGNOSTIC_STAGE,
)


# ---------------------------------------------------------------------------
# Reply shapes — DERIVED from the supervisor's own builders, never typed out
# ---------------------------------------------------------------------------
#
# Calling the builder and taking its key set is what makes drift impossible: a field added
# to `staging_opened` is a field this client immediately demands, and a field removed is one
# it immediately stops accepting. Typing the names out here would be a second copy of a
# contract that has exactly one owner.

_OPEN_OPENED_FIELDS = frozenset(gto.opened("0" * 64))
_OPEN_REFUSED_FIELDS = frozenset(gto.refused(gto.REFUSE_MALFORMED))
_STAGING_OPENED_FIELDS = frozenset(gsu.staging_opened("s", 0))
_STAGING_OPEN_REFUSED_FIELDS = frozenset(gsu.staging_open_refused(gsu.REFUSE_MALFORMED))
_CHUNK_ACK_FIELDS = frozenset(gsu.chunk_ack(0))
_CHUNK_REFUSED_FIELDS = frozenset(gsu.chunk_refused(gsu.REFUSE_MALFORMED, 0))
_FINAL_PUBLISHED_FIELDS = frozenset(gsu.final_published("system", "0" * 64, False))
_FINAL_REFUSED_FIELDS = frozenset(gsu.final_refused(gsu.REFUSE_MALFORMED))
_EVIDENCE_REFUSED_FIELDS = frozenset(ger.evidence_request_refused(ger.REFUSE_MALFORMED))


# ---------------------------------------------------------------------------
# Ingress validation (§4.10(g))
# ---------------------------------------------------------------------------


class SubmitRequest:
    """One validated §4.10(g) frame, reduced to what the ladder needs.

    Immutable by convention and by use: every attribute is set once here and only read
    afterwards. `challenge_doc_b64` is the CALLER'S EXACT STRING — the whole point of
    keeping it beside the decoded payload rather than instead of it.
    """

    __slots__ = ("task_id", "challenge_doc_b64", "install_id", "request_nonce",
                 "artifact_bytes")

    def __init__(self, *, task_id: str, challenge_doc_b64: str, install_id: str,
                 request_nonce: str, artifact_bytes: Mapping[str, bytes]) -> None:
        self.task_id = task_id
        self.challenge_doc_b64 = challenge_doc_b64
        self.install_id = install_id
        self.request_nonce = request_nonce
        self.artifact_bytes = dict(artifact_bytes)


def _require_str(body: Mapping[str, Any], field: str) -> str:
    value = body[field]
    if not isinstance(value, str):
        raise SubmitIngressError("%s must be a string" % field)
    return value


def _require_bounded_id(body: Mapping[str, Any], field: str) -> str:
    value = _require_str(body, field)
    if not (0 < len(value) <= MAX_ID_LEN):
        raise SubmitIngressError(
            "%s must be 1..%d characters, got %d" % (field, MAX_ID_LEN, len(value)))
    return value


def _decoded_challenge_payload(challenge_doc_b64: str) -> Mapping[str, Any]:
    """Read `install_id` and `request_nonce` off the signed document — and NOTHING else.

    §4.10(g)'s frame does not carry them and §4.10(a0)'s does, so exactly two values have to
    be lifted out of the document to build the first message. This is EXTRACTION, not
    verification: the decode below is not a canonicality gate (§4.10(a0) owns that and its
    `noncanonical` must stay reachable), not a signature check, not a shape check against
    §4.1. It refuses only what would make the next frame unbuildable, and the exact string
    that arrived is what travels.
    """
    try:
        document_bytes = decode_base64url(challenge_doc_b64)
    except ProtocolError as exc:
        raise SubmitIngressError("challenge_doc_b64 is not canonical base64url: %s" % exc)
    if len(document_bytes) > MAX_CHALLENGE_DOC_BYTES:
        raise SubmitIngressError(
            "challenge_doc_b64 decodes to %d bytes, over the %d cap"
            % (len(document_bytes), MAX_CHALLENGE_DOC_BYTES))
    try:
        document = strict_loads(document_bytes)
    except ProtocolError as exc:
        raise SubmitIngressError("challenge_doc_b64 is not a strict JSON object: %s" % exc)
    payload = document.get("payload")
    if not isinstance(payload, Mapping):
        raise SubmitIngressError("the challenge document carries no payload object")
    return payload


def _history_bytes(history: Any) -> bytes:
    """§4.10(g)'s `history` — validated, then canonicalized by the SHIPPED formula.

    `brops_canonical.history_bytes` is the merged desktop's own `JCS([{content, role}, …])`
    (`ai.rs::governed_history_sha256`), so the digest this client declares to §2.4 staging is
    the digest the Rust authority committed in the §4.1 challenge. Re-deriving the encoding
    here would be a second spelling of a formula that must have exactly one.
    """
    if not isinstance(history, list):
        raise SubmitIngressError("history must be a JSON array")
    if len(history) > MAX_MESSAGES:
        raise SubmitIngressError(
            "history carries %d messages, over the %d cap" % (len(history), MAX_MESSAGES))
    for index, entry in enumerate(history):
        if not isinstance(entry, Mapping):
            raise SubmitIngressError("history[%d] must be a JSON object" % index)
        if set(entry.keys()) != set(HISTORY_ENTRY_FIELDS):
            raise SubmitIngressError(
                "history[%d] must carry exactly %s, got %s"
                % (index, sorted(HISTORY_ENTRY_FIELDS), sorted(entry.keys())))
        role = entry["role"]
        if role not in HISTORY_ROLES:
            raise SubmitIngressError(
                "history[%d].role %r is not one of %s" % (index, role, list(HISTORY_ROLES)))
        content = entry["content"]
        if not isinstance(content, str):
            raise SubmitIngressError("history[%d].content must be a string" % index)
        encoded = len(content.encode("utf-8"))
        if encoded > MAX_MESSAGE_BYTES:
            raise SubmitIngressError(
                "history[%d].content is %d bytes, over the %d per-message cap"
                % (index, encoded, MAX_MESSAGE_BYTES))
    data = brops_canonical.history_bytes(history)
    if len(data) > MAX_CONVERSATION_BYTES:
        raise SubmitIngressError(
            "JCS(history) is %d bytes, over the %d conversation cap"
            % (len(data), MAX_CONVERSATION_BYTES))
    return data


def validate_submit_request(request: Any) -> SubmitRequest:
    """Is `request` a §4.10(g) frame? Return what the ladder needs, or raise.

    Every refusal here is an INGRESS error: the desktop wrote the frame and no supervisor has
    been contacted yet. The three canonical byte formulas are applied as part of validation
    rather than after it, so there is no window in which an unvalidated value has a digest.
    """
    if not isinstance(request, Mapping):
        raise SubmitIngressError("the submit frame must be a JSON object")
    keys = set(request.keys())
    expected = set(SUBMIT_REQUEST_FIELDS)
    unknown = keys - expected
    if unknown:
        raise SubmitIngressError("the submit frame has unknown field(s) %s" % sorted(unknown))
    missing = expected - keys
    if missing:
        raise SubmitIngressError("the submit frame is missing field(s) %s" % sorted(missing))
    if request["protocol"] != BRIDGE_SUBMIT_PROTOCOL:
        raise SubmitIngressError(
            "the submit frame names protocol %r, not %r"
            % (request["protocol"], BRIDGE_SUBMIT_PROTOCOL))

    task_id = _require_bounded_id(request, "task_id")
    challenge_doc_b64 = _require_str(request, "challenge_doc_b64")
    payload = _decoded_challenge_payload(challenge_doc_b64)

    system = _require_str(request, "system")
    system_data = brops_canonical.system_bytes(system)
    if len(system_data) > MAX_SYSTEM_BYTES:
        raise SubmitIngressError(
            "system is %d bytes, over the %d cap" % (len(system_data), MAX_SYSTEM_BYTES))

    history_data = _history_bytes(request["history"])

    # The §4.10(g) OBJECT form. `governed_generation_config_bytes` validates first and
    # canonicalizes second (§4.10(g)'s locked ordering), so an exponent, a signed zero or a
    # precision mismatch is refused before a byte reaches JCS. Its cap is deliberately
    # unchecked — 349 against 65536; see the module docstring.
    try:
        generation_config_data = brops_canonical.governed_generation_config_bytes(
            request["generation_config"])
    except ValueError as exc:
        raise SubmitIngressError("generation_config is not a §4.10(g) object: %s" % exc)

    for field in ("install_id", "request_nonce"):
        value = payload.get(field)
        if not isinstance(value, str) or not (0 < len(value) <= MAX_ID_LEN):
            raise SubmitIngressError(
                "the challenge payload's %s is not a 1..%d character string"
                % (field, MAX_ID_LEN))

    return SubmitRequest(
        task_id=task_id,
        challenge_doc_b64=challenge_doc_b64,
        install_id=payload["install_id"],
        request_nonce=payload["request_nonce"],
        artifact_bytes={
            "system": system_data,
            "history": history_data,
            "generation_config": generation_config_data,
        },
    )


# ---------------------------------------------------------------------------
# Reply validation — the SHAPE only, never the meaning
# ---------------------------------------------------------------------------


def _reply_arm(reply: Any, protocol: str, arms: Mapping[str, frozenset], stage: str,
               refusal_reasons: Sequence[str],
               refused_status: str) -> Tuple[str, Mapping[str, Any]]:
    """Select the arm of one supervisor reply, or raise.

    `arms` maps a `status` literal to the EXACT key set that status carries. Both halves are
    checked, because a reply that is simultaneously two arms is as broken as a reply that is
    neither, and only checking the discriminator would admit it.

    A `refused` arm whose reason is outside the closed set is a TRANSPORT failure, not a
    thirtieth reason: §4.5's relay rule and §4.10(h) (**NOT IMPLEMENTED**) route reasons BY
    NAME, so an unpublished literal would travel into a desktop Block string as though a
    supervisor had decided it.
    """
    if not isinstance(reply, Mapping):
        raise SupervisorTransportError(
            "the supervisor answered %s with %s, not a JSON object"
            % (stage, type(reply).__name__))
    if reply.get("protocol") != protocol:
        raise SupervisorTransportError(
            "the %s reply names protocol %r, not %r" % (stage, reply.get("protocol"), protocol))
    status = reply.get("status")
    if status not in arms:
        raise SupervisorTransportError(
            "the %s reply names status %r, not one of %s"
            % (stage, status, sorted(arms)))
    if set(reply.keys()) != arms[status]:
        raise SupervisorTransportError(
            "the %s %r reply carries fields %s, expected exactly %s"
            % (stage, status, sorted(reply), sorted(arms[status])))
    if status == refused_status and reply["reason"] not in refusal_reasons:
        raise SupervisorTransportError(
            "the %s refusal names %r, which is not one of %s"
            % (stage, reply["reason"], sorted(refusal_reasons)))
    return status, reply


def _require_reply_id(reply: Mapping[str, Any], field: str, stage: str) -> str:
    """An id off a REPLY, bounded exactly as the supervisor bounds one on a request.

    This is the check that makes the chunk-frame arithmetic hold: `staging_session_id` goes
    straight into every chunk frame, and a 245982-byte maximum only stands while the id is
    ≤ 128. An unbounded id would blow `MAX_STAGING_CHUNK_FRAME_BYTES` inside `encode_frame`,
    which is a fault about the peer rather than about the chunk.
    """
    value = reply[field]
    if not isinstance(value, str) or not (0 < len(value) <= MAX_ID_LEN):
        raise SupervisorTransportError(
            "the %s reply's %s is not a 1..%d character string" % (stage, field, MAX_ID_LEN))
    return value


def _require_reply_cursor(reply: Mapping[str, Any], stage: str) -> int:
    value = reply["next_seq"]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SupervisorTransportError(
            "the %s reply's next_seq is %r, not a non-negative integer" % (stage, value))
    return value


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------


def _open_turn(submit: SubmitRequest, call: Callable[..., Any]) -> str:
    """§4.10(a0). The FIRST governed message; nothing may be staged before it returns.

    `challenge_doc_b64` is the caller's exact string. `install_id`/`request_nonce` were read
    off the same document, and the supervisor re-checks that they agree with the payload it
    verifies (`context_mismatch`), so this client cannot name a turn the signature did not.
    """
    status, reply = _reply_arm(
        call({
            "protocol": gto.OPEN_PROTOCOL,
            "install_id": submit.install_id,
            "request_nonce": submit.request_nonce,
            "challenge_doc_b64": submit.challenge_doc_b64,
        }, CONTROL_HOP_TIMEOUT_S),
        gto.OPEN_RESULT_PROTOCOL,
        {gto.STATUS_OPENED: _OPEN_OPENED_FIELDS, gto.STATUS_REFUSED: _OPEN_REFUSED_FIELDS},
        "governed-turn-open", gto.OPEN_REFUSAL_REASONS, gto.STATUS_REFUSED)
    if status == gto.STATUS_REFUSED:
        raise UpstreamRefusal("governed-turn-open", reply["reason"])
    handle = reply["challenge_handle"]
    if not isinstance(handle, str) or len(handle) != 64 or any(
            character not in "0123456789abcdef" for character in handle):
        raise SupervisorTransportError(
            "the governed-turn-open reply's challenge_handle is not lowercase 64-hex")
    return handle


def _stage_artifact(submit: SubmitRequest, challenge_handle: str, artifact: str,
                    call: Callable[..., Any]) -> None:
    """§4.10(a) -> §4.10(b) x N -> §4.10(c) for ONE artifact. Returns NOTHING.

    It deliberately returns no `inputs_ready`. The first draft returned the §4.10(c) flag and
    type-checked it, and the mutation harness showed the check surviving: nothing read the
    value, so deleting the guard changed no behaviour. That is the same "reads as protection
    while protecting nothing" class §4.10(a)/(c) deleted rather than shipped, and the right
    fix is the one taken here — the flag is not read at all, because §4.10(d) owns the
    question and answers it `no_inputs_ready`. `_reply_arm` still requires the key to be
    PRESENT, so a reply missing it is refused; its VALUE is simply none of this hop's
    business.

    The cursor is the SUPERVISOR'S `next_seq`, never a local counter. That is what makes an
    idempotent re-open work without a second code path: §4.10(a) re-emits the original
    session id with the CURRENT cursor, which may already be ≥ 1, and this loop simply starts
    from wherever the durable row actually is. `expected_chunk_len` and `n_chunks` are
    §4.10(b)'s own deterministic-length rule, imported: a chunk whose length this client
    chose would be refused `nondeterministic_chunk`, and inventing the formula again here is
    how the two would come to disagree.

    One honest note on that reuse, from the mutation pass. Replacing
    `expected_chunk_len(declared_len, offset)` with the bare stride is an EQUIVALENT mutant
    and survives: `data[offset:offset + 184320]` already clamps at the end of the buffer, so
    both expressions produce byte-identical chunks for every input. The call is kept anyway,
    and not as a check — it is kept so the length rule is the SUPERVISOR's named function
    rather than an accident of Python slicing, which is what a future edit would break
    first.
    """
    data = submit.artifact_bytes[artifact]
    declared_len = len(data)
    declared_sha256 = brops_canonical.sha256_hex(data)

    status, reply = _reply_arm(
        call({
            "protocol": gsu.STAGING_OPEN_PROTOCOL,
            "install_id": submit.install_id,
            "challenge_handle": challenge_handle,
            "request_nonce": submit.request_nonce,
            "artifact": artifact,
            "declared_len": declared_len,
            "declared_sha256": declared_sha256,
        }, CONTROL_HOP_TIMEOUT_S),
        gsu.STAGING_OPEN_RESULT_PROTOCOL,
        {gsu.STATUS_OPENED: _STAGING_OPENED_FIELDS,
         gsu.STATUS_REFUSED: _STAGING_OPEN_REFUSED_FIELDS},
        "staging-open", gsu.STAGING_OPEN_REFUSAL_REASONS, gsu.STATUS_REFUSED)
    if status == gsu.STATUS_REFUSED:
        raise UpstreamRefusal("staging-open", reply["reason"])
    session_id = _require_reply_id(reply, "staging_session_id", "staging-open")
    cursor = _require_reply_cursor(reply, "staging-open")

    total = gsu.n_chunks(declared_len)
    while cursor < total:
        offset = cursor * gsu.MAX_STAGING_CHUNK_BYTES
        length = gsu.expected_chunk_len(declared_len, offset)
        status, reply = _reply_arm(
            call({
                "protocol": gsu.STAGING_CHUNK_PROTOCOL,
                "staging_session_id": session_id,
                "seq": cursor,
                "bytes_b64": brops_canonical.b64url(data[offset:offset + length]),
            }, CONTROL_HOP_TIMEOUT_S),
            gsu.STAGING_CHUNK_RESULT_PROTOCOL,
            {gsu.STATUS_ACK: _CHUNK_ACK_FIELDS, gsu.STATUS_REFUSED: _CHUNK_REFUSED_FIELDS},
            "staging-chunk", gsu.STAGING_CHUNK_REFUSAL_REASONS, gsu.STATUS_REFUSED)
        if status == gsu.STATUS_REFUSED:
            raise UpstreamRefusal("staging-chunk", reply["reason"])
        if reply["reason"] is not None:
            raise SupervisorTransportError(
                "an ack'd staging-chunk reply carries a reason, which §4.10(b)'s "
                "discriminated union forbids")
        advanced = _require_reply_cursor(reply, "staging-chunk")
        # A cursor that does not move is the one reply this loop cannot survive: it would
        # re-send the same chunk forever inside a subprocess the desktop can only kill. It
        # is a fault about the peer, not a refusal — §4.10(b) has no literal for it.
        if advanced <= cursor:
            raise SupervisorTransportError(
                "the staging-chunk ack left the cursor at %d after seq %d; the supervisor "
                "acknowledged a chunk without advancing" % (advanced, cursor))
        cursor = advanced

    status, reply = _reply_arm(
        call({
            "protocol": gsu.STAGING_FINAL_PROTOCOL,
            "staging_session_id": session_id,
            "seq": cursor,
        }, CONTROL_HOP_TIMEOUT_S),
        gsu.STAGING_FINAL_RESULT_PROTOCOL,
        {gsu.STATUS_PUBLISHED: _FINAL_PUBLISHED_FIELDS,
         gsu.STATUS_REFUSED: _FINAL_REFUSED_FIELDS},
        "staging-final", gsu.STAGING_FINAL_REFUSAL_REASONS, gsu.STATUS_REFUSED)
    if status == gsu.STATUS_REFUSED:
        raise UpstreamRefusal("staging-final", reply["reason"])
    if reply["artifact"] != artifact:
        raise SupervisorTransportError(
            "the staging-final reply publishes %r, not the %r this session declared"
            % (reply["artifact"], artifact))


def _trigger(submit: SubmitRequest, challenge_handle: str,
             call: Callable[..., Any]) -> Dict[str, Any]:
    """§4.10(d) -> the §4.6 frame.

    §4.10(d)'s reply is a tagged union across TWO protocols, and it is told apart by the
    top-level `protocol` const, never by inspecting fields — that is the whole reason the
    pre-acceptance gate was given its own const. The post-acceptance arm is §4.10(e)'s
    verdict, which `reframe_turn_result` validates with the ENGINE's own definition before
    re-framing, so a reply that is neither is a transport failure rather than a frame.
    """
    reply = call({
        "protocol": ger.EVIDENCE_REQUEST_PROTOCOL,
        "install_id": submit.install_id,
        "challenge_handle": challenge_handle,
        "request_nonce": submit.request_nonce,
    }, EXECUTION_HOP_TIMEOUT_S)
    if isinstance(reply, Mapping) and reply.get("protocol") == ger.EVIDENCE_REQUEST_RESULT_PROTOCOL:
        _status, refusal = _reply_arm(
            reply, ger.EVIDENCE_REQUEST_RESULT_PROTOCOL,
            {ger.STATUS_REFUSED: _EVIDENCE_REFUSED_FIELDS},
            ger.DIAGNOSTIC_STAGE, ger.EVIDENCE_REQUEST_REFUSAL_REASONS, ger.STATUS_REFUSED)
        raise UpstreamRefusal(ger.DIAGNOSTIC_STAGE, refusal["reason"])
    if not isinstance(reply, Mapping) or reply.get("protocol") != GOVERNED_TURN_RESULT_PROTOCOL:
        raise SupervisorTransportError(
            "the evidence-request reply names protocol %r, which is neither %r nor %r"
            % (reply.get("protocol") if isinstance(reply, Mapping) else None,
               ger.EVIDENCE_REQUEST_RESULT_PROTOCOL, GOVERNED_TURN_RESULT_PROTOCOL))
    try:
        return reframe_turn_result(reply)
    except Exception as exc:  # noqa: BLE001 — BridgeFrameError, or anything a hostile shape raises
        raise SupervisorTransportError(str(exc))


def drive_governed_turn(
    request: Any,
    *,
    request_supervisor: Callable[[Mapping[str, Any], float], Any],
    sent: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Drive ONE governed turn from ONE §4.10(g) frame and return the §4.6 reply.

    `request_supervisor(frame, timeout_s)` is the only impure thing this module touches, and
    it is injected for the same reason `drive_acceptance` is on the supervisor side: what
    §4.10(g) owns is the ORDER and the shapes, not the socket. `engine_sidecar` supplies the
    real `brops_socket` round trip.

    `sent` is an optional list this function appends every outgoing `protocol` to. It exists
    so the §4.10(g) ordering claims — turn-open FIRST, and NO `brops.governed-turn-output-
    read.v1` from this subprocess — are tested against what actually went on the wire rather
    than against a reading of the code.

    Raises `SubmitIngressError`, `SupervisorTransportError` or `UpstreamRefusal`; every one
    of them is out-of-band and produces NO §4.6 frame.
    """
    if not callable(request_supervisor):
        raise SupervisorTransportError("request_supervisor must be callable")

    def call(frame: Mapping[str, Any], timeout_s: float) -> Any:
        if sent is not None:
            sent.append(frame["protocol"])
        return request_supervisor(frame, timeout_s)

    submit = validate_submit_request(request)
    # §4.10(a0) -> §4.10(a): the open MUST precede the first staging-open. It is expressed as
    # a data dependency rather than as a comment — `challenge_handle` does not exist until
    # the open returns, and every staging message requires it — so the order cannot be
    # rearranged without deleting the value the later messages are built from.
    challenge_handle = _open_turn(submit, call)
    for artifact in STAGING_ARTIFACTS:
        _stage_artifact(submit, challenge_handle, artifact, call)
    return _trigger(submit, challenge_handle, call)


__all__ = [
    "BRIDGE_SUBMIT_PROTOCOL",
    "CONTROL_HOP_TIMEOUT_S",
    "DIAGNOSTIC_STAGES",
    "EXECUTION_HOP_TIMEOUT_S",
    "HISTORY_ENTRY_FIELDS",
    "HISTORY_ROLES",
    "MAX_CHALLENGE_DOC_BYTES",
    "MAX_CONVERSATION_BYTES",
    "MAX_MESSAGES",
    "MAX_MESSAGE_BYTES",
    "MAX_SYSTEM_BYTES",
    "SIDECAR_SUBPROCESS_DEADLINE_S",
    "STAGING_ARTIFACTS",
    "SUBMIT_REQUEST_FIELDS",
    "SubmitIngressError",
    "SubmitRequest",
    "SupervisorTransportError",
    "UpstreamRefusal",
    "drive_governed_turn",
    "validate_submit_request",
]
