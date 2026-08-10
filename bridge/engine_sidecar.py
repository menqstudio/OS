#!/usr/bin/env python3
"""bridge/engine_sidecar.py — the process the desktop cockpit shells out to.

The desktop is a *conductor*: it never holds a lease, a key, or the engine. It
writes ONE request JSON to this sidecar's **stdin** and reads ONE reply JSON from
**stdout**. Which request it is now depends on an explicit `op` (see "Op dispatch"
below); without one it is the original `bridge.task-request`, and the reply is a
`bridge.result`. That path hosts `bridge.engine_adapter.run_governed_turn`,
injecting the engine-side callables (`run_task` / `read_result`). The adapter makes
NO trust decision: it carries the run's SIGNED receipt material (`envelope_jcs_b64`
+ `signature_b64`) for the DESKTOP, which is the final authority and verifies the
signature (design §3). Every failure is still fail-closed (`result=null`); there is
no self-asserted `verified` boolean.

Op dispatch
-----------
`governance.read` routes to the engine's own `bro_control_room_api.governance_read`
and its reply is relayed VERBATIM, because that reply is three-valued and the middle
value is the fragile one: `ok:true`+`records` (read, found these), `ok:true`+
`empty:true` (read, found nothing), `ok:false`+`error` (could not read). A refusal
never carries a `records` key at any hop, so no consumer can mistake a blind engine
for a quiet one. Ops are READS: nothing dispatched here may reach `_real_callables`,
the supervisor socket, the signer or the builder. An op this build does not
implement is refused BY NAME — never ignored, never answered with an empty read.

Protocol dispatch — the ONE request that is neither an op nor a task-request
---------------------------------------------------------------------------
`bridge.governed-turn-output-read.v1` (design §4.10(f)) is keyed on a top-level
`protocol`, not on `op`, and it is checked FIRST. It is disjoint from both older
shapes by construction: `bridge/contracts/task-request.schema.json` is
`additionalProperties:false` with no `protocol` key, and every op carries `op`.

This one DOES reach the supervisor socket — it is the only thing here that does —
and it is still not an execution: it is the egress half of a turn that is already
over, one immutable byte range per one-shot subprocess. The sidecar is a STATELESS
PROXY on this path and originates NO verdict of its own. It forwards the caller's
four fields UNCHANGED under the supervisor's protocol const, and relays whatever the
supervisor answers. So every `stream_unknown` / `stream_expired` /
`stream_binding_mismatch` / `seq_out_of_range` / `malformed` a desktop ever sees was
decided by the supervisor, against its own durable row and its own clock — including
`malformed`, which this hop deliberately does NOT produce locally.

A LOCAL failure of this hop (no socket provisioned, connect/timeout, an unframable
request, a reply that is not a §4.10(f) frame) yields **no §4.10(f) frame at all**
(§4.10(f) NOTE, P1-5): it degrades to the protocol-less `bridge.op.v1` refusal, which
the desktop cannot parse as a governed verdict and must treat as an out-of-band
transport failure. Fabricating `stream_unknown` for a socket this process could not
open would be this sidecar claiming to have heard from a supervisor it never reached.

Modes
-----
* ``--self-test`` (CLI flag ONLY — never an env var) — inject canned callables (no
  engine, no provisioning). Proves the stdin->stdout->bridge-result path end to end.
  The canned receipt carries NO signature, so the desktop Blocks it — the self-test
  exercises transport, never a trust bypass. Used by CI + unit tests. **Never for
  real use**; the desktop never passes it and strips any fake flag from the child
  env, so production cannot reach it.
* real (default) — wire the engine. Requires operator-provisioned state on disk
  (issuer key, trusted-key registry, signed workspace binding, builder command),
  supplied via env: ``BRO_KEYDIR``, ``BRO_REGISTRY_ROOT``, ``BRO_BINDING``,
  ``BRO_REPOSITORY_ROOT``, ``BRO_BUILDER_COMMAND``. Absent provisioning -> fail
  closed. Each is checked for PRESENCE only; see `_PROVISION_ENV` for why
  ``BRO_REGISTRY_ROOT`` is not the engine's trusted-key registry root.

SECURITY — the isolated signer is deliberately NOT wired here yet
----------------------------------------------------------------
Trust is now a DESKTOP signature check, so the sidecar no longer decides
verification. But the engine's isolated trusted SIGNER (which mints the signed
receipt the desktop verifies) is **Wave 3b** — until it lands, real mode has no
signed receipt to return, so it **fails closed** rather than emit an unsigned one.
The sidecar's contract, provisioning checks, and fail-closed plumbing are complete
and tested now; only the audited signer swap remains.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from typing import Any, Callable

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
# The Wave 3b signer/store/attestation live in the engine (reuse its crypto + custody).
_ENGINE = _HERE.parent / "engine"
for _sub in ("runtime", "tools"):
    _p = str(_ENGINE / _sub)
    if (_ENGINE / _sub).is_dir() and _p not in sys.path:
        sys.path.insert(0, _p)

from engine_adapter import run_governed_turn  # noqa: E402  (bridge/ on path above)

# Operator-provisioned state the real supervisor requires (none may come from the desktop).
#
# These are a PRESENCE check and nothing else: `_real_run_task` refuses to proceed while
# any of them is empty, and no value here is read by anything. In particular
# `BRO_REGISTRY_ROOT` is NOT the engine's trusted-key registry root — nothing consumes
# it, and setting it redirects no verification anywhere. The engine reads its registry
# from `bro_signature.resolve_registry_root`, which is governed by
# `BRO_TRUSTED_REGISTRY_ROOT` (O-3) under custody rules this presence check does not
# apply. The two are deliberately different names: a deployment that set this one to
# satisfy the check below must not thereby have moved its trust root.
_PROVISION_ENV = (
    "BRO_KEYDIR",
    "BRO_REGISTRY_ROOT",
    "BRO_BINDING",
    "BRO_REPOSITORY_ROOT",
    "BRO_BUILDER_COMMAND",
)

# Wave 3b (audit P0-1): the sidecar holds NO signer material and NEVER reaches the signer.
# Its only governance endpoint is the SUPERVISOR SERVICE, reached over this socket; the
# supervisor (a separate principal) builds the authoritative run state, attests, and
# relays to the isolated signer service. The receipt-signing + attestation keys live with
# those services, unreachable by the sidecar.
_SUPERVISOR_SOCKET_ENV = "BROPS_SUPERVISOR_SOCKET"


def _fail(task_id: Any, error: str) -> dict:
    """Fail-closed bridge-result (mirrors engine_adapter._fail): never a result."""
    return {"ok": False, "result": None, "receipt": None, "error": str(error)}


# --------------------------------------------------------------------------- #
# Fake mode — CI smoke only. Mirrors bridge/tests/test_engine_adapter.py seams.
# --------------------------------------------------------------------------- #
class _FakeOutcome:
    """A canned, completed SupervisorResult-shaped object (duck-typed)."""

    def __init__(self, task_id: str, text: str) -> None:
        self.task_id = task_id
        self.status = "completed"
        self.exit_code = 0
        self.evidence = ("evidence:self-test",)
        self.message = text
        self._text = text


def _fake_run_task(request: dict) -> _FakeOutcome:
    return _FakeOutcome(
        str(request.get("task_id", "t-self-test")),
        "SELF-TEST OK — governed round-trip plumbing verified. rationale="
        + str(request.get("rationale", "")),
    )


def _fake_read(outcome: Any) -> str:
    return getattr(outcome, "_text", "")


# --------------------------------------------------------------------------- #
# Signed self-test — exercises the REAL Wave 3b signer/store/attestation chain end to
# end (ephemeral keys + temp store, a fake COMPLETED run) so the sidecar->adapter->
# signed-bridge-result->schema path is proven cross-platform, without a live builder.
# CLI-flag only (`--self-test-signed`), never an env var. It signs a real receipt the
# desktop would still BLOCK (no trusted manifest yet, design §5 STOP).
# --------------------------------------------------------------------------- #
def _signed_self_test_callables() -> tuple[Callable[[dict], Any], Callable[[Any], str]]:
    import tempfile

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    import time

    from brops_canonical import policy_bundle_sha256
    from brops_evidence_store import EvidenceStore
    from brops_receipt_signer import SignerAuthorizationPolicy
    from brops_sign_flow import sign_completed_run
    from brops_supervisor_attest import RunState

    def _mk_key():
        priv = Ed25519PrivateKey.generate()
        raw_priv = priv.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        ).hex()
        raw_pub = priv.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ).hex()
        return raw_priv, raw_pub

    sig_priv, _ = _mk_key()
    att_priv, att_pub = _mk_key()
    signing_key = {"key_id": "self-test-receipt-key", "private_key": sig_priv}
    attestation_key = {"key_id": "self-test-attestation-key", "private_key": att_priv}
    store = EvidenceStore(tempfile.mkdtemp(prefix="brops-selftest-store-"))
    # The signer's own authorization policy (audit P1-7), matching the fake run below.
    policy = SignerAuthorizationPolicy(
        allowed_executor_ids=frozenset({"exec-self-test"}),
        allowed_builder_ids=frozenset({"builder-self-test"}),
        allowed_supervisor_ids=frozenset({"sup-self-test"}),
        expected_policy_id="policy-self-test",
        expected_policy_version="1",
        expected_policy_bundle_sha256=policy_bundle_sha256(b"self-test-policy-bundle"),
    )

    def run_task(request: dict) -> Any:
        task_id = str(request.get("task_id", "t-self-test-signed"))
        state = RunState(
            run_id=task_id,
            execution_attempt_id="attempt-self-test",
            lease_id="lease-self-test",
            request_nonce="00000000-0000-4000-8000-000000000000",
            receipt_id="11111111-1111-4111-8111-111111111111",
            decision="completed",
            workspace_id="ws-self-test",
            install_id="install-self-test",
            supervisor_id="sup-self-test",
            executor_id="exec-self-test",
            builder_id="builder-self-test",
            policy_id="policy-self-test",
            policy_version="1",
            requested_at="1000",
            completed_at="2000",
            system="You are a governed assistant (self-test).",
            history=[{"role": "user", "content": str(request.get("rationale", "hi"))}],
            output="SELF-TEST-SIGNED OK — real signed receipt minted (desktop still Blocks).",
            generation_config='{"model":"self-test"}',
            containment_evidence={"contained": True, "group": "pg-self-test"},
            policy_bundle=b"self-test-policy-bundle",
        )

        class _Provider:
            def terminal_run_state(self, run_id, execution_attempt_id):
                if (run_id, execution_attempt_id) == (state.run_id, state.execution_attempt_id):
                    return state
                return None

        return sign_completed_run(
            task_id,
            "attempt-self-test",
            run_state_provider=_Provider(),
            store=store,
            signing_key=signing_key,
            attestation_key=attestation_key,
            supervisor_attestation_pubkey_hex=att_pub,
            policy=policy,
            now_ms=int(time.time() * 1000),
        )

    def read_result(outcome: Any) -> str:
        return getattr(outcome, "_text", "")

    return run_task, read_result


# --------------------------------------------------------------------------- #
# Real mode — the sidecar is a pure RELAY to the supervisor service (audit P0-1). It
# holds no signer material and never reaches the signer. It forwards the run handle
# {run_id, execution_attempt_id} to the supervisor service, which builds the
# authoritative run state, attests, and relays to the isolated signer service; the
# sidecar returns the governed-result's output + signed receipt wire to the desktop.
# The desktop STILL Blocks (NoTrustedManifest) until 3b-2/3b-3 — design §5 STOP.
# --------------------------------------------------------------------------- #
class _GovernedOutcome:
    """A SupervisorResult-shaped relay of the supervisor service's governed-result."""

    def __init__(self, run_id: str, governed: dict) -> None:
        r = governed.get("receipt", {}) or {}
        self.task_id = run_id
        self.status = "completed"
        self.exit_code = 0
        self.evidence = (f"evidence:receipt:{r.get('run_id', run_id)}",)
        self._text = governed.get("output", "")
        self.receipt_envelope_jcs_b64 = r.get("envelope_jcs_b64")
        self.receipt_signature_b64 = r.get("signature_b64")
        self.receipt_containment_evidence_b64 = r.get("containment_evidence_b64")
        self.receipt_attestation_evidence_jcs_b64 = r.get("attestation_evidence_jcs_b64")
        self.receipt_attestation_signature_b64 = r.get("attestation_signature_b64")
        self.receipt_supervisor_attestation_key_id = r.get("supervisor_attestation_key_id")
        self.receipt_run_id = r.get("run_id")
        self.receipt_execution_attempt_id = r.get("execution_attempt_id")
        self.receipt_lease_id = r.get("lease_id")


