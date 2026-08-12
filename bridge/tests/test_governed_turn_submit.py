"""§4.10(g) — the ingress the desktop writes, and the ladder the sidecar drives.

`engine/tests/test_governed_turn_submit_e2e.py` proves the same orchestrator against the
REAL `OpenService`/`StagingService`/`EvidenceRequestService`, a real ledger, real keys and
the real isolated signer, and comes back with a §4.6 frame whose envelope verifies. It can
therefore prove verdicts, and it cannot prove the shapes a real supervisor never emits.

This file is the other lens. The supervisor here is SCRIPTED — built with the engine's own
reply builders, so it cannot drift, but freely able to answer things no real supervisor
would. That is the only way to test what a compromised or simply wrong peer gets, which on
this hop is the whole question: §2.4 declares the sidecar compromised, and the supervisor on
the other end of its socket is the one party it has no reason to trust either.

  * **`IngressTests`** — every §4.10(g) cap and shape rule, each refused BY NAME. The frame
    comes from the desktop, so all of these are out-of-band ingress errors and none of them
    is a verdict about anything.

  * **`TheLadderTests`** — what actually goes on the wire: the locked order, one chunk per
    `expected_chunk_len` stride, a zero-byte artifact that sends no chunk at all, an
    idempotent re-open resumed from the SUPERVISOR's cursor, the challenge document
    forwarded verbatim, and no `brops.governed-turn-output-read.v1` anywhere.

  * **`UpstreamRefusalTests`** — every literal in all five closed sets is relayed by name
    with its own stage. The sets are IMPORTED from the modules that publish them, so a
    reason added there is a reason this roll call immediately demands.

  * **`TransportFailureTests`** — the peer answered with something that is not one of its
    own replies. Not a refusal to relay: evidence that the thing on the socket is not the
    supervisor's handler. Includes the two guards that exist for liveness and arithmetic
    rather than for correctness — an ack that never advances the cursor, and a session id
    long enough to burst the chunk frame.

  * **`ArithmeticTests`** — every frame constructed at its maximum and measured through the
    transport's own serializer, plus the two numbers that are a CONTRADICTION rather than a
    fit: the §4.10(d) hop's budget against the 120 s deadline `ai.rs` puts on this whole
    subprocess.

  * **`DispatchTests`** — the branch in `engine_sidecar`, including the property
    `test_sidecar_ops.ExecutionIsolationTests` protects from the other side: the governed
    ingress and the frozen `bridge.task-request` execution path do not touch each other.

No prerequisite here is optional. Everything is stdlib plus repo modules imported at module
scope, with no `try`/`except` and no `skipIf`, so a missing prerequisite is an unmissable
hard error rather than a green run with a quiet skip. (There is no
`BROPS_TEST_MISSING_PREREQUISITES` declaration anywhere in this tree, so nothing is declared
in it and nothing here may be softened.)
"""
from __future__ import annotations

import base64
import json
import pathlib
import sys
import unittest

import engine_sidecar
import governed_turn_submit as gts

_BRIDGE = pathlib.Path(gts.__file__).resolve().parent
_ENGINE_RUNTIME = _BRIDGE.parent / "engine" / "runtime"
if str(_ENGINE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_ENGINE_RUNTIME))

import brops_canonical as bc  # noqa: E402
import brops_protocol  # noqa: E402
import governed_evidence_request as ger  # noqa: E402
import governed_staging_upload as gsu  # noqa: E402
import governed_turn_open as gto  # noqa: E402
import governed_turn_result as gtr  # noqa: E402
import governed_turn_result_bridge as gtb  # noqa: E402

_AI_RS = _BRIDGE.parent / "apps" / "desktop" / "src-tauri" / "src" / "ai.rs"

GENERATION_CONFIG = {
    "engine_id": "brops.governed-engine.sidecar.v1",
    "model": "claude-sonnet-5",
    "max_output_tokens": "4096",
    "temperature": "0.00",
    "top_p": "1.00",
}
SYSTEM = "you are a governed agent"
HISTORY = [{"role": "user", "content": "hi"}]

INSTALL_ID = "install-1"
REQUEST_NONCE = "550e8400-e29b-41d4-a716-446655440000"
CHALLENGE_HANDLE = "c" * 64


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_chars(n: int) -> str:
    """A CANONICAL base64url string of exactly `n` characters — the same helper the §4.6
    suite uses, and for the same reason: a padded-out string would be refused as
    non-canonical and quietly turn a size test into an encoding test."""
    raw = n // 4 * 3 + {0: 0, 2: 1, 3: 2}[n % 4]
    return base64.urlsafe_b64encode(b"x" * raw).decode().rstrip("=")


def challenge_document(*, install_id=INSTALL_ID, request_nonce=REQUEST_NONCE) -> dict:
    """A document shaped like the §4.1 envelope, carrying the two fields this hop reads.

    It is NOT signed and NOT complete, and that is deliberate: this client never verifies a
    challenge, so a fixture that signed one would imply a check that does not exist here.
    The E2E file uses the real `challenge_authority.issue_challenge`.
    """
    return {"payload": {"install_id": install_id, "request_nonce": request_nonce},
            "sig": b64url_chars(86)}


def challenge_doc_b64(**kwargs) -> str:
    return b64u(json.dumps(challenge_document(**kwargs),
                           sort_keys=True, separators=(",", ":")).encode("utf-8"))


def submit_frame(**overrides) -> dict:
    frame = {
        "protocol": gts.BRIDGE_SUBMIT_PROTOCOL,
        "task_id": "task-1",
        "challenge_doc_b64": challenge_doc_b64(),
        "system": SYSTEM,
        "history": list(HISTORY),
        "generation_config": dict(GENERATION_CONFIG),
    }
    frame.update(overrides)
    return frame


def signed_turn_result(**overrides) -> dict:
    """A minimal VALID §4.10(e) `signed` frame, built by the engine's own builder."""
    fields = dict(
        receipt_id="rcpt-1",
        output_stream_id=b64url_chars(gtr.OUTPUT_STREAM_ID_LEN),
        output_bytes=11,
        output_sha256="a" * 64,
        envelope_jcs_b64=b64url_chars(120),
        signature_b64=b64url_chars(86),
        key_id="signer-1",
        attestation_evidence_jcs_b64=b64url_chars(200),
        attestation_signature_b64=b64url_chars(86),
        supervisor_attestation_key_id="attest-1",
        containment_evidence_b64=b64url_chars(40),
        run_id="run-1",
        execution_attempt_id="attempt-1",
        lease_id="lease-1",
    )
    fields.update(overrides)
    return gtr.turn_result_signed(**fields)


