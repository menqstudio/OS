#!/usr/bin/env python3
"""Run the LIVE governed supervisor WITH the §4.10(g) sidecar ladder wired (Wave 3b, rev-30).

``run_supervisor.py`` is the §5 half: it serves the five ``op`` lifecycle messages to the
BROKER uid and constructs none of the four sidecar services — an engine test asserts that
absence, and that test stays true because this is a SEPARATE runner rather than an edit to it.
The two are different deployments of one front door and each stays independently meaningful:
``run_live_turn.sh`` proves the §5 chain over direct AF_UNIX, this proves the §4.10(g) ladder.

What is wired here that is wired nowhere else
----------------------------------------------
All four services, on ONE socket, with TWO principals kept disjoint by
``governed_supervisor_server.handle_connection``:

  * ``OpenService``            — §4.10(a0), against a REAL §4.2 registry document resolved
                                 from this supervisor's own state under a binary-pinned root.
  * ``StagingService``         — §4.10(a)(b)(c), over a supervisor-private 0700 staging root.
  * ``EvidenceRequestService`` — §4.10(d), whose ``drive_acceptance`` is the real §5
                                 ``AcceptanceDriver``.
  * ``OutputReadService``      — §4.10(f), both halves (the mint at completion and the read).

and the one seam every test on every platform has had to stand in for:

  * ``RecorderExecutor``       — §6.1 step 5, the REAL contained execution. It spawns the
                                 privileged recorder under ``sudo``, which execs the root-owned
                                 setuid launcher, which drops to the executor uid and ``fexecve``s
                                 the pinned executor image. No stand-in, and no fallback: the
                                 shipped default (``RefusingExecutor``) refuses
                                 ``platform_unsupported`` pre-record, and so does this one when
                                 the host cannot contain an execution.

Fail-closed throughout, Linux-only (``SO_PEERCRED``). Every prerequisite is required: a missing
key, policy, registry document, staging root or recorder binary aborts startup rather than
degrading to a supervisor that serves without the authority its replies claim.

Run AS the supervisor account:
    sudo -u brops-supervisor python3 run_ladder_supervisor.py --config <config.json> \
        --ladder <tcb/ladder.json>
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "runtime")))

import ipc_policy  # noqa: E402
import live_crypto as lc  # noqa: E402
import isolated_signer_server as iss  # noqa: E402
import governed_acceptance as gac  # noqa: E402
import governed_evidence_request as ger  # noqa: E402
import governed_output_read as gor  # noqa: E402
import governed_staging_upload as gsu  # noqa: E402
import governed_supervisor_ledger as gsl  # noqa: E402
import governed_supervisor_server as gss  # noqa: E402
import governed_turn_open as gto  # noqa: E402
from governed_supervisor import SupervisorConfig, recompute_request_sha256  # noqa: E402

#: How long the contained execution may take before this supervisor gives up on it. It is
#: DELIBERATELY under ``governed_supervisor_server.CONNECTION_BUDGET_S`` (120 s), which is the
#: total deadline on the §4.10(d) connection the sidecar is waiting on: acceptance, this
#: execution, the completion, the attestation and the isolated-signer round trip all have to
#: fit inside that one budget. A child allowed the whole 120 s would guarantee the reply misses
#: it, and the sidecar would read a governed refusal as a transport failure.
EXECUTION_WAIT_S = 90.0

#: The signer round trip (§6.1 steps 11-12). Same reasoning: it shares the §4.10(d) budget.
SIGNER_TIMEOUT_S = 20.0

#: A bound on the recorder's evidence chain, so a hostile file cannot exhaust the supervisor.
MAX_EVIDENCE_BYTES = 1 << 20


class LadderError(RuntimeError):
    """A provisioning fault this runner refuses to start under."""


# ---------------------------------------------------------------------------
# The protected store, from the supervisor's side
# ---------------------------------------------------------------------------


def _is_handle(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


class Store:
    """The content-addressed protected store: the handle IS the digest, both ways.

    ``read`` re-verifies ``sha256(bytes) == handle`` on every read, which is what makes a
    handle safe to accept from a durable row: the bytes it names cannot have been swapped for
    others under the same address. ``publish`` is atomic-by-rename and idempotent for exactly
    the same reason — republishing identical bytes is a no-op, and no other bytes can claim
    that name.
    """

    #: A blob larger than this is refused rather than read into memory. The three staged
    #: artifacts are capped by §2.4 (8 MiB for `history`, the largest), and the executor's
    #: reply and containment report are smaller still.
    MAX_BLOB_BYTES = 16 << 20

    def __init__(self, store_dir: str) -> None:
        self.dir = store_dir

    def read(self, handle: Any) -> bytes:
        if not _is_handle(handle):
            raise LadderError("not a 64-hex content address: %r" % (handle,))
        path = os.path.join(self.dir, handle)
        with open(path, "rb") as fh:
            data = fh.read(self.MAX_BLOB_BYTES + 1)
        if len(data) > self.MAX_BLOB_BYTES:
            raise LadderError("store blob %s exceeds %d bytes" % (handle, self.MAX_BLOB_BYTES))
        if hashlib.sha256(data).hexdigest() != handle:
            raise LadderError("store corruption: blob digest != handle %s" % handle)
        return data

    def publish(self, data: bytes) -> str:
        handle = hashlib.sha256(data).hexdigest()
        final = os.path.join(self.dir, handle)
        if not os.path.exists(final):
            tmp = final + ".tmp-%d" % os.getpid()
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, final)
            try:
                os.chmod(final, 0o644)  # the signer, on its own uid, reads it by handle
            except OSError:
                pass
        return handle


# ---------------------------------------------------------------------------
# §6.1 step 5 — the REAL contained execution
# ---------------------------------------------------------------------------


class RecorderExecutor(gac.ExecutionService):
    """The privileged recorder → setuid launcher → contained executor spawn, as an
    ``ExecutionService``.

    This is the same OS ladder ``chain_executor.rs`` drives in the §5 proof, invoked from the
    other side of the design: in §5 the BROKER spawns the recorder and reports the lifecycle
    over the socket, and in §4.10(d) the SUPERVISOR owns the whole of §5 internally, so the
    spawn belongs to this seam. Nothing about the recorder's own defences changes — it reads
    every path from its ROOT-OWNED policy at a compile-time path and refuses any argv value
    that disagrees, so the argv below is checked against root's copy before the trusted binary
    does anything.

    **The one thing this seam cannot express, stated rather than implied.** The recorder opens
    ``store/system``, ``store/history`` and ``store/generation_config`` BY NAME as fds 3/4/5 —
    the rev-30 §2.7 closed-argv/FD contract gives it no way to be handed a per-turn content
    address. So the bytes the executor reads are selected by filename, while the bytes §4.10(c)
    staged are selected by digest. Two things bind them, and both are checked rather than
    assumed: this method refuses to launch unless the acceptance row's three handles equal the
    digests pinned in the root-owned lease, and the launcher itself re-hashes the descriptors
    it holds against those same pins before it will ``fexecve``. Teaching the recorder to take
    the three handles per run would change the §2.7 argv contract, which is an Architect
    decision and not one to smuggle into a proof harness.
    """

    def __init__(self, *, execution_config: Mapping[str, Any], recorder_command,
                 clock_ms, staged_pins: Mapping[str, str], hop_log) -> None:
        self.cfg = dict(execution_config)
        self.recorder_command = list(recorder_command)
        self.clock_ms = clock_ms
        # The three digests the ROOT-OWNED lease pins, read once at startup from the file the
        # launcher itself re-hashes against. Held so `run` can refuse a turn whose staged
        # handles are not these, instead of launching an execution on other bytes.
        self.staged_pins = dict(staged_pins)
        self.hop_log = hop_log

    # -- §4.5 `platform_unsupported`: a PRE-RECORD block ---------------------
    def preflight(self) -> None:
        if sys.platform != "linux":
            raise gac.GovernedExecutionUnavailable(
                "the §6.1 step-5 ladder is Linux-only (setuid launcher + SO_PEERCRED + six uids)")
        for key in ("launcher_path", "executor_path", "lease_file"):
            path = self.cfg[key]
            if not os.path.isfile(path):
                raise gac.GovernedExecutionUnavailable(
                    "the contained-execution %s is not provisioned at %s" % (key, path))
        for key in ("report_dir", "evidence_state_dir", "recorder_store_dir"):
            path = self.cfg[key]
            if not os.path.isdir(path):
                raise gac.GovernedExecutionUnavailable(
                    "the contained-execution %s is not provisioned at %s" % (key, path))
        recorder_bin = self.recorder_command[-1]
        if not os.path.isfile(recorder_bin):
            raise gac.GovernedExecutionUnavailable(
                "the privileged recorder is not provisioned at %s" % recorder_bin)

    # -- §5 step 8b: launch ONCE, report the start while the child runs -------
    def run(self, request: gac.ExecutionRequest, on_started) -> gac.ExecutionOutcome:
        staged = {
            "system": request.system_handle,
            "history": request.history_handle,
            "generation_config": request.generation_config_handle,
        }
        for name, handle in staged.items():
            pinned = self.staged_pins.get(name)
            if pinned != handle:
                # Not a refusal vocabulary decision — a raise here becomes the driver's
                # `RECOVERY_REQUIRED` + `not_completed`, which is the fail-closed direction.
                # Launching anyway would execute bytes the acceptance row does not name.
                raise LadderError(
                    "the acceptance row stages %s=%s but the root-owned lease pins %s; the "
                    "contained execution reads store/%s by name, so these must be one value"
                    % (name, handle, pinned, name))

        attempt = request.execution_attempt_id
        report_dir = self.cfg["report_dir"]
        state_dir = self.cfg["evidence_state_dir"]
        # The three per-run file names. `ladder-` distinguishes them from the §5 proof's
        # `live-` names in the same directory, and it is the token the sudoers vector wildcards.
        out_path = os.path.join(report_dir, "ladder-%s.out" % attempt)
        containment_path = out_path + ".containment.json"
        evidence_path = os.path.join(state_dir, "%s.evidence.json" % attempt)
        for stale in (out_path, containment_path):
            # The recorder's own directory; the evidence chain is NOT cleared here — this
            # process cannot write $RECSTATE and has no business touching the recorder's
            # evidence.
            try:
                os.unlink(stale)
            except OSError:
                pass

        argv = self.recorder_command + [
            "--store", self.cfg["recorder_store_dir"],
            "--launcher", self.cfg["launcher_path"],
            "--executor", self.cfg["executor_path"],
            "--lease", self.cfg["lease_file"],
            "--cgroup", self.cfg["cgroup_arg"],
            "--out", out_path,
            "--containment-out", containment_path,
            "--evidence-out", evidence_path,
            "--evidence-state", state_dir,
        ]
        self.hop_log("execution.spawn", None, {"attempt": attempt, "argv": argv})

        child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        # §5 locks `EXECUTION_STARTING → EXECUTING` to "the launcher confirms the child is
        # running AND its process metadata is durably persisted". Reported BEFORE the wait,
        # from the real pid, exactly as `chain_executor.rs` does.
        on_started(gac.StartedExecution(process_group_id=str(child.pid),
                                        cgroup_id=self.cfg["cgroup_arg"],
                                        execution_started_marker=None))
        try:
            stdout, _ = child.communicate(timeout=EXECUTION_WAIT_S)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate()
            raise LadderError("the contained execution exceeded %.0fs" % EXECUTION_WAIT_S)
        text = (stdout or b"").decode("utf-8", "replace")
        self.hop_log("execution.exit", None,
                     {"attempt": attempt, "exit": child.returncode,
                      "recorder_stdout": text[-2000:]})
        if child.returncode != 0:
            raise LadderError("the recorder exited %d: %s" % (child.returncode, text[-500:]))

        # The recorder publishes BOTH blobs into the protected store from its own uid (§2.3).
        # This seam only NAMES them: the isolated signer re-derives `output_sha256` /
        # `output_bytes` by reading the store, and `complete_governed_run` refuses a completion
        # whose `output_handle` disagrees with the recorder's own evidence chain — so a handle
        # invented here buys nothing and is caught one hop later.
        output = self._read_nonempty(out_path, "the governed output")
        containment = self._read_nonempty(containment_path, "the containment report")
        return gac.ExecutionOutcome(
            output_handle=hashlib.sha256(output).hexdigest(),
            containment_evidence_handle=hashlib.sha256(containment).hexdigest(),
            completed_at_ms=self.clock_ms(),
        )

    @staticmethod
    def _read_nonempty(path: str, what: str) -> bytes:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            raise LadderError("%s is absent at %s: %s" % (what, path, exc))
        if not data:
            raise LadderError("%s at %s is empty; a run with no output is not a completion"
                              % (what, path))
        return data


# ---------------------------------------------------------------------------
# Hop logging — the uids that ran each hop, as the KERNEL reported them
# ---------------------------------------------------------------------------


class HopLogged:
    """Delegates to a service and records each served frame's protocol + SO_PEERCRED uid.

    The uid written here is ``conn.peer_uid``, which ``SocketPeerConn`` read from the kernel
    with ``SO_PEERCRED`` — not a value any peer sent and not one this process chose. That is
    the whole reason the log is worth reading as evidence.
    """

    def __init__(self, inner: Any, log) -> None:
        self._inner = inner
        self._log = log

    @property
    def allowed_sidecar_uid(self) -> int:
        return self._inner.allowed_sidecar_uid

    def handle(self, request: Any, **kwargs: Any) -> Any:
        protocol = request.get("protocol") if isinstance(request, Mapping) else None
        reply = self._inner.handle(request, **kwargs)
        detail = {
            "status": reply.get("status") if isinstance(reply, Mapping) else None,
            "reason": reply.get("reason") if isinstance(reply, Mapping) else None,
        }
        detail.update(self._read_detail(request, reply))
        self._log(protocol, kwargs.get("peer_uid"), detail)
        return reply

    @staticmethod
    def _read_detail(request: Any, reply: Any) -> dict:
        """The §4.10(f) fields worth recording, and only those.

        §4.10(a0)/(a)(b)(c)/(d) answer with `{status, reason}`; §4.10(f) answers with
        `{ok, seq, error}` and carries no `status` at all, so before this the hop log recorded
        two nulls for every served range — the uid was there and WHICH range it served was not.
        "record every chunk's seq and the uid that served it" needs both halves, and only this
        side can supply the second: `peer_uid` is what the kernel reported over SO_PEERCRED, and
        the desktop cannot write this file.

        `bytes_b64` is deliberately absent. The hop log is evidence about WHO was served WHICH
        range, not a second copy of the output — and a 245760-character field per line would
        make the one thing it is for unreadable.
        """
        if not isinstance(request, Mapping) or not isinstance(reply, Mapping):
            return {}
        if request.get("protocol") != gor.OUTPUT_READ_PROTOCOL:
            return {}
        error = reply.get("error")
        return {
            "requested_seq": request.get("seq"),
            "requested_output_stream_id": request.get("output_stream_id"),
            "ok": reply.get("ok"),
            "seq": reply.get("seq"),
            "eof": reply.get("eof"),
            "chunk_bytes_b64_len": len(reply["bytes_b64"])
            if isinstance(reply.get("bytes_b64"), str) else None,
            "refusal_reason": error.get("reason") if isinstance(error, Mapping) else None,
        }

    def __getattr__(self, name: str) -> Any:
        # `measure_output` / `mint_for_completion` on the OutputReadService reach the real
        # object; nothing about them is a sidecar hop, so nothing is logged for them.
        return getattr(self._inner, name)


@dataclass(frozen=True)
class LadderServices:
    """The whole §4.10(g) service graph, built once and handed to the front door.

    It is a RETURN VALUE rather than a block inside ``main`` for one reason: the wiring is the
    part that can be wrong, and a graph that can only be built by binding a socket can only be
    checked by binding a socket. This lets the same construction be driven against
    ``governed_supervisor_server.dispatch`` directly — no AF_UNIX, no root — which is the only
    way any of it is reachable on a box that is not the deployment.
    """

    config: SupervisorConfig
    verify_sig: Any
    open_service: Any
    staging_service: Any
    evidence_service: Any
    output_read_service: Any
    driver: gac.AcceptanceDriver
    ledger_conn: Any
    store: Store
    clock_ms: Any
    publish_artifact: Any
    read_run_evidence: Any
    sign_attestation: Any
    supervisor_attestation_key_id: str


def build_ladder_services(cfg: Mapping[str, Any], ladder: Mapping[str, Any], *,
                          allowed_sidecar_uid: int,
                          execution: Optional[gac.ExecutionService] = None,
                          sign_result: Any = None,
                          clock_ms: Any = None,
                          hop: Any = None) -> LadderServices:
    """Construct the four §4.10(g) services and the §5 driver from the kit's own config.

    ``execution`` and ``sign_result`` are parameters and NOT defaults-with-a-fallback: the
    production bindings are built here when they are omitted, and a caller that supplies its own
    is stating so at the call site. There is deliberately no "use a stub if the real thing is
    missing" branch — that is the shape that lets a proof pass on a host that cannot run one.
    """
    if hop is None:
        def hop(_protocol, _peer_uid, _detail):  # noqa: ANN001 — a no-op recorder
            return None
    if clock_ms is None:
        def clock_ms() -> int:
            return int(time.time() * 1000)

    sup = cfg["supervisor"]
    sup_attest_key_id = cfg["trust"]["supervisor_attestation_key_id"]
    store = Store(cfg["store_dir"])

    with open(cfg["keys"]["supervisor_attest_priv"], "rb") as fh:
        sup_attest_priv = lc.load_private(fh.read())
    with open(cfg["keys"]["challenge_pub_hex"], "r", encoding="ascii") as fh:
        challenge_pub = lc.load_public_hex(fh.read().strip())

    registry_path = ladder["registry"]["document_path"]

    def resolve_registry_document() -> Any:
        """§5 step 3: "a fresh reload + floor — do NOT reuse the open-time snapshot". Read from
        disk on every call, so a rotation between the open and the acceptance is SEEN rather
        than assumed away."""
        return load_tcb_json(registry_path)

    def _verify(public_key_b64url: Any, message: bytes, sig: Any) -> bool:
        """Ed25519 verify BOUND to the key the caller resolved, never to a pinned constant.

        A seam that ignored ``public_key`` would make every registry and key refusal decorative
        — the supervisor would be checking a signature under whichever key it had to hand rather
        than the one the verified snapshot selected.
        """
        try:
            raw = base64.urlsafe_b64decode(
                public_key_b64url + "=" * (-len(public_key_b64url) % 4))
            return lc.verify_b64url(lc.load_public_hex(raw.hex()), message, sig)
        except Exception:  # noqa: BLE001 — a seam that raises must fail closed, not escape
            return False

    def verify_root_sig(message: bytes, sig: str, public_key: str) -> bool:
        return _verify(public_key, message, sig)

    def verify_challenge_sig(message: bytes, sig: str, public_key: str) -> bool:
        return _verify(public_key, message, sig)

    def verify_sig(message: bytes, sig: str) -> bool:
        """The §5 op surface's two-argument form, where the challenge key is pinned. Kept so the
        broker's ``op`` lifecycle stays exactly what ``run_supervisor.py`` serves; the ladder
        never reaches it."""
        return lc.verify_b64url(challenge_pub, message, sig)

    def sign_attestation(message: bytes) -> str:
        return lc.sign_b64url(sup_attest_priv, message)

    evidence_dir = cfg["execution"]["evidence_state_dir"]

    def read_run_evidence(attempt: Any) -> Optional[bytes]:
        """The RECORDER's evidence chain, from a directory only the recorder writes (F-01).

        The attempt id reaches the filesystem, so it must not be able to escape the directory —
        it is a supervisor-minted id, and the supervisor still does not get to assume its own
        inputs. Bounded so a hostile file cannot exhaust this process.
        """
        if not attempt or not all(c.isalnum() or c in "-_" for c in attempt):
            return None
        path = os.path.join(evidence_dir, attempt + ".evidence.json")
        try:
            with open(path, "rb") as fh:
                data = fh.read(MAX_EVIDENCE_BYTES + 1)
        except OSError:
            return None
        if len(data) > MAX_EVIDENCE_BYTES:
            return None
        return data

    if sign_result is None:
        signer_socket = ladder["signer_socket"]

        def sign_result(sign_request: Mapping[str, Any]) -> Mapping[str, Any]:
            """§6.1 steps 11-12, over the isolated signer's own AF_UNIX socket.

            The supervisor is the signer's peer here, which is what this kit's
            ``isolated-signer.ipc-policy.json`` names. It hands the signer the exact
            ``JCS(evidence)`` it attested; the signer verifies that attestation under the
            pinned supervisor key and RECOMPUTES the envelope from the protected store before
            signing, so this hop transports a request and confers no authority.

            The op envelope and the reply translation are `isolated_signer_server`'s own —
            NOT written here. The first live run of this kit died precisely because they were
            written here, by assumption: the driver's seam takes the signer's own reply and
            the wire carries the broker-shaped op reply (`signature`, not `signature_b64`; no
            `status`), and the sign-request must travel NESTED under `op`. A deployment script
            that re-derives a wire contract is a second author of it, and the two drift the
            first time either moves.
            """
            return iss.request_sign_result(signer_socket, dict(sign_request),
                                           timeout=SIGNER_TIMEOUT_S)

    config = SupervisorConfig(
        launcher_executable_sha256=sup["launcher_executable_sha256"],
        executor_executable_sha256=sup["executor_executable_sha256"],
        id_fn=lambda: uuid.uuid4().hex,
        supervisor_id=sup["supervisor_id"],
        executor_id=sup["executor_id"],
        builder_id=sup["builder_id"],
        policy_id=sup["policy_id"],
        policy_version=sup["policy_version"],
        policy_bundle_handle=sup["policy_bundle_handle"],
        challenge_registry_handle=sup["challenge_registry_handle"],
        challenge_registry_hash=sup["challenge_registry_hash"],
        challenge_registry_epoch=int(sup["challenge_registry_epoch"]),
        challenge_registry_root_key_id=sup["challenge_registry_root_key_id"],
    )
    open_config = gto.OpenConfig.from_supervisor_config(
        config,
        registry_root_public_key=ladder["registry"]["root_public_key_b64url"],
        registry_epoch_floor=int(ladder["registry"]["epoch_floor"]),
    )
    allowlist = frozenset(ladder["execution_allowlist"])
    if not allowlist:
        # An empty allowlist refuses every turn. That is the correct fail-closed default and a
        # useless service, so refusing to start says it where the message is about provisioning.
        raise LadderError("the ladder execution allowlist is empty: no turn could ever execute")
    acceptance_config = gac.AcceptanceConfig(
        supervisor=config, open_config=open_config, execution_allowlist=allowlist)

    staging_root = ladder["staging_root"]
    if not os.path.isdir(staging_root):
        raise LadderError("the supervisor's private staging root is not provisioned at %s"
                          % staging_root)

    if execution is None:
        execution = RecorderExecutor(
            execution_config=cfg["execution"],
            recorder_command=ladder["recorder_command"],
            clock_ms=clock_ms,
            staged_pins=lease_pins(cfg["execution"]["lease_file"]),
            hop_log=hop,
        )

    ledger_conn = gsl.open_ledger(sup["ledger_db"])

    output_read_service = HopLogged(
        gor.OutputReadService(allowed_sidecar_uid=allowed_sidecar_uid,
                              read_output=store.read), hop)
    driver = gac.AcceptanceDriver(
        config=acceptance_config,
        conn=ledger_conn,
        clock_ms=clock_ms,
        read_artifact=store.read,
        publish_artifact=store.publish,
        resolve_registry_document=resolve_registry_document,
        verify_root_sig=verify_root_sig,
        verify_challenge_sig=verify_challenge_sig,
        read_run_evidence=read_run_evidence,
        sign_attestation=sign_attestation,
        supervisor_attestation_key_id=sup_attest_key_id,
        sign_result=sign_result,
        output_read_service=output_read_service,
        execution=execution,
    )
    open_service = HopLogged(
        gto.OpenService(
            config=open_config,
            allowed_sidecar_uid=allowed_sidecar_uid,
            publish_document=store.publish,
            resolve_registry_document=resolve_registry_document,
            verify_root_sig=verify_root_sig,
            verify_challenge_sig=verify_challenge_sig,
        ), hop)
    staging_service = HopLogged(
        gsu.StagingService(
            allowed_sidecar_uid=allowed_sidecar_uid,
            staging_root=staging_root,
            publish_artifact=store.publish,
        ), hop)
    evidence_service = HopLogged(
        ger.EvidenceRequestService(
            allowed_sidecar_uid=allowed_sidecar_uid,
            drive_acceptance=driver,
        ), hop)

    return LadderServices(
        config=config,
        verify_sig=verify_sig,
        open_service=open_service,
        staging_service=staging_service,
        evidence_service=evidence_service,
        output_read_service=output_read_service,
        driver=driver,
        ledger_conn=ledger_conn,
        store=store,
        clock_ms=clock_ms,
        publish_artifact=store.publish,
        read_run_evidence=read_run_evidence,
        sign_attestation=sign_attestation,
        supervisor_attestation_key_id=sup_attest_key_id,
    )


def load_tcb_json(path: str) -> Any:
    """Read a ROOT-OWNED, non-group/other-writable JSON file, checked on the OPEN descriptor.

    Same rule and same reasoning as ``ipc_policy.load_allowed_peer_uid``: the registry document
    and the ladder config decide which challenge keys this supervisor accepts and which model
    profiles it may execute, so a copy a service account could rewrite would authorize whatever
    it liked. Measured on the descriptor rather than by a second ``stat``, so a swap between the
    check and the read cannot change what was measured.

    ``O_NOFOLLOW`` is requested when the platform has it, which on the only platform this
    service SERVES on (Linux — ``bind_listener`` refuses everywhere else) is always. It is
    looked up rather than named so the module stays importable off Linux, where the four
    services can still be constructed and driven directly for verification.
    """
    import stat as _stat

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not _stat.S_ISREG(info.st_mode):
            raise LadderError("%s is not a regular file" % path)
        if info.st_uid != 0:
            raise LadderError("%s is owned by uid %d, not root; a config a service account can "
                              "rewrite authorizes whatever it likes" % (path, info.st_uid))
        if info.st_mode & (_stat.S_IWGRP | _stat.S_IWOTH):
            raise LadderError("%s is group/other-writable" % path)
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            fd = -1  # ownership moved to the file object
            return json.load(fh)
    finally:
        if fd >= 0:
            os.close(fd)


def lease_pins(lease_path: str) -> dict:
    """The three request digests the ROOT-OWNED §4.3 lease file pins.

    Read from the very file the launcher re-hashes its held descriptors against, so the equality
    ``RecorderExecutor.run`` enforces is between the acceptance row and the LAUNCHER'S OWN pin —
    not between the acceptance row and a second copy of the same three numbers.
    """
    pins = {}
    with open(lease_path, "r", encoding="utf-8") as fh:
        for line in fh:
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            pins[key.strip()] = value.strip()
    out = {}
    for artifact in ("system", "history", "generation_config"):
        value = pins.get(artifact + "_sha256")
        if not _is_handle(value):
            raise LadderError("the lease at %s pins no %s_sha256" % (lease_path, artifact))
        out[artifact] = value
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--ladder", required=True, help="the root-owned tcb/ladder.json")
    args = ap.parse_args()
    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    # The ladder config carries the execution allowlist and the registry pin, so it is TCB and is
    # read under the same custody rules the IPC policies are. `load_allowed_peer_uid` cannot be
    # reused for it — that function answers a different question — so the check is its own.
    ladder = load_tcb_json(args.ladder)

    # ---- the two principals, each from its OWN root-owned policy ----------------------
    allowed_broker_uid = ipc_policy.load_allowed_peer_uid(
        cfg["ipc_policies"]["supervisor"], "supervisor")
    allowed_sidecar_uid = ipc_policy.load_allowed_peer_uid(
        ladder["ipc_policies"]["supervisor-sidecar"], "supervisor-sidecar")
    # `handle_connection` refuses the §2.6 collapse at the door, before a frame is read. It is
    # refused HERE too: a supervisor that would serve nothing must not bind a socket and look
    # healthy.
    if allowed_broker_uid == allowed_sidecar_uid:
        raise LadderError("§2.6 principal collapse: the sidecar uid equals the broker uid")

    # ---- the hop log: the uid the KERNEL reported for each served frame ---------------
    hop_log_path = ladder["hop_log"]

    def hop(protocol: Any, peer_uid: Any, detail: Any) -> None:
        record = {"ts_ms": int(time.time() * 1000), "protocol": protocol, "peer_uid": peer_uid,
                  "supervisor_euid": os.geteuid(), "detail": detail}
        with open(hop_log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    services = build_ladder_services(cfg, ladder, allowed_sidecar_uid=allowed_sidecar_uid,
                                     hop=hop)

    sock_path = cfg["sockets"]["supervisor"]
    if os.path.exists(sock_path):
        os.unlink(sock_path)
    listener = gss.bind_listener(sock_path)
    os.chmod(sock_path, 0o777)
    print("RESULT: ladder supervisor listening sock=%s euid=%d broker_uid=%d sidecar_uid=%d "
          "services=open,staging,evidence-request,output-read"
          % (sock_path, os.geteuid(), allowed_broker_uid, allowed_sidecar_uid), flush=True)
    hop("supervisor.start", None, {"sock": sock_path, "broker_uid": allowed_broker_uid,
                                   "sidecar_uid": allowed_sidecar_uid})

    def accept_one():
        return gss.accept_socket_conn(listener)

    # ---- §2.4's background sweep, with its startup pass -------------------------------
    # The supervisor is the principal that owns the staging root and the ledger, so it is the
    # principal that reclaims them. Without this thread the §2.4 session and byte quotas never
    # come back: `count_install_sessions` counts every row an install holds (the LIVE-count
    # tolerance is granted to `MAX_CONCURRENT_GOVERNED_TURNS` alone), so six sessions — two
    # completing turns — are the install's whole budget for the life of the deployment. That was
    # measured on this kit before the sweep existed, not inferred, and `run_ladder_turn.sh` now
    # drives a THIRD completing turn that only this thread can make possible.
    #
    # It gets its OWN connection: `sqlite3` objects belong to the thread that made them, and
    # `open_ledger` sets the busy timeout that makes two writers on one WAL file wait instead
    # of fail. It is a daemon thread because the sweep must never hold the supervisor open —
    # nothing it does is unsafe to interrupt, since the ledger commits before the unlink and
    # the next pass collects whatever a kill left behind.
    sweep_stop = threading.Event()

    def sweep_loop():
        conn = gsl.open_ledger(cfg["supervisor"]["ledger_db"])
        try:
            gsu.sweep_forever(
                conn=conn, staging_root=ladder["staging_root"], clock_ms=services.clock_ms,
                stop=sweep_stop,
                on_pass=lambda report: hop("staging.sweep", None, report.as_detail()),
            )
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    sweeper = threading.Thread(target=sweep_loop, name="staging-sweep", daemon=True)
    sweeper.start()

    try:
        gss.serve_forever(
            accept_one,
            allowed_broker_uid,
            services.config,
            services.verify_sig,
            recompute_request_sha256,
            services.clock_ms,
            ledger_conn=services.ledger_conn,
            publish_artifact=services.publish_artifact,
            read_run_evidence=services.read_run_evidence,
            sign_attestation=services.sign_attestation,
            supervisor_attestation_key_id=services.supervisor_attestation_key_id,
            open_service=services.open_service,
            staging_service=services.staging_service,
            evidence_request_service=services.evidence_service,
            output_read_service=services.output_read_service,
        )
    finally:
        sweep_stop.set()
        try:
            services.ledger_conn.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            os.unlink(sock_path)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