def _real_callables(
    request: dict,
) -> tuple[Callable[[dict], Any], Callable[[Any], str]]:
    """Return the engine-bound callables, or raise RuntimeError (fail-closed). The sidecar
    connects ONLY to the supervisor service — never the signer — and holds no signer
    material. The desktop request carries NO execution attempt id (audit P1-5): the
    supervisor reserves/generates the attempt and binds it into the signed terminal
    record. That attempt-reservation + the authoritative execution→receipt binding are
    Wave 3b-1B (design-locked in `WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`), so real
    governed mode fail-closes here until 3b-1B lands. The isolated signing BOUNDARY itself
    (services + ACL + a valid signed record → signed) is machine-proven by the Linux
    `engine-isolation` CI job. `--self-test-signed` exercises the signer chain today."""
    missing = [k for k in _PROVISION_ENV if not os.environ.get(k, "").strip()]
    if missing:
        raise RuntimeError("governed engine not provisioned: missing " + ", ".join(missing))
    supervisor_socket = os.environ.get(_SUPERVISOR_SOCKET_ENV, "").strip()
    if not supervisor_socket:
        raise RuntimeError(
            "governed supervisor service not provisioned: BROPS_SUPERVISOR_SOCKET is "
            "required — the sidecar relays to the supervisor service and never holds "
            "signer keys or reaches the signer"
        )
    raise RuntimeError(
        "governed engine real-mode is pending the Wave 3b-1B supervisor-reserved "
        "execution attempt + authoritative execution→receipt binding; the isolated "
        "signing boundary is proven by the engine-isolation CI job and --self-test-signed"
    )


