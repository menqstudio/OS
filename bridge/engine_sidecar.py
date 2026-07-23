#!/usr/bin/env python3
"""bridge/engine_sidecar.py — the process the desktop cockpit shells out to.

The desktop is a *conductor*: it never holds a lease, a key, or the engine. It
writes ONE `bridge.task-request` JSON to this sidecar's **stdin** and reads ONE
`bridge.result` JSON from **stdout**. The sidecar hosts
`bridge.engine_adapter.run_governed_turn`, injecting the engine-side callables
(`run_task` / `read_result`). The adapter makes NO trust decision: it carries the
run's SIGNED receipt material (`envelope_jcs_b64` + `signature_b64`) for the DESKTOP,
which is the final authority and verifies the signature (design §3). Every failure
is still fail-closed (`result=null`); there is no self-asserted `verified` boolean.

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

# Wave 3b receipt-signer material (its own key custody, separate from BRO_KEYDIR — the
# receipt-signing key must NEVER live in BRO_KEYDIR; design §1.2). Required IN ADDITION to
# `_PROVISION_ENV` before real mode can mint a signed receipt.
_SIGNER_PROVISION_ENV = (
    "BROPS_RECEIPT_SIGNER_KEYDIR",
    "BROPS_SUPERVISOR_ATTESTATION_KEYDIR",
    "BROPS_SUPERVISOR_ATTESTATION_PUBKEY",
    "BROPS_EVIDENCE_STORE_DIR",
)


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

    from brops_evidence_store import EvidenceStore
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
        )

    def read_result(outcome: Any) -> str:
        return getattr(outcome, "_text", "")

    return run_task, read_result


# --------------------------------------------------------------------------- #
# Real mode — provisioning + engine wiring.
# --------------------------------------------------------------------------- #
def _real_callables(
    request: dict,
) -> tuple[Callable[[dict], Any], Callable[[Any], str]]:
    """Return the engine-bound callables, or raise RuntimeError with a fail-closed
    reason. Gates, all fail-closed:

    1. supervisor provisioning — every `_PROVISION_ENV` var must be present;
    2. signer provisioning — every `_SIGNER_PROVISION_ENV` var must be present (the
       receipt-signing key has its OWN custody, never `BRO_KEYDIR`; design §1.2);
    3. live run-state provider — the isolated signer/store/attestation chain now EXISTS
       (Wave 3b-1, `brops_receipt_signer`/`brops_evidence_store`/`brops_supervisor_attest`),
       but wiring the LIVE supervisor's terminal run-state into it (so `run_task` builds a
       real `RunState` from an executed governed turn under a dedicated OS principal) is
       the remaining Linux-first 3b-1 step, and the desktop still resolves
       `NoTrustedManifest` ⇒ Blocks until the manifest lands (3b-2/3b-3). Until then real
       mode fails closed rather than emit anything. `--self-test-signed` exercises the
       full signer chain today.
    """
    missing = [k for k in _PROVISION_ENV if not os.environ.get(k, "").strip()]
    if missing:
        raise RuntimeError(
            "governed engine not provisioned: missing " + ", ".join(missing)
        )
    missing_signer = [k for k in _SIGNER_PROVISION_ENV if not os.environ.get(k, "").strip()]
    if missing_signer:
        raise RuntimeError(
            "governed engine receipt signer not provisioned: missing "
            + ", ".join(missing_signer)
        )
    raise RuntimeError(
        "governed engine real-mode is pending the Wave 3b-1 live supervisor run-state "
        "provider and the Wave 3b-2/3b-3 desktop trusted manifest; the isolated signer "
        "chain is implemented and self-tested (`--self-test-signed`) but refusing to "
        "emit until the live wiring + trusted key land"
    )


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #
def run(argv: list[str], stdin, stdout) -> int:
    """Read one task-request from stdin, write one bridge-result to stdout.

    Always exits 0 and always writes a schema-shaped bridge-result — the verdict
    travels in the payload (`ok`), never in the exit status. Fail-closed on every
    error path.
    """
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
        result = run_governed_turn(request, run_task=run_task, read_result=read_result)
    except Exception as exc:  # noqa: BLE001 — fail closed, never leak a partial result
        result = _fail(task_id, exc)

    json.dump(result, stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:], sys.stdin, sys.stdout))
