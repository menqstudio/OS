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
  closed.

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
    """A refusal for an op with no reply protocol of its own.

    Note what is absent: no `records`, no `result`. There is no field a consumer
    could read as "the call succeeded and produced nothing".
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
    """Route one parsed request to its op. Never raises; never returns None."""
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