# --------------------------------------------------------------------------- #
# Op dispatch — one process, several QUESTIONS, one reply each.
#
# For a long time a stdin round trip could only mean one thing: run a governed turn.
# So the Phase-2 governance mirror sent a perfectly well-formed read and got the
# governed-turn path's fail-closed answer back, and the cockpit rendered its honest
# blocked state forever — not because the engine had nothing to say, but because
# nothing here was listening for a question. The envelope now carries an `op`.
#
#   no `op` key      -> the original bridge.task-request path, unchanged. A
#                       task-request can never grow one by accident:
#                       task-request.schema.json is additionalProperties:false.
#   a registered op  -> that op's handler, which owns its own reply protocol and
#                       its own refusal shape.
#   anything else    -> a NAMED refusal saying which op was asked for and which ops
#                       this build serves. Never a silent no-op, and never a reply
#                       shaped like a satisfied read.
#
# Every op here is a READ. None may reach `_real_callables`, the supervisor socket,
# the signer or the builder: that path stays exactly as fail-closed as it was, and a
# read must not even be able to knock on it.
# --------------------------------------------------------------------------- #

#: Reply protocol for a refusal that belongs to no richer protocol of its own.
BRIDGE_OP_PROTOCOL = "bridge.op.v1"

#: The governance mirror's wire contract. Held as a LITERAL on purpose: the refusal
#: below has to be emitable when `bro_control_room_api` cannot even be imported, which
#: is precisely when its constant is out of reach. `bridge/tests/test_sidecar_ops.py`
#: asserts this literal still equals the engine's `GOVERNANCE_PROTOCOL` / `GOVERNANCE_OP`,
#: so the two cannot drift apart in silence.
GOVERNANCE_PROTOCOL = "brops.governance-read.v1"
GOVERNANCE_READ_OP = "governance.read"

