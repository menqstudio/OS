"""§5 acceptance driven from §4.10(d) — the supplier, not the gate (rev-30 §5 / §6.1).

`test_governed_evidence_request.py` proves the PRE-acceptance gate and stubs what happens
after it. `test_governed_chain_e2e.py` proves the same durable ladder driven by the BROKER's
five §5 v2 wire ops. This file proves the third thing, which until now did not exist: the
production supplier `governed_acceptance.AcceptanceDriver`, reached the way production
reaches it — through the real §4.10(a0) open, the real §4.10(a)(b)(c) staging upload, and the
real §4.10(d) `EvidenceRequestService` — answering with a real §4.10(e) frame.

Everything under test is REAL: four distinct Ed25519 keypairs (challenge / registry-root /
supervisor-attestation / receipt), a root-signed `brops.challenge-key-registry.v1`, a durable
ledger on a real FILE, a content-addressed store whose handle IS the digest, the real
`challenge_authority.issue_challenge`, and the real `isolated_signer.IsolatedSigner`. The one
double is the §6.1 step-5 CONTAINED EXECUTION, which needs Linux, six service uids and a
setuid launcher; it is a typed seam and its default binding refuses (`RefusingExecutor`), so
the fixture's executor is a stand-in for a thing that genuinely cannot run here and every
test that depends on it says so by living in this file rather than in a live-kit script.
"""

import base64
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import challenge_key_registry as ckr  # noqa: E402
import governed_acceptance as gac  # noqa: E402
import governed_evidence_request as ger  # noqa: E402
import governed_output_stream as gos  # noqa: E402
import governed_staging_upload as gsu  # noqa: E402
import governed_staging_ledger as gstage  # noqa: E402
import governed_supervisor_ledger as gsl  # noqa: E402
import governed_turn_open as gto  # noqa: E402
import governed_turn_result as gtr  # noqa: E402
import isolated_signer as isg  # noqa: E402
from challenge_authority import AuthorityConfig, issue_challenge  # noqa: E402
from governed_output_read import OutputReadService  # noqa: E402
from governed_supervisor import (  # noqa: E402
    SupervisorConfig,
    SupervisorError,
    _canonical_bytes,
)

NOW = 1_700_000_000_000
SIDECAR_UID = 4242

SUPERVISOR_ID = "sup-acceptance-1"
EXECUTOR_ID = "exec-1"
BUILDER_ID = "builder-1"
CHALLENGE_KEY_ID = "chal-key-1"
ROOT_KEY_ID = "reg-root-1"
SUP_ATTEST_KEY_ID = "sup-attest-1"
RECEIPT_KEY_ID = "receipt-key-1"

SYSTEM_BYTES = b"you are a governed agent"
HISTORY_BYTES = b'[{"content":"hi","role":"user"}]'
GENCFG_BYTES = b'{"max_output_tokens":4096,"model":"claude-sonnet-5"}'
POLICY_BYTES = b"policy-bundle-bytes"
CONTAINMENT_BYTES = b'{"contained":true,"protocol":"brops.containment-evidence.v1"}'
REPLY_BYTES = b"the exact governed reply bytes the executor produced"

ARTIFACTS = (("system", SYSTEM_BYTES), ("history", HISTORY_BYTES),
             ("generation_config", GENCFG_BYTES))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class _Key:
    """One REAL Ed25519 keypair exposed as the sign/verify seams the services take."""

    def __init__(self):
        self._sk = Ed25519PrivateKey.generate()
        self._pk = self._sk.public_key()

    @property
    def public_b64(self) -> str:
        from cryptography.hazmat.primitives import serialization

        raw = self._pk.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return b64u(raw)

    def sign(self, message: bytes) -> str:
        return b64u(self._sk.sign(message))

    def verify(self, message: bytes, sig_b64: str) -> bool:
        try:
            self._pk.verify(unb64u(sig_b64), message)
            return True
        except Exception:
            return False


class _Store:
    """A real content-addressed protected store: the handle IS the digest, and a read
    re-verifies it — the property `brops_evidence_store.EvidenceStore` provides in
    production and the reason `read_artifact` may be trusted to answer by handle."""

    def __init__(self):
        self.blobs = {}

    def publish(self, data: bytes) -> str:
        handle = sha(bytes(data))
        self.blobs.setdefault(handle, bytes(data))
        return handle

    def read(self, handle) -> bytes:
        data = self.blobs.get(handle)
        if data is None:
            raise KeyError("no artifact %r" % (handle,))
        if sha(data) != handle:  # pragma: no cover - the dict is keyed by the digest
            raise ValueError("store returned bytes that are not the handle")
        return data