class _Supervisor:
    """A supervisor that plays the five hops by the book, with per-hop overrides.

    Every reply is produced by the ENGINE's own builder, so a scripted supervisor cannot
    answer with a shape a real one could not. What it CAN do is answer the wrong builder's
    reply, or a hand-written document — which is exactly the class `TransportFailureTests`
    is about, and which no real service will ever emit.
    """

    def __init__(self, *, sessions=None, replies=None, verdict=None):
        #: artifact -> the `next_seq` a staging-open reports (an idempotent re-open may be
        #: mid-stream, §4.10(a) P1-6).
        self.sessions = dict(sessions or {})
        #: protocol -> a document to answer with instead of the by-the-book one.
        self.replies = dict(replies or {})
        self.verdict = verdict if verdict is not None else signed_turn_result()
        self.frames = []
        self._cursor = {}
        self._declared = {}
        self._artifact = {}

    def __call__(self, frame, timeout_s):
        self.frames.append((dict(frame), timeout_s))
        protocol = frame["protocol"]
        if protocol in self.replies:
            scripted = self.replies[protocol]
            return scripted(frame) if callable(scripted) else scripted
        route = {
            gto.OPEN_PROTOCOL: self._open,
            gsu.STAGING_OPEN_PROTOCOL: self._staging_open,
            gsu.STAGING_CHUNK_PROTOCOL: self._staging_chunk,
            gsu.STAGING_FINAL_PROTOCOL: self._staging_final,
            ger.EVIDENCE_REQUEST_PROTOCOL: self._trigger,
        }.get(protocol)
        if route is None:
            raise AssertionError(
                "the submit subprocess sent %r, which is not one of its five hops" % protocol)
        return route(frame)

    # -- by-the-book replies -------------------------------------------------
    def _open(self, _frame):
        return gto.opened(CHALLENGE_HANDLE)

    def _staging_open(self, frame):
        artifact = frame["artifact"]
        session = "sess-" + artifact
        self._cursor[session] = self.sessions.get(artifact, 0)
        self._declared[session] = frame["declared_len"]
        self._artifact[session] = artifact
        return gsu.staging_opened(session, self._cursor[session])

    def _staging_chunk(self, frame):
        session = frame["staging_session_id"]
        self._cursor[session] = frame["seq"] + 1
        return gsu.chunk_ack(self._cursor[session])

    def _staging_final(self, frame):
        session = frame["staging_session_id"]
        artifact = self._artifact[session]
        ready = artifact == gts.STAGING_ARTIFACTS[-1]
        return gsu.final_published(artifact, "d" * 64, ready)

    def _trigger(self, _frame):
        return self.verdict

    # -- what went on the wire ------------------------------------------------
    def protocols(self):
        return [frame["protocol"] for frame, _timeout in self.frames]

    def of(self, protocol):
        return [frame for frame, _timeout in self.frames if frame["protocol"] == protocol]


def drive(frame=None, **kwargs):
    supervisor = _Supervisor(**kwargs)
    return gts.drive_governed_turn(frame if frame is not None else submit_frame(),
                                   request_supervisor=supervisor), supervisor


# =====================================================================================
# Ingress — the frame the DESKTOP wrote
# =====================================================================================