# Operator-provisioned state for the governance READ, deliberately disjoint from
# _PROVISION_ENV: a read shares nothing with the execution path, so a half-provisioned
# builder can neither enable nor disable the mirror, and provisioning the mirror grants
# no step toward running anything. Only the state dir is required; the evidence store
# and the trusted-key registry are optional, and when they are absent the ENGINE
# refuses the surfaces that need them, by name, in its own words.
_GOVERNANCE_STATE_DIR_ENV = "BROPS_GOVERNANCE_STATE_DIR"
_GOVERNANCE_EVIDENCE_STORE_ENV = "BROPS_GOVERNANCE_EVIDENCE_STORE"
_GOVERNANCE_REGISTRY_ROOT_ENV = "BROPS_GOVERNANCE_REGISTRY_ROOT"


def _op_refusal(request: Any, error: Any) -> dict:
    """A refusal for a request with no reply protocol of its own.

    Note what is absent: no `records`, no `result`. There is no field a consumer
    could read as "the call succeeded and produced nothing".

    It carries a SECOND load now, and the second one is the stricter of the two.
    4.10(f) requires a local failure of the output-read hop to produce **no 4.10(f)
    frame at all** - not a refusal inside that protocol - because a `stream_unknown`
    this process invented would be a claim about a supervisor it never reached. This
    document is what "no frame" is emitted as: it names no 4.10(f) protocol, carries
    no `reason`, and cannot be parsed as a governed verdict, so the desktop can only
    read it as the out-of-band transport failure it is. `op` is `None` for those
    callers, which is honest - the output read is not an op.
    """
    op = request.get("op") if isinstance(request, dict) else None
    return {
        "protocol": BRIDGE_OP_PROTOCOL,
        "schema": 1,
        "ok": False,
        "op": op if isinstance(op, str) else None,
        "error": str(error),
    }


def _governance_refusal(request: Any, error: Any) -> dict:
    """A governance-read refusal, in the ENGINE's own refusal shape.

    Field-for-field what `bro_control_room_api._governance_refusal` emits, and for
    exactly its reason: "I could not look" must not be mistakable for "I looked and
    found nothing". So there is no `records` key here either — a consumer reaching
    for `records` finds nothing to read, rather than an empty list to believe.

    `surface` / `task_id` are echoed only when they are strings, so a refusal cannot
    be used to bounce arbitrary caller-shaped JSON back into the reply document.
    """
    surface = request.get("surface") if isinstance(request, dict) else None
    task_id = request.get("task_id") if isinstance(request, dict) else None
    return {
        "protocol": GOVERNANCE_PROTOCOL,
        "schema": 1,
        "ok": False,
        "surface": surface if isinstance(surface, str) else None,
        "task_id": task_id if isinstance(task_id, str) else None,
        "read_at_epoch": int(time.time()),
        "error": str(error),
    }


def _governance_runtime() -> Any:
    """Open the operator-provisioned governance runtime for READING, or raise.

    Every failure below is a refusal reason, never a degraded read. An unset state
    directory, a state directory that does not exist, an evidence store that does
    not exist, a key registry that will not load — each of them means "I could not
    look", and answering any of them with an empty mirror would paint a calm page
    over a blind engine. The one thing this function will not do is invent a store
    and then report it as empty.
    """
    state_dir = os.environ.get(_GOVERNANCE_STATE_DIR_ENV, "").strip()
    if not state_dir:
        raise RuntimeError(
            f"governance mirror not provisioned: {_GOVERNANCE_STATE_DIR_ENV} must name "
            "the engine's orchestration runtime state directory. This is a refusal, not "
            "an empty mirror — the engine was never asked")
    path = pathlib.Path(state_dir)
    if not path.is_dir():
        raise RuntimeError(
            f"{_GOVERNANCE_STATE_DIR_ENV}={state_dir!r} is not an existing directory; "
            "refusing to create one and report it as empty — an absent store is not an "
            "empty store")
    store = os.environ.get(_GOVERNANCE_EVIDENCE_STORE_ENV, "").strip()
    if store and not pathlib.Path(store).is_dir():
        raise RuntimeError(
            f"{_GOVERNANCE_EVIDENCE_STORE_ENV}={store!r} is not an existing directory; "
            "refusing to read an evidence chain out of a store that is not there")
    registry = os.environ.get(_GOVERNANCE_REGISTRY_ROOT_ENV, "").strip()
    keys = None
    if registry:
        # Provisioned-but-unloadable is a refusal, never a quiet downgrade to "unkeyed":
        # an unkeyed runtime refuses the signed surfaces with a reason that would blame
        # the wrong thing, and the operator would be told the engine holds no keys when
        # in fact the registry they provisioned was rejected.
        from bro_signature import SignatureError, load_trusted_keys

        try:
            keys = load_trusted_keys(pathlib.Path(registry))
        except SignatureError as exc:
            raise RuntimeError(
                f"{_GOVERNANCE_REGISTRY_ROOT_ENV} is set but its trusted-key registry "
                f"could not be loaded: {exc}") from exc
    from bro_orchestration_runtime_v1 import DurableOrchestrationRuntimeV1

    return DurableOrchestrationRuntimeV1(
        path,
        evidence_keys=keys,
        evidence_store=pathlib.Path(store) if store else None,
    )