def build_run_evidence(output_bytes, *, head_sequence, output_sha256=None):
    """A recorder evidence chain shaped exactly like `governed_recorder` writes one.

    The supervisor derives the head from THIS and refuses a completion whose `output_handle`
    is not the `output-captured` digest (audit F-01), so a test that wants to model a lying
    executor passes an `output_sha256` that does not match the bytes.
    """
    def canon(payload):
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    payloads = [
        ("lease-validated", {"lease_sha256": sha(b"lease")}),
        ("execution-launched", {"cgroup": "cg-1"}),
        ("output-captured", {
            "launcher_exit": 0,
            "output_bytes": len(output_bytes),
            "output_sha256": output_sha256 or sha(output_bytes),
        }),
    ]
    previous, events = None, []
    for sequence, (event_type, payload) in enumerate(payloads, start=1):
        event = {
            "event_type": event_type,
            "payload": payload,
            "payload_sha256": sha(canon(payload)),
            "previous_event_hash": previous,
            "sequence": sequence,
        }
        previous = sha(canon(event))
        events.append(event)
    return json.dumps({
        "event_count": len(events),
        "events": events,
        "final_event_hash": previous,
        "head_sequence": head_sequence,
        "last_sequence": len(events),
        "protocol": "brops.run-evidence-chain.v1",
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")


class _Executor(gac.ExecutionService):
    """The §6.1 step-5 stand-in. It does exactly what the contained executor's OBSERVABLE
    effects are — the output lands in the store, the recorder writes its chain, the launcher
    reports the child running — and nothing else. It cannot be a real executor here: §2.7's
    ladder is Linux + setuid + six uids, which is why the shipped default refuses."""

    def __init__(self, case, *, output=REPLY_BYTES, fail=None, skip_started=False,
                 captured_digest=None, containment=CONTAINMENT_BYTES, preflight_error=None):
        self.case = case
        self.output = output
        self.fail = fail
        self.skip_started = skip_started
        self.captured_digest = captured_digest
        self.containment = containment
        self.preflight_error = preflight_error
        self.runs = []
        self.preflights = 0

    def preflight(self):
        self.preflights += 1
        if self.preflight_error is not None:
            raise gac.GovernedExecutionUnavailable(self.preflight_error)

    def run(self, request, on_started):
        self.runs.append(request)
        if not self.skip_started:
            on_started(gac.StartedExecution(process_group_id="4242", cgroup_id="cg-1",
                                            execution_started_marker=None))
        if self.fail is not None:
            raise self.fail
        output_handle = self.case.store.publish(self.output)
        self.case.run_evidence[request.execution_attempt_id] = build_run_evidence(
            self.output, head_sequence=self.case.next_head_sequence,
            output_sha256=self.captured_digest)
        self.case.next_head_sequence += 1
        containment_handle = self.case.store.publish(self.containment)
        return gac.ExecutionOutcome(
            output_handle=output_handle,
            containment_evidence_handle=containment_handle,
            completed_at_ms=self.case.clock,
        )


class _Case(unittest.TestCase):
    """One real ledger file, one real store, one real registry, four real keypairs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.ledger_path = str(self.base / "sup.db")
        self.conn = gsl.open_ledger(self.ledger_path)
        self.staging_root = self.base / "staging"
        self.store = _Store()
        self.clock = NOW
        self.run_evidence = {}
        self.next_head_sequence = 7
        self.minted = 0

        self.challenge_key = _Key()
        self.root_key = _Key()
        self.attest_key = _Key()
        self.receipt_key = _Key()

        self.handles = {name: self.store.publish(data) for name, data in (
            ("system", SYSTEM_BYTES), ("history", HISTORY_BYTES),
            ("generation_config", GENCFG_BYTES), ("policy_bundle", POLICY_BYTES))}
        self.registry_document = self.build_registry()
        self.executor = _Executor(self)
        self.signer_calls = []

    def _cleanup(self):
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            self.tmp.cleanup()
        except OSError:
            # Windows holds a handle on a just-closed SQLite file for a moment; the temp
            # dir is the OS's problem, not the test's verdict.
            pass

    # ---- ids ------------------------------------------------------------------
    def mint_id(self):
        self.minted += 1
        return "acc-id-%04d" % self.minted

    # ---- the registry ---------------------------------------------------------
    def build_registry(self, *, epoch=7, revoked_at=None, valid_from=1,
                       valid_to=2_000_000_000_000, key_id=CHALLENGE_KEY_ID,
                       public_key=None):
        payload = {
            "artifact_type": ckr.REGISTRY_ARTIFACT_TYPE,
            "root_key_id": ROOT_KEY_ID,
            "registry_epoch": epoch,
            "registry_issued_at_ms": 1_600_000_000_000,
            "keys": [{
                "challenge_key_id": key_id,
                "public_key": public_key or self.challenge_key.public_b64,
                "valid_from_ms": valid_from,
                "valid_to_ms": valid_to,
                "key_epoch": 2,
                "revoked": revoked_at is not None,
                "revoked_at_ms": revoked_at,
            }],
        }
        return {"payload": payload,
                "root_sig": self.root_key.sign(ckr.canonical_bytes(payload))}

    def verify_root_sig(self, message, sig, public_key):
        del public_key  # the anchor's key material is the fixture's own root key
        return self.root_key.verify(message, sig)

    def verify_challenge_sig(self, message, sig, public_key):
        # BOUND to the resolved public key: a verifier that ignored it would make every
        # registry/key refusal below decorative.
        if public_key != self.challenge_key.public_b64:
            return False
        return self.challenge_key.verify(message, sig)

    # ---- configs --------------------------------------------------------------
    def supervisor_config(self, **overrides):
        kwargs = dict(
            launcher_executable_sha256="1" * 64,
            executor_executable_sha256="2" * 64,
            id_fn=self.mint_id,
            supervisor_id=SUPERVISOR_ID,
            executor_id=EXECUTOR_ID,
            builder_id=BUILDER_ID,
            policy_id="policy-1",
            policy_version="v1",
            policy_bundle_handle=self.handles["policy_bundle"],
            challenge_registry_handle=sha(b"stale-registry-handle"),
            challenge_registry_hash=sha(b"stale-registry-hash"),
            challenge_registry_epoch=0,
            challenge_registry_root_key_id=ROOT_KEY_ID,
        )
        kwargs.update(overrides)
        return SupervisorConfig(**kwargs)

    def acceptance_config(self, *, allowlist=None, supervisor=None, epoch_floor=0):
        supervisor = supervisor or self.supervisor_config()
        return gac.AcceptanceConfig(
            supervisor=supervisor,
            open_config=gto.OpenConfig.from_supervisor_config(
                supervisor, registry_root_public_key=self.root_key.public_b64,
                registry_epoch_floor=epoch_floor),
            execution_allowlist=frozenset(
                {sha(GENCFG_BYTES)} if allowlist is None else allowlist),
        )

    def output_service(self):
        return OutputReadService(allowed_sidecar_uid=SIDECAR_UID,
                                 read_output=self.store.read)

    def signer(self, **overrides):
        kwargs = dict(
            receipt_key_id=RECEIPT_KEY_ID,
            receipt_private_key_handle="kms://receipt",
            supervisor_attestation_key_id=SUP_ATTEST_KEY_ID,
            supervisor_attestation_key_handle="kms://sup-attest",
            allowed_executor_ids={EXECUTOR_ID},
            allowed_builder_ids={BUILDER_ID},
            allowed_supervisor_ids={SUPERVISOR_ID},
            allowed_policies={("policy-1", "v1"): self.handles["policy_bundle"]},
        )
        kwargs.update(overrides)
        return isg.IsolatedSigner(
            config=isg.SignerConfig(**kwargs),
            store=self._signer_store(),
            sign_fn=lambda _handle, message: self.receipt_key.sign(message),
            verify_attestation=lambda _h, message, sig: self.attest_key.verify(message, sig),
            clock_ms=lambda: self.clock,
        )

    def _signer_store(self):
        """The signer reads the SAME protected store the supervisor publishes into."""
        store = isg.ArtifactStore()
        for handle, data in self.store.blobs.items():
            store.put(data, handle)
        return store

    def sign_result(self, sign_request):
        self.signer_calls.append(sign_request)
        return self.signer().sign_result(sign_request)

    # ---- the driver -----------------------------------------------------------
    def driver(self, **overrides):
        kwargs = dict(
            config=self.acceptance_config(),
            conn=self.conn,
            clock_ms=lambda: self.clock,
            read_artifact=self.store.read,
            publish_artifact=self.store.publish,
            resolve_registry_document=lambda: self.registry_document,
            verify_root_sig=self.verify_root_sig,
            verify_challenge_sig=self.verify_challenge_sig,
            read_run_evidence=self.run_evidence.get,
            sign_attestation=self.attest_key.sign,
            supervisor_attestation_key_id=SUP_ATTEST_KEY_ID,
            sign_result=self.sign_result,
            output_read_service=self.output_service(),
            execution=self.executor,
        )
        kwargs.update(overrides)
        return gac.AcceptanceDriver(**kwargs)

    # ---- walking a turn to INPUTS_READY through the REAL protocols -------------
    def challenge_document(self, *, nonce="550e8400-e29b-41d4-a716-446655440000",
                           run_id="run-1", task_id="task-1", requested_at=None,
                           issued=None, gencfg=GENCFG_BYTES):
        row = {
            "run_id": run_id,
            "task_id": task_id,
            "workspace_id": "ws-1",
            "install_id": "install-1",
            "request_nonce": nonce,
            "system_sha256": sha(SYSTEM_BYTES),
            "history_sha256": sha(HISTORY_BYTES),
            "generation_config_sha256": sha(gencfg),
            "requested_at_ms": NOW - 5_000 if requested_at is None else requested_at,
        }
        return issue_challenge(
            row,
            AuthorityConfig(install_id="install-1", challenge_key_id=CHALLENGE_KEY_ID, supervisor_id=SUPERVISOR_ID),
            self.challenge_key.sign,
            (lambda: NOW) if issued is None else (lambda: issued),
        )

    def open_turn(self, document=None, *, config=None):
        """Drive the REAL §4.10(a0) open: publishes the exact signed document and creates
        the `governed_turn_staging` row. Nothing below fabricates that row."""
        document = document or self.challenge_document()
        service = gto.OpenService(
            config=(config or self.acceptance_config()).open_config,
            allowed_sidecar_uid=SIDECAR_UID,
            publish_document=self.store.publish,
            resolve_registry_document=lambda: self.registry_document,
            verify_root_sig=self.verify_root_sig,
            verify_challenge_sig=self.verify_challenge_sig,
        )
        reply = service.handle({
            "protocol": gto.OPEN_PROTOCOL,
            "install_id": document["payload"]["install_id"],
            "request_nonce": document["payload"]["request_nonce"],
            "challenge_doc_b64": b64u(_canonical_bytes(document)),
        }, peer_uid=SIDECAR_UID, conn=self.conn, clock_ms=lambda: self.clock)
        self.assertEqual(reply.get("status"), "opened", reply)
        return document, reply["challenge_handle"]

    def upload_all(self, document, *, gencfg=GENCFG_BYTES):
        """Drive the REAL §4.10(a)(b)(c) upload of all three inputs to INPUTS_READY."""
        service = gsu.StagingService(
            allowed_sidecar_uid=SIDECAR_UID,
            staging_root=str(self.staging_root),
            publish_artifact=self.store.publish,
        )

        def call(body):
            return service.handle(body, peer_uid=SIDECAR_UID, conn=self.conn,
                                  clock_ms=lambda: self.clock)

        payload = document["payload"]
        handle = sha(_canonical_bytes(document))
        for artifact, data in (("system", SYSTEM_BYTES), ("history", HISTORY_BYTES),
                               ("generation_config", gencfg)):
            opened = call({
                "protocol": gsu.STAGING_OPEN_PROTOCOL,
                "install_id": payload["install_id"],
                "challenge_handle": handle,
                "request_nonce": payload["request_nonce"],
                "artifact": artifact,
                "declared_len": len(data),
                "declared_sha256": sha(data),
            })
            self.assertEqual(opened["status"], "opened", opened)
            ack = call({
                "protocol": gsu.STAGING_CHUNK_PROTOCOL,
                "staging_session_id": opened["staging_session_id"],
                "seq": 0, "bytes_b64": b64u(data),
            })
            self.assertEqual(ack["status"], "ack", ack)
            published = call({"protocol": gsu.STAGING_FINAL_PROTOCOL,
                              "staging_session_id": opened["staging_session_id"], "seq": 1})
            self.assertEqual(published["status"], "published", published)

    def ready_turn(self, **kwargs):
        gencfg = kwargs.pop("gencfg", GENCFG_BYTES)
        document, handle = self.open_turn(self.challenge_document(gencfg=gencfg, **kwargs))
        self.upload_all(document, gencfg=gencfg)
        row = gstage.load_staging(self.conn, document["payload"]["install_id"],
                               document["payload"]["request_nonce"])
        self.assertEqual(row["state"], gstage.INPUTS_READY)
        return document, handle

    # ---- the message under test -----------------------------------------------
    def trigger(self, document, *, driver=None):
        """Send the REAL §4.10(d) frame through the REAL front door, with the driver
        supplied as `drive_acceptance` exactly as a deployment would supply it."""
        payload = document["payload"]
        service = ger.EvidenceRequestService(
            allowed_sidecar_uid=SIDECAR_UID,
            drive_acceptance=driver or self.driver(),
        )
        return service.handle({
            "protocol": ger.EVIDENCE_REQUEST_PROTOCOL,
            "install_id": payload["install_id"],
            "challenge_handle": sha(_canonical_bytes(document)),
            "request_nonce": payload["request_nonce"],
        }, peer_uid=SIDECAR_UID, conn=self.conn)

    def run_turn(self, **kwargs):
        driver = kwargs.pop("driver", None)
        document, _handle = self.ready_turn(**kwargs)
        return document, self.trigger(document, driver=driver)

    def acceptance_row(self, document):
        return gsl.load_acceptance_by_challenge(self.conn, sha(_canonical_bytes(document)))

    def assertRefused(self, reply, reason):
        self.assertEqual(reply.get("protocol"), gtr.GOVERNED_TURN_RESULT_PROTOCOL, reply)
        self.assertEqual(reply.get("status"), gtr.STATUS_REFUSED, reply)
        self.assertEqual(reply.get("reason"), reason, reply)
        gtr.validate_turn_result(reply)
        return reply


# ---------------------------------------------------------------------------
# The whole round trip
# ---------------------------------------------------------------------------


class TheGovernedRoundTripTests(_Case):

    def test_an_admitted_turn_becomes_a_signed_4_10_e_verdict(self):
        document, reply = self.run_turn()

        self.assertEqual(reply["protocol"], gtr.GOVERNED_TURN_RESULT_PROTOCOL)
        self.assertEqual(reply["status"], gtr.STATUS_SIGNED)
        gtr.validate_turn_result(reply)

        # (1) the receipt signature verifies under the receipt key over JCS(payload)
        payload = json.loads(unb64u(reply["envelope_jcs_b64"]).decode("utf-8"))
        self.assertTrue(
            self.receipt_key.verify(unb64u(reply["envelope_jcs_b64"]), reply["signature_b64"]),
            "the envelope signature must verify over the exact transported bytes")
        # (2) the attestation covers the exact attested bytes the frame carries
        evidence_jcs = unb64u(reply["attestation_evidence_jcs_b64"])
        self.assertTrue(self.attest_key.verify(evidence_jcs, reply["attestation_signature_b64"]))
        self.assertEqual(payload["attestation_evidence_sha256"], sha(evidence_jcs))
        # (3) the output is bound by digest AND length to the bytes execution produced
        self.assertEqual(payload["output_sha256"], sha(REPLY_BYTES))
        self.assertEqual(payload["output_bytes"], len(REPLY_BYTES))
        self.assertEqual(reply["output_sha256"], payload["output_sha256"])
        self.assertEqual(reply["output_bytes"], payload["output_bytes"])
        # (4) the ids are the supervisor's own durable ones
        row = self.acceptance_row(document)
        self.assertEqual(reply["execution_attempt_id"], row["execution_attempt_id"])
        self.assertEqual(reply["receipt_id"], row["receipt_id"])
        self.assertEqual(reply["lease_id"], row["lease_id"])
        self.assertEqual(reply["run_id"], "run-1")
        # `key_id` is the isolated signer's own receipt key, relayed out of the payload the
        # signature covers - never the supervisor's attestation key id, which travels in its
        # own field.
        self.assertEqual(reply["key_id"], payload["key_id"])
        self.assertEqual(reply["key_id"], RECEIPT_KEY_ID)
        self.assertEqual(reply["supervisor_attestation_key_id"], SUP_ATTEST_KEY_ID)
        self.assertNotEqual(reply["key_id"], reply["supervisor_attestation_key_id"])
        # (5) the §4.10(f) capability is the one minted at completion
        stream = gos.load_stream_for_attempt(self.conn, row["execution_attempt_id"])
        self.assertEqual(reply["output_stream_id"], stream["output_stream_id"])
        # (6) the containment artifact rides the frame, base64url of the exact bytes
        self.assertEqual(unb64u(reply["containment_evidence_b64"]), CONTAINMENT_BYTES)
        # (7) the turn ends COMPLETED
        self.assertEqual(row["state"], gsl.COMPLETED)

    def test_the_executor_is_handed_the_supervisor_s_own_lease_and_pins(self):
        document, _reply = self.run_turn()
        row = self.acceptance_row(document)
        self.assertEqual(len(self.executor.runs), 1)
        request = self.executor.runs[0]
        self.assertEqual(request.execution_attempt_id, row["execution_attempt_id"])
        self.assertEqual(request.lease_id, row["lease_id"])
        self.assertEqual(request.lease_expires_at_ms, row["lease_expires_at_ms"])
        self.assertEqual(request.launcher_executable_sha256, "1" * 64)
        self.assertEqual(request.executor_executable_sha256, "2" * 64)
        self.assertEqual(request.generation_config_handle, sha(GENCFG_BYTES))

    def test_the_signer_is_handed_the_exact_attested_bytes(self):
        """§5(f): the evidence is PARSED from the `evidence_jcs` the supervisor signed, never
        rebuilt beside it, so the signer's re-hash is over identical bytes by construction."""
        _document, reply = self.run_turn()
        self.assertEqual(len(self.signer_calls), 1)
        request = self.signer_calls[0]
        self.assertEqual(request["protocol"], isg.SIGN_REQUEST_PROTOCOL)
        self.assertEqual(set(request), {"protocol", "attestation", "evidence"})
        rebuilt = json.dumps(request["evidence"], sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        self.assertEqual(rebuilt, unb64u(reply["attestation_evidence_jcs_b64"]))


# ---------------------------------------------------------------------------
# What is minted here, and only here
# ---------------------------------------------------------------------------


class WhatThisSeamMintsTests(_Case):

    def test_the_execution_attempt_id_exists_for_the_first_time_at_the_acceptance_cas(self):
        """§4.10(d): the trigger "carries **no** execution_attempt_id (the supervisor
        reserves it, §5)". §5 step 4: "reserve execution_attempt_id"."""
        document, handle = self.ready_turn()
        # Before the trigger: the staging row exists, and it has no such column at all.
        staging = gstage.load_staging(self.conn, "install-1", document["payload"]["request_nonce"])
        self.assertNotIn("execution_attempt_id", staging.keys())
        self.assertIsNone(gsl.load_acceptance_by_challenge(self.conn, handle))
        reply = self.trigger(document)
        self.assertEqual(reply["status"], gtr.STATUS_SIGNED)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM governed_turn_acceptance").fetchone()[0], 1)

    def test_the_acceptance_clock_is_read_exactly_once_and_is_the_persisted_instant(self):
        """§5 step 2: "read the supervisor clock **exactly once** →
        challenge_accepted_at_ms". The lease window, the §5 step-3 predicate and the row must
        all be the SAME number, not three reads that happened to agree."""
        reads = []

        def clock():
            reads.append(NOW + len(reads))  # a MOVING clock: a second read is visible
            return reads[-1]

        document, _handle = self.ready_turn()
        driver = self.driver(clock_ms=clock)
        reply = self.trigger(document, driver=driver)
        self.assertEqual(reply["status"], gtr.STATUS_SIGNED)
        row = self.acceptance_row(document)
        self.assertEqual(row["challenge_accepted_at_ms"], NOW)
        self.assertEqual(row["lease_issued_at_ms"], NOW)
        self.assertEqual(row["lease_expires_at_ms"], NOW + gsl.LEASE_DURATION_MS)

    def test_the_nonce_is_consumed_by_the_acceptance_cas_and_nowhere_earlier(self):
        """§4.10(a0) "does NOT consume the nonce"; §5 step 4's CAS is the consume, enforced
        by `UNIQUE (install_id, request_nonce)` on the acceptance table."""
        document, _handle = self.ready_turn()
        nonce = document["payload"]["request_nonce"]
        self.assertIsNone(gsl.load_lease_by_nonce(self.conn, "install-1", nonce))
        self.trigger(document)
        self.assertIsNotNone(gsl.load_lease_by_nonce(self.conn, "install-1", nonce))

    def test_the_acceptance_row_records_the_acceptance_time_registry_not_the_config_constant(self):
        """§5 step 3: "Bind this exact **acceptance-time** challenge_registry_handle/_hash/
        _epoch/_root_key_id into the acceptance row". The fixture's SupervisorConfig carries
        deliberately WRONG constants, so a driver that copied them would be caught here."""
        document, _reply = self.run_turn()
        row = self.acceptance_row(document)
        snapshot, _ = ckr.resolve_registry(
            self.registry_document, anchor=self.acceptance_config().open_config.anchor(),
            epoch_floor=0, verify_root_sig=self.verify_root_sig)
        self.assertEqual(row["challenge_registry_epoch"], snapshot.registry_epoch)
        self.assertEqual(row["challenge_registry_handle"], snapshot.registry_handle)
        self.assertEqual(row["challenge_registry_hash"], snapshot.registry_hash)
        self.assertNotEqual(row["challenge_registry_epoch"], 0)
        self.assertEqual(row["challenge_registry_root_key_id"], ROOT_KEY_ID)


# ---------------------------------------------------------------------------
# §5 steps 10-12: a second trigger is idempotent, never a second execution
# ---------------------------------------------------------------------------


class IdempotenceTests(_Case):

    def test_a_second_trigger_for_a_completed_turn_returns_the_identical_frame(self):
        """§5 step 11: "A COMPLETED retry returns **only** the same attempt's independently
        re-verified terminal record/result (idempotent)"."""
        document, first = self.run_turn()
        second = self.trigger(document)
        self.assertEqual(first, second)
        self.assertEqual(len(self.executor.runs), 1, "a retry must not execute again")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM governed_turn_acceptance").fetchone()[0], 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM governed_output_streams").fetchone()[0], 1)

    def test_a_retry_re_reads_the_output_token_and_never_re_mints_it(self):
        """§4.10(f): "a COMPLETED retry **re-reads, never re-mints**" the token."""
        document, first = self.run_turn()
        second = self.trigger(document)
        self.assertEqual(first["output_stream_id"], second["output_stream_id"])

    def test_a_trigger_arriving_at_a_started_attempt_moves_to_recovery_required(self):
        """§5 step 10, LOCKED: "once EXECUTION_STARTING is durable the attempt is NEVER
        automatically relaunched … A restart finding EXECUTION_STARTING or EXECUTING without
        complete terminal proof moves to RECOVERY_REQUIRED (fail-closed)"."""
        document, _handle = self.ready_turn()
        executor = _Executor(self, fail=RuntimeError("boom"), skip_started=True)
        # First trigger: the gate CASes to EXECUTION_STARTING, the seam then fails.
        self.assertRefused(self.trigger(document, driver=self.driver(execution=executor)),
                           "not_completed")
        row = self.acceptance_row(document)
        self.assertEqual(row["state"], gsl.RECOVERY_REQUIRED)
        # Second trigger: terminal, still no relaunch.
        fresh = _Executor(self)
        self.assertRefused(self.trigger(document, driver=self.driver(execution=fresh)),
                           "not_completed")
        self.assertEqual(fresh.runs, [])

    def test_an_attempt_left_in_executing_by_a_crash_is_never_relaunched(self):
        """A row genuinely left in `EXECUTING`. The executor confirms the child started (so
        the ledger commits `EXECUTING`) and the process is then killed - modelled with a
        `BaseException`, which the driver's `except Exception` deliberately does not catch,
        so nothing advances the row and the durable state is exactly what a crash leaves.
        Then, per s5, the next trigger moves it to `RECOVERY_REQUIRED` and never relaunches."""
        document, _handle = self.ready_turn()

        class _Killed(_Executor):
            def run(self, request, on_started):
                self.runs.append(request)
                on_started(gac.StartedExecution(process_group_id="7", cgroup_id="cg-1"))
                raise KeyboardInterrupt("the host went away mid-run")

        crashed = _Killed(self)
        with self.assertRaises(KeyboardInterrupt):
            self.trigger(document, driver=self.driver(execution=crashed))
        self.assertEqual(self.acceptance_row(document)["state"], gsl.EXECUTING)

        fresh = _Executor(self)
        self.assertRefused(self.trigger(document, driver=self.driver(execution=fresh)),
                           "not_completed")
        self.assertEqual(fresh.runs, [], "a crashed attempt must never be relaunched")
        self.assertEqual(self.acceptance_row(document)["state"], gsl.RECOVERY_REQUIRED)


# ---------------------------------------------------------------------------
# Every governed refusal, reachable BY NAME
# ---------------------------------------------------------------------------


class RefusalsAreReachableTests(_Case):

    # ---- pre-record ---------------------------------------------------------
    def test_platform_unsupported_when_no_contained_executor_is_provisioned(self):
        """The SHIPPED default. §4.5 makes this a pre-record Block: no row, no lease."""
        document, handle = self.ready_turn()
        driver = self.driver(execution=gac.RefusingExecutor())
        self.assertRefused(self.trigger(document, driver=driver), "platform_unsupported")
        self.assertIsNone(gsl.load_acceptance_by_challenge(self.conn, handle))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM governed_turn_acceptance").fetchone()[0], 0)

    def test_platform_unsupported_creates_no_row_so_the_challenge_survives(self):
        document, _handle = self.ready_turn()
        self.assertRefused(
            self.trigger(document, driver=self.driver(execution=gac.RefusingExecutor())),
            "platform_unsupported")
        # The SAME signed challenge is still usable once execution is provisioned.
        self.assertEqual(self.trigger(document)["status"], gtr.STATUS_SIGNED)

    def test_handle_missing_when_the_published_challenge_document_is_gone(self):
        document, handle = self.ready_turn()
        del self.store.blobs[handle]
        self.assertRefused(self.trigger(document), "handle_missing")

    def test_handle_missing_when_the_store_answers_with_other_bytes(self):
        """The digest is re-derived here rather than trusted from the seam."""
        document, _handle = self.ready_turn()
        driver = self.driver(read_artifact=lambda h: b"not the document")
        self.assertRefused(self.trigger(document, driver=driver), "handle_missing")

    # MARKED: the two `malformed` branches of `_load_challenge` are NOT reachable from
    # anything a hostile sidecar can send. The driver re-derives `sha256(bytes) ==
    # challenge_handle` first, so reaching the decode with non-document bytes needs a staging
    # row whose `challenge_handle` addresses those bytes - i.e. TAMPERED durable state
    # (`governed_turn_staging` is 0700 supervisor-only), or a preimage. They exist because a
    # supervisor must answer rather than raise on its own store's contents, and they are
    # driven here the only way they can be driven.
    def _plant_staging_for(self, blob, *, nonce="planted-nonce"):
        handle = self.store.publish(blob)
        gstage.open_staging(self.conn, gstage.NewStaging(
            install_id="install-1", request_nonce=nonce, challenge_handle=handle,
            run_id="run-1", task_id="task-1", workspace_id="ws-1",
            system_sha256=sha(SYSTEM_BYTES), history_sha256=sha(HISTORY_BYTES),
            generation_config_sha256=sha(GENCFG_BYTES),
            challenge_expires_at_ms=NOW + 30_000), NOW)
        self._make_ready(handle, nonce)
        return handle

    def _trigger_handle(self, handle, nonce):
        service = ger.EvidenceRequestService(allowed_sidecar_uid=SIDECAR_UID,
                                             drive_acceptance=self.driver())
        return service.handle({
            "protocol": ger.EVIDENCE_REQUEST_PROTOCOL, "install_id": "install-1",
            "challenge_handle": handle, "request_nonce": nonce,
        }, peer_uid=SIDECAR_UID, conn=self.conn)

    def _make_ready(self, handle, nonce):
        """Walk a planted staging row to INPUTS_READY through the REAL upload handlers."""
        service = gsu.StagingService(allowed_sidecar_uid=SIDECAR_UID,
                                     staging_root=str(self.staging_root),
                                     publish_artifact=self.store.publish)

        def call(body):
            return service.handle(body, peer_uid=SIDECAR_UID, conn=self.conn,
                                  clock_ms=lambda: self.clock)

        for artifact, data in ARTIFACTS:
            opened = call({"protocol": gsu.STAGING_OPEN_PROTOCOL, "install_id": "install-1",
                           "challenge_handle": handle, "request_nonce": nonce,
                           "artifact": artifact, "declared_len": len(data),
                           "declared_sha256": sha(data)})
            self.assertEqual(opened["status"], "opened", opened)
            call({"protocol": gsu.STAGING_CHUNK_PROTOCOL,
                  "staging_session_id": opened["staging_session_id"], "seq": 0,
                  "bytes_b64": b64u(data)})
            call({"protocol": gsu.STAGING_FINAL_PROTOCOL,
                  "staging_session_id": opened["staging_session_id"], "seq": 1})

    def test_malformed_when_the_stored_challenge_document_does_not_decode(self):
        handle = self._plant_staging_for(b"{not json")
        self.assertRefused(self._trigger_handle(handle, "planted-nonce"), "malformed")

    def test_hash_mismatch_when_the_stored_document_is_not_canonical(self):
        """The canonicality gate, stated as the equality that actually matters. A stored
        document that is valid JSON but NOT `canonical_bytes({payload, sig})` hashes to one
        digest while `accept_open`'s `challenge_handle_for` computes another, and §4.10(d)'s
        join of the staging row to its acceptance row would then be over two digests of one
        turn. MARKED: like the two `malformed` branches, reachable only from tampered durable
        state - §4.10(a0)'s own canonicality gate refuses this document at the door."""
        document = self.challenge_document(nonce="non-canonical-nonce")
        loose = json.dumps(document, sort_keys=True, separators=(", ", ": ")).encode("utf-8")
        self.assertNotEqual(loose, _canonical_bytes(document))
        self.assertEqual(json.loads(loose.decode("utf-8")), document)
        handle = self._plant_staging_for(loose, nonce="non-canonical-nonce")
        self.assertRefused(self._trigger_handle(handle, "non-canonical-nonce"),
                           "hash_mismatch")

    def test_malformed_when_the_stored_document_is_not_payload_sig(self):
        blob = json.dumps({"nope": 1}, sort_keys=True, separators=(",", ":")).encode()
        handle = self._plant_staging_for(blob, nonce="planted-nonce-2")
        self.assertRefused(self._trigger_handle(handle, "planted-nonce-2"), "malformed")

    # ---- §5 step 3: the acceptance-time predicate ----------------------------
    def test_challenge_invalidated_when_the_key_was_revoked_between_open_and_acceptance(self):
        """§5 step 3: "A key revoked/removed or a registry rotated between open and
        acceptance is refused here (`challenge_invalidated`)"."""
        document, _handle = self.ready_turn()
        self.registry_document = self.build_registry(epoch=8, revoked_at=NOW - 1)
        self.assertRefused(self.trigger(document), "challenge_invalidated")

    def test_challenge_invalidated_when_the_key_is_revoked_between_issue_and_acceptance(self):
        """The instant the predicate is applied AT is `challenge_accepted_at_ms`, not
        `challenge_issued_at_ms`. A key revoked strictly BETWEEN the two is usable by
        §4.10(a0)'s open-time preliminary check and unusable here, which is the entire reason
        §5 step 3 exists as a separate predicate."""
        document, _handle = self.ready_turn()
        self.registry_document = self.build_registry(epoch=8, revoked_at=NOW + 5_000)
        # As of `challenge_issued_at_ms` (NOW) the key is still live...
        snapshot, _ = ckr.resolve_registry(
            self.registry_document, anchor=self.acceptance_config().open_config.anchor(),
            epoch_floor=0, verify_root_sig=self.verify_root_sig)
        self.assertIsNotNone(ckr.select_key(snapshot, CHALLENGE_KEY_ID, NOW)[0])
        # ...and as of `challenge_accepted_at_ms` it is not.
        self.clock = NOW + 10_000
        self.assertRefused(self.trigger(document), "challenge_invalidated")
        self.assertEqual(self.executor.runs, [])

    def test_the_registry_is_re_resolved_for_every_acceptance(self):
        """§5 step 3: "a fresh `load_trusted_keys`-style reload + floor — do NOT reuse the
        open-time snapshot". A driver that resolved once and cached would serve a second turn
        under key material that has since been revoked."""
        first, _ = self.ready_turn()
        self.assertEqual(self.trigger(first)["status"], gtr.STATUS_SIGNED)
        # The second turn is OPENED and staged under the live registry, exactly as the first
        # was; the rotation happens between its open and its acceptance.
        second, _ = self.ready_turn(nonce="6ba7b814-9dad-11d1-80b4-00c04fd430c8")
        self.registry_document = self.build_registry(epoch=8, revoked_at=NOW - 1)
        self.assertRefused(self.trigger(second), "challenge_invalidated")

    def test_challenge_invalidated_when_the_key_left_the_snapshot(self):
        document, _handle = self.ready_turn()
        self.registry_document = self.build_registry(epoch=8, key_id="a-different-key")
        self.assertRefused(self.trigger(document), "challenge_invalidated")

    def test_challenge_invalidated_when_the_registry_cannot_be_resolved(self):
        document, _handle = self.ready_turn()
        driver = self.driver(resolve_registry_document=lambda: {"payload": "junk"})
        self.assertRefused(self.trigger(document, driver=driver), "challenge_invalidated")

    def test_challenge_invalidated_when_the_registry_resolver_raises(self):
        document, _handle = self.ready_turn()

        def boom():
            raise RuntimeError("registry unreadable")

        driver = self.driver(resolve_registry_document=boom)
        self.assertRefused(self.trigger(document, driver=driver), "challenge_invalidated")

    def test_challenge_invalidated_when_the_acceptance_time_key_no_longer_verifies(self):
        """The signature is re-checked under the key the ACCEPTANCE-TIME snapshot selected."""
        document, _handle = self.ready_turn()
        impostor = _Key()
        self.registry_document = self.build_registry(epoch=8,
                                                     public_key=impostor.public_b64)
        self.assertRefused(self.trigger(document), "challenge_invalidated")

    def test_challenge_invalidated_when_the_registry_rolled_back_below_the_floor(self):
        document, _handle = self.ready_turn()
        config = self.acceptance_config(epoch_floor=9)
        self.assertRefused(self.trigger(document, driver=self.driver(config=config)),
                           "challenge_invalidated")

    def test_timestamp_invalid_when_the_challenge_expired_before_acceptance(self):
        """§4.5: "timestamp_invalid additionally covers an **acceptance-time challenge-window
        expiry**", distinct from §4.10(a0)'s pre-row `challenge_expired`."""
        document, _handle = self.ready_turn()
        expires = document["payload"]["challenge_expires_at_ms"]
        self.clock = expires + 1
        self.assertRefused(self.trigger(document), "timestamp_invalid")

    def test_the_expiry_boundary_admits_the_exact_instant(self):
        document, _handle = self.ready_turn()
        self.clock = document["payload"]["challenge_expires_at_ms"]
        self.assertEqual(self.trigger(document)["status"], gtr.STATUS_SIGNED)

    def test_timestamp_invalid_when_the_challenge_was_issued_after_acceptance(self):
        """The limb `accept_open` does NOT own: challenge_issued_at_ms <= accepted."""
        document, _handle = self.ready_turn(issued=NOW + 10_000)
        self.clock = NOW + 9_999
        self.assertRefused(self.trigger(document), "timestamp_invalid")
        self.assertEqual(self.executor.runs, [], "refused at acceptance, before any launch")

    def test_timestamp_invalid_when_the_request_postdates_its_own_acceptance(self):
        """The other limb `accept_open` does NOT own: requested_at_ms <= accepted.

        The `runs == []` assertion is the whole point of checking it HERE. The isolated
        signer ALSO refuses this turn `timestamp_invalid` at §6.1 step 12 — its own
        `_check_timestamps` catches the same disorder — so a test that only asserted the
        reason would pass with this limb deleted and would be proving the SIGNER's check,
        not this one. §5 step 3 requires the refusal at acceptance: before a lease, before a
        launch, before a model call."""
        document, _handle = self.ready_turn(requested_at=NOW + 5_000)
        self.assertRefused(self.trigger(document), "timestamp_invalid")
        self.assertEqual(self.executor.runs, [], "refused at acceptance, before any launch")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM governed_turn_completion").fetchone()[0], 0)

    def test_hash_mismatch_when_the_request_digest_does_not_re_derive(self):
        document, _handle = self.ready_turn()
        driver = self.driver(recompute_request_sha256=lambda payload: "f" * 64)
        self.assertRefused(self.trigger(document, driver=driver), "hash_mismatch")

    def test_identity_denied_when_the_challenge_names_another_supervisor(self):
        row = {
            "run_id": "run-1", "task_id": "task-1", "workspace_id": "ws-1",
            "install_id": "install-1", "request_nonce": "nonce-other-supervisor",
            "system_sha256": sha(SYSTEM_BYTES), "history_sha256": sha(HISTORY_BYTES),
            "generation_config_sha256": sha(GENCFG_BYTES), "requested_at_ms": NOW - 5_000,
        }
        document = issue_challenge(
            row, AuthorityConfig(
                                 install_id="install-1",challenge_key_id=CHALLENGE_KEY_ID,
                                 supervisor_id="a-different-supervisor"),
            self.challenge_key.sign, lambda: NOW)
        # §4.10(a0) refuses this at open, so the staging row is planted the only other way a
        # supervisor could ever hold one — and the acceptance-time check still refuses it.
        handle = sha(_canonical_bytes(document))
        self.store.publish(_canonical_bytes(document))
        gstage.open_staging(self.conn, gstage.NewStaging(
            install_id="install-1", request_nonce=row["request_nonce"],
            challenge_handle=handle, run_id="run-1", task_id="task-1", workspace_id="ws-1",
            system_sha256=sha(SYSTEM_BYTES), history_sha256=sha(HISTORY_BYTES),
            generation_config_sha256=sha(GENCFG_BYTES),
            challenge_expires_at_ms=document["payload"]["challenge_expires_at_ms"]), NOW)
        self.upload_all(document)
        self.assertRefused(self.trigger(document), "identity_denied")

    # ---- §2 / §4.5: the execution allowlist ---------------------------------
    def test_model_profile_unknown_blocks_the_row_and_issues_no_lease(self):
        """§4.5: "a **pre-launch acceptance Block** (BLOCKED; no lease is issued, no launch)"."""
        document, _handle = self.ready_turn()
        driver = self.driver(config=self.acceptance_config(allowlist=frozenset()))
        self.assertRefused(self.trigger(document, driver=driver), "model_profile_unknown")
        row = self.acceptance_row(document)
        self.assertEqual(row["state"], gsl.BLOCKED)
        self.assertIsNone(row["lease_handle"])
        self.assertEqual(row["failure_reason"], "model_profile_unknown")
        self.assertEqual(self.executor.runs, [])

    def test_a_blocked_attempt_re_serves_its_own_reason(self):
        document, _handle = self.ready_turn()
        driver = self.driver(config=self.acceptance_config(allowlist=frozenset()))
        self.trigger(document, driver=driver)
        self.assertRefused(self.trigger(document, driver=driver), "model_profile_unknown")

    def test_a_blocked_row_with_an_off_contract_reason_falls_back_to_not_completed(self):
        document, _handle = self.ready_turn()
        driver = self.driver(config=self.acceptance_config(allowlist=frozenset()))
        self.trigger(document, driver=driver)
        self.conn.execute(
            "UPDATE governed_turn_acceptance SET failure_reason = 'something-else'")
        self.assertRefused(self.trigger(document, driver=driver), "not_completed")

    def test_an_allowlisted_profile_proceeds(self):
        document, reply = self.run_turn()
        self.assertEqual(reply["status"], gtr.STATUS_SIGNED)
        self.assertEqual(self.acceptance_row(document)["generation_config_handle"],
                         sha(GENCFG_BYTES))

    # ---- §5 steps 6-8a: lease and gate --------------------------------------
    def test_lease_not_ready_when_the_lease_document_cannot_be_published(self):
        """§4.5 pins this member to this hop: "the execute trigger (§4.10(d)) arrives before
        the row reaches LEASE_READY"."""
        document, _handle = self.ready_turn()
        calls = []

        def publish(data):
            calls.append(data)
            if len(calls) == 1:
                raise OSError("store is read-only")
            return self.store.publish(data)

        self.assertRefused(self.trigger(document, driver=self.driver(publish_artifact=publish)),
                           "lease_not_ready")
        self.assertEqual(self.acceptance_row(document)["state"], gsl.ACCEPTED_PREPARED)

    def test_hash_mismatch_when_the_published_lease_does_not_re_hash(self):
        document, _handle = self.ready_turn()
        driver = self.driver(publish_artifact=lambda data: "0" * 64)
        self.assertRefused(self.trigger(document, driver=driver), "hash_mismatch")

    def test_lease_expired_when_the_launch_gate_has_too_little_budget(self):
        """§5 step 8a: exact-180000 remaining PROCEEDS, 179999 refuses. The driver reads the
        clock again at the gate, so moving it between acceptance and the gate is the real
        shape of this failure."""
        document, _handle = self.ready_turn()
        reads = []

        def clock():
            reads.append(1)
            if len(reads) == 1:
                return NOW  # acceptance: lease is NOW .. NOW+210000
            return NOW + gsl.LEASE_DURATION_MS - gsl.MIN_LAUNCH_REMAINING_MS + 1

        self.assertRefused(self.trigger(document, driver=self.driver(clock_ms=clock)),
                           "lease_expired")
        self.assertEqual(self.acceptance_row(document)["state"], gsl.EXPIRED)

    def test_the_launch_gate_boundary_proceeds_at_exactly_min_launch_remaining(self):
        document, _handle = self.ready_turn()
        reads = []

        def clock():
            reads.append(1)
            if len(reads) == 1:
                return NOW
            return NOW + gsl.LEASE_DURATION_MS - gsl.MIN_LAUNCH_REMAINING_MS

        reply = self.trigger(document, driver=self.driver(clock_ms=clock))
        self.assertEqual(reply["status"], gtr.STATUS_SIGNED, reply)

    def test_an_expired_attempt_stays_expired_on_a_retry(self):
        document, _handle = self.ready_turn()
        reads = []

        def clock():
            reads.append(1)
            return NOW if len(reads) == 1 else NOW + gsl.LEASE_DURATION_MS + 1

        self.assertRefused(self.trigger(document, driver=self.driver(clock_ms=clock)),
                           "lease_expired")
        self.assertRefused(self.trigger(document), "lease_expired")
        self.assertEqual(self.executor.runs, [])

    # ---- §5 step 11: completion ---------------------------------------------
    def test_hash_mismatch_when_the_run_reports_output_the_recorder_did_not_capture(self):
        """The F-01 wall, at this seam: the reply digest the run reports must be the digest
        the RECORDER's own evidence chain committed to."""
        document, _handle = self.ready_turn()
        executor = _Executor(self, captured_digest=sha(b"a different reply"))
        self.assertRefused(self.trigger(document, driver=self.driver(execution=executor)),
                           "hash_mismatch")

    def test_malformed_when_the_recorder_wrote_no_evidence_chain(self):
        document, _handle = self.ready_turn()
        driver = self.driver(read_run_evidence=lambda attempt: None)
        self.assertRefused(self.trigger(document, driver=driver), "malformed")

    def test_stale_evidence_when_the_head_is_below_the_durable_floor(self):
        first, _ = self.ready_turn()
        self.next_head_sequence = 99
        self.assertEqual(self.trigger(first)["status"], gtr.STATUS_SIGNED)
        second, _ = self.ready_turn(nonce="6ba7b810-9dad-11d1-80b4-00c04fd430c8")
        self.next_head_sequence = 3
        self.assertRefused(self.trigger(second), "stale_evidence")

    def test_evidence_fork_when_one_head_is_claimed_twice(self):
        first, _ = self.ready_turn()
        self.assertEqual(self.trigger(first)["status"], gtr.STATUS_SIGNED)
        second, _ = self.ready_turn(nonce="6ba7b811-9dad-11d1-80b4-00c04fd430c8")
        self.next_head_sequence = 7  # the head the first turn already recorded
        # DIFFERENT chain content under the SAME head - a fork. An identical chain at the
        # same head is the idempotent re-anchor and is not one, which is why the output has
        # to differ for this test to be about what it says it is about.
        self.executor = _Executor(self, output=b"a different governed reply")
        self.assertRefused(self.trigger(second), "evidence_fork")

    def test_not_completed_when_the_execution_seam_fails(self):
        document, _handle = self.ready_turn()
        executor = _Executor(self, fail=RuntimeError("launcher exited 1"))
        self.assertRefused(self.trigger(document, driver=self.driver(execution=executor)),
                           "not_completed")
        self.assertEqual(self.acceptance_row(document)["state"], gsl.RECOVERY_REQUIRED)

    def test_not_completed_when_the_launcher_never_confirmed_the_child_started(self):
        """§5's single STARTING->EXECUTING trigger: without the launcher's confirmation the
        completion CAS has no legal predecessor, so nothing is recorded."""
        document, _handle = self.ready_turn()
        executor = _Executor(self, skip_started=True)
        self.assertRefused(self.trigger(document, driver=self.driver(execution=executor)),
                           "not_completed")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM governed_turn_completion").fetchone()[0], 0)

    # ---- the two acceptance conflicts ---------------------------------------
    def test_acceptance_conflict_when_the_challenge_is_bound_to_another_install(self):
        """§4.5: "the §5 absent -> ACCEPTED_PREPARED CAS loses to a conflicting existing
        binding"."""
        document, handle = self.ready_turn()
        self.trigger(document)
        self.conn.execute(
            "UPDATE governed_turn_acceptance SET install_id = 'another-install'")
        self.assertRefused(self.trigger(document), "acceptance_conflict")

    def test_acceptance_conflict_when_the_cas_loses_a_race(self):
        """§4.5: "`acceptance_conflict` = the §5 `absent -> ACCEPTED_PREPARED` CAS loses to a
        conflicting existing binding". `_locate` cannot see this one: the competing row
        appears AFTER its two probes and BEFORE the CAS, which is exactly the window a second
        supervisor process occupies."""
        document, _handle = self.ready_turn()
        nonce = document["payload"]["request_nonce"]
        planted = []

        def read_artifact(handle):
            if not planted:
                planted.append(True)
                gsl.accept_prepare(self.conn, gsl.NewAcceptance(
                    install_id="install-1", request_nonce=nonce,
                    challenge_handle=sha(b"a competing challenge"), run_id="run-1",
                    task_id="task-1", workspace_id="ws-1",
                    execution_attempt_id="competing-attempt",
                    challenge_accepted_at_ms=NOW,
                    challenge_registry_handle="r" * 64, challenge_registry_hash="s" * 64,
                    challenge_registry_epoch=7, challenge_registry_root_key_id=ROOT_KEY_ID,
                    lease_payload_bytes=b"{}", lease_id="competing-lease",
                    lease_issued_at_ms=NOW, lease_expires_at_ms=NOW + 210_000,
                    receipt_id="competing-receipt", supervisor_id=SUPERVISOR_ID,
                    requested_at_ms=NOW - 5_000, request_sha256="d" * 64,
                    system_handle=sha(SYSTEM_BYTES), history_handle=sha(HISTORY_BYTES),
                    generation_config_handle=sha(GENCFG_BYTES)), NOW)
            return self.store.read(handle)

        self.assertRefused(self.trigger(document, driver=self.driver(read_artifact=read_artifact)),
                           "acceptance_conflict")

    def test_challenge_replay_when_the_nonce_already_bought_a_different_challenge(self):
        """§4.5 pins this member to exactly this gate: "the §5 acceptance CAS finds the
        request_nonce already ACCEPTED for a different challenge_handle"."""
        first, _ = self.ready_turn()
        self.assertEqual(self.trigger(first)["status"], gtr.STATUS_SIGNED)
        nonce = first["payload"]["request_nonce"]

        # The production route to this state, spelled out: §2.4's sweep "deletes an expired/
        # abandoned staging row WITHOUT consuming the challenge nonce", so the desktop may
        # re-issue against the SAME nonce. The ACCEPTANCE row does not go with it - that is
        # the whole point of the acceptance ledger outliving staging - so the nonce is
        # already spent for execution while staging has forgotten it.
        self.conn.execute("DELETE FROM governed_turn_staging_chunk")
        self.conn.execute("DELETE FROM governed_turn_staging_session")
        self.conn.execute("DELETE FROM governed_turn_staging WHERE request_nonce = ?", (nonce,))

        second = self.challenge_document(nonce=nonce, task_id="task-2")
        self.assertNotEqual(sha(_canonical_bytes(second)), sha(_canonical_bytes(first)))
        self.open_turn(second)
        self.upload_all(second)
        self.assertRefused(self.trigger(second), "challenge_replay")

    # ---- §6.1 steps 11-13 ---------------------------------------------------
    def test_containment_missing_when_the_report_cannot_be_read(self):
        """§5(j): "a missing or empty report is a REFUSAL, not a fallback"."""
        document, _handle = self.ready_turn()
        executor = _Executor(self, containment=b"x")
        reply = self.trigger(document, driver=self.driver(execution=executor))
        self.assertEqual(reply["status"], gtr.STATUS_SIGNED, reply)
        # Now lose the artifact and re-trigger the COMPLETED turn.
        del self.store.blobs[sha(b"x")]
        self.assertRefused(self.trigger(document), "containment_missing")

    def test_containment_missing_when_the_report_is_empty(self):
        document, _handle = self.ready_turn()
        self.trigger(document)
        handle = sha(CONTAINMENT_BYTES)
        driver = self.driver(read_artifact=lambda h: b"" if h == handle else self.store.read(h))
        self.assertRefused(self.trigger(document, driver=driver), "containment_missing")

    def test_stream_unknown_when_the_completed_turn_s_capability_was_swept(self):
        """§4.10(f) phase 3: the row is gone, the terminal record stays the sole authority."""
        document, _reply = self.run_turn()
        self.conn.execute("DELETE FROM governed_output_streams")
        self.assertRefused(self.trigger(document), "stream_unknown")

    def test_a_signer_reply_with_a_real_payload_but_the_wrong_artifact_type_is_a_fault(self):
        """The `artifact_type` check must be able to fail on its own. A reply with NO payload
        is caught one line later by the payload check, so a test using one would pass with
        the discriminator deleted - it would prove the payload check twice."""
        document, _handle = self.ready_turn()

        def wrong_type(request):
            reply = dict(self.signer().sign_result(request))
            reply["artifact_type"] = "brops.something-else.v1"
            return reply

        with self.assertRaises(SupervisorError):
            self.trigger(document, driver=self.driver(sign_result=wrong_type))

    def test_containment_missing_when_the_store_read_raises(self):
        """Distinct from the EMPTY case, and distinct from the SIGNER's own
        `containment_missing`: this drives the read failure at §4.10(e) frame-build time,
        with the signer's own store still holding the artifact, so only this module's
        `except` can produce the verdict."""
        document, _handle = self.ready_turn()
        self.assertEqual(self.trigger(document)["status"], gtr.STATUS_SIGNED)
        handle = sha(CONTAINMENT_BYTES)

        def read_artifact(h):
            if h == handle:
                raise OSError("the protected store lost it")
            return self.store.read(h)

        self.assertRefused(self.trigger(document, driver=self.driver(read_artifact=read_artifact)),
                           "containment_missing")

    def test_not_completed_when_a_completed_row_has_no_completion(self):
        """MARKED: unreachable through this ladder - `record_completion` writes the
        completion and the `COMPLETED` state in ONE transaction - so this is tampered or
        foreign durable state. It is refused rather than worked around."""
        document, _reply = self.run_turn()
        self.conn.execute("DELETE FROM governed_turn_completion")
        self.assertRefused(self.trigger(document), "not_completed")

    def test_a_signer_refusal_is_relayed_by_name(self):
        document, _handle = self.ready_turn()

        def refuse(_request):
            return {"artifact_type": isg.REFUSAL_ARTIFACT_TYPE, "status": "refused",
                    "reason": isg.REASON_ATTESTATION_INVALID}

        self.assertRefused(self.trigger(document, driver=self.driver(sign_result=refuse)),
                           "attestation_invalid")

    def test_the_signers_one_reason_outside_the_closed_union_is_mapped_not_relayed(self):
        """`chain_document_disagrees_with_attested_evidence` was added to the signer by audit
        R3-01 AFTER rev-30 froze GOVERNED_REFUSAL_REASONS, so it is not a member. Relaying it
        would put a verdict outside a closed set."""
        document, _handle = self.ready_turn()
        self.assertNotIn(isg.REASON_CHAIN_DISAGREEMENT, gtr.GOVERNED_REFUSAL_REASONS)

        def refuse(_request):
            return {"artifact_type": isg.REFUSAL_ARTIFACT_TYPE, "status": "refused",
                    "reason": isg.REASON_CHAIN_DISAGREEMENT}

        self.assertRefused(self.trigger(document, driver=self.driver(sign_result=refuse)),
                           "hash_mismatch")

    def test_every_signer_refusal_reason_lands_inside_the_closed_union(self):
        reasons = [getattr(isg, name) for name in dir(isg) if name.startswith("REASON_")]
        self.assertGreaterEqual(len(reasons), 13)
        for reason in reasons:
            with self.subTest(reason=reason):
                mapped = gac._SIGNER_REASONS.get(reason, reason)
                self.assertIn(mapped, gtr.GOVERNED_REFUSAL_REASONS)

    def test_every_accept_open_refusal_reason_lands_inside_the_closed_union(self):
        import governed_supervisor as gs

        reasons = [getattr(gs, name) for name in dir(gs) if name.startswith("REFUSE_")]
        self.assertGreaterEqual(len(reasons), 6)
        for reason in reasons:
            with self.subTest(reason=reason):
                self.assertIn(reason, gac._ACCEPT_REASONS)
                self.assertIn(gac._ACCEPT_REASONS[reason], gtr.GOVERNED_REFUSAL_REASONS)


# ---------------------------------------------------------------------------
# The one bound that CAN fire — §4.6's envelope cap, and the one that cannot
# ---------------------------------------------------------------------------


class ConcurrencyAndStoreFailureTests(_Case):
    """Paths a single driver cannot reach alone: another supervisor process moving the same
    durable row, and a protected store that fails mid-turn. Both are real - the ledger is
    shared state and the store is a filesystem - and both must produce a §4.10(e) verdict
    rather than an exception escaping the protocol."""

    def test_a_row_another_process_already_moved_terminal_is_not_advanced_twice(self):
        """The `_advance` swallow. A second supervisor takes the `RECOVERY_REQUIRED` edge
        while this one is still inside the execution seam; this one must not turn a benign
        race into a second verdict about the same turn."""
        document, _handle = self.ready_turn()
        case = self

        class _Raced(_Executor):
            def run(self, request, on_started):
                self.runs.append(request)
                case.conn.execute(
                    "UPDATE governed_turn_acceptance SET state = 'RECOVERY_REQUIRED'"
                    " WHERE execution_attempt_id = ?", (request.execution_attempt_id,))
                raise RuntimeError("and then this one died too")

        self.assertRefused(self.trigger(document, driver=self.driver(execution=_Raced(self))),
                           "not_completed")
        self.assertEqual(self.acceptance_row(document)["state"], gsl.RECOVERY_REQUIRED)

    def test_a_row_another_process_expired_is_not_launched_by_this_one(self):
        """The launch gate's `IllegalTransition` arm. Between this driver's own read and its
        CAS another process drove the row to `EXPIRED`; the gate must lose the CAS and this
        driver must launch nothing."""
        document, _handle = self.ready_turn()
        raced = []

        def clock():
            # The attempt id does not exist until the CAS commits, so the race is staged by
            # reading it back out of the ledger: once the row is LEASE_READY, another process
            # drives it to EXPIRED before this driver's own gate CAS runs.
            row = self.conn.execute(
                "SELECT execution_attempt_id, state FROM governed_turn_acceptance").fetchone()
            if row is not None and row["state"] == gsl.LEASE_READY and not raced:
                raced.append(row["execution_attempt_id"])
                gsl.advance(self.conn, raced[0], gsl.EXPIRED, NOW, failure_reason="raced")
            return NOW

        self.assertRefused(self.trigger(document, driver=self.driver(clock_ms=clock)),
                           "lease_expired")
        self.assertEqual(raced, [self.acceptance_row(document)["execution_attempt_id"]])
        self.assertEqual(self.acceptance_row(document)["state"], gsl.EXPIRED)
        self.assertEqual(self.executor.runs, [])

    def test_a_recorder_evidence_read_that_raises_is_a_verdict_not_an_exception(self):
        document, _handle = self.ready_turn()

        def boom(attempt):
            raise OSError("the evidence directory is unreadable")

        self.assertRefused(self.trigger(document, driver=self.driver(read_run_evidence=boom)),
                           "malformed")

    def test_a_store_that_fails_publishing_a_terminal_artifact_is_a_verdict(self):
        """Not the lease publish (that has its own `lease_not_ready` verdict one step
        earlier) - the RECORD publish, inside the completion."""
        document, _handle = self.ready_turn()
        calls = []

        def publish(data):
            calls.append(data)
            if len(calls) > 2:      # 1 = the lease at LEASE_READY, 2 = the lease again
                raise OSError("no space left on the protected store")
            return self.store.publish(data)

        self.assertRefused(self.trigger(document, driver=self.driver(publish_artifact=publish)),
                           "malformed")

    def test_an_output_the_store_cannot_measure_is_a_verdict(self):
        """§4.10(f)'s `output_bytes` is MEASURED, so a store that cannot return the output
        cannot mint a stream - and §4.10(f) says a completing turn's stream is ALWAYS
        created, so the turn has not completed."""
        document, _handle = self.ready_turn()
        case = self

        class _Blind:
            allowed_sidecar_uid = SIDECAR_UID

            def measure_output(self, handle):
                raise SupervisorError("output artifact unreadable at completion")

            def mint_for_completion(self, conn, new, now_ms):  # pragma: no cover
                raise AssertionError("must not be reached")

        self.assertRefused(
            self.trigger(document, driver=self.driver(output_read_service=_Blind())),
            "malformed")


class TheStateLadderIsExhaustiveTests(_Case):

    def test_the_state_ladder_is_exhaustive_over_the_closed_enum(self):
        """Every member of the ledger's closed `state` domain has a branch in `_drive`, so
        there is no residual "unknown state" case for a guard to defend. This test IS that
        guard: it fails the day a tenth state is added without a branch, which a
        `if state != COMPLETED: raise` line could never do (the DDL `CHECK` makes a value
        outside the domain unstorable, so that line could not fire)."""
        handled = (
            {gsl.ACCEPTED_PREPARED, gsl.LEASE_READY, gsl.EXECUTION_STARTING, gsl.EXECUTING,
             gsl.BLOCKED, gsl.COMPLETED}
            | set(gac._TERMINAL_REASONS)
        )
        self.assertEqual(handled, set(gsl.ALL_STATES))
        for state in gac._TERMINAL_REASONS:
            with self.subTest(state=state):
                self.assertIn(gac._TERMINAL_REASONS[state], gtr.GOVERNED_REFUSAL_REASONS)


class TheCapsAreArithmeticTests(_Case):
    """§4.6 freezes `envelope_jcs_b64 <= 2848` and `attestation_evidence_jcs_b64 <= 4664` as
    machine-checked derivations "at schema max". For the payload and evidence THIS tree's
    signer builds, one of those two numbers is wrong and the other has room to spare, and the
    difference decides which check exists."""

    HEX_KEYS = frozenset({"request_sha256", "record_handle", "lease_handle",
                          "execution_receipt_handle", "output_sha256",
                          "evidence_final_event_hash", "attestation_evidence_sha256"})

    def _max_envelope(self, id_len):
        payload = {}
        for key in isg.ENVELOPE_STRING_KEYS:
            if key == "artifact_type":
                payload[key] = isg.ENVELOPE_ARTIFACT_TYPE
            elif key in self.HEX_KEYS:
                payload[key] = "a" * 64
            else:
                payload[key] = "x" * id_len
        payload.update({
            "output_bytes": gtr.MAX_OUTPUT_BYTES,
            "challenge_accepted_at_ms": 1_700_000_000_000,
            "completed_at_ms": 1_700_000_000_000,
            "evidence_event_count": 3,
            "evidence_last_sequence": 3,
            "evidence_head_sequence": 7,
        })
        return len(b64u(isg._jcs_bytes(payload)))

    def test_the_maximum_signed_envelope_overflows_the_frozen_4_6_cap(self):
        """At the signer's own `STRING_CAP` of 128 the envelope is 2888 base64url chars
        against a cap of 2848 — 40 OVER. The design's derivation was made for §4.4's evidence
        shape, not for the 23-key payload this signer builds."""
        self.assertEqual(self._max_envelope(isg.STRING_CAP), 2888)
        self.assertEqual(gtr.MAX_ENVELOPE_JCS_B64_LEN, 2848)

    def test_the_envelope_cap_first_binds_at_an_id_length_of_125(self):
        """124-character ids fit; 125 do not. That is the boundary the driver's `oversize`
        refusal is placed at, and it is inside the schema's own `<=128` bound — so this is a
        bound that CAN fire on a legal turn, unlike §4.10(e)'s 262144 frame cap."""
        self.assertLessEqual(self._max_envelope(124), gtr.MAX_ENVELOPE_JCS_B64_LEN)
        self.assertGreater(self._max_envelope(125), gtr.MAX_ENVELOPE_JCS_B64_LEN)
        self.assertEqual((self._max_envelope(124), self._max_envelope(125)), (2840, 2852))

    def test_the_attestation_cap_can_never_fire_which_is_why_no_check_exists(self):
        """The evidence at schema max is 4032 base64url chars against a cap of 4664 — 632 to
        spare. A check on that limb could not fail, which is the class this repository
        deletes rather than ships (§4.10(a)/(c), §4.10(e), §4.10(f) each did the same)."""
        evidence = {}
        for field in isg.EVIDENCE_STRING_FIELDS:
            evidence[field] = "x" * isg.STRING_CAP
        for field in isg.EVIDENCE_HANDLE_FIELDS + isg.EVIDENCE_DIGEST_FIELDS:
            evidence[field] = "a" * 64
        for field in isg.EVIDENCE_TS_FIELDS:
            evidence[field] = (2 ** 64) - 1
        for field in isg.EVIDENCE_COUNT_FIELDS:
            evidence[field] = (2 ** 63) - 1
        encoded = len(b64u(isg._canonical_bytes(evidence)))
        self.assertEqual(encoded, 4032)
        self.assertLess(encoded, gtr.MAX_ATTESTATION_EVIDENCE_JCS_B64_LEN)

    def test_oversize_is_refused_rather_than_faulting_the_frame_validator(self):
        """A real turn whose ids are long enough to cross the cap gets a governed `oversize`
        verdict — not a `SupervisorError`, which is what building the frame anyway would
        produce and which §4.10(e) has no vocabulary for."""
        document, _handle = self.ready_turn()
        long_id = "y" * isg.STRING_CAP

        def sign_result(request):
            reply = self.signer().sign_result(request)
            if reply.get("status") == "signed":
                payload = dict(reply["payload"])
                for key in ("receipt_id", "run_id", "execution_attempt_id", "task_id",
                            "workspace_id", "install_id", "request_nonce", "key_id",
                            "supervisor_attestation_key_id"):
                    payload[key] = long_id
                reply = dict(reply, payload=payload)
            return reply

        self.assertRefused(self.trigger(document, driver=self.driver(sign_result=sign_result)),
                           "oversize")

    def test_an_oversize_containment_report_is_refused_rather_than_carried(self):
        document, _handle = self.ready_turn()
        huge = b"c" * (49_153 * 3)
        executor = _Executor(self, containment=huge)
        self.assertRefused(self.trigger(document, driver=self.driver(execution=executor)),
                           "oversize")


# ---------------------------------------------------------------------------
# Supervisor-side FAULTS are not verdicts
# ---------------------------------------------------------------------------


class SupervisorFaultTests(_Case):

    def test_an_unreachable_signer_is_a_fault_not_a_refusal(self):
        """§4.10(e) publishes no reason for "the supervisor could not obtain its own
        signature", so inventing one would put a verdict outside a closed set."""
        document, _handle = self.ready_turn()

        def unreachable(_request):
            raise ConnectionRefusedError("no signer socket")

        with self.assertRaises(ConnectionRefusedError):
            self.trigger(document, driver=self.driver(sign_result=unreachable))

    def test_a_signer_reply_that_is_neither_envelope_nor_refusal_is_a_fault(self):
        document, _handle = self.ready_turn()
        with self.assertRaises(SupervisorError):
            self.trigger(document, driver=self.driver(sign_result=lambda r: {"ok": True}))

    def test_an_execution_seam_returning_the_wrong_type_is_a_fault(self):
        document, _handle = self.ready_turn()

        class _Bad(_Executor):
            def run(self, request, on_started):
                on_started(gac.StartedExecution(process_group_id="1", cgroup_id="c"))
                return {"output_handle": "x"}

        with self.assertRaises(SupervisorError):
            self.trigger(document, driver=self.driver(execution=_Bad(self)))

    def test_a_non_gated_turn_is_a_fault(self):
        with self.assertRaises(SupervisorError):
            self.driver()({"install_id": "install-1"})

    def test_a_moving_clock_that_returns_a_non_int_is_a_fault(self):
        document, _handle = self.ready_turn()
        with self.assertRaises(SupervisorError):
            self.trigger(document, driver=self.driver(clock_ms=lambda: "now"))


class ConstructionTests(_Case):

    def test_a_driver_without_an_output_service_is_refused_at_construction(self):
        with self.assertRaises(SupervisorError):
            self.driver(output_read_service=None)

    def test_a_driver_without_a_ledger_is_refused_at_construction(self):
        with self.assertRaises(SupervisorError):
            self.driver(conn=None)

    def test_every_seam_must_be_callable(self):
        for name in ("clock_ms", "read_artifact", "publish_artifact",
                     "resolve_registry_document", "verify_root_sig", "verify_challenge_sig",
                     "read_run_evidence", "sign_attestation", "sign_result",
                     "recompute_request_sha256"):
            with self.subTest(seam=name):
                with self.assertRaises(SupervisorError):
                    self.driver(**{name: "not callable"})

    def test_an_execution_binding_that_is_not_an_execution_service_is_refused(self):
        with self.assertRaises(SupervisorError):
            self.driver(execution=lambda *a: None)

    def test_the_default_execution_binding_refuses(self):
        """A driver constructed without an `execution` seam must not silently execute."""
        driver = gac.AcceptanceDriver(
            config=self.acceptance_config(), conn=self.conn, clock_ms=lambda: self.clock,
            read_artifact=self.store.read, publish_artifact=self.store.publish,
            resolve_registry_document=lambda: self.registry_document,
            verify_root_sig=self.verify_root_sig,
            verify_challenge_sig=self.verify_challenge_sig,
            read_run_evidence=self.run_evidence.get,
            sign_attestation=self.attest_key.sign,
            supervisor_attestation_key_id=SUP_ATTEST_KEY_ID,
            sign_result=self.sign_result, output_read_service=self.output_service())
        self.assertIsInstance(driver.execution, gac.RefusingExecutor)
        with self.assertRaises(gac.GovernedExecutionUnavailable):
            driver.execution.preflight()
        with self.assertRaises(gac.GovernedExecutionUnavailable):
            driver.execution.run(None, None)

    def test_two_supervisor_ids_in_one_config_is_refused(self):
        other = self.supervisor_config(supervisor_id="a-different-supervisor")
        with self.assertRaises(SupervisorError):
            gac.AcceptanceConfig(
                supervisor=other,
                open_config=gto.OpenConfig.from_supervisor_config(
                    self.supervisor_config(), registry_root_public_key=self.root_key.public_b64))

    def test_an_allowlist_entry_that_is_not_a_digest_is_refused(self):
        with self.assertRaises(SupervisorError):
            self.acceptance_config(allowlist=frozenset({"claude-sonnet-5"}))

    def test_an_empty_allowlist_is_constructible_and_refuses_every_turn(self):
        """The `SignerConfig.allowed_policies` precedent: an unprovisioned allowlist is not
        an open one."""
        config = self.acceptance_config(allowlist=frozenset())
        self.assertEqual(config.execution_allowlist, frozenset())
        document, _handle = self.ready_turn()
        self.assertRefused(self.trigger(document, driver=self.driver(config=config)),
                           "model_profile_unknown")


# ---------------------------------------------------------------------------
# Nothing that belongs to a later piece is minted here
# ---------------------------------------------------------------------------


class NothingLaterIsMintedTests(_Case):

    def test_the_driver_never_answers_in_the_pre_acceptance_namespace(self):
        """§4.10(d)'s union is split by discriminator: once a row exists the verdict belongs
        to §4.10(e). `handle_evidence_request` faults on a continuation that returns the
        other arm, and this driver must never make it do so."""
        document, _handle = self.ready_turn()
        for driver in (self.driver(), self.driver(execution=gac.RefusingExecutor())):
            reply = self.trigger(document, driver=driver)
            self.assertEqual(reply["protocol"], gtr.GOVERNED_TURN_RESULT_PROTOCOL)
            self.assertNotEqual(reply["protocol"], ger.EVIDENCE_REQUEST_RESULT_PROTOCOL)

    def test_the_driver_builds_no_bridge_or_sign_result_frame(self):
        """§4.6's `bridge.governed-turn-result.v1` and §4.5's `brops.governed-sign-result.v1`
        are later pieces; nothing here may mint one."""
        source = (ROOT / "runtime" / "governed_acceptance.py").read_text(encoding="utf-8")
        for absent in ("bridge.governed-turn-result.v1", "brops.governed-sign-result.v1",
                       "bridge.governed-turn-output-read.v1", "governed_internal_refusal"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, source)

    def test_the_driver_reads_no_clock_of_its_own(self):
        source = (ROOT / "runtime" / "governed_acceptance.py").read_text(encoding="utf-8")
        for banned in ("import time", "time.time", "datetime", "monotonic"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, source)

    def test_the_set_of_reasons_this_driver_can_decide_is_pinned(self):
        """`governed_turn_result` states in a comment which members of the closed union now
        have a producer and which still do not. A comment cannot be wrong quietly if a test
        reads the source and checks it, so this does.

        The seven with no producer are not an oversight and each has a reason: three belong
        to §4.10(f)'s OUTPUT-READ frame rather than to §4.10(e) (`stream_expired`,
        `stream_binding_mismatch`, `seq_out_of_range` - produced by `governed_output_read`,
        into a different protocol); `retry_conflict` is decided pre-acceptance by §4.10(d)'s
        own internal set, where it is a diagnostic and not a governed verdict;
        `output_oversize` and `output_timeout` belong to the §6.1 step-5 execution that no
        host here can run; and `tcb_integrity_violation` is §2.5's integrity floor, which
        does not exist in the engine at all."""
        import re

        source = (ROOT / "runtime" / "governed_acceptance.py").read_text(encoding="utf-8")
        produced = {
            reason for reason in gtr.GOVERNED_REFUSAL_REASONS
            if re.search(r"_Refuse\(\s*[\"']%s[\"']" % re.escape(reason), source)
            or ('"%s":' % reason) in source or (': "%s"' % reason) in source
        }
        self.assertEqual(
            sorted(produced & set(gtr.GOVERNED_ADDED_REFUSAL_REASONS)),
            ["acceptance_conflict", "challenge_invalidated", "challenge_replay",
             "evidence_fork", "lease_expired", "lease_not_ready", "model_profile_unknown",
             "platform_unsupported", "stale_evidence", "stream_unknown"])
        self.assertEqual(
            sorted(set(gtr.GOVERNED_ADDED_REFUSAL_REASONS) - produced),
            ["output_oversize", "output_timeout", "retry_conflict", "seq_out_of_range",
             "stream_binding_mismatch", "stream_expired", "tcb_integrity_violation"])
        self.assertEqual(
            sorted(produced & set(gtr.RATIFIED_REFUSAL_REASONS)),
            ["containment_missing", "handle_missing", "hash_mismatch", "identity_denied",
             "malformed", "not_completed", "oversize", "timestamp_invalid"])
        # Every one of them is a member of the closed union, by construction.
        for reason in produced:
            with self.subTest(reason=reason):
                self.assertIn(reason, gtr.GOVERNED_REFUSAL_REASONS)

    def test_no_governed_surface_is_wired_by_this_module(self):
        """The live supervisor still constructs none of the sidecar services, so this driver
        has no production construction site and opens no door."""
        live = (ROOT / "ci" / "live" / "run_supervisor.py").read_text(encoding="utf-8")
        for absent in ("AcceptanceDriver", "EvidenceRequestService", "OpenService",
                       "StagingService", "OutputReadService"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, live)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
