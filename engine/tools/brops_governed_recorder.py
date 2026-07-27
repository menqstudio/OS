"""Wave 3b-1B evidence-recorder RUNNER (§2.3 / §8 — the dedicated recorder principal).

Runs as its OWN long-lived process under the dedicated `brops-recorder` OS principal. It HOLDS
the evidence-recorder key and OWNS `store/rec/`: for each governed turn the supervisor sends the
executor output + turn metadata, and the recorder writes the output, containment, the
evidence-recorder-signed execution receipt, and the signed `bro_evidence` chain to `store/rec/`,
returning their handles. The supervisor is a DIFFERENT principal that can neither write `store/rec/`
(the OS ACLs forbid it — machine-proven by `engine/ci/isolation_proof.sh`) nor hold this key, so a
compromised supervisor cannot fabricate recorder-namespace evidence. `bro_signature` only verifies;
there is no arbitrary-bytes signing endpoint — the recorder signs ONLY the fixed receipt/evidence
shapes below.
"""
from __future__ import annotations

import json
import os
import pathlib
import signal
import subprocess
import tempfile
import time
import uuid
import sys
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bro_evidence import event_hash as evidence_event_hash
from bro_signature import canonical_bytes
from broctl import sign_payload
from brops_evidence_store import NamespacedEvidenceStore
from brops_governed_common import (
    EXECUTION_TIMEOUT_MS, GovernedProtocolError, MAX_OUTPUT_BYTES, b64url_encode,
    require_exact_keys, require_id,
)

PROTOCOL = "brops.governed-record-request.v1"
RESULT_PROTOCOL = "brops.governed-record-result.v1"

# The recorder now OWNS execution (rev-26 §0 principal hierarchy): the supervisor sends only the
# INPUT handles + turn metadata; the recorder launches the contained executor via the setuid
# launcher, reads its output pipe directly, and measures teardown itself — so the entity that signs
# the execution receipt is the same entity that observed the execution. The supervisor never sees
# the output bytes and cannot substitute them. It does NOT send output_b64 anymore.
_REQUEST_KEYS = frozenset({
    "protocol", "run_id", "execution_attempt_id", "lease_id", "receipt_id",
    "task_id", "agent_id", "runner_id", "executor_id",
    "system_handle", "history_handle", "generation_config_handle", "issued_at_epoch",
})

_DEFAULT_LAUNCHER = pathlib.Path(__file__).with_name("brops_executor_launcher.py")


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class RecorderComponents:
    # The recorder reads the supervisor-written inputs from sup/ and writes its own artifacts to
    # rec/, so it holds the whole namespaced store (not just rec/). It also holds the PINNED executor
    # command + launcher — taken from the recorder's OWN config, never from the request, so a
    # compromised supervisor cannot choose what binary runs.
    store: NamespacedEvidenceStore
    evidence_recorder_key: Mapping[str, str]
    executor_command: tuple = ()
    launcher_path: pathlib.Path = _DEFAULT_LAUNCHER
    clock_ms: Callable[[], int] = _now_ms
    monotonic: Callable[[], float] = time.monotonic


def _sign_document(payload: Mapping[str, Any], key: Mapping[str, str]) -> dict[str, Any]:
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key["private_key"]))
    return {"payload": dict(payload),
            "signature": b64url_encode(private.sign(canonical_bytes(dict(payload))))}


def _atomic_write_json(path: pathlib.Path, obj: Any) -> None:
    """Write JSON durably: a temp file in the same dir, fsync, then a single atomic os.replace.
    A crash can leave a stale temp (garbage-collected on the next run) but NEVER a half-written
    evidence event/head — the signer would in any case reject a truncated head on signature verify,
    but atomic replace means a reader only ever sees the complete file (matches the store's rigor)."""
    data = json.dumps(obj).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
    tmp = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if os.name == "posix":
            os.chmod(tmp, 0o640)
        os.replace(tmp, path)          # atomic on POSIX + NTFS
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass


def _measure_teardown(pgid: int) -> tuple[bool, str]:
    """Sweep any survivors of the executor's process group, then confirm the group is empty. The
    recorder OWNS the group (it launched the executor under setsid), so this is a real measurement,
    not an assertion: contained iff no process of the group survives teardown. POSIX-only (the FD /
    process-group model is Linux; on other platforms execution is not the tested path)."""
    if os.name != "posix":
        return True, "contained"
    try:
        os.killpg(pgid, signal.SIGKILL)     # sweep stragglers the executor may have spawned
    except ProcessLookupError:
        pass                                # group already empty
    try:
        os.killpg(pgid, 0)                  # probe: any members left?
    except ProcessLookupError:
        return True, "contained"            # ESRCH → nothing survived → contained
    return False, "escaped"                 # something is still alive after teardown