def _governance_api(runtime: Any) -> Any:
    """The engine's read-only control-room API over `runtime`. Its own seam so a test
    can substitute a misbehaving engine and prove the relay below still fails closed."""
    from bro_control_room_api import ControlRoomAPIV1

    return ControlRoomAPIV1(runtime)


def _op_governance_read(request: dict) -> dict:
    """Serve one `brops.governance-read.v1` request from the engine's own stores.

    The request is forwarded UNMODIFIED and the reply is relayed VERBATIM. Both
    halves matter. The engine checks the request's field set for equality, so a
    sidecar that helpfully stripped or added a field would answer a question nobody
    asked; and the reply is three-valued, so any re-shaping here is a chance to
    collapse "found nothing" into "could not look", or worse, the other way round.
    This hop adds nothing and drops nothing.

    READ ONLY: no `_real_callables`, no supervisor socket, no signer, no builder.
    It opens a runtime for reading and asks it a question.
    """
    try:
        runtime = _governance_runtime()
        api = _governance_api(runtime)
    except Exception as exc:  # noqa: BLE001 — provisioning/import failure is a refusal
        return _governance_refusal(request, exc)
    reply = api.governance_read(request)
    if not isinstance(reply, dict) or "ok" not in reply:
        return _governance_refusal(
            request, "the engine governance API returned no usable reply document")
    if reply["ok"] is not True and "records" in reply:
        # Today's engine cannot produce this, and it is checked anyway: the single
        # thing this hop must never forward is a refusal wearing a successful read's
        # clothes. Re-issued as a proper refusal, carrying the engine's own reason.
        return _governance_refusal(
            request, reply.get("error") or "the engine refused the governance read")
    return reply


# --------------------------------------------------------------------------- #
# 4.10(f) DESKTOP HOP - `bridge.governed-turn-output-read.v1`, the chunked output PULL.
#
# The output of a governed turn is NEVER pushed and never inlined. 4.6 proves the inline
# form overflows the frame (a full-schema result with a 128 KiB output reaches ~266707
# against a 262144 cap), and 2.3 forbids the desktop the protected store, so the exact
# bytes the recorder captured reach the party that renders them through this loop and
# through nothing else. The transport under it is one-request/one-response in BOTH
# directions - `brops_socket` is a pure responder, and this process reads ONE stdin
# request and writes ONE stdout reply - so the desktop drives the loop by re-invoking a
# FRESH one-shot sidecar once per chunk, and this hop is stateless by construction rather
# than by discipline.
#
# What this hop is NOT
# --------------------
# It is not an authority over the bytes and does not pretend to be one. 4.6/7.1 put that
# authority in the isolated signer's envelope: the desktop asserts
# `len(reassembled) == envelope.output_bytes` AND `SHA256(reassembled) ==
# envelope.output_sha256` over the RAW bytes before any normalization. So a tampered,
# re-ordered, dropped or cross-turn chunk fails the whole-output digest no matter what
# this proxy does - which is exactly why this file adds no integrity check of its own.
# 4.10(f) states the matching limit in writing: the 256-bit token buys unguessability, and
# it provides NO confidentiality against this sidecar, which is the transport proxy for
# every turn and therefore sees every token and every byte.
#
# It also does not check the ECHO. `output_stream_id`/`seq` come back as the supervisor
# sent them and are compared by the DESKTOP, against values it took from the verified
# signed envelope. A check performed here would be performed by the party 2.4 declares
# compromised, over values it chose, and would be worth nothing to the party that matters.
#
# The arithmetic, done first (4.10(f), and it is load-bearing on BOTH legs)
# -------------------------------------------------------------------------
# A chunk is 184320 decoded bytes = 245760 base64url characters, and the largest legal
# supervisor reply is exactly **245940** bytes against `brops_protocol.MAX_FRAME_BYTES =
# 262144` - 16204 of headroom. Reframed for the desktop the same reply is **245941**
# (`bridge.` is one character longer than `brops.`). Three separate bounds have to admit
# those numbers, and only one of them did by accident:
#
#   * supervisor -> sidecar socket: `brops_protocol.read_frame` at 262144. Fits, 16204 spare.
#   * sidecar -> desktop stdout: unbounded here, read by `ai.rs` under
#     `MAX_STDOUT_BYTES = 9437184`. Fits, with ~9.2 MiB spare.
#   * the bounds that do NOT fit, and are the reason this hop cannot be short-circuited:
#     the supervisor's BROKER-facing frame bound is 8192 (`governed_supervisor_server.
#     MAX_FRAME_BYTES`), and the desktop's own framed IPC caps a payload at 8192
#     (`ipc_framing::MAX_FRAME_PAYLOAD_BYTES`). A 245941-byte chunk is 30x too large for
#     either. So the pull is a subprocess stdio hop through this sidecar not as a stylistic
#     choice but because no framed-IPC path in the tree can carry it, and a future attempt
#     to "simplify" it onto one would fail at the first full chunk.
#     `bridge/tests/test_governed_output_read_bridge.py` CONSTRUCTS the literal maximum and
#     asserts all four numbers rather than leaving them as a comment.
#
# There is deliberately NO size check in this file. A REQUEST here is at most 422 bytes
# (four ids at their caps plus the discriminator) against 262144, and a REPLY is bounded by
# the supervisor's own writer and re-bounded by `brops_protocol.encode_frame`/`read_frame`
# on the way past. A cap on either would be a line that cannot fire - the class deleted
# rather than shipped in 4.10(a)/(c).
# --------------------------------------------------------------------------- #

