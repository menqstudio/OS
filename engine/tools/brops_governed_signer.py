"""Isolated signer for the additive Wave 3b-1B governed-turn family.

The signer accepts only a supervisor-attested, handle-only evidence document.  It
re-reads and verifies the complete protected chain, derives model identity from the
signed generation-config bytes, constructs the receipt envelope itself and signs it.
There is no arbitrary-bytes signing endpoint.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from bro_signature import canonical_bytes
from brops_evidence_store import EvidenceStore, EvidenceStoreError
from brops_governed_common import (
    LEASE_DURATION_MS, GovernedProtocolError, b64url_decode, b64url_encode,
    generation_config_sha256, model_profile_id, request_sha256,
    require_exact_keys, require_hex64, require_id, sha256_hex,
    validate_generation_config,
)

PROTOCOL = "brops.governed-sign-request.v1"
RESULT_PROTOCOL = "brops.governed-sign-result.v1"
ATTESTATION_PROTOCOL = "brops.run-attestation.v1"
ENVELOPE_TYPE = "brops.governed-receipt-envelope.v1"

REFUSAL_REASONS = frozenset({
    "malformed", "attestation_invalid", "handle_missing", "hash_mismatch",
    "challenge_invalidated", "run_binding_invalid", "policy_mismatch",
    "identity_denied", "lease_expired", "stale_evidence", "evidence_fork",
})

_EVIDENCE_KEYS = frozenset({
    "run_id", "execution_attempt_id", "lease_id", "task_id", "request_nonce",
    "receipt_id", "decision", "workspace_id", "install_id", "supervisor_id",
    "executor_id", "runner_id", "policy_id", "policy_version",
    "requested_at_ms", "completed_at_ms", "challenge_accepted_at_ms",
    "system_handle", "history_handle", "generation_config_handle", "output_handle",
    "containment_evidence_handle", "policy_bundle_handle", "lease_handle",
    "execution_receipt_handle", "challenge_handle",
    "challenge_key_id", "challenge_registry_handle", "challenge_registry_hash",
    "challenge_registry_epoch", "challenge_registry_root_key_id",
    "evidence_event_count", "evidence_last_sequence", "evidence_head_sequence",
    "evidence_final_event_hash",
})


class GovernedSignRefused(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason if reason in REFUSAL_REASONS else "malformed"


_FLOOR_DDL = """
CREATE TABLE IF NOT EXISTS governed_evidence_head_floor (
  install_id TEXT NOT NULL, task_id TEXT NOT NULL,
  highest_head_sequence INTEGER NOT NULL CHECK(highest_head_sequence >= 1),
  event_count INTEGER NOT NULL CHECK(event_count >= 1),
  last_sequence INTEGER NOT NULL CHECK(last_sequence >= 1),
  final_event_hash TEXT NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  PRIMARY KEY (install_id, task_id)
);
"""


def apply_head_floor(db_path, install_id: str, task_id: str, head_sequence: int,
                     event_count: int, last_sequence: int, final_event_hash: str,
                     now_ms: int, detailed: Mapping[str, Any] | None = None) -> None:
    """§7 durable evidence-head anti-rollback floor (signer-owned), keyed on (install_id, task_id).

    Runs the LOCKED A–E matrix in one BEGIN IMMEDIATE tx and COMMITS the floor BEFORE the caller
    signs the §4.9 envelope, closing the TOCTOU:
      A. head_sequence < stored high-water            -> refuse stale_evidence (rollback)
      B. head_sequence == stored & content equal       -> idempotent re-sign (no change)
         head_sequence == stored & content differs      -> refuse evidence_fork
      C. head_sequence >  stored & content equal        -> valid unchanged re-anchor (advance head only)
      D. head_sequence >  stored & count increased       -> accept iff the new chain reproduces the
                                                            stored chain as its EXACT prefix (needs
                                                            `detailed` from validate_chain_detailed)
      E. any other higher-head case                      -> refuse evidence_fork
      bootstrap (no row)                                 -> INSERT the validated head
    A real evidence head has head_sequence/event_count/last_sequence >= 1 and last_sequence ==
    event_count; anything else is a fork (a degenerate head cannot anchor identity)."""
    for value in (head_sequence, event_count, last_sequence):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise GovernedSignRefused("evidence_fork", "degenerate evidence head")
    if last_sequence != event_count:
        raise GovernedSignRefused("evidence_fork", "last_sequence != event_count")
    if (not isinstance(final_event_hash, str) or len(final_event_hash) != 64
            or any(c not in "0123456789abcdef" for c in final_event_hash)):
        raise GovernedSignRefused("evidence_fork", "final_event_hash not a 64-hex sha256 digest")
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_FLOOR_DDL)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT highest_head_sequence,event_count,last_sequence,final_event_hash "
            "FROM governed_evidence_head_floor WHERE install_id=? AND task_id=?",
            (install_id, task_id)).fetchone()
        if row is None:  # bootstrap
            conn.execute(
                "INSERT INTO governed_evidence_head_floor(install_id,task_id,highest_head_sequence,"
                "event_count,last_sequence,final_event_hash,updated_at_ms) VALUES(?,?,?,?,?,?,?)",
                (install_id, task_id, head_sequence, event_count, last_sequence, final_event_hash, now_ms))
            conn.execute("COMMIT"); return
        stored_hhs, stored_ec, stored_ls, stored_feh = row
        content_equal = (event_count == stored_ec and last_sequence == stored_ls
                         and final_event_hash == stored_feh)
        if head_sequence < stored_hhs:                                            # A
            conn.execute("ROLLBACK")
            raise GovernedSignRefused("stale_evidence", "rolled-back evidence head")
        if head_sequence == stored_hhs:                                           # B
            if content_equal:
                conn.execute("COMMIT"); return
            conn.execute("ROLLBACK")
            raise GovernedSignRefused("evidence_fork", "same head_sequence, different content")
        if content_equal:                                                         # C
            conn.execute(
                "UPDATE governed_evidence_head_floor SET highest_head_sequence=?,updated_at_ms=? "
                "WHERE install_id=? AND task_id=?", (head_sequence, now_ms, install_id, task_id))
            conn.execute("COMMIT"); return
        if event_count > stored_ec and last_sequence == event_count:              # D
            hashes = list((detailed or {}).get("event_hashes") or [])
            prevs = list((detailed or {}).get("previous_event_hashes") or [])
            idx = stored_ec - 1
            if (detailed is None or (detailed.get("event_count") != event_count)
                    or len(hashes) != event_count or idx >= len(hashes)
                    or hashes[idx] != stored_feh
                    or idx + 1 >= len(prevs) or prevs[idx + 1] != stored_feh):
                conn.execute("ROLLBACK")
                raise GovernedSignRefused("evidence_fork", "extension does not reproduce stored prefix")
            conn.execute(
                "UPDATE governed_evidence_head_floor SET highest_head_sequence=?,event_count=?,"
                "last_sequence=?,final_event_hash=?,updated_at_ms=? WHERE install_id=? AND task_id=?",
                (head_sequence, event_count, last_sequence, final_event_hash, now_ms, install_id, task_id))
            conn.execute("COMMIT"); return
        conn.execute("ROLLBACK")                                                  # E
        raise GovernedSignRefused("evidence_fork", "divergent higher-head lineage")
    finally:
        conn.close()


@dataclass(frozen=True)
class GovernedSignerComponents:
    store: EvidenceStore
    receipt_signing_key: Mapping[str, str]
    supervisor_attestation_pubkey_hex: str
    supervisor_attestation_key_id: str
    lease_issuer_pubkey_hex: str
    lease_issuer_key_id: str
    # §8 authority separation: the execution receipt is verified under the evidence-recorder key,
    # the terminal record under the governed-turn-recorder key. A record signed by the
    # evidence-recorder key (or a receipt by the governed-turn-recorder key) fails its own key_id pin.
    evidence_recorder_pubkey_hex: str
    evidence_recorder_key_id: str
    governed_turn_recorder_pubkey_hex: str
    governed_turn_recorder_key_id: str
    challenge_root_pubkeys_hex: Mapping[str, str]
    record_dir: pathlib.Path
    allowed_executor_ids: frozenset[str]
    allowed_runner_ids: frozenset[str]
    allowed_supervisor_ids: frozenset[str]
    expected_policy_id: str
    expected_policy_version: str
    # §7 signer-owned durable evidence-head anti-rollback floor DB (separate from the read-only store).
    head_floor_db: pathlib.Path


def _verify_sig(payload: Mapping[str, Any], sig_b64: str, public_key_hex: str, reason: str) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex)).verify(
            b64url_decode(sig_b64, max_bytes=64), canonical_bytes(dict(payload))
        )
    except (InvalidSignature, ValueError, GovernedProtocolError) as exc:
        raise GovernedSignRefused(reason) from exc


def _load_json(store: EvidenceStore, handle: str) -> dict[str, Any]:
    require_hex64(handle, "handle")
    try:
        raw = store.read(handle)
    except EvidenceStoreError as exc:
        raise GovernedSignRefused("handle_missing", str(exc)) from exc
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise GovernedSignRefused("malformed", "artifact is not canonical JSON") from exc
    if not isinstance(obj, dict) or canonical_bytes(obj) != raw:
        raise GovernedSignRefused("hash_mismatch", "artifact is not canonical")
    return obj


def _verify_attestation(request: Mapping[str, Any], c: GovernedSignerComponents) -> Mapping[str, Any]:
    require_exact_keys(request, {"protocol", "attestation", "evidence"}, "sign request")
    if request["protocol"] != PROTOCOL:
        raise GovernedSignRefused("malformed")
    att = request["attestation"]
    evidence = request["evidence"]
    require_exact_keys(att, {"attestation_protocol", "supervisor_key_id", "sig"}, "attestation")
    require_exact_keys(evidence, _EVIDENCE_KEYS, "evidence")
    if att["attestation_protocol"] != ATTESTATION_PROTOCOL or att["supervisor_key_id"] != c.supervisor_attestation_key_id:
        raise GovernedSignRefused("attestation_invalid")
    _verify_sig(evidence, att["sig"], c.supervisor_attestation_pubkey_hex, "attestation_invalid")
    return evidence


def _verify_registry(registry: Mapping[str, Any], c: GovernedSignerComponents) -> Mapping[str, Any]:
    require_exact_keys(registry, {"payload", "root_sig"}, "challenge registry")
    payload = registry["payload"]
    required = {"artifact_type", "root_key_id", "registry_epoch", "registry_issued_at_ms", "keys"}
    require_exact_keys(payload, required, "registry payload")
    if payload["artifact_type"] != "brops.challenge-key-registry.v1":
        raise GovernedSignRefused("challenge_invalidated")
    root_id = payload["root_key_id"]
    pub = c.challenge_root_pubkeys_hex.get(root_id)
    if not pub:
        raise GovernedSignRefused("challenge_invalidated")
    _verify_sig(payload, registry["root_sig"], pub, "challenge_invalidated")
    if not isinstance(payload["keys"], list) or len(payload["keys"]) > 256:
        raise GovernedSignRefused("challenge_invalidated")
    ids = [k.get("challenge_key_id") for k in payload["keys"] if isinstance(k, dict)]
    if len(ids) != len(set(ids)):
        raise GovernedSignRefused("challenge_invalidated")
    return payload


def _signed_payload(doc: Mapping[str, Any], *, artifact_type: str, key_id: str,
                    pubkey_hex: str, sig_field: str = "signature") -> Mapping[str, Any]:
    require_exact_keys(doc, {"payload", sig_field}, artifact_type)
    payload = doc["payload"]
    if not isinstance(payload, Mapping) or payload.get("artifact_type") != artifact_type or payload.get("key_id") != key_id:
        raise GovernedSignRefused("run_binding_invalid")
    _verify_sig(payload, doc[sig_field], pubkey_hex, "run_binding_invalid")
    return payload


def sign_governed(request: Mapping[str, Any], c: GovernedSignerComponents, now_ms: int) -> dict[str, Any]:
    receipt_id = None
    try:
        evidence = _verify_attestation(request, c)
        receipt_id = require_id(evidence["receipt_id"], "receipt_id")
        if evidence["decision"] != "completed":
            raise GovernedSignRefused("run_binding_invalid")
        if evidence["executor_id"] not in c.allowed_executor_ids or evidence["runner_id"] not in c.allowed_runner_ids or evidence["supervisor_id"] not in c.allowed_supervisor_ids:
            raise GovernedSignRefused("identity_denied")
        if evidence["policy_id"] != c.expected_policy_id or evidence["policy_version"] != c.expected_policy_version:
            raise GovernedSignRefused("policy_mismatch")

        # Read every authoritative artifact through its content handle.
        challenge_doc = _load_json(c.store, evidence["challenge_handle"])
        registry_doc = _load_json(c.store, evidence["challenge_registry_handle"])
        lease_doc = _load_json(c.store, evidence["lease_handle"])
        execution_receipt_doc = _load_json(c.store, evidence["execution_receipt_handle"])
        record_path = c.record_dir / f"{evidence['run_id']}__{evidence['execution_attempt_id']}.json"
        try:
            record_raw = record_path.read_bytes()
            record_doc = json.loads(record_raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise GovernedSignRefused("handle_missing", "terminal record mirror missing") from exc
        if not isinstance(record_doc, dict) or canonical_bytes(record_doc) != record_raw:
            raise GovernedSignRefused("hash_mismatch", "terminal record mirror noncanonical")
        record_handle = sha256_hex(record_raw)
        if c.store.read(record_handle) != record_raw:
            raise GovernedSignRefused("hash_mismatch", "terminal record mirror/store mismatch")
        registry_payload = _verify_registry(registry_doc, c)
        if sha256_hex(canonical_bytes(registry_payload)) != evidence["challenge_registry_hash"]:
            raise GovernedSignRefused("challenge_invalidated")
        if registry_payload["registry_epoch"] != evidence["challenge_registry_epoch"] or registry_payload["root_key_id"] != evidence["challenge_registry_root_key_id"]:
            raise GovernedSignRefused("challenge_invalidated")

        require_exact_keys(challenge_doc, {"payload", "sig"}, "challenge")
        challenge = challenge_doc["payload"]
        key_entry = next((k for k in registry_payload["keys"] if k.get("challenge_key_id") == challenge.get("challenge_key_id")), None)
        if key_entry is None or challenge.get("challenge_key_id") != evidence["challenge_key_id"]:
            raise GovernedSignRefused("challenge_invalidated")
        accepted_ms = evidence["challenge_accepted_at_ms"]
        if not isinstance(accepted_ms, int):
            raise GovernedSignRefused("malformed")
        revoked_at = key_entry.get("revoked_at_ms")
        if not (key_entry.get("valid_from_ms") <= accepted_ms <= key_entry.get("valid_to_ms")):
            raise GovernedSignRefused("challenge_invalidated")
        if key_entry.get("revoked") and (not isinstance(revoked_at, int) or revoked_at <= accepted_ms):
            raise GovernedSignRefused("challenge_invalidated")
        challenge_pub_hex = b64url_decode(key_entry["public_key"], max_bytes=32).hex()
        _verify_sig(challenge, challenge_doc["sig"], challenge_pub_hex, "challenge_invalidated")

        lease = _signed_payload(
            lease_doc, artifact_type="brops.governed-turn-lease.v1",
            key_id=c.lease_issuer_key_id, pubkey_hex=c.lease_issuer_pubkey_hex,
        )
        execution_receipt = _signed_payload(
            execution_receipt_doc, artifact_type="brops.governed-turn-execution-receipt.v1",
            key_id=c.evidence_recorder_key_id, pubkey_hex=c.evidence_recorder_pubkey_hex,
        )
        record = _signed_payload(
            record_doc, artifact_type="brops.governed-turn-record.v1",
            key_id=c.governed_turn_recorder_key_id, pubkey_hex=c.governed_turn_recorder_pubkey_hex,
        )

        system = c.store.read(evidence["system_handle"])
        history = c.store.read(evidence["history_handle"])
        config_raw = c.store.read(evidence["generation_config_handle"])
        output = c.store.read(evidence["output_handle"])
        # §8: bind the containment the signer trusts to the gov-turn-recorder-signed record. The
        # store read is content-addressed (handle == sha256(bytes)); this ties that handle to the
        # value the terminal record committed, so a substituted containment fails run_binding_invalid.
        if evidence["containment_evidence_handle"] != record.get("containment_evidence_sha256"):
            raise GovernedSignRefused("run_binding_invalid", "containment handle not bound to the record")
        containment = _load_json(c.store, evidence["containment_evidence_handle"])
        c.store.read(evidence["policy_bundle_handle"])
        try:
            config = validate_generation_config(json.loads(config_raw.decode("utf-8")))
        except Exception as exc:  # noqa: BLE001
            raise GovernedSignRefused("run_binding_invalid") from exc
        cfg_hash = generation_config_sha256(config)
        req_hash = request_sha256(
            workspace_id=evidence["workspace_id"], install_id=evidence["install_id"],
            request_nonce=evidence["request_nonce"], system_sha256=sha256_hex(system),
            history_sha256=sha256_hex(history), generation_config_sha256=cfg_hash,
            requested_at_ms=evidence["requested_at_ms"],
        )

        challenge_expected = {
            "run_id": evidence["run_id"], "task_id": evidence["task_id"],
            "request_nonce": evidence["request_nonce"], "workspace_id": evidence["workspace_id"],
            "install_id": evidence["install_id"], "supervisor_id": evidence["supervisor_id"],
        }
        for name, expected in challenge_expected.items():
            if challenge.get(name) != expected:
                raise GovernedSignRefused("run_binding_invalid")
        lease_record_expected = {
            **challenge_expected,
            "execution_attempt_id": evidence["execution_attempt_id"],
            "lease_id": evidence["lease_id"],
        }
        for name, expected in lease_record_expected.items():
            if lease.get(name) != expected or record.get(name) != expected:
                raise GovernedSignRefused("run_binding_invalid")
        for name, expected in {
            "run_id": evidence["run_id"], "execution_attempt_id": evidence["execution_attempt_id"],
            "lease_id": evidence["lease_id"], "receipt_id": evidence["receipt_id"],
        }.items():
            if execution_receipt.get(name) != expected:
                raise GovernedSignRefused("run_binding_invalid")
        if record.get("receipt_id") != evidence["receipt_id"]:
            raise GovernedSignRefused("run_binding_invalid")
        if challenge["request_sha256"] != req_hash or record["request_sha256"] != req_hash:
            raise GovernedSignRefused("run_binding_invalid")
        if challenge["generation_config_sha256"] != cfg_hash or lease["generation_config_sha256"] != cfg_hash or record["generation_config_sha256"] != cfg_hash:
            raise GovernedSignRefused("run_binding_invalid")
        if lease["model_profile_id"] != model_profile_id(cfg_hash):
            raise GovernedSignRefused("run_binding_invalid")
        # §7 lease-time invariants (fail-closed): lease_issued == challenge_accepted; the lease is
        # exactly LEASE_DURATION_MS long; and execution is fully inside the lease window in order.
        issued = lease["lease_issued_at_ms"]; expires = lease["lease_expires_at_ms"]
        started = execution_receipt["started_at_ms"]; finished = execution_receipt["finished_at_ms"]
        completed = record["completed_at_ms"]
        if lease.get("challenge_accepted_at_ms") != issued:
            raise GovernedSignRefused("run_binding_invalid", "lease_issued != challenge_accepted")
        if expires - issued != LEASE_DURATION_MS:
            raise GovernedSignRefused("run_binding_invalid", "lease duration != LEASE_DURATION_MS")
        if not (issued <= started <= finished <= completed <= expires):
            raise GovernedSignRefused("lease_expired", "execution outside the lease window")
        if now_ms < record["completed_at_ms"] - 60_000 or now_ms - record["completed_at_ms"] > 300_000:
            raise GovernedSignRefused("stale_evidence")
        output_hash = sha256_hex(output)
        if len(output) != record["output_bytes"] or output_hash != record["output_sha256"]:
            raise GovernedSignRefused("hash_mismatch")
        if execution_receipt["output_handle"] != output_hash or execution_receipt["output_sha256"] != output_hash or execution_receipt["output_bytes"] != len(output):
            raise GovernedSignRefused("run_binding_invalid")
        if containment.get("contained") is not True or containment.get("teardown_outcome") != "contained":
            raise GovernedSignRefused("run_binding_invalid")
        for field in ("evidence_event_count", "evidence_last_sequence", "evidence_head_sequence", "evidence_final_event_hash"):
            if record.get(field) != evidence[field]:
                raise GovernedSignRefused("evidence_fork")
        # §7 — durable evidence-head anti-rollback floor, committed BEFORE the envelope is minted:
        # a replayed OLDER head (lower head_sequence) ⇒ stale_evidence; a divergent lineage ⇒
        # evidence_fork; an unchanged re-anchor advances the high-water; a byte-identical re-sign is
        # idempotent. Keyed on (install_id, task_id) in a BEGIN IMMEDIATE tx.
        apply_head_floor(
            c.head_floor_db, evidence["install_id"], evidence["task_id"],
            evidence["evidence_head_sequence"], evidence["evidence_event_count"],
            evidence["evidence_last_sequence"], evidence["evidence_final_event_hash"], now_ms)

        attestation_evidence = canonical_bytes(dict(evidence))
        envelope = {
            "artifact_type": ENVELOPE_TYPE,
            "key_id": c.receipt_signing_key["key_id"],
            "receipt_id": evidence["receipt_id"],
            "run_id": evidence["run_id"],
            "execution_attempt_id": evidence["execution_attempt_id"],
            "task_id": evidence["task_id"],
            "workspace_id": evidence["workspace_id"],
            "install_id": evidence["install_id"],
            "request_nonce": evidence["request_nonce"],
            "request_sha256": req_hash,
            "record_handle": record_handle,
            "lease_handle": evidence["lease_handle"],
            "execution_receipt_handle": evidence["execution_receipt_handle"],
            "output_sha256": output_hash,
            "output_bytes": len(output),
            "challenge_accepted_at_ms": accepted_ms,
            "completed_at_ms": evidence["completed_at_ms"],
            "evidence_final_event_hash": evidence["evidence_final_event_hash"],
            "evidence_event_count": evidence["evidence_event_count"],
            "evidence_last_sequence": evidence["evidence_last_sequence"],
            "evidence_head_sequence": evidence["evidence_head_sequence"],
            "supervisor_attestation_key_id": c.supervisor_attestation_key_id,
            "attestation_evidence_sha256": sha256_hex(attestation_evidence),
        }
        envelope_bytes = canonical_bytes(envelope)
        private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(c.receipt_signing_key["private_key"]))
        signature = private.sign(envelope_bytes)
        return {
            "protocol": RESULT_PROTOCOL, "status": "signed",
            "receipt_id": evidence["receipt_id"],
            "envelope_jcs_b64": b64url_encode(envelope_bytes),
            "signature_b64": b64url_encode(signature),
            "key_id": c.receipt_signing_key["key_id"],
            "attestation_evidence_jcs_b64": b64url_encode(attestation_evidence),
            "attestation_signature_b64": request["attestation"]["sig"],
            "supervisor_attestation_key_id": c.supervisor_attestation_key_id,
            "run_id": evidence["run_id"],
            "execution_attempt_id": evidence["execution_attempt_id"],
            "lease_id": evidence["lease_id"],
            "task_id": evidence["task_id"],
            "challenge_accepted_at_ms": evidence["challenge_accepted_at_ms"],
            "challenge_handle": evidence["challenge_handle"],
            "challenge_key_id": evidence["challenge_key_id"],
            "challenge_registry_handle": evidence["challenge_registry_handle"],
            "challenge_registry_hash": evidence["challenge_registry_hash"],
            "challenge_registry_epoch": evidence["challenge_registry_epoch"],
            "challenge_registry_root_key_id": evidence["challenge_registry_root_key_id"],
            "lease_handle": evidence["lease_handle"],
            "execution_receipt_handle": evidence["execution_receipt_handle"],
            "evidence_event_count": evidence["evidence_event_count"],
            "evidence_last_sequence": evidence["evidence_last_sequence"],
            "evidence_head_sequence": evidence["evidence_head_sequence"],
            "evidence_final_event_hash": evidence["evidence_final_event_hash"],
            "record_handle": record_handle,
            "output_sha256": output_hash, "output_bytes": len(output),
        }
    except (GovernedSignRefused, GovernedProtocolError, EvidenceStoreError, KeyError, TypeError,
            ValueError, sqlite3.DatabaseError) as exc:
        # A head-floor DB fault (lock timeout / corruption) is fail-closed: without the floor we
        # cannot prove the head is not a rollback, so we refuse to sign rather than emit an envelope.
        reason = exc.reason if isinstance(exc, GovernedSignRefused) else "malformed"
        return {"protocol": RESULT_PROTOCOL, "status": "refused", "receipt_id": receipt_id, "reason": reason}


def load_governed_signer_components(env: Mapping[str, str] | None = None) -> GovernedSignerComponents:
    """Load v1B signer trust from the isolated signer's own environment."""
    import os
    import pathlib
    from brops_receipt_signer import load_receipt_signing_key

    e = os.environ if env is None else env
    roots = json.loads(pathlib.Path(e["BROPS_CHALLENGE_ROOTS_FILE"]).read_text("utf-8"))
    if not isinstance(roots, dict) or not roots:
        raise ValueError("challenge root map missing")
    return GovernedSignerComponents(
        store=EvidenceStore(e["BROPS_EVIDENCE_STORE_DIR"]),
        receipt_signing_key=load_receipt_signing_key(e["BROPS_RECEIPT_SIGNER_KEYDIR"]),
        supervisor_attestation_pubkey_hex=e["BROPS_SUPERVISOR_ATTESTATION_PUBKEY"].strip(),
        supervisor_attestation_key_id=e["BROPS_SUPERVISOR_ATTESTATION_KEY_ID"].strip(),
        lease_issuer_pubkey_hex=e["BROPS_LEASE_ISSUER_PUBKEY"].strip(),
        lease_issuer_key_id=e["BROPS_LEASE_ISSUER_KEY_ID"].strip(),
        evidence_recorder_pubkey_hex=e["BROPS_EVIDENCE_RECORDER_PUBKEY"].strip(),
        evidence_recorder_key_id=e["BROPS_EVIDENCE_RECORDER_KEY_ID"].strip(),
        governed_turn_recorder_pubkey_hex=e["BROPS_GOVERNED_TURN_RECORDER_PUBKEY"].strip(),
        governed_turn_recorder_key_id=e["BROPS_GOVERNED_TURN_RECORDER_KEY_ID"].strip(),
        challenge_root_pubkeys_hex={str(k): str(v) for k, v in roots.items()},
        record_dir=pathlib.Path(e["BROPS_GOVERNED_RECORD_DIR"]),
        allowed_executor_ids=frozenset(x.strip() for x in e["BROPS_ALLOWED_EXECUTOR_IDS"].split(",") if x.strip()),
        allowed_runner_ids=frozenset(x.strip() for x in e["BROPS_ALLOWED_RUNNER_IDS"].split(",") if x.strip()),
        allowed_supervisor_ids=frozenset(x.strip() for x in e["BROPS_ALLOWED_SUPERVISOR_IDS"].split(",") if x.strip()),
        expected_policy_id=e["BROPS_EXPECTED_POLICY_ID"].strip(),
        expected_policy_version=e["BROPS_EXPECTED_POLICY_VERSION"].strip(),
        head_floor_db=pathlib.Path(e["BROPS_GOVERNED_HEAD_FLOOR_DB"]),
    )