def _run_executor(c: RecorderComponents, system_handle: str, history_handle: str,
                  config_handle: str) -> tuple[bytes, int, int, bool, str]:
    """Launch the pinned contained executor via the setuid launcher, read its output pipe DIRECTLY,
    and measure teardown. The recorder (this principal) owns the whole execution; the supervisor
    never touches the output bytes and cannot substitute them. Uses the executor command PINNED in
    the recorder's own config, never a supervisor-supplied one. Raises GovernedProtocolError on any
    operational failure so the caller can refuse fail-closed."""
    if not c.executor_command:
        raise GovernedProtocolError("model_profile_unknown")
    start_ms = c.clock_ms(); start_mono = c.monotonic()
    # §2.3: the inputs live in sup/ (supervisor-written); resolve each to its holding namespace and
    # open READ-ONLY. The recorder can read sup/ (group member) but never writes it.
    fds = [os.open(c.store.path(h), os.O_RDONLY)
           for h in (system_handle, history_handle, config_handle)]
    env = os.environ.copy()
    env.update({
        "BROPS_LAUNCH_SYSTEM_FD": str(fds[0]),
        "BROPS_LAUNCH_HISTORY_FD": str(fds[1]),
        "BROPS_LAUNCH_CONFIG_FD": str(fds[2]),
    })
    command = (os.environ.get("PYTHON", sys.executable), str(c.launcher_path), *c.executor_command)

    def _preexec() -> None:
        os.setsid()

    try:
        proc = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, pass_fds=tuple(fds), preexec_fn=_preexec if os.name == "posix" else None,
        )
        try:
            output, _stderr = proc.communicate(timeout=EXECUTION_TIMEOUT_MS / 1000)
        except subprocess.TimeoutExpired:
            _measure_teardown(proc.pid)     # SIGKILL the runaway group
            proc.communicate()
            raise GovernedProtocolError("output_timeout")
        contained, teardown_outcome = _measure_teardown(proc.pid)
        if proc.returncode != 0:
            raise GovernedProtocolError("run_binding_invalid")
        if len(output) > MAX_OUTPUT_BYTES:
            raise GovernedProtocolError("output_oversize")
        elapsed = (c.monotonic() - start_mono) * 1000
        if elapsed >= EXECUTION_TIMEOUT_MS:
            raise GovernedProtocolError("output_timeout")
        return output, start_ms, c.clock_ms(), contained, teardown_outcome
    finally:
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass


def record_governed_turn(request: Mapping[str, Any], c: RecorderComponents) -> dict[str, Any]:
    """OWN one governed turn's execution and evidence: launch the contained executor, read its
    output, measure teardown, then write the output + measured containment + evidence-recorder-signed
    execution receipt + signed bro_evidence chain to store/rec/, returning their handles + the
    execution timing. Fail-closed on any malformed request or operational failure."""
    try:
        require_exact_keys(request, _REQUEST_KEYS, "governed record request")
        if request["protocol"] != PROTOCOL:
            raise GovernedProtocolError("wrong record protocol")
        run_id = require_id(request["run_id"], "run_id")
        attempt = require_id(request["execution_attempt_id"], "execution_attempt_id")
        lease_id = require_id(request["lease_id"], "lease_id")
        receipt_id = require_id(request["receipt_id"], "receipt_id")
        task_id = require_id(request["task_id"], "task_id")
        agent_id = require_id(request["agent_id"], "agent_id")
        runner_id = require_id(request["runner_id"], "runner_id")
        executor_id = require_id(request["executor_id"], "executor_id")
        system_handle = require_id(request["system_handle"], "system_handle")
        history_handle = require_id(request["history_handle"], "history_handle")
        config_handle = require_id(request["generation_config_handle"], "generation_config_handle")
        if isinstance(request["issued_at_epoch"], bool) or not isinstance(request["issued_at_epoch"], int):
            raise GovernedProtocolError("issued_at_epoch must be an integer")
        issued_at_epoch = request["issued_at_epoch"]
    except (GovernedProtocolError, KeyError, TypeError, ValueError) as exc:
        return {"protocol": RESULT_PROTOCOL, "status": "refused", "reason": f"malformed:{exc}"}

    # OWN the execution: launch the contained executor, read its output pipe, measure teardown.
    try:
        output, started, finished, contained, teardown_outcome = _run_executor(
            c, system_handle, history_handle, config_handle)
    except GovernedProtocolError as exc:
        return {"protocol": RESULT_PROTOCOL, "status": "refused", "reason": str(exc)}

    key_id = c.evidence_recorder_key["key_id"]
    priv = c.evidence_recorder_key["private_key"]
    output_handle = c.store.rec.publish(output)
    containment = {
        "artifact_type": "brops.governed-turn-containment.v1",
        "run_id": run_id, "execution_attempt_id": attempt, "lease_id": lease_id,
        "runner_id": runner_id, "executor_id": executor_id,
        "cgroup_id": "process-group:" + attempt, "process_group_id": attempt,
        "contained": contained, "teardown_outcome": teardown_outcome, "measured_at_ms": finished,
    }
    containment_handle = c.store.rec.publish(canonical_bytes(containment))
    execution_receipt_payload = {
        "artifact_type": "brops.governed-turn-execution-receipt.v1",
        "key_id": key_id, "receipt_id": receipt_id, "task_id": task_id,
        "run_id": run_id, "execution_attempt_id": attempt, "lease_id": lease_id,
        "runner_id": runner_id, "executor_id": executor_id,
        "exit_code": 0, "contained": contained, "output_handle": output_handle,
        "output_sha256": output_handle, "output_bytes": len(output),
        "started_at_ms": started, "finished_at_ms": finished,
    }
    execution_receipt = _sign_document(execution_receipt_payload, c.evidence_recorder_key)
    execution_receipt_handle = c.store.rec.publish(canonical_bytes(execution_receipt))

    # §7 — a REAL signed bro_evidence chain in store/rec/evidence/ (evidence-recorder authority).
    evidence_dir = pathlib.Path(c.store.rec.root) / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(evidence_dir, 0o2750)
    evidence_event_id = str(uuid.uuid4())
    event_payload = {
        "artifact_type": "evidence-event", "key_id": key_id, "event_id": evidence_event_id,
        "sequence": 1, "previous_event_hash": None, "task_id": task_id,
        "event_type": "governed-turn-completed", "agent_id": agent_id,
        "payload_hash": output_handle, "issued_at_epoch": issued_at_epoch,
    }
    final_event_hash = evidence_event_hash(event_payload)
    head_payload = {
        "artifact_type": "evidence-head", "key_id": key_id, "task_id": task_id,
        "final_event_hash": final_event_hash, "event_count": 1, "last_sequence": 1,
        "head_sequence": 1, "issued_at_epoch": issued_at_epoch,
    }
    # Write the event BEFORE the head, each atomically: the head names final_event_hash, so a reader
    # that sees the head is guaranteed the event it points at is already fully on disk.
    _atomic_write_json(evidence_dir / f"{evidence_event_id}.json", sign_payload(priv, event_payload))
    _atomic_write_json(evidence_dir / f"{task_id}.head.json", sign_payload(priv, head_payload))

    return {
        "protocol": RESULT_PROTOCOL, "status": "recorded",
        "output_handle": output_handle, "output_bytes": len(output),
        "started_at_ms": started, "finished_at_ms": finished,
        "containment": containment, "containment_handle": containment_handle,
        "execution_receipt_handle": execution_receipt_handle,
        "evidence_event_id": evidence_event_id, "evidence_final_event_hash": final_event_hash,
        "evidence_event_count": 1, "evidence_last_sequence": 1, "evidence_head_sequence": 1,
    }


def load_recorder_components(env: Mapping[str, str]) -> RecorderComponents:
    def _key(directory: str, name: str) -> dict[str, str]:
        data = json.loads((pathlib.Path(directory) / name).read_text(encoding="utf-8"))
        return {"key_id": data["key_id"], "private_key": data["private_key"]}
    launcher = env.get("BROPS_LAUNCHER_PATH")
    return RecorderComponents(
        store=NamespacedEvidenceStore(pathlib.Path(env["BROPS_EVIDENCE_STORE_DIR"])),
        evidence_recorder_key=_key(env["BROPS_EVIDENCE_RECORDER_KEYDIR"],
                                   "brops-governed-evidence-recorder.json"),
        executor_command=tuple(json.loads(env["BROPS_EXECUTOR_COMMAND"])),
        launcher_path=pathlib.Path(launcher) if launcher else _DEFAULT_LAUNCHER,
    )