#: The desktop->sidecar request and its reply (4.10(f)). Held as LITERALS, for the same
#: reason `GOVERNANCE_PROTOCOL` is: the dispatch has to recognise the request before any
#: engine module is imported, and on this path an import failure is precisely one of the
#: local failures that must NOT produce a 4.10(f) frame. The SUPERVISOR-side names, the
#: closed reason set and the chunk stride are imported from the engine instead of restated
#: (`_output_read_contract` below), so the two hops cannot drift; the drift test pins that
#: these two literals differ from the engine's by the `bridge.`/`brops.` prefix and by
#: nothing else.
BRIDGE_OUTPUT_READ_PROTOCOL = "bridge.governed-turn-output-read.v1"
BRIDGE_OUTPUT_READ_RESULT_PROTOCOL = "bridge.governed-turn-output-read-result.v1"

#: How long this hop waits on the supervisor socket. Comfortably inside the 120 s deadline
#: `ai.rs::governed_sidecar_call` puts on the whole subprocess, so a supervisor that
#: accepts and then goes silent surfaces as THIS hop's out-of-band refusal - which names
#: the socket - rather than as a killed child the desktop can only describe as a timeout.
_SUPERVISOR_READ_TIMEOUT_S = 30.0


def _output_read_contract():
    """The engine's own 4.10(f) constants, imported rather than copied.

    Everything here is a value the SUPERVISOR publishes: the protocol consts of the hop
    this proxy forwards to, the exhaustive reply field set, the closed refusal set, and the
    chunk stride. A second copy in this file is exactly the drift that would let the
    sidecar accept a reply the supervisor can no longer produce, or reject one it can.

    Importing the supervisor's module grants this process nothing. `handle_output_read`
    needs a ledger connection, a store reader and a peer uid to do anything at all, and
    this process holds none of the three; the supervisor's authority is its own uid, its
    own 0700 database and its own socket, none of which is an import away.
    """
    import governed_output_read as gor  # engine/runtime is on sys.path (see the header)

    return gor


def _supervisor_socket_path() -> str:
    """The provisioned supervisor socket, or raise.

    Unprovisioned is a LOCAL failure, not a stream verdict: this process never reached a
    supervisor, so it has no business reporting one. It raises, and the caller degrades to
    the protocol-less refusal that the desktop reads as out-of-band (4.10(f) NOTE).
    """
    path = os.environ.get(_SUPERVISOR_SOCKET_ENV, "").strip()
    if not path:
        raise RuntimeError(
            f"the governed output-read hop is not provisioned: {_SUPERVISOR_SOCKET_ENV} is "
            "unset, so there is no supervisor to ask. This is a local transport failure and "
            "deliberately NOT a bridge.governed-turn-output-read-result.v1 refusal - no "
            "supervisor decided anything about this stream")
    return path


def _supervisor_request(socket_path: str, frame: dict) -> dict:
    """One request frame out, one reply frame back, over the supervisor's AF_UNIX socket.

    Its own function so a test can substitute a supervisor without a socket - the same seam
    `_governance_runtime` / `_governance_api` are. `brops_socket.request` is reused rather
    than reimplemented: it already speaks the exact 4-byte big-endian length prefix the
    supervisor front door reads and writes, under `brops_protocol`'s 262144 cap, which is
    the one bound a 245940-byte chunk reply needs.
    """
    import brops_socket

    return brops_socket.request(socket_path, frame, timeout=_SUPERVISOR_READ_TIMEOUT_S)