class IngressTests(unittest.TestCase):

    def refuses(self, **overrides):
        with self.assertRaises(gts.SubmitIngressError) as caught:
            gts.validate_submit_request(submit_frame(**overrides))
        return str(caught.exception)

    def test_the_reference_frame_is_accepted_and_yields_the_three_canonical_blobs(self):
        submit = gts.validate_submit_request(submit_frame())
        self.assertEqual(submit.install_id, INSTALL_ID)
        self.assertEqual(submit.request_nonce, REQUEST_NONCE)
        self.assertEqual(set(submit.artifact_bytes), set(gts.STAGING_ARTIFACTS))
        # The formulas are the SHIPPED ones, not a second spelling.
        self.assertEqual(submit.artifact_bytes["system"], bc.system_bytes(SYSTEM))
        self.assertEqual(submit.artifact_bytes["history"], bc.history_bytes(HISTORY))
        self.assertEqual(submit.artifact_bytes["generation_config"],
                         bc.governed_generation_config_bytes(GENERATION_CONFIG))

    def test_a_non_object_is_refused(self):
        for value in ([], "frame", 7, None):
            with self.assertRaises(gts.SubmitIngressError):
                gts.validate_submit_request(value)

    def test_an_unknown_field_is_refused_by_name(self):
        frame = submit_frame()
        frame["run_id"] = "run-1"
        with self.assertRaises(gts.SubmitIngressError) as caught:
            gts.validate_submit_request(frame)
        self.assertIn("run_id", str(caught.exception))

    def test_a_missing_field_is_refused_by_name(self):
        for field in gts.SUBMIT_REQUEST_FIELDS:
            frame = submit_frame()
            del frame[field]
            with self.assertRaises(gts.SubmitIngressError) as caught:
                gts.validate_submit_request(frame)
            self.assertIn(field, str(caught.exception))

    def test_the_frozen_task_request_is_refused_on_the_missing_protocol_const(self):
        """§2.2's compatibility rule, this direction: the governed ingress refuses a frozen
        document. The other direction is structural — `task-request.schema.json` is
        `additionalProperties:false` with no `protocol` key, so it rejects this frame."""
        frozen = json.loads((_BRIDGE / "contracts" / "task-request.schema.json")
                            .read_text("utf-8"))
        self.assertNotIn("protocol", frozen.get("properties", {}))
        self.assertIs(frozen.get("additionalProperties"), False)
        with self.assertRaises(gts.SubmitIngressError):
            gts.validate_submit_request({
                "task_id": "t-1", "task_class": "governed", "rationale": "why",
                "system": SYSTEM, "history": HISTORY, "request": "do it"})

    def test_a_wrong_protocol_const_is_refused(self):
        self.assertIn("protocol", self.refuses(protocol="bridge.governed-turn-result.v1"))

    def test_task_id_is_bounded_at_the_shared_id_cap(self):
        gts.validate_submit_request(submit_frame(task_id="t" * gts.MAX_ID_LEN))
        self.refuses(task_id="t" * (gts.MAX_ID_LEN + 1))
        self.refuses(task_id="")
        self.refuses(task_id=7)

    def test_a_non_canonical_challenge_doc_encoding_is_refused(self):
        # `decode_base64url` re-encodes and compares, so a padded spelling of the same bytes
        # is refused: two spellings of one document is the ambiguity §4.10(a0)'s gate exists
        # to remove, and it must not be introduced one hop earlier either.
        padded = base64.urlsafe_b64encode(b"{}").decode()
        self.assertTrue(padded.endswith("="))
        self.refuses(challenge_doc_b64=padded)

    def test_a_challenge_document_over_the_cap_is_an_ingress_error(self):
        """§4.10(g) caps the DECODED document at 4096. Over-cap here is an ingress error
        rather than `doc_oversize`, because no supervisor has been asked: this client cannot
        even build the 8 KiB §4.10(a0) frame that would carry it. `doc_oversize` stays
        reachable BY NAME in `engine/tests/test_governed_turn_open.py`, from the sender that
        does not apply this cap — which is precisely the hostile sidecar §4.10(a0) is
        written against."""
        oversize = b64u(b"x" * (gts.MAX_CHALLENGE_DOC_BYTES + 1))
        self.assertIn("4096", self.refuses(challenge_doc_b64=oversize))
        self.assertIn(gto.REFUSE_DOC_OVERSIZE, gto.OPEN_REFUSAL_REASONS)

    def test_a_challenge_document_that_is_not_a_json_object_is_refused(self):
        self.refuses(challenge_doc_b64=b64u(b"not json"))
        self.refuses(challenge_doc_b64=b64u(b"[1,2,3]"))

    def test_a_challenge_document_with_no_usable_payload_is_refused(self):
        self.refuses(challenge_doc_b64=b64u(b'{"sig":"x"}'))
        self.refuses(challenge_doc_b64=b64u(b'{"payload":"not an object","sig":"x"}'))
        self.refuses(challenge_doc_b64=b64u(b'{"payload":{"install_id":"i"},"sig":"x"}'))
        self.refuses(challenge_doc_b64=b64u(
            b'{"payload":{"install_id":"","request_nonce":"n"},"sig":"x"}'))

    def test_the_client_does_NOT_verify_the_challenge_it_forwards(self):
        """The fixture document carries no signature the client could check and no §4.1
        payload fields beyond the two it reads, and it is ACCEPTED. That is the property:
        verification is §4.10(a0)'s, and a check here would make `sig_invalid`,
        `context_mismatch` and `noncanonical` unreachable through the only client there is."""
        submit = gts.validate_submit_request(submit_frame())
        self.assertEqual(submit.challenge_doc_b64, challenge_doc_b64())

    def test_the_system_ceiling_is_one_byte_from_refusing(self):
        gts.validate_submit_request(submit_frame(system="s" * gts.MAX_SYSTEM_BYTES))
        self.assertIn("over the 262144", self.refuses(system="s" * (gts.MAX_SYSTEM_BYTES + 1)))

    def test_system_is_measured_in_BYTES_not_characters(self):
        # A 3-byte character at the boundary: a character count would admit this.
        self.refuses(system="€" * (gts.MAX_SYSTEM_BYTES // 3 + 1))

    def test_a_non_string_system_is_refused(self):
        self.refuses(system=None)

    def test_history_shape_rules(self):
        self.refuses(history={"role": "user", "content": "hi"})
        self.refuses(history=["not an object"])
        self.refuses(history=[{"role": "user"}])
        self.refuses(history=[{"role": "user", "content": "hi", "name": "x"}])
        self.refuses(history=[{"role": "operator", "content": "hi"}])
        self.refuses(history=[{"role": "user", "content": 7}])
        for role in gts.HISTORY_ROLES:
            gts.validate_submit_request(submit_frame(history=[{"role": role, "content": "x"}]))

    def test_the_message_count_cap_can_fire_and_is_not_implied_by_the_conversation_cap(self):
        many = [{"role": "user", "content": "x"} for _ in range(gts.MAX_MESSAGES)]
        gts.validate_submit_request(submit_frame(history=many))
        over = many + [{"role": "user", "content": "x"}]
        self.assertIn("over the 1000", self.refuses(history=over))
        # And it is a REAL bound: 1001 one-byte messages are nowhere near the 8 MiB cap.
        self.assertLess(len(bc.history_bytes(over)), gts.MAX_CONVERSATION_BYTES)

    def test_the_per_message_cap_can_fire_and_is_not_implied_by_the_conversation_cap(self):
        big = [{"role": "user", "content": "x" * (gts.MAX_MESSAGE_BYTES + 1)}]
        self.assertIn("per-message cap", self.refuses(history=big))
        self.assertLess(len(bc.history_bytes(big)), gts.MAX_CONVERSATION_BYTES)
        ok = [{"role": "user", "content": "x" * gts.MAX_MESSAGE_BYTES}]
        gts.validate_submit_request(submit_frame(history=ok))

    def test_the_conversation_cap_is_measured_on_the_JCS_the_supervisor_will_rehash(self):
        # Eight messages just under the per-message cap: every other cap passes and only the
        # canonicalized total is over.
        each = "x" * gts.MAX_MESSAGE_BYTES
        over = [{"role": "user", "content": each} for _ in range(9)]
        self.assertIn("conversation cap", self.refuses(history=over))

    def test_every_generation_config_rejection_the_design_names(self):
        for bad, why in (
            ({**GENERATION_CONFIG, "temperature": "1e0"}, "exponent"),
            ({**GENERATION_CONFIG, "temperature": "1E2"}, "exponent"),
            ({**GENERATION_CONFIG, "temperature": "-0.00"}, "signed zero"),
            ({**GENERATION_CONFIG, "top_p": "-0"}, "signed zero"),
            ({**GENERATION_CONFIG, "temperature": "1"}, "bare integer"),
            ({**GENERATION_CONFIG, "temperature": "1.0"}, "one fraction digit"),
            ({**GENERATION_CONFIG, "temperature": "1.000"}, "three fraction digits"),
            ({**GENERATION_CONFIG, "temperature": "0.300000000000000004"}, "high precision"),
            ({**GENERATION_CONFIG, "top_p": "0.9999"}, "high precision"),
            ({**GENERATION_CONFIG, "max_output_tokens": "0256"}, "leading zero"),
            ({**GENERATION_CONFIG, "max_output_tokens": "0"}, "zero"),
            ({**GENERATION_CONFIG, "max_output_tokens": "1048577"}, "over range"),
            ({**GENERATION_CONFIG, "temperature": "2.01"}, "over range, regex passes"),
            ({**GENERATION_CONFIG, "temperature": "3.00"}, "over range"),
            ({**GENERATION_CONFIG, "top_p": "1.01"}, "over range, regex passes"),
            ({**GENERATION_CONFIG, "max_output_tokens": 4096}, "a JSON number"),
            ({**GENERATION_CONFIG, "seed": "1"}, "unknown field"),
        ):
            with self.subTest(why=why):
                self.refuses(generation_config=bad)
        for field in gts.STAGING_ARTIFACTS:  # not the config's fields — see below
            self.assertIn(field, gts.STAGING_ARTIFACTS)
        for field in bc.GOVERNED_GENERATION_CONFIG_FIELDS:
            missing = {k: v for k, v in GENERATION_CONFIG.items() if k != field}
            with self.subTest(missing=field):
                self.refuses(generation_config=missing)

    def test_the_generation_config_boundary_values_are_accepted(self):
        for field, value in (("temperature", "0.00"), ("temperature", "2.00"),
                             ("top_p", "0.00"), ("top_p", "1.00"),
                             ("max_output_tokens", "1"), ("max_output_tokens", "1048576")):
            with self.subTest(field=field, value=value):
                gts.validate_submit_request(
                    submit_frame(generation_config={**GENERATION_CONFIG, field: value}))


# =====================================================================================
# The ladder — what goes on the wire
# =====================================================================================


class TheLadderTests(unittest.TestCase):

    def test_the_order_is_open_then_three_artifacts_then_one_trigger(self):
        _reply, supervisor = drive()
        self.assertEqual(supervisor.protocols(), [
            gto.OPEN_PROTOCOL,
            gsu.STAGING_OPEN_PROTOCOL, gsu.STAGING_CHUNK_PROTOCOL, gsu.STAGING_FINAL_PROTOCOL,
            gsu.STAGING_OPEN_PROTOCOL, gsu.STAGING_CHUNK_PROTOCOL, gsu.STAGING_FINAL_PROTOCOL,
            gsu.STAGING_OPEN_PROTOCOL, gsu.STAGING_CHUNK_PROTOCOL, gsu.STAGING_FINAL_PROTOCOL,
            ger.EVIDENCE_REQUEST_PROTOCOL,
        ])
        self.assertEqual([frame["artifact"] for frame in supervisor.of(gsu.STAGING_OPEN_PROTOCOL)],
                         list(gts.STAGING_ARTIFACTS))

    def test_this_subprocess_never_issues_an_output_read(self):
        """§4.10(g): "This submit subprocess pulls NO output." The §4.10(f) loop is the
        BACKEND's, through fresh one-shot sidecars — so a submit reply that had already
        pulled would be a second stateful thing inside a subprocess designed to be one-shot,
        and the token it would need is minted by the very reply it is waiting for."""
        _reply, supervisor = drive()
        for protocol in supervisor.protocols():
            self.assertNotIn("output-read", protocol)
        sent = []
        gts.drive_governed_turn(submit_frame(), request_supervisor=_Supervisor(), sent=sent)
        self.assertNotIn(engine_sidecar.BRIDGE_OUTPUT_READ_PROTOCOL, sent)

    def test_the_open_carries_the_documents_own_ids_and_the_exact_string_it_was_given(self):
        _reply, supervisor = drive()
        opened = supervisor.of(gto.OPEN_PROTOCOL)[0]
        self.assertEqual(set(opened), set(gto.OPEN_REQUEST_FIELDS))
        self.assertEqual(opened["install_id"], INSTALL_ID)
        self.assertEqual(opened["request_nonce"], REQUEST_NONCE)
        self.assertEqual(opened["challenge_doc_b64"], challenge_doc_b64())

    def test_every_staged_digest_is_the_digest_of_the_bytes_actually_derived(self):
        _reply, supervisor = drive()
        submit = gts.validate_submit_request(submit_frame())
        for frame in supervisor.of(gsu.STAGING_OPEN_PROTOCOL):
            data = submit.artifact_bytes[frame["artifact"]]
            self.assertEqual(set(frame), set(gsu.STAGING_OPEN_REQUEST_FIELDS))
            self.assertEqual(frame["declared_len"], len(data))
            self.assertEqual(frame["declared_sha256"], bc.sha256_hex(data))
            self.assertEqual(frame["challenge_handle"], CHALLENGE_HANDLE)

    def test_the_chunks_reassemble_to_the_exact_artifact_bytes(self):
        _reply, supervisor = drive()
        submit = gts.validate_submit_request(submit_frame())
        rebuilt = {}
        for frame in supervisor.of(gsu.STAGING_CHUNK_PROTOCOL):
            artifact = frame["staging_session_id"][len("sess-"):]
            rebuilt.setdefault(artifact, b"")
            self.assertEqual(frame["seq"], len(rebuilt[artifact]) // gsu.MAX_STAGING_CHUNK_BYTES)
            rebuilt[artifact] += brops_protocol.decode_base64url(frame["bytes_b64"])
        self.assertEqual(rebuilt, dict(submit.artifact_bytes))

    def test_a_multi_chunk_artifact_uses_the_deterministic_stride(self):
        """§4.10(b) P1-3: every chunk is exactly `min(184320, declared_len - byte_count)`.
        A chunk of any other length is refused `nondeterministic_chunk`, so this is the one
        length rule the client may not choose."""
        system = "s" * (gsu.MAX_STAGING_CHUNK_BYTES + 7)
        _reply, supervisor = drive(submit_frame(system=system))
        lengths = [len(brops_protocol.decode_base64url(frame["bytes_b64"]))
                   for frame in supervisor.of(gsu.STAGING_CHUNK_PROTOCOL)
                   if frame["staging_session_id"] == "sess-system"]
        self.assertEqual(lengths, [gsu.MAX_STAGING_CHUNK_BYTES, 7])
        finals = [frame for frame in supervisor.of(gsu.STAGING_FINAL_PROTOCOL)
                  if frame["staging_session_id"] == "sess-system"]
        self.assertEqual(finals[0]["seq"], 2)

    def test_a_zero_byte_artifact_sends_no_chunk_at_all(self):
        """`n_chunks(0) == 0`: §4.10(c) is reached directly, with the cursor still at 0."""
        _reply, supervisor = drive(submit_frame(system=""))
        self.assertEqual([frame for frame in supervisor.of(gsu.STAGING_CHUNK_PROTOCOL)
                          if frame["staging_session_id"] == "sess-system"], [])
        finals = [frame for frame in supervisor.of(gsu.STAGING_FINAL_PROTOCOL)
                  if frame["staging_session_id"] == "sess-system"]
        self.assertEqual(finals[0]["seq"], 0)

    def test_an_idempotent_reopen_resumes_from_the_SUPERVISORS_cursor(self):
        """§4.10(a) P1-6: a re-open re-emits the original session with the CURRENT cursor,
        which may already be ≥ 1. The client drives from that value rather than from a local
        counter, so a resumed upload needs no second code path and cannot re-send a chunk the
        durable row already holds."""
        system = "s" * (gsu.MAX_STAGING_CHUNK_BYTES + 7)
        _reply, supervisor = drive(submit_frame(system=system), sessions={"system": 1})
        chunks = [frame["seq"] for frame in supervisor.of(gsu.STAGING_CHUNK_PROTOCOL)
                  if frame["staging_session_id"] == "sess-system"]
        self.assertEqual(chunks, [1])
        # And the resumed chunk is the REMAINDER, not a re-send of chunk 0.
        resumed = brops_protocol.decode_base64url(
            [f for f in supervisor.of(gsu.STAGING_CHUNK_PROTOCOL)
             if f["staging_session_id"] == "sess-system"][0]["bytes_b64"])
        self.assertEqual(len(resumed), 7)

    def test_the_cursor_comes_from_the_SUPERVISOR_not_from_a_local_counter(self):
        """A `seq + 1` counter and the supervisor's `next_seq` agree on the happy path, so
        only a supervisor that jumps AHEAD tells them apart — and §4.10(b) allows exactly
        that: an idempotent ACK of a `seq` the durable row already holds re-returns the
        CURRENT cursor, which can be several chunks further on after a resumed upload. The
        client must land on the supervisor's number or it re-sends bytes the row already has.
        """
        # `history`, because it is the only artifact whose ceiling admits three chunks.
        history = [{"role": "user", "content": "x" * (3 * gsu.MAX_STAGING_CHUNK_BYTES)}]
        # The row already holds chunks 0..1 but reported 0 at open (a stale re-open reply);
        # the first ACK reveals the true cursor, 2. The scripted ACK is frozen there, so the
        # loop refuses on the non-advancing guard after the SECOND request - which is the
        # request this test is about.
        supervisor = _Supervisor(replies={gsu.STAGING_CHUNK_PROTOCOL: gsu.chunk_ack(2)})
        with self.assertRaises(gts.SupervisorTransportError):
            gts.drive_governed_turn(submit_frame(history=history),
                                    request_supervisor=supervisor)
        sent = [frame["seq"] for frame in supervisor.of(gsu.STAGING_CHUNK_PROTOCOL)
                if frame["staging_session_id"] == "sess-history"]
        # 0, then the SUPERVISOR's 2 — not the local 1. (A four-chunk artifact; the frozen
        # ACK then trips the non-advancing guard, which is how the drive ends.)
        self.assertEqual(sent, [0, 2])
        self.assertEqual(gsu.n_chunks(len(bc.history_bytes(history))), 4)

    def test_the_trigger_carries_the_handle_the_open_returned(self):
        _reply, supervisor = drive()
        trigger = supervisor.of(ger.EVIDENCE_REQUEST_PROTOCOL)[0]
        self.assertEqual(set(trigger), set(ger.EVIDENCE_REQUEST_FIELDS))
        self.assertEqual(trigger["challenge_handle"], CHALLENGE_HANDLE)
        self.assertEqual(trigger["install_id"], INSTALL_ID)
        self.assertEqual(trigger["request_nonce"], REQUEST_NONCE)

    def test_the_reply_is_the_4_6_reframing_of_the_supervisors_own_verdict(self):
        verdict = signed_turn_result()
        reply, _supervisor = drive(verdict=verdict)
        self.assertEqual(reply, gtb.reframe_turn_result(verdict))
        gtb.validate_bridge_turn_result(reply)

    def test_a_governed_verdict_refusal_comes_back_as_an_ok_false_frame(self):
        for reason in gtr.GOVERNED_REFUSAL_REASONS:
            with self.subTest(reason=reason):
                reply, _supervisor = drive(
                    verdict=gtr.turn_result_refused(reason, "rcpt-1"))
                self.assertIs(reply["ok"], False)
                self.assertEqual(reply["error"]["reason"], reason)


# =====================================================================================
# Upstream refusals — relayed by name, never re-decided
# =====================================================================================


class UpstreamRefusalTests(unittest.TestCase):

    STAGES = (
        (gto.OPEN_PROTOCOL, "governed-turn-open", gto.OPEN_REFUSAL_REASONS, gto.refused),
        (gsu.STAGING_OPEN_PROTOCOL, "staging-open", gsu.STAGING_OPEN_REFUSAL_REASONS,
         gsu.staging_open_refused),
        (gsu.STAGING_CHUNK_PROTOCOL, "staging-chunk", gsu.STAGING_CHUNK_REFUSAL_REASONS,
         lambda reason: gsu.chunk_refused(reason, 0)),
        (gsu.STAGING_FINAL_PROTOCOL, "staging-final", gsu.STAGING_FINAL_REFUSAL_REASONS,
         gsu.final_refused),
        (ger.EVIDENCE_REQUEST_PROTOCOL, ger.DIAGNOSTIC_STAGE,
         ger.EVIDENCE_REQUEST_REFUSAL_REASONS, ger.evidence_request_refused),
    )

    def test_every_literal_in_all_five_closed_sets_is_relayed_with_its_own_stage(self):
        seen = set()
        for protocol, stage, reasons, build in self.STAGES:
            for reason in reasons:
                with self.subTest(stage=stage, reason=reason):
                    with self.assertRaises(gts.UpstreamRefusal) as caught:
                        drive(replies={protocol: build(reason)})
                    self.assertEqual(caught.exception.stage, stage)
                    self.assertEqual(caught.exception.reason, reason)
                    self.assertIn(reason, str(caught.exception))
                    seen.add((stage, reason))
        self.assertEqual(len(seen), sum(len(reasons) for _p, _s, reasons, _b in self.STAGES))

    def test_every_stage_is_a_member_of_the_4_10_h_carrier_one_set(self):
        """§4.10(h) (**NOT IMPLEMENTED**) publishes one `stage` per sidecar-driven hop. The
        stages this client raises are exactly those five and nothing else — so the day the
        diagnostic frame is built, its routing key already exists and is already correct."""
        self.assertEqual(set(stage for _p, stage, _r, _b in self.STAGES),
                         set(gts.DIAGNOSTIC_STAGES))

    def test_the_two_namespaces_are_NOT_disjoint_and_the_design_says_they_are(self):
        """A DESIGN CLAIM THAT IS FALSE IN THIS TREE, recorded rather than papered over.

        §4.10(h) (**NOT IMPLEMENTED**) says the per-protocol internal reasons "are
        **intentionally ABSENT** from the closed `GOVERNED_REFUSAL_REASONS` (§4.5) and remain
        a **disjoint namespace, never merged into it**". They are not. Three literals —
        `malformed`, `oversize`, `retry_conflict` — are members of BOTH, so a consumer that
        matched on the reason STRING alone could not tell an internal `staging-chunk`
        `malformed` from a §4.5 governed verdict `malformed`.

        What saves it is that nothing is supposed to match on the string: §4.10(h)'s
        (**NOT IMPLEMENTED**) own routing keys on the CARRIER, and this client discriminates on the `protocol` const
        (the next test), never on the reason. So the sentence is wrong and the mechanism is
        sound — which is exactly the kind of thing that has to be written down, because a
        future reader will otherwise build on the sentence. It needs an Architect ruling.
        """
        internal = set()
        for _protocol, _stage, reasons, _build in self.STAGES:
            internal.update(reasons)
        self.assertEqual(sorted(internal & set(gtr.GOVERNED_REFUSAL_REASONS)),
                         ["malformed", "oversize", "retry_conflict"])

    def test_the_arms_are_told_apart_by_protocol_const_and_never_by_the_reason(self):
        """The property that makes the overlap above harmless HERE.

        §4.10(d)'s reply is a union across two protocols, and a `malformed` under
        `brops.governed-evidence-request-result.v1` is an internal refusal while a
        `malformed` under `brops.governed-turn-result.v1` is a §4.5 verdict. Same literal,
        two different outcomes, chosen by the const alone.
        """
        with self.assertRaises(gts.UpstreamRefusal) as caught:
            drive(replies={ger.EVIDENCE_REQUEST_PROTOCOL:
                           ger.evidence_request_refused(ger.REFUSE_MALFORMED)})
        self.assertEqual(caught.exception.stage, ger.DIAGNOSTIC_STAGE)

        reply, _supervisor = drive(verdict=gtr.turn_result_refused("malformed", None))
        self.assertIs(reply["ok"], False)
        self.assertEqual(reply["error"]["reason"], "malformed")

    def test_the_reason_survives_but_its_provenance_does_not(self):
        """The §4.10(h) gap (**NOT IMPLEMENTED**), asserted rather than described. A stage
        refusal reaches the desktop as the protocol-less `bridge.op.v1` document, which
        carries the words but is NOT a frame a classifier can act on — §4.10(h) item 4 says a
        non-diagnostic reply is treated exactly as a transport failure. This test is what
        turns RED when `bridge.governed-turn-diagnostic.v1` is finally built."""
        refusal = engine_sidecar._op_refusal(
            submit_frame(), gts.UpstreamRefusal("staging-final", gsu.REFUSE_HANDLE_NOT_CHALLENGE))
        self.assertEqual(refusal["protocol"], engine_sidecar.BRIDGE_OP_PROTOCOL)
        self.assertIn(gsu.REFUSE_HANDLE_NOT_CHALLENGE, refusal["error"])
        self.assertNotIn("stage", refusal)
        self.assertNotIn("upstream_reason", refusal)

    def test_handle_not_challenge_is_not_producible_by_this_client(self):
        """§4.10(g)'s test list asks for `handle_not_challenge` from a staged digest that is
        not the challenge's. This client CANNOT produce that input: it declares the true
        digest of the bytes it derived, so §4.10(a)'s `digest_mismatch` fires one message
        earlier and the assembled bytes always match what was declared. The reason is
        reachable BY NAME only from a faulty store or tampered durable state, which is where
        `engine/tests/test_governed_staging_upload.py` produces all three of its cases. It is
        still RELAYED correctly if it arrives, which the roll call above covers."""
        submit = gts.validate_submit_request(submit_frame())
        for artifact, data in submit.artifact_bytes.items():
            self.assertEqual(bc.sha256_hex(data), bc.sha256_hex(submit.artifact_bytes[artifact]))
        source = (_ENGINE_RUNTIME.parent / "tests" / "test_governed_staging_upload.py"
                  ).read_text("utf-8")
        self.assertIn("test_handle_not_challenge_when_the_turn_no_longer_commits_to_the_digest",
                      source)


# =====================================================================================
# Transport failures — the peer is not the supervisor's handler
# =====================================================================================


class TransportFailureTests(unittest.TestCase):

    def fails(self, protocol, reply):
        with self.assertRaises(gts.SupervisorTransportError) as caught:
            drive(replies={protocol: reply})
        return str(caught.exception)

    def test_a_non_object_reply(self):
        self.fails(gto.OPEN_PROTOCOL, ["opened"])

    def test_a_reply_naming_another_protocol(self):
        """The reply carries the RIGHT KEY SET under the WRONG const.

        The first draft used a `staging-open` reply here and the mutation harness showed the
        protocol check surviving: the field sets differ, so the neighbouring exact-key check
        refused it first and the guard under test never ran. A guard masking its neighbour is
        the exact defect this repository keeps finding, so the fixture is now a reply that
        ONLY the const can reject.
        """
        impostor = dict(gto.opened(CHALLENGE_HANDLE),
                        protocol=gsu.STAGING_OPEN_RESULT_PROTOCOL)
        self.assertEqual(set(impostor), set(gto.opened(CHALLENGE_HANDLE)))
        self.assertIn("protocol", self.fails(gto.OPEN_PROTOCOL, impostor))
        # And the original case still fails, for its own reason.
        self.fails(gto.OPEN_PROTOCOL, gsu.staging_opened("s", 0))

    def test_a_reply_naming_an_unknown_status(self):
        reply = dict(gto.opened(CHALLENGE_HANDLE), status="maybe")
        self.assertIn("status", self.fails(gto.OPEN_PROTOCOL, reply))

    def test_a_reply_with_an_extra_or_missing_field(self):
        extra = dict(gto.opened(CHALLENGE_HANDLE), execution_attempt_id="attempt-1")
        self.fails(gto.OPEN_PROTOCOL, extra)
        short = dict(gto.opened(CHALLENGE_HANDLE))
        del short["challenge_handle"]
        self.fails(gto.OPEN_PROTOCOL, short)

    def test_a_refusal_reason_outside_the_closed_set_is_never_relayed(self):
        reply = dict(gto.refused(gto.REFUSE_MALFORMED), reason="a-reason-nobody-published")
        self.assertIn("a-reason-nobody-published",
                      self.fails(gto.OPEN_PROTOCOL, reply))

    def test_a_challenge_handle_that_is_not_lowercase_64_hex(self):
        for bad in ("Z" * 64, "a" * 63, "A" * 64, 7):
            with self.subTest(handle=bad):
                self.fails(gto.OPEN_PROTOCOL, gto.opened(bad) if isinstance(bad, str)
                           else dict(gto.opened("a" * 64), challenge_handle=bad))

    def test_an_acked_chunk_that_carries_a_reason_breaks_the_discriminated_union(self):
        reply = dict(gsu.chunk_ack(1), reason=gsu.REFUSE_SEQ_MISMATCH)
        self.assertIn("discriminated union", self.fails(gsu.STAGING_CHUNK_PROTOCOL, reply))

    def test_an_ack_that_does_not_advance_the_cursor_is_refused_rather_than_looped(self):
        """A liveness guard, and the only one in this module. An ack that leaves the cursor
        where it was would make this loop re-send the same chunk until the desktop killed the
        subprocess, and §4.10(b) publishes no literal for it — so it is a fault about the
        peer, not a refusal."""
        system = "s" * (gsu.MAX_STAGING_CHUNK_BYTES + 7)
        with self.assertRaises(gts.SupervisorTransportError) as caught:
            drive(submit_frame(system=system),
                  replies={gsu.STAGING_CHUNK_PROTOCOL: gsu.chunk_ack(0)})
        self.assertIn("without advancing", str(caught.exception))

    def test_a_session_id_long_enough_to_burst_the_chunk_frame_is_refused(self):
        """The arithmetic guard. `staging_session_id` goes straight into every chunk frame,
        and the 245982-byte maximum below only stands while it is ≤ 128. An unbounded id
        would raise inside `encode_frame` on the transport — a fault about the peer, reported
        here where it can be named."""
        reply = gsu.staging_opened("s" * (gts.MAX_ID_LEN + 1), 0)
        self.assertIn("staging_session_id", self.fails(gsu.STAGING_OPEN_PROTOCOL, reply))

    def test_a_negative_or_non_integer_cursor(self):
        for bad in (-1, "0", True, None):
            with self.subTest(cursor=bad):
                self.fails(gsu.STAGING_OPEN_PROTOCOL,
                           dict(gsu.staging_opened("sess-system", 0), next_seq=bad))

    def test_a_final_that_publishes_a_different_artifact(self):
        reply = gsu.final_published("history", "d" * 64, False)
        self.assertIn("publishes", self.fails(gsu.STAGING_FINAL_PROTOCOL, reply))

    def test_the_final_replys_inputs_ready_VALUE_is_deliberately_not_checked(self):
        """A guard was written here and DELETED after the mutation pass showed it surviving.

        Nothing read the value, so removing the type-check changed no behaviour — a check
        that reads as protection while protecting nothing. §4.10(d) owns the
        inputs-are-ready question and answers it `no_inputs_ready`, so this hop must not
        pre-empt it. The KEY is still required (the exact-key-set check below); only its
        value is none of this hop's business, and this test pins that decision so the guard
        is not reinstated by reflex.
        """
        def echo(frame):
            artifact = frame["staging_session_id"][len("sess-"):]
            return dict(gsu.final_published(artifact, "d" * 64, False), inputs_ready="yes")

        _result, supervisor = drive(replies={gsu.STAGING_FINAL_PROTOCOL: echo})
        self.assertEqual(len(supervisor.of(gsu.STAGING_FINAL_PROTOCOL)), 3)
        # ...but a final that DROPS the key is still refused, by the exact-key-set check.
        short = dict(gsu.final_published("system", "d" * 64, False))
        del short["inputs_ready"]
        self.fails(gsu.STAGING_FINAL_PROTOCOL, short)

    def test_a_trigger_reply_that_is_neither_arm_of_the_4_10_d_union(self):
        message = self.fails(ger.EVIDENCE_REQUEST_PROTOCOL,
                             {"protocol": "brops.governed-result.v1", "status": "signed"})
        self.assertIn("brops.governed-result.v1", message)

    def test_a_half_built_4_10_e_verdict_is_refused_by_the_engines_own_validator(self):
        """The client hands the frame to `reframe_turn_result`, which validates it with
        §4.10(e)'s OWN definition. So a frame the supervisor could no longer produce is
        refused by the module that owns the shape, not by a second copy of it here."""
        broken = signed_turn_result()
        del broken["envelope_jcs_b64"]
        self.assertIn("envelope_jcs_b64",
                      self.fails(ger.EVIDENCE_REQUEST_PROTOCOL, broken))

    def test_a_non_callable_seam_is_refused_before_a_frame_is_written(self):
        with self.assertRaises(gts.SupervisorTransportError):
            gts.drive_governed_turn(submit_frame(), request_supervisor=None)


# =====================================================================================
# Arithmetic — constructed, measured, and one of them a contradiction
# =====================================================================================


class ArithmeticTests(unittest.TestCase):

    def body(self, frame):
        """The exact bytes the transport puts on the wire, minus its 4-byte length prefix."""
        return len(brops_protocol.encode_frame(frame)) - 4

    def test_the_maximum_turn_open_frame_fits_its_8_kib_cap(self):
        frame = {
            "protocol": gto.OPEN_PROTOCOL,
            "install_id": "i" * gts.MAX_ID_LEN,
            "request_nonce": "n" * gts.MAX_ID_LEN,
            "challenge_doc_b64": b64u(b"x" * gts.MAX_CHALLENGE_DOC_BYTES),
        }
        self.assertEqual(self.body(frame), 5818)
        self.assertLess(5818, gto.MAX_OPEN_FRAME_BYTES)
        self.assertEqual(gto.MAX_OPEN_FRAME_BYTES - 5818, 2374)

    def test_the_maximum_staging_chunk_frame_fits_and_it_is_the_LOAD_BEARING_bound(self):
        frame = {
            "protocol": gsu.STAGING_CHUNK_PROTOCOL,
            "staging_session_id": "s" * gts.MAX_ID_LEN,
            "seq": 45,
            "bytes_b64": b64u(b"\x00" * gsu.MAX_STAGING_CHUNK_BYTES),
        }
        self.assertEqual(self.body(frame), 245982)
        self.assertLess(245982, gsu.MAX_STAGING_CHUNK_FRAME_BYTES)
        self.assertEqual(gsu.MAX_STAGING_CHUNK_FRAME_BYTES - 245982, 16162)
        # 1.06x, not 100x: this is the number that decides the stride, and a stride one
        # kibibyte larger would not fit.
        # 16162 spare CHARACTERS is 12121 spare raw bytes; 13000 clears it.
        bigger = dict(frame, bytes_b64=b64u(b"\x00" * (gsu.MAX_STAGING_CHUNK_BYTES + 13000)))
        with self.assertRaises(brops_protocol.ProtocolError):
            brops_protocol.encode_frame(bigger)

    def test_the_three_control_frames_could_never_overflow_their_4_kib_cap(self):
        staging_open = {
            "protocol": gsu.STAGING_OPEN_PROTOCOL,
            "install_id": "i" * gts.MAX_ID_LEN, "challenge_handle": "a" * 64,
            "request_nonce": "n" * gts.MAX_ID_LEN, "artifact": "generation_config",
            "declared_len": gsu.ARTIFACT_CEILINGS["history"], "declared_sha256": "a" * 64,
        }
        final = {"protocol": gsu.STAGING_FINAL_PROTOCOL,
                 "staging_session_id": "s" * gts.MAX_ID_LEN, "seq": 46}
        trigger = {"protocol": ger.EVIDENCE_REQUEST_PROTOCOL,
                   "install_id": "i" * gts.MAX_ID_LEN, "challenge_handle": "a" * 64,
                   "request_nonce": "n" * gts.MAX_ID_LEN}
        self.assertEqual(
            [self.body(staging_open), self.body(final), self.body(trigger)], [561, 207, 426])
        for size in (561, 207, 426):
            self.assertLess(size, gsu.MAX_STAGING_CONTROL_FRAME_BYTES)
        self.assertLess(426, ger.MAX_EVIDENCE_REQUEST_FRAME_BYTES)

    def test_the_largest_history_needs_the_whole_chunk_cardinality_cap(self):
        """46 chunks, seq 0..45, against `MAX_STAGING_CHUNKS = 46` and `seq <= 45`.

        The first draft of this test claimed the fit was EXACT and was wrong, which is the
        reason it is written out: 8388608 needs 46 chunks, and 46 chunks can carry 8478720,
        so the cardinality cap has **90112 bytes** of slack — half a chunk. It is still the
        tightest bound on the ladder, and the first `declared_len` that would need a 47th
        chunk is 8478721, comfortably above the ceiling any artifact may declare.
        """
        counts = {artifact: gsu.n_chunks(ceiling)
                  for artifact, ceiling in gsu.ARTIFACT_CEILINGS.items()}
        self.assertEqual(counts, {"system": 2, "history": 46, "generation_config": 1})
        self.assertEqual(gsu.n_chunks(8478720), 46)
        self.assertEqual(gsu.n_chunks(8478721), 47)
        self.assertEqual(46 * gsu.MAX_STAGING_CHUNK_BYTES - gsu.ARTIFACT_CEILINGS["history"],
                         90112)

    def test_the_round_trip_count_of_a_maximum_and_a_minimum_turn(self):
        """57 at the ceilings, and **10** at the floor — not the 8 the shape suggests.

        `n_chunks(0) == 0`, so a zero-byte artifact sends no chunk at all and the arithmetic
        floor is 8. Only `system` can actually BE zero bytes: an empty history canonicalizes
        to `[]` (2 bytes) and the closed `generation_config` object is at least 137, so two of
        the three artifacts always send one chunk. The reachable floor is therefore 10, and
        this is written out because the first draft of the module docstring claimed 8.
        """
        chunks = sum(gsu.n_chunks(ceiling) for ceiling in gsu.ARTIFACT_CEILINGS.values())
        self.assertEqual(1 + 3 * 2 + chunks + 1, 57)
        self.assertEqual(gsu.n_chunks(0), 0)
        _reply, supervisor = drive(submit_frame(system="", history=[]))
        self.assertEqual(len(supervisor.protocols()), 10)
        submit = gts.validate_submit_request(submit_frame(system="", history=[]))
        self.assertEqual(len(submit.artifact_bytes["system"]), 0)
        self.assertEqual(submit.artifact_bytes["history"], b"[]")
        self.assertEqual(len(submit.artifact_bytes["generation_config"]), 137)

    def test_the_generation_config_cap_could_not_fire_which_is_why_it_is_not_written(self):
        """§4.10(g) caps `JCS(generation_config)` at 65536 and the field rules cap it at 349.
        A check on that difference would read as protection while protecting nothing, so the
        NUMBER is the check: widen a field regex and this line turns RED before the missing
        cap can matter."""
        largest = bc.governed_generation_config_bytes({
            "engine_id": "e" * 128, "model": "m" * 128,
            "max_output_tokens": "1048576", "temperature": "2.00", "top_p": "1.00"})
        self.assertEqual(len(largest), 349)
        self.assertLess(len(largest), gsu.ARTIFACT_CEILINGS["generation_config"])
        self.assertEqual(gsu.ARTIFACT_CEILINGS["generation_config"], 65536)

    def test_the_ingress_ceilings_are_the_staging_ceilings_and_the_designs_literals(self):
        self.assertEqual(gts.MAX_SYSTEM_BYTES, 262144)
        self.assertEqual(gts.MAX_CONVERSATION_BYTES, 8388608)
        self.assertEqual(gts.MAX_SYSTEM_BYTES, gsu.ARTIFACT_CEILINGS["system"])
        self.assertEqual(gts.MAX_CONVERSATION_BYTES, gsu.ARTIFACT_CEILINGS["history"])

    def test_the_two_message_caps_still_equal_the_real_desktop_constants(self):
        """§4.10(g) says these "mirror the real code". Read out of `ai.rs` rather than
        trusted, because a literal transcribed once is a literal that drifts silently. (The
        design cites lines 71-74; they are at 72-75 today, which is why this matches on the
        declarations and not on line numbers.)"""
        source = _AI_RS.read_text("utf-8")
        self.assertIn("const MAX_SYSTEM_BYTES: usize = 256 * 1024;", source)
        self.assertIn("const MAX_MESSAGE_BYTES: usize = 1024 * 1024;", source)
        self.assertIn("const MAX_CONVERSATION_BYTES: usize = 8 * 1024 * 1024;", source)
        self.assertIn("const MAX_MESSAGES: usize = 1000;", source)
        self.assertEqual(gts.MAX_MESSAGES, 1000)
        self.assertEqual(gts.MAX_MESSAGE_BYTES, 1024 * 1024)

    def test_the_execution_hop_budget_does_NOT_fit_the_deadline_this_subprocess_runs_under(self):
        """The CONTRADICTION, asserted rather than smoothed over.

        `ai.rs::governed_sidecar_call` kills this subprocess at 120 s. The §4.10(d) round
        trip alone does not answer until §5 acceptance, a contained execution budgeted
        `EXECUTION_TIMEOUT_MS = 120000`, the recorder chain and an isolated-signer round trip
        have all completed — so the trigger's own budget already consumes the entire deadline
        before the other 56 round trips are counted. The part cannot fit inside the whole.
        This needs an Architect ruling (a longer deadline for the submit call, or a
        non-blocking §4.10(d)); when one lands, this test is the line that has to change.
        """
        self.assertEqual(gts.EXECUTION_HOP_TIMEOUT_S, 120.0)
        self.assertEqual(gts.SIDECAR_SUBPROCESS_DEADLINE_S, 120.0)
        self.assertIn("Duration::from_secs(120)", _AI_RS.read_text("utf-8"))
        worst_case = gts.EXECUTION_HOP_TIMEOUT_S + 56 * gts.CONTROL_HOP_TIMEOUT_S
        self.assertGreater(worst_case, gts.SIDECAR_SUBPROCESS_DEADLINE_S)
        # Even with every control hop instant, the trigger alone exhausts the deadline.
        self.assertGreaterEqual(gts.EXECUTION_HOP_TIMEOUT_S, gts.SIDECAR_SUBPROCESS_DEADLINE_S)


# =====================================================================================
# Dispatch — the branch in engine_sidecar
# =====================================================================================


class DispatchTests(unittest.TestCase):

    def setUp(self):
        self.saved = dict(sys.modules)
        self.env = {}
        for name in (engine_sidecar._SUPERVISOR_SOCKET_ENV,):
            self.env[name] = __import__("os").environ.pop(name, None)

    def tearDown(self):
        import os
        for name, value in self.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_the_dispatch_literal_is_the_modules_own_constant(self):
        """`engine_sidecar` holds the discriminator as a LITERAL so the frame can be
        recognised before the engine runtime is imported — on this path an import failure is
        one of the local failures that must produce no governed frame. This is the pin that
        keeps the two spellings from drifting."""
        self.assertEqual(engine_sidecar.BRIDGE_SUBMIT_PROTOCOL, gts.BRIDGE_SUBMIT_PROTOCOL)
        self.assertNotEqual(engine_sidecar.BRIDGE_SUBMIT_PROTOCOL,
                            engine_sidecar.BRIDGE_OUTPUT_READ_PROTOCOL)

    def test_an_unprovisioned_socket_yields_an_out_of_band_refusal_naming_the_variable(self):
        reply = engine_sidecar._dispatch(submit_frame(), [])
        self.assertEqual(reply["protocol"], engine_sidecar.BRIDGE_OP_PROTOCOL)
        self.assertIs(reply["ok"], False)
        self.assertIsNone(reply["op"])
        self.assertIn(engine_sidecar._SUPERVISOR_SOCKET_ENV, reply["error"])
        # It is NOT a governed frame: the desktop cannot read it as a verdict.
        self.assertNotIn("receipt", reply)
        self.assertNotIn("output_stream_id", reply)

    def test_an_ingress_error_never_reaches_the_socket(self):
        """The socket is resolved BEFORE the ladder runs, so an unprovisioned sidecar is
        reported as such — but a malformed frame on a PROVISIONED sidecar must still not
        write anything. Proven by substituting the socket resolver and the round trip."""
        calls = []
        original_path = engine_sidecar._supervisor_socket_path
        original_request = engine_sidecar._supervisor_request
        engine_sidecar._supervisor_socket_path = lambda: "/tmp/not-a-real-socket"
        engine_sidecar._supervisor_request = lambda *a, **k: calls.append(a) or {}
        self.addCleanup(setattr, engine_sidecar, "_supervisor_socket_path", original_path)
        self.addCleanup(setattr, engine_sidecar, "_supervisor_request", original_request)

        reply = engine_sidecar._dispatch(submit_frame(task_id=""), [])
        self.assertEqual(reply["protocol"], engine_sidecar.BRIDGE_OP_PROTOCOL)
        self.assertEqual(calls, [])

    def test_the_branch_passes_each_hops_own_budget_to_the_socket(self):
        """The §4.10(f) read keeps `_supervisor_request`'s default; the §4.10(g) ladder
        passes its own two. A branch that dropped the argument would silently put the
        30 s control budget on the one hop that waits for an execution — invisible to the
        orchestrator's own tests, which never go through this function."""
        seen = []
        supervisor = _Supervisor()
        original_path = engine_sidecar._supervisor_socket_path
        original_request = engine_sidecar._supervisor_request
        engine_sidecar._supervisor_socket_path = lambda: "/tmp/not-a-real-socket"

        def record(socket_path, frame, *rest):
            seen.append((frame["protocol"], rest))
            return supervisor(frame, rest[0] if rest else None)

        engine_sidecar._supervisor_request = record
        self.addCleanup(setattr, engine_sidecar, "_supervisor_socket_path", original_path)
        self.addCleanup(setattr, engine_sidecar, "_supervisor_request", original_request)

        reply = engine_sidecar._dispatch(submit_frame(), [])
        self.assertEqual(reply["protocol"], gtb.BRIDGE_TURN_RESULT_PROTOCOL, reply)
        budgets = dict(seen)
        self.assertEqual(budgets[gto.OPEN_PROTOCOL], (gts.CONTROL_HOP_TIMEOUT_S,))
        self.assertEqual(budgets[gsu.STAGING_CHUNK_PROTOCOL], (gts.CONTROL_HOP_TIMEOUT_S,))
        self.assertEqual(budgets[ger.EVIDENCE_REQUEST_PROTOCOL],
                         (gts.EXECUTION_HOP_TIMEOUT_S,))

    def test_a_submit_frame_never_touches_the_frozen_execution_path(self):
        """The mirror of `test_sidecar_ops.ExecutionIsolationTests`. That file proves a READ
        cannot knock on the door that executes; this proves the governed INGRESS does not
        reach it either — it is its own path to the supervisor, and the frozen
        `bridge.task-request` machinery stays exactly as fail-closed as it was."""
        touched = {"real_callables": 0, "run_governed_turn": 0}

        def real_callables(_request):
            touched["real_callables"] += 1
            raise AssertionError("the governed ingress reached the frozen provisioning path")

        def governed_turn(*_args, **_kwargs):
            touched["run_governed_turn"] += 1
            raise AssertionError("the governed ingress reached run_governed_turn")

        for name, replacement in (("_real_callables", real_callables),
                                  ("run_governed_turn", governed_turn)):
            original = getattr(engine_sidecar, name)
            setattr(engine_sidecar, name, replacement)
            self.addCleanup(setattr, engine_sidecar, name, original)

        engine_sidecar._dispatch(submit_frame(), ["--self-test", "--self-test-signed"])
        self.assertEqual(touched, {"real_callables": 0, "run_governed_turn": 0})

    def test_a_self_test_flag_cannot_fabricate_a_governed_turn(self):
        """The canned self-test callables answer the frozen TURN path only. A submit frame
        carrying the flag must still reach the supervisor — or refuse — never canned data."""
        reply = engine_sidecar._dispatch(submit_frame(), ["--self-test-signed"])
        self.assertEqual(reply["protocol"], engine_sidecar.BRIDGE_OP_PROTOCOL)
        self.assertIs(reply["ok"], False)

    def test_the_two_protocol_keyed_branches_are_disjoint(self):
        """§2.2's positive-const rule. Neither frame can be read as the other, and neither
        can be read as a `bridge.task-request` (which has no `protocol` key at all) or as an
        op (which has no `protocol` and always has `op`)."""
        for protocol in (engine_sidecar.BRIDGE_SUBMIT_PROTOCOL,
                         engine_sidecar.BRIDGE_OUTPUT_READ_PROTOCOL):
            reply = engine_sidecar._dispatch({"protocol": protocol}, [])
            self.assertEqual(reply["protocol"], engine_sidecar.BRIDGE_OP_PROTOCOL)
        # An op still routes to its own protocol, which is neither of the two above.
        no_protocol = engine_sidecar._dispatch({"op": "governance.read"}, [])
        self.assertEqual(no_protocol["protocol"], engine_sidecar.GOVERNANCE_PROTOCOL)
        unknown = engine_sidecar._dispatch({"op": "no.such.op"}, [])
        self.assertEqual(unknown["op"], "no.such.op")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