def _forwarded_output_read(request: dict, protocol: str) -> dict:
    """The supervisor frame for this request: the caller's fields, UNCHANGED, re-labelled.

    4.10(f): "the sidecar forwards these fields UNCHANGED to the supervisor". Taken
    literally, and the literal reading is the honest one. This proxy does NOT validate the
    caller's four fields, because validating them would mean ANSWERING for them, and
    `malformed` is a supervisor verdict in a closed supervisor set. So a missing field, an
    extra field, a `seq` that is a string, a 42-character token - all of them travel, and
    the supervisor's own exhaustive shape check refuses them with the one literal it
    published for exactly that. `malformed` is therefore reachable BY NAME through this
    hop, produced by the party entitled to produce it.

    Two things this cannot smuggle. `protocol` is written FIRST and the caller's own
    `protocol` is dropped, so the frame is always labelled with the one protocol this hop
    may speak. And any other key - an `op`, a second discriminator - is forwarded as the
    extra field it is, which the supervisor's exact-field check refuses: the sidecar's
    grant on that socket is a closed tuple of protocol names, so this door cannot be
    widened into the 5 lifecycle by anything a caller writes here.
    """
    frame = {"protocol": protocol}
    for key, value in request.items():
        if key != "protocol":
            frame[key] = value
    return frame


def _validated_output_read_reply(reply: object, gor) -> dict:
    """Return the reply if it IS a 4.10(f) supervisor reply; raise if it is not.

    The shape only - never the meaning. A reply that fails this is not a refusal the
    desktop can act on; it is evidence that the thing on the other end of the socket is not
    the supervisor's output-read handler, so it becomes a local failure and no 4.10(f)
    frame is emitted at all.

    `bytes_b64` is decoded here even though the bytes are then relayed verbatim, and that
    is the point: `brops_protocol.decode_base64url` refuses anything that is not the
    CANONICAL base64url of its own bytes, so a value that decodes only under a lenient
    decoder - which is what `base64.urlsafe_b64decode` is - never reaches a desktop that
    might decode it differently. The decoded length is checked against the supervisor's own
    stride for the same reason the supervisor checks it on the way out.
    """
    if not isinstance(reply, dict):
        raise RuntimeError("the supervisor answered with %s, not a JSON object"
                           % type(reply).__name__)
    if set(reply) != set(gor.OUTPUT_READ_REPLY_FIELDS):
        raise RuntimeError(
            "the supervisor reply is not a %s frame: fields %s, expected exactly %s"
            % (gor.OUTPUT_READ_RESULT_PROTOCOL, sorted(reply),
               sorted(gor.OUTPUT_READ_REPLY_FIELDS)))
    if reply["protocol"] != gor.OUTPUT_READ_RESULT_PROTOCOL:
        raise RuntimeError("the supervisor reply names protocol %r, not %r"
                           % (reply["protocol"], gor.OUTPUT_READ_RESULT_PROTOCOL))
    ok = reply["ok"]
    if not isinstance(ok, bool):
        raise RuntimeError("the supervisor reply's `ok` is %r, not a boolean" % (ok,))
    if ok:
        if reply["error"] is not None:
            raise RuntimeError("an ok supervisor reply carries an error object")
        if not isinstance(reply["eof"], bool):
            raise RuntimeError("an ok supervisor reply's `eof` is not a boolean")
        if not isinstance(reply["seq"], int) or isinstance(reply["seq"], bool):
            raise RuntimeError("an ok supervisor reply's `seq` is not an integer")
        if not isinstance(reply["output_stream_id"], str):
            raise RuntimeError("an ok supervisor reply names no output_stream_id")
        import brops_protocol

        try:
            chunk = brops_protocol.decode_base64url(reply["bytes_b64"])
        except brops_protocol.ProtocolError as exc:
            raise RuntimeError("an ok supervisor reply's bytes_b64 is not canonical "
                               "base64url: %s" % exc)
        if len(chunk) > gor.OUTPUT_CHUNK_BYTES:
            raise RuntimeError("an ok supervisor reply carries %d bytes, over the %d stride"
                               % (len(chunk), gor.OUTPUT_CHUNK_BYTES))
        return reply
    for absent in ("bytes_b64", "eof"):
        if reply[absent] is not None:
            raise RuntimeError("a refused supervisor reply carries %s" % absent)
    error = reply["error"]
    if not isinstance(error, dict) or set(error) != {"reason"}:
        raise RuntimeError("a refused supervisor reply's error object is not {reason}")
    if error["reason"] not in gor.OUTPUT_READ_REFUSAL_REASONS:
        # An unpublished literal must never be relayed: 4.10(f) says the bridge enum is
        # "IDENTICAL to the supervisor's (NOT a superset)", and a reason outside the closed
        # set would travel all the way into a desktop Block reason string.
        raise RuntimeError("a refused supervisor reply names %r, which is not one of %s"
                           % (error["reason"], sorted(gor.OUTPUT_READ_REFUSAL_REASONS)))
    return reply


def _bridge_output_read(request: dict) -> dict:
    """Serve one `bridge.governed-turn-output-read.v1`: forward, validate, reframe.

    Exactly one supervisor round trip, then this process exits. Reframing is a single key:
    the supervisor's `protocol` const becomes the bridge one and every other field - `ok`,
    `output_stream_id`, `seq`, `bytes_b64`, `eof`, `error` - is relayed VERBATIM, because
    the sidecar originates no verdict and a re-shaped verdict is an originated one.

    Every failure of this process's OWN transport raises out of here and becomes the
    protocol-less `bridge.op.v1` refusal, per the 4.10(f) NOTE: a local failure "is NOT one
    of these reasons and produces NO reply frame". That is the whole reason this function
    has no fail-closed refusal of its own to fall back on.
    """
    gor = _output_read_contract()
    socket_path = _supervisor_socket_path()
    frame = _forwarded_output_read(request, gor.OUTPUT_READ_PROTOCOL)
    reply = _validated_output_read_reply(_supervisor_request(socket_path, frame), gor)
    relayed = dict(reply)
    relayed["protocol"] = BRIDGE_OUTPUT_READ_RESULT_PROTOCOL
    return relayed


#: op -> (handler, refusal factory). Registering an op is adding a row; the dispatch
#: needs no edit, and an op absent from this table is refused by name. The refusal
#: factory is per-op so a refusal stays inside the protocol the caller was speaking.
_OPS: dict[str, tuple[Callable[[dict], dict], Callable[[Any, Any], dict]]] = {
    GOVERNANCE_READ_OP: (_op_governance_read, _governance_refusal),
}


def _governed_turn(request: dict, argv: list[str]) -> dict:
    """The original bridge.task-request path — one governed turn, unchanged."""
    task_id = request.get("task_id")
    # Self-test is a CLI-flag-only backdoor — deliberately NOT reachable via an
    # environment variable. A production desktop launch inherits its parent env; an
    # env-activated fake verifier there would fabricate a "verified" result. The
    # desktop never passes --self-test (and strips any fake flag before spawning), so
    # production can only ever reach real mode. (Architect merge-blocker, slice 2.)
    fake = "--self-test" in argv
    signed_self_test = "--self-test-signed" in argv
    try:
        if signed_self_test:
            run_task, read_result = _signed_self_test_callables()
        elif fake:
            run_task, read_result = _fake_run_task, _fake_read
        else:
            run_task, read_result = _real_callables(request)
        return run_governed_turn(request, run_task=run_task, read_result=read_result)
    except Exception as exc:  # noqa: BLE001 — fail closed, never leak a partial result
        return _fail(task_id, exc)


def _dispatch(request: dict, argv: list[str]) -> dict:
    """Route one parsed request to its handler. Never raises; never returns None.

    Three disjoint shapes, in the order they are recognised: a top-level `protocol`
    naming the 4.10(f) output read, an `op`, and - with neither - the original
    `bridge.task-request`. The disjointness is structural rather than conventional: the
    task-request schema is `additionalProperties:false` and has no `protocol` key, so it
    cannot grow one; and no op is keyed on `protocol`.

    The output read is checked FIRST so it can never be reinterpreted as a governed turn
    by a future edit that adds a `protocol` key elsewhere.
    """
    if request.get("protocol") == BRIDGE_OUTPUT_READ_PROTOCOL:
        try:
            return _bridge_output_read(request)
        except Exception as exc:  # noqa: BLE001 - 4.10(f): a LOCAL failure emits NO 4.10(f) frame
            return _op_refusal(request, exc)
    if "op" not in request:
        return _governed_turn(request, argv)
    op = request["op"]
    entry = _OPS.get(op) if isinstance(op, str) else None
    if entry is None:
        return _op_refusal(request, (
            f"unsupported bridge op: {op!r}. This sidecar serves ops "
            f"{sorted(_OPS)} plus the bridge.task-request envelope (no `op` key). An "
            "op it does not implement is refused by name, never silently ignored"))
    handler, refusal = entry
    try:
        return handler(request)
    except Exception as exc:  # noqa: BLE001 — an op that fails is a refusal, not a result
        return refusal(request, exc)


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #
def run(argv: list[str], stdin, stdout) -> int:
    """Read one request from stdin, write one reply to stdout.

    Always exits 0 and always writes a reply — the verdict travels in the payload
    (`ok`), never in the exit status. Which reply document it is follows the request:
    no `op` gives a `bridge.result` for the governed turn, an op gives that op's own
    reply. Fail-closed on every error path.
    """
    request: Any = None
    task_id: Any = None
    try:
        raw = stdin.read()
        request = json.loads(raw) if raw and raw.strip() else {}
        if not isinstance(request, dict):
            raise ValueError("task-request must be a JSON object")
        task_id = request.get("task_id")
    except Exception as exc:  # noqa: BLE001 — any parse failure is fail-closed
        json.dump(_fail(task_id, f"invalid task-request on stdin: {exc}"), stdout)
        return 0

    reply = _dispatch(request, argv)
    # Serialize whole, THEN write. An op relays a much richer document than the four
    # flat fields of a bridge-result, and a value that will not encode must not leave
    # half a JSON object on the pipe for the desktop to parse as a truncated success.
    try:
        encoded = json.dumps(reply)
    except (TypeError, ValueError) as exc:
        encoded = json.dumps(
            _op_refusal(request, f"bridge reply could not be serialized: {exc}"))
    stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:], sys.stdin, sys.stdout))
