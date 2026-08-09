"""Offline tests for ``brops.governed-turn-open.v1`` — rev-30 §4.10(a0) + §2.4 staging.

No socket, no OS trust chain, no key material: signature verification is a real ``hmac``
over the exact canonical bytes, the store is a real content-addressed dict, and the ledger
is a real SQLite file created from the canonical shared DDL. Everything a stranger needs to
run this is in the standard library.

The tests are organized as the design's own obligations:

  * every refusal in the closed §4.10(a0) set is REACHABLE, by name, from a request a
    hostile sidecar could actually send;
  * the §2.4 state machine is driven, and its illegal transitions are refused by the
    DATABASE (raw SQL, bypassing every Python guard) rather than only by code;
  * the P1-5 shape — a requester supplying an id the supervisor must mint — is refused,
    and the staging table has no column that could hold one;
  * the boundaries the design fixes to the millisecond are tested AT the boundary, on both
    sides.
"""

import base64
import hashlib
import hmac
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import challenge_key_registry as ckr  # noqa: E402
import governed_staging_ledger as gsl  # noqa: E402
import governed_supervisor_server as gss  # noqa: E402
import governed_turn_open as gto  # noqa: E402
from governed_supervisor import (  # noqa: E402
    CHALLENGE_PROTOCOL,
    SupervisorConfig,
    SupervisorError,
    recompute_request_sha256,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CHALLENGE_KEY = b"test-challenge-signing-key-not-a-secret"
ROOT_KEY = b"test-registry-root-key-not-a-secret"

SIDECAR_UID = 4101
BROKER_UID = 4102

ROOT_KEY_ID = "chal-root-1"
ROOT_PUBLIC_KEY = "R" * 43          # 43 b64url chars (§4.2), stand-in for the pinned anchor
CHALLENGE_KEY_ID = "chal-key-2026-07"
CHALLENGE_PUBLIC_KEY = "K" * 43

NOW = 1_700_000_100_000
ISSUED = NOW
TTL = 30_000


def _canonical(obj) -> bytes:
    """The governed family's encoding — the exact bytes the challenge authority signs."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _mac(key: bytes, message: bytes) -> str:
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _verify_challenge_sig(message: bytes, sig: str, public_key: str) -> bool:
    """A real MAC check, and it is BOUND TO THE PUBLIC KEY the registry resolved.

    Binding the check to `public_key` is what makes `key_invalid`/`registry_unknown`
    meaningful in these tests: a verifier that ignored the resolved key would pass even when
    the registry named a different one, and the whole registry step would be decorative.
    """
    expected = _mac(CHALLENGE_KEY + public_key.encode("ascii"), message)
    return hmac.compare_digest(expected, sig)


def _sign_challenge(message: bytes, public_key: str = CHALLENGE_PUBLIC_KEY) -> str:
    return _mac(CHALLENGE_KEY + public_key.encode("ascii"), message)


def _verify_root_sig(message: bytes, sig: str, public_key: str) -> bool:
    expected = _mac(ROOT_KEY + public_key.encode("ascii"), message)
    return hmac.compare_digest(expected, sig)


def _registry_payload(*, epoch=7, keys=None):
    return {
        "artifact_type": ckr.REGISTRY_ARTIFACT_TYPE,
        "root_key_id": ROOT_KEY_ID,
        "registry_epoch": epoch,
        "registry_issued_at_ms": 1_600_000_000_000,
        "keys": keys if keys is not None else [_key_entry()],
    }


def _key_entry(*, key_id=CHALLENGE_KEY_ID, public_key=CHALLENGE_PUBLIC_KEY,
               valid_from=1, valid_to=2_000_000_000_000, revoked=False, revoked_at=None):
    return {
        "challenge_key_id": key_id,
        "public_key": public_key,
        "valid_from_ms": valid_from,
        "valid_to_ms": valid_to,
        "key_epoch": 2,
        "revoked": revoked,
        "revoked_at_ms": revoked_at,
    }


def _registry_document(**kwargs):
    payload = _registry_payload(**kwargs)
    return {"payload": payload,
            "root_sig": _mac(ROOT_KEY + ROOT_PUBLIC_KEY.encode("ascii"), _canonical(payload))}


def _payload(*, issued=ISSUED, ttl=TTL, install_id="install-1", nonce="nonce-abc-123",
             supervisor_id="sup-1", key_id=CHALLENGE_KEY_ID, task_id="task-1"):
    payload = {
        "protocol": CHALLENGE_PROTOCOL,
        "challenge_key_id": key_id,
        "run_id": "run-1",
        "task_id": task_id,
        "workspace_id": "ws-1",
        "install_id": install_id,
        "supervisor_id": supervisor_id,
        "request_nonce": nonce,
        "system_sha256": "a" * 64,
        "history_sha256": "b" * 64,
        "generation_config_sha256": "c" * 64,
        "request_sha256": "",
        "requested_at_ms": 1_700_000_000_000,
        "challenge_issued_at_ms": issued,
        "challenge_expires_at_ms": issued + ttl,
    }
    payload["request_sha256"] = recompute_request_sha256(payload)
    return payload


def _document(payload, *, public_key=CHALLENGE_PUBLIC_KEY):
    return {"payload": payload, "sig": _sign_challenge(_canonical(payload), public_key)}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _request(payload=None, *, document=None, document_bytes=None, **overrides):
    if document_bytes is None:
        if document is None:
            document = _document(payload if payload is not None else _payload())
        document_bytes = _canonical(document)
    body = {
        "protocol": gto.OPEN_PROTOCOL,
        "install_id": overrides.pop("install_id", None) or json.loads(document_bytes)["payload"]["install_id"],
        "request_nonce": overrides.pop("request_nonce", None) or json.loads(document_bytes)["payload"]["request_nonce"],
        "challenge_doc_b64": overrides.pop("challenge_doc_b64", None) or _b64(document_bytes),
    }
    body.update(overrides)
    return body


class _Store:
    """A real content-addressed store: the handle IS the digest of the bytes written."""

    def __init__(self):
        self.blobs = {}

    def publish(self, data: bytes) -> str:
        handle = hashlib.sha256(data).hexdigest()
        self.blobs.setdefault(handle, data)
        return handle


def _supervisor_config():
    return SupervisorConfig(
        launcher_executable_sha256="1" * 64,
        executor_executable_sha256="2" * 64,
        id_fn=lambda: "unused",
        supervisor_id="sup-1",
        executor_id="exec-1",
        builder_id="builder-1",
        policy_id="policy-1",
        policy_version="v1",
        policy_bundle_handle="e" * 64,
        challenge_registry_handle="reg-handle",
        challenge_registry_hash="reg-hash",
        challenge_registry_epoch=7,
        challenge_registry_root_key_id=ROOT_KEY_ID,
    )


def _open_config(**kwargs):
    return gto.OpenConfig.from_supervisor_config(
        _supervisor_config(),
        registry_root_public_key=ROOT_PUBLIC_KEY,
        **kwargs,
    )


class _Case(unittest.TestCase):
    """One durable ledger on a REAL file per test (a supervisor with no durable state has
    no authority to admit anything, so the tests do not fake one)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = gsl.open_ledger(str(pathlib.Path(self.tmp.name) / "sup.db"))
        self.addCleanup(self.conn.close)
        self.store = _Store()
        self.registry_document = _registry_document()
        self.clock = NOW

    def _service(self, *, config=None, publish=None, registry_document=None,
                 sidecar_uid=SIDECAR_UID):
        return gto.OpenService(
            config=config or _open_config(),
            allowed_sidecar_uid=sidecar_uid,
            publish_document=publish or self.store.publish,
            resolve_registry_document=(
                lambda: self.registry_document if registry_document is None else registry_document
            ),
            verify_root_sig=_verify_root_sig,
            verify_challenge_sig=_verify_challenge_sig,
        )

    def open(self, request=None, *, peer_uid=SIDECAR_UID, now=None, **service_kwargs):
        service = self._service(**service_kwargs)
        return service.handle(
            request if request is not None else _request(),
            peer_uid=peer_uid,
            conn=self.conn,
            clock_ms=lambda: self.clock if now is None else now,
        )

    def staging_rows(self):
        return self.conn.execute(
            "SELECT * FROM governed_turn_staging ORDER BY created_at_ms"
        ).fetchall()


# ---------------------------------------------------------------------------
# The happy path + what it does and does NOT create
# ---------------------------------------------------------------------------


class OpenAdmitsATurnTests(_Case):
    def test_a_valid_signed_challenge_is_opened_and_staged_uploading(self):
        payload = _payload()
        document_bytes = _canonical(_document(payload))
        reply = self.open(_request(document_bytes=document_bytes))

        self.assertEqual(reply["protocol"], gto.OPEN_RESULT_PROTOCOL)
        self.assertEqual(reply["status"], "opened")
        # §3/§4.10(a0): the handle is SHA256 of the EXACT signed document bytes.
        self.assertEqual(reply["challenge_handle"],
                         hashlib.sha256(document_bytes).hexdigest())

        rows = self.staging_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["state"], gsl.UPLOADING)
        self.assertEqual(row["install_id"], payload["install_id"])
        self.assertEqual(row["request_nonce"], payload["request_nonce"])
        self.assertEqual(row["challenge_expires_at_ms"], payload["challenge_expires_at_ms"])
        # The three digests the VERIFIED challenge committed — copied, never chosen.
        self.assertEqual(row["system_sha256"], payload["system_sha256"])
        self.assertEqual(row["history_sha256"], payload["history_sha256"])
        self.assertEqual(row["generation_config_sha256"], payload["generation_config_sha256"])
        # No input has been published yet, so no handle is recorded.
        self.assertIsNone(row["system_handle"])
        self.assertIsNone(row["history_handle"])
        self.assertIsNone(row["generation_config_handle"])

    def test_the_exact_document_bytes_are_published_into_the_store(self):
        document_bytes = _canonical(_document(_payload()))
        reply = self.open(_request(document_bytes=document_bytes))
        self.assertEqual(self.store.blobs[reply["challenge_handle"]], document_bytes)

    def test_open_creates_no_acceptance_row_and_no_execution_attempt(self):
        """The whole point of §4.10(a0): admission is not acceptance."""
        self.open()
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM governed_turn_acceptance").fetchone()[0], 0
        )

    def test_the_staging_table_has_no_execution_attempt_id_column(self):
        """P1-5, at the schema level: there is nowhere to put a caller-minted attempt id."""
        columns = {
            r[1] for r in self.conn.execute("PRAGMA table_info(governed_turn_staging)")
        }
        self.assertNotIn("execution_attempt_id", columns)
        self.assertNotIn("lease_id", columns)
        self.assertNotIn("challenge_accepted_at_ms", columns)

    def test_the_admission_clock_read_is_not_persisted_anywhere(self):
        """§4.10(a0): the resource-admission ``now_ms`` is discarded, never stamped."""
        self.clock = 1_700_000_123_456
        self.open()
        row = self.staging_rows()[0]
        # created/updated are the ledger's own row timestamps; nothing stores it as an
        # acceptance time, and no column claims to be one.
        self.assertNotIn("challenge_accepted_at_ms", row.keys())


# ---------------------------------------------------------------------------
# P1-5 — the requester may not mint what the supervisor mints
# ---------------------------------------------------------------------------


class RequesterSuppliedIdIsRefusedTests(_Case):
    def test_a_request_carrying_execution_attempt_id_is_refused_malformed(self):
        reply = self.open(_request(execution_attempt_id="attacker-chosen-attempt"))
        self.assertEqual(reply["status"], "refused")
        self.assertEqual(reply["reason"], gto.REFUSE_MALFORMED)
        self.assertEqual(self.staging_rows(), [])
        self.assertEqual(self.store.blobs, {})

    def test_the_other_supervisor_minted_ids_are_refused_the_same_way(self):
        for field in ("lease_id", "receipt_id", "challenge_accepted_at_ms", "challenge_handle"):
            with self.subTest(field=field):
                reply = self.open(_request(**{field: "x"}))
                self.assertEqual(reply["reason"], gto.REFUSE_MALFORMED)
                self.assertEqual(self.staging_rows(), [])

    def test_the_request_field_set_is_exactly_the_four_named_fields(self):
        self.assertEqual(
            gto.OPEN_REQUEST_FIELDS,
            ("protocol", "install_id", "request_nonce", "challenge_doc_b64"),
        )


# ---------------------------------------------------------------------------
# Every refusal in the closed set, reachable by name
# ---------------------------------------------------------------------------


class RefusalsAreReachableTests(_Case):
    def test_peer_denied_for_a_non_sidecar_peer(self):
        reply = self.open(peer_uid=BROKER_UID)
        self.assertEqual(reply["reason"], gto.REFUSE_PEER_DENIED)
        self.assertEqual(self.staging_rows(), [])

    def test_peer_denied_when_no_sidecar_principal_is_configured(self):
        """A supervisor with no ``OpenService`` serves this protocol to nobody."""
        reply = gss.dispatch(
            _request(), _supervisor_config(), lambda *a: True, recompute_request_sha256,
            lambda: NOW, conn=self.conn, open_service=None, peer_uid=SIDECAR_UID,
        )
        self.assertEqual(reply["reason"], gto.REFUSE_PEER_DENIED)

    def test_doc_oversize_on_a_decoded_document_over_4096_bytes(self):
        payload = _payload()
        payload["task_id"] = "t" * 5000
        payload["request_sha256"] = recompute_request_sha256(payload)
        document_bytes = _canonical(_document(payload))
        self.assertGreater(len(document_bytes), gto.MAX_CHALLENGE_DOC_BYTES)
        reply = self.open(_request(document_bytes=document_bytes))
        self.assertEqual(reply["reason"], gto.REFUSE_DOC_OVERSIZE)

    def test_doc_oversize_boundary_exact_4096_is_admitted(self):
        """The cap is ``<= 4096``; a document of exactly 4096 bytes must pass it."""
        payload = _payload()
        # `task_id` is not part of the request envelope, so padding it changes the
        # document length and nothing else. Solve for the exact cap rather than guessing.
        pad = gto.MAX_CHALLENGE_DOC_BYTES - len(_canonical(_document(payload)))
        payload["task_id"] = payload["task_id"] + "t" * pad
        document_bytes = _canonical(_document(payload))
        self.assertEqual(len(document_bytes), gto.MAX_CHALLENGE_DOC_BYTES)
        reply = self.open(_request(document_bytes=document_bytes))
        self.assertEqual(reply["status"], "opened")

    def test_doc_oversize_at_cap_plus_one_is_caught_by_the_DECODED_cap(self):
        """One byte over, and small enough that the encoded-length pre-check cannot catch it.

        The pre-check on the base64 string exists only to bound allocation; the verdict
        §4.10(a0) specifies is about the DECODED size. A document at 4097 bytes still
        encodes well under the pre-check threshold, so only the decoded cap can refuse it —
        which is the point of testing here rather than at 5 KiB.
        """
        payload = _payload()
        pad = gto.MAX_CHALLENGE_DOC_BYTES + 1 - len(_canonical(_document(payload)))
        payload["task_id"] = payload["task_id"] + "t" * pad
        document_bytes = _canonical(_document(payload))
        self.assertEqual(len(document_bytes), gto.MAX_CHALLENGE_DOC_BYTES + 1)
        encoded = _b64(document_bytes)
        self.assertLessEqual(len(encoded), 4 * ((gto.MAX_CHALLENGE_DOC_BYTES + 2) // 3) + 4)
        reply = self.open(_request(document_bytes=document_bytes))
        self.assertEqual(reply["reason"], gto.REFUSE_DOC_OVERSIZE)

    def test_malformed_on_base64_that_decodes_correctly_but_is_not_canonical(self):
        """Two encodings, one document — refused, because only one of them was sent.

        base64 leaves spare bits in the final character whenever the input length is not a
        multiple of 3, so several distinct strings decode to identical bytes. Accepting all
        of them would mean the transported string and the bytes the handle covers are not in
        one-to-one correspondence, which is exactly the divergence the canonicality gate
        exists to forbid one layer up.
        """
        # Spare bits only exist when the byte length is not a multiple of 3, so pad the
        # (signature-irrelevant) task_id until the document lands on such a length.
        for extra in range(3):
            payload = _payload()
            payload["task_id"] = payload["task_id"] + "t" * extra
            document_bytes = _canonical(_document(payload))
            if len(document_bytes) % 3:
                break
        encoded = _b64(document_bytes)
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        alias = None
        for ch in alphabet:
            if ch == encoded[-1]:
                continue
            candidate = encoded[:-1] + ch
            try:
                decoded = base64.urlsafe_b64decode(candidate + "=" * (-len(candidate) % 4))
            except Exception:
                continue
            if decoded == document_bytes:
                alias = candidate
                break
        self.assertIsNotNone(alias, "no non-canonical alias exists for this length")
        reply = self.open(_request(challenge_doc_b64=alias))
        self.assertEqual(reply["reason"], gto.REFUSE_MALFORMED)
        self.assertEqual(self.staging_rows(), [])

    def test_malformed_on_a_duplicate_key_in_the_challenge_document(self):
        payload = _payload()
        good = _canonical(_document(payload)).decode("utf-8")
        # A duplicate top-level key that `json.loads` would otherwise silently collapse.
        dup = good[:-1] + ',"sig":"x"}'
        reply = self.open(_request(document_bytes=dup.encode("utf-8")))
        self.assertEqual(reply["reason"], gto.REFUSE_MALFORMED)

    def test_malformed_on_an_extra_field_in_the_challenge_payload(self):
        payload = _payload()
        payload["extra"] = "smuggled"
        reply = self.open(_request(document_bytes=_canonical(_document(payload))))
        self.assertEqual(reply["reason"], gto.REFUSE_MALFORMED)

    def test_malformed_on_non_base64url_input(self):
        reply = self.open(_request(challenge_doc_b64="not valid base64!!"))
        self.assertEqual(reply["reason"], gto.REFUSE_MALFORMED)

    def test_noncanonical_on_bytes_that_are_not_the_canonical_encoding(self):
        """Same document, whitespace-padded: the signature still verifies, the gate does not."""
        document = _document(_payload())
        pretty = json.dumps(document, sort_keys=True, indent=1).encode("utf-8")
        reply = self.open(_request(document_bytes=pretty))
        self.assertEqual(reply["reason"], gto.REFUSE_NONCANONICAL)
        self.assertEqual(self.store.blobs, {})

    def test_noncanonical_on_reordered_keys(self):
        payload = _payload()
        document = _document(payload)
        reordered = ('{"sig":' + json.dumps(document["sig"]) + ',"payload":'
                     + json.dumps(document["payload"], sort_keys=True, separators=(",", ":")) + "}")
        reply = self.open(_request(document_bytes=reordered.encode("utf-8")))
        self.assertEqual(reply["reason"], gto.REFUSE_NONCANONICAL)

    def test_noncanonical_when_the_two_canonicalizers_disagree(self):
        """The strict intersection, at the only place the two encoders differ.

        §4.10(a0) names ``bro_signature.canonical_bytes`` (``ensure_ascii=False``); the
        governed chain actually signs with ``ensure_ascii=True``. A non-ASCII id is the ONLY
        input on which those disagree, and this document is genuinely canonical under the
        signer's encoder — its signature verifies. It is refused anyway, because a document
        only one of the two encoders calls canonical is one the design and the tree would
        address differently, and the supervisor takes the stricter reading.
        """
        payload = _payload(task_id="tåsk-1")
        document_bytes = _canonical(_document(payload))     # ensure_ascii=True: escaped
        self.assertIn(b"\\u00e5", document_bytes)
        self.assertNotIn("å".encode("utf-8"), document_bytes)
        reply = self.open(_request(document_bytes=document_bytes))
        self.assertEqual(reply["reason"], gto.REFUSE_NONCANONICAL)
        self.assertEqual(self.store.blobs, {})

    def test_registry_unknown_when_the_root_signature_does_not_verify(self):
        bad = _registry_document()
        bad["root_sig"] = "0" * 64
        reply = self.open(registry_document=bad)
        self.assertEqual(reply["reason"], gto.REFUSE_REGISTRY_UNKNOWN)

    def test_registry_unknown_when_the_registry_names_another_root(self):
        payload = _registry_payload()
        payload["root_key_id"] = "some-other-root"
        doc = {"payload": payload,
               "root_sig": _mac(ROOT_KEY + ROOT_PUBLIC_KEY.encode("ascii"), _canonical(payload))}
        reply = self.open(registry_document=doc)
        self.assertEqual(reply["reason"], gto.REFUSE_REGISTRY_UNKNOWN)

    def test_registry_unknown_on_a_rolled_back_epoch(self):
        reply = self.open(
            config=_open_config(registry_epoch_floor=9),
            registry_document=_registry_document(epoch=7),
        )
        self.assertEqual(reply["reason"], gto.REFUSE_REGISTRY_UNKNOWN)

    def test_registry_unknown_when_the_challenge_key_is_not_in_the_snapshot(self):
        reply = self.open(
            _request(_payload(key_id="a-key-nobody-registered")),
        )
        self.assertEqual(reply["reason"], gto.REFUSE_REGISTRY_UNKNOWN)

    def test_registry_unknown_when_the_resolver_itself_fails(self):
        def boom():
            raise OSError("registry file unreadable")

        service = gto.OpenService(
            config=_open_config(), allowed_sidecar_uid=SIDECAR_UID,
            publish_document=self.store.publish, resolve_registry_document=boom,
            verify_root_sig=_verify_root_sig, verify_challenge_sig=_verify_challenge_sig,
        )
        reply = service.handle(_request(), peer_uid=SIDECAR_UID, conn=self.conn,
                               clock_ms=lambda: NOW)
        self.assertEqual(reply["reason"], gto.REFUSE_REGISTRY_UNKNOWN)

    def test_key_invalid_when_the_key_was_not_yet_valid_at_issue_time(self):
        doc = _registry_document(keys=[_key_entry(valid_from=ISSUED + 1)])
        reply = self.open(registry_document=doc)
        self.assertEqual(reply["reason"], gto.REFUSE_KEY_INVALID)

    def test_key_invalid_when_the_key_was_revoked_at_or_before_issue_time(self):
        doc = _registry_document(
            keys=[_key_entry(revoked=True, revoked_at=ISSUED)]
        )
        reply = self.open(registry_document=doc)
        self.assertEqual(reply["reason"], gto.REFUSE_KEY_INVALID)

    def test_sig_invalid_on_a_forged_signature(self):
        document = _document(_payload())
        document["sig"] = "f" * 64
        reply = self.open(_request(document_bytes=_canonical(document)))
        self.assertEqual(reply["reason"], gto.REFUSE_SIG_INVALID)
        self.assertEqual(self.staging_rows(), [])

    def test_sig_invalid_when_the_challenge_was_signed_under_a_different_key(self):
        """A genuine signature by a key the registry did not resolve is still no signature."""
        payload = _payload()
        document = {"payload": payload,
                    "sig": _sign_challenge(_canonical(payload), "Z" * 43)}
        reply = self.open(_request(document_bytes=_canonical(document)))
        self.assertEqual(reply["reason"], gto.REFUSE_SIG_INVALID)

    def test_context_mismatch_when_the_request_install_id_is_not_the_signed_one(self):
        document_bytes = _canonical(_document(_payload()))
        request = _request(document_bytes=document_bytes)
        request["install_id"] = "install-someone-else"
        reply = self.open(request)
        self.assertEqual(reply["reason"], gto.REFUSE_CONTEXT_MISMATCH)

    def test_context_mismatch_when_the_request_nonce_is_not_the_signed_one(self):
        document_bytes = _canonical(_document(_payload()))
        request = _request(document_bytes=document_bytes)
        request["request_nonce"] = "a-different-nonce"
        reply = self.open(request)
        self.assertEqual(reply["reason"], gto.REFUSE_CONTEXT_MISMATCH)

    def test_context_mismatch_when_the_challenge_names_another_supervisor(self):
        reply = self.open(_request(_payload(supervisor_id="sup-2")))
        self.assertEqual(reply["reason"], gto.REFUSE_CONTEXT_MISMATCH)

    def test_context_mismatch_when_request_sha256_does_not_re_derive(self):
        payload = _payload()
        payload["request_sha256"] = "9" * 64
        reply = self.open(_request(document_bytes=_canonical(_document(payload))))
        self.assertEqual(reply["reason"], gto.REFUSE_CONTEXT_MISMATCH)

    def test_challenge_expired_one_ms_past_the_boundary(self):
        payload = _payload()
        reply = self.open(_request(document_bytes=_canonical(_document(payload))),
                          now=payload["challenge_expires_at_ms"] + 1)
        self.assertEqual(reply["reason"], gto.REFUSE_CHALLENGE_EXPIRED)
        # "A `challenge_expired` refusal creates NO staging row, publishes nothing."
        self.assertEqual(self.staging_rows(), [])
        self.assertEqual(self.store.blobs, {})

    def test_challenge_expired_boundary_is_inclusive_and_admits_now_equal_expiry(self):
        payload = _payload()
        reply = self.open(_request(document_bytes=_canonical(_document(payload))),
                          now=payload["challenge_expires_at_ms"])
        self.assertEqual(reply["status"], "opened")

    def test_handle_mismatch_when_the_store_returns_a_different_handle(self):
        reply = self.open(publish=lambda data: "0" * 64)
        self.assertEqual(reply["reason"], gto.REFUSE_HANDLE_MISMATCH)
        self.assertEqual(self.staging_rows(), [])

    def test_handle_mismatch_when_the_store_raises(self):
        def broken(data):
            raise OSError("store unwritable")

        reply = self.open(publish=broken)
        self.assertEqual(reply["reason"], gto.REFUSE_HANDLE_MISMATCH)
        self.assertEqual(self.staging_rows(), [])

    def test_retry_conflict_on_a_different_challenge_under_the_same_nonce(self):
        self.assertEqual(self.open()["status"], "opened")
        # Same (install_id, request_nonce), different turn.
        other = _payload(task_id="task-2")
        reply = self.open(_request(document_bytes=_canonical(_document(other))))
        self.assertEqual(reply["reason"], gto.REFUSE_RETRY_CONFLICT)
        self.assertEqual(len(self.staging_rows()), 1)

    def test_retry_conflict_when_the_same_challenge_reappears_under_a_new_nonce(self):
        """A replayed document wearing a new label collides on ``UNIQUE(challenge_handle)``."""
        payload = _payload()
        document_bytes = _canonical(_document(payload))
        self.assertEqual(self.open(_request(document_bytes=document_bytes))["status"], "opened")

        request = _request(document_bytes=document_bytes)
        request["request_nonce"] = "nonce-2"
        # The request nonce must still match the signed one, so this is refused earlier —
        # by the context binding. Drive the UNIQUE directly with a re-signed twin instead.
        self.assertEqual(self.open(request)["reason"], gto.REFUSE_CONTEXT_MISMATCH)

        with self.assertRaises(gsl.Conflict):
            gsl.open_staging(
                self.conn,
                gsl.NewStaging(
                    install_id=payload["install_id"], request_nonce="nonce-2",
                    challenge_handle=hashlib.sha256(document_bytes).hexdigest(),
                    run_id=payload["run_id"], task_id=payload["task_id"],
                    workspace_id=payload["workspace_id"],
                    system_sha256=payload["system_sha256"],
                    history_sha256=payload["history_sha256"],
                    generation_config_sha256=payload["generation_config_sha256"],
                    challenge_expires_at_ms=payload["challenge_expires_at_ms"],
                ),
                NOW,
            )

    def test_a_replayed_challenge_handle_is_a_conflict_even_when_the_install_is_at_quota(self):
        """Identity is resolved BEFORE resource limits, so a replay is named as a replay.

        If the quota check ran first, a replayed ``challenge_handle`` arriving while the
        install happened to be full would be reported as ``quota_turns`` — telling the caller
        to wait and retry a document that must never be admitted again, and hiding a replay
        behind a capacity message. The verdict must not depend on how busy the install is.
        """
        payload = _payload()
        for n in range(gsl.MAX_CONCURRENT_GOVERNED_TURNS):
            self.assertEqual(self.open(_request(_payload(nonce="nonce-%d" % n)))["status"],
                             "opened")
        replay = gsl.NewStaging(
            install_id=payload["install_id"], request_nonce="a-brand-new-nonce",
            # The handle already staged by the first open above.
            challenge_handle=self.staging_rows()[0]["challenge_handle"],
            run_id=payload["run_id"], task_id=payload["task_id"],
            workspace_id=payload["workspace_id"],
            system_sha256=payload["system_sha256"], history_sha256=payload["history_sha256"],
            generation_config_sha256=payload["generation_config_sha256"],
            challenge_expires_at_ms=payload["challenge_expires_at_ms"],
        )
        with self.assertRaises(gsl.Conflict):
            gsl.open_staging(self.conn, replay, NOW)

    def test_quota_turns_on_the_third_concurrent_live_turn(self):
        for n in range(gsl.MAX_CONCURRENT_GOVERNED_TURNS):
            reply = self.open(_request(_payload(nonce="nonce-%d" % n)))
            self.assertEqual(reply["status"], "opened", reply)
        reply = self.open(_request(_payload(nonce="nonce-overflow")))
        self.assertEqual(reply["reason"], gto.REFUSE_QUOTA_TURNS)
        self.assertEqual(len(self.staging_rows()), gsl.MAX_CONCURRENT_GOVERNED_TURNS)

    def test_the_closed_reason_set_is_exactly_the_one_the_design_enumerates(self):
        """A reply reason outside this set would fall through the sidecar's §4.10(h)
        diagnostic routing table (NOT IMPLEMENTED — a later ordered piece), so the set is
        asserted against the design's literal list rather than derived from the code it is
        supposed to be checking."""
        self.assertEqual(
            set(gto.OPEN_REFUSAL_REASONS),
            {
                "peer_denied", "doc_oversize", "malformed", "noncanonical",
                "handle_mismatch", "registry_unknown", "key_invalid", "sig_invalid",
                "context_mismatch", "challenge_expired", "retry_conflict", "quota_turns",
            },
        )


# ---------------------------------------------------------------------------
# Idempotency (P1-6)
# ---------------------------------------------------------------------------


class IdempotentReopenTests(_Case):
    def test_a_byte_identical_reopen_returns_the_same_handle_and_one_row(self):
        request = _request()
        first = self.open(request)
        second = self.open(request)
        self.assertEqual(first, second)
        self.assertEqual(len(self.staging_rows()), 1)

    def test_the_expiry_gate_is_evaluated_on_the_idempotent_reopen_too(self):
        """§4.10(a0): "The gate is evaluated on EVERY open (first AND idempotent re-open)"."""
        payload = _payload()
        request = _request(document_bytes=_canonical(_document(payload)))
        self.assertEqual(self.open(request)["status"], "opened")
        reply = self.open(request, now=payload["challenge_expires_at_ms"] + 1)
        self.assertEqual(reply["reason"], gto.REFUSE_CHALLENGE_EXPIRED)
        # The original row survives: a refused re-open changes nothing.
        self.assertEqual(len(self.staging_rows()), 1)

    def test_an_expired_row_does_not_occupy_a_quota_slot(self):
        """§2.4 live-count rule (P1-3): expired rows are not counted, swept or not."""
        short = _payload(nonce="short", issued=ISSUED, ttl=1_000)
        self.assertEqual(self.open(_request(short))["status"], "opened")
        self.assertEqual(self.open(_request(_payload(nonce="n2")))["status"], "opened")

        after = short["challenge_expires_at_ms"] + 1
        # Three rows would exceed MAX_CONCURRENT_GOVERNED_TURNS if the expired one counted.
        third = _payload(nonce="n3", issued=after, ttl=TTL)
        reply = self.open(_request(third), now=after)
        self.assertEqual(reply["status"], "opened", reply)
        self.assertEqual(len(self.staging_rows()), 3)
        self.assertEqual(gsl.count_live_turns(self.conn, "install-1", after), 2)


# ---------------------------------------------------------------------------
# §2.4 states — enforced by the DATABASE, not only by code
# ---------------------------------------------------------------------------


class StagingStateMachineTests(_Case):
    def _row(self):
        self.open()
        return self.staging_rows()[0]

    def test_the_state_domain_is_closed_by_a_check_constraint(self):
        self._row()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE governed_turn_staging SET state = 'FINISHED'")

    def test_the_check_constraint_holds_on_its_own_with_the_triggers_dropped(self):
        """Each layer proved SEPARATELY, because together they mask each other.

        With both triggers in place, an out-of-domain state is refused by the transition
        trigger before the CHECK is ever consulted — so the test above passes even if the
        CHECK is deleted. Dropping the triggers isolates the constraint and shows the closed
        domain is enforced by the column itself, which is what survives a future edit to
        either trigger.
        """
        bare = sqlite3.connect(":memory:")
        self.addCleanup(bare.close)
        bare.executescript(
            (ROOT / "runtime" / "supervisor_ledger.sql").read_text(encoding="utf-8"))
        bare.execute("DROP TRIGGER trg_governed_turn_staging_insert_state")
        bare.execute("DROP TRIGGER trg_governed_turn_staging_transition")
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            bare.execute(
                "INSERT INTO governed_turn_staging (install_id, request_nonce,"
                " challenge_handle, run_id, task_id, workspace_id, system_sha256,"
                " history_sha256, generation_config_sha256, state,"
                " challenge_expires_at_ms, created_at_ms, updated_at_ms)"
                " VALUES ('i','n',?,'r','t','w',?,?,?,'INPUTS_READY_PROBABLY',1,1,1)",
                ("d" * 64, "a" * 64, "b" * 64, "c" * 64),
            )
        self.assertIn("CHECK constraint failed", str(ctx.exception))

    def test_a_row_may_only_be_created_verifying(self):
        """Nothing may declare its way to ``INPUTS_READY`` without publishing anything."""
        for state in (gsl.UPLOADING, gsl.INPUTS_READY):
            with self.subTest(state=state):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.conn.execute(
                        "INSERT INTO governed_turn_staging (install_id, request_nonce,"
                        " challenge_handle, run_id, task_id, workspace_id, system_sha256,"
                        " history_sha256, generation_config_sha256, state,"
                        " challenge_expires_at_ms, created_at_ms, updated_at_ms)"
                        " VALUES ('i','n-%s',?,'r','t','w',?,?,?,?,1,1,1)" % state,
                        ("d" * 64, "a" * 64, "b" * 64, "c" * 64, state),
                    )
                self.assertIn("must be created VERIFYING", str(ctx.exception))

    def test_the_two_legal_edges_are_permitted(self):
        row = self._row()
        self.assertEqual(row["state"], gsl.UPLOADING)   # VERIFYING -> UPLOADING already ran
        self.conn.execute(
            "UPDATE governed_turn_staging SET state = ? WHERE challenge_handle = ?",
            (gsl.INPUTS_READY, row["challenge_handle"]),
        )
        self.assertEqual(self.staging_rows()[0]["state"], gsl.INPUTS_READY)

    def test_skipping_uploading_to_reach_inputs_ready_is_refused_by_the_database(self):
        # Raw SQL: a fresh VERIFYING row, then the illegal jump, with no Python guard between.
        self.conn.execute(
            "INSERT INTO governed_turn_staging (install_id, request_nonce, challenge_handle,"
            " run_id, task_id, workspace_id, system_sha256, history_sha256,"
            " generation_config_sha256, state, challenge_expires_at_ms, created_at_ms,"
            " updated_at_ms) VALUES ('i','n',?,'r','t','w',?,?,?,'VERIFYING',1,1,1)",
            ("d" * 64, "a" * 64, "b" * 64, "c" * 64),
        )
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.conn.execute(
                "UPDATE governed_turn_staging SET state = 'INPUTS_READY' WHERE request_nonce = 'n'")
        self.assertIn("illegal staging state transition", str(ctx.exception))

    def test_moving_backwards_is_refused_by_the_database(self):
        row = self._row()
        self.conn.execute(
            "UPDATE governed_turn_staging SET state = 'INPUTS_READY' WHERE challenge_handle = ?",
            (row["challenge_handle"],),
        )
        for target in ("UPLOADING", "VERIFYING"):
            with self.subTest(target=target):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(
                        "UPDATE governed_turn_staging SET state = ? WHERE challenge_handle = ?",
                        (target, row["challenge_handle"]),
                    )

    def test_recording_a_published_handle_is_allowed_without_changing_state(self):
        row = self._row()
        self.conn.execute(
            "UPDATE governed_turn_staging SET system_handle = ?, state = state"
            " WHERE challenge_handle = ?",
            ("f" * 64, row["challenge_handle"]),
        )
        self.assertEqual(self.staging_rows()[0]["system_handle"], "f" * 64)

    def test_the_challenge_binding_is_immutable_in_the_database(self):
        row = self._row()
        for column, value in (("challenge_handle", "9" * 64), ("task_id", "task-hijacked"),
                              ("install_id", "install-2"), ("system_sha256", "9" * 64),
                              ("challenge_expires_at_ms", 99)):
            with self.subTest(column=column):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.conn.execute(
                        "UPDATE governed_turn_staging SET %s = ? WHERE rowid = ?" % column,
                        (value, row["rowid"] if "rowid" in row.keys() else 1),
                    )
                self.assertIn("binding is immutable", str(ctx.exception))

    def test_the_two_unique_constraints_exist(self):
        self._row()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO governed_turn_staging (install_id, request_nonce, challenge_handle,"
                " run_id, task_id, workspace_id, system_sha256, history_sha256,"
                " generation_config_sha256, state, challenge_expires_at_ms, created_at_ms,"
                " updated_at_ms) VALUES ('install-1','nonce-abc-123',?,'r','t','w',?,?,?,"
                "'VERIFYING',1,1,1)",
                ("9" * 64, "a" * 64, "b" * 64, "c" * 64),
            )

    def test_a_corrupt_or_foreign_row_state_is_refused_not_interpreted(self):
        """A stored state outside the closed domain means a corrupt or foreign DB.

        The CHECK stops this ledger from ever writing one, so the guard is proved against a
        DB that has the same table name and no CHECK — exactly what "somebody handed the
        supervisor a different file" looks like. Coercing such a row to the nearest state it
        resembles is how a row nobody wrote becomes a row somebody trusts.
        """
        foreign = sqlite3.connect(":memory:")
        self.addCleanup(foreign.close)
        foreign.row_factory = sqlite3.Row
        foreign.execute(
            "CREATE TABLE governed_turn_staging (install_id TEXT, request_nonce TEXT,"
            " challenge_handle TEXT, state TEXT)")
        foreign.execute(
            "INSERT INTO governed_turn_staging VALUES ('i','n',?,'INPUTS_READY_PROBABLY')",
            ("d" * 64,))
        with self.assertRaises(gsl.Corrupt):
            gsl.load_staging(foreign, "i", "n")
        with self.assertRaises(gsl.Corrupt):
            gsl.load_staging_by_handle(foreign, "d" * 64)


# ---------------------------------------------------------------------------
# §4.2 registry — the half §4.10(a0) leans on
# ---------------------------------------------------------------------------


class RegistryDocumentTests(unittest.TestCase):
    def _resolve(self, document, epoch_floor=0):
        return ckr.resolve_registry(
            document,
            anchor=ckr.RootAnchor(root_key_id=ROOT_KEY_ID, public_key=ROOT_PUBLIC_KEY),
            epoch_floor=epoch_floor,
            verify_root_sig=_verify_root_sig,
        )

    def test_a_root_signed_registry_resolves_with_two_distinct_digests(self):
        document = _registry_document()
        snapshot, reason = self._resolve(document)
        self.assertIsNone(reason)
        self.assertNotEqual(snapshot.registry_hash, snapshot.registry_handle)
        self.assertEqual(snapshot.registry_hash,
                         hashlib.sha256(_canonical(document["payload"])).hexdigest())
        self.assertEqual(snapshot.registry_handle,
                         hashlib.sha256(_canonical(document)).hexdigest())

    def test_revoked_true_with_a_null_time_is_refused(self):
        doc = _registry_document(keys=[_key_entry(revoked=True, revoked_at=None)])
        self.assertEqual(self._resolve(doc)[1], ckr.REGISTRY_UNKNOWN)

    def test_revoked_false_with_a_non_null_time_is_refused(self):
        doc = _registry_document(keys=[_key_entry(revoked=False, revoked_at=5)])
        self.assertEqual(self._resolve(doc)[1], ckr.REGISTRY_UNKNOWN)

    def test_revoked_at_before_valid_from_is_refused(self):
        doc = _registry_document(
            keys=[_key_entry(valid_from=1000, revoked=True, revoked_at=999)])
        self.assertEqual(self._resolve(doc)[1], ckr.REGISTRY_UNKNOWN)

    def test_duplicate_challenge_key_ids_are_refused(self):
        doc = _registry_document(keys=[_key_entry(), _key_entry()])
        self.assertEqual(self._resolve(doc)[1], ckr.REGISTRY_UNKNOWN)

    def test_more_than_256_keys_is_refused(self):
        keys = [_key_entry(key_id="k-%d" % i) for i in range(ckr.MAX_REGISTRY_KEYS + 1)]
        self.assertEqual(self._resolve(_registry_document(keys=keys))[1], ckr.REGISTRY_UNKNOWN)

    def test_a_seconds_not_ms_timestamp_is_out_of_the_canonical_range(self):
        payload = _registry_payload()
        payload["registry_issued_at_ms"] = 0     # below the §1 lower bound of 1
        doc = {"payload": payload,
               "root_sig": _mac(ROOT_KEY + ROOT_PUBLIC_KEY.encode("ascii"), _canonical(payload))}
        self.assertEqual(self._resolve(doc)[1], ckr.REGISTRY_UNKNOWN)

    def test_an_unknown_artifact_type_is_refused(self):
        payload = _registry_payload()
        payload["artifact_type"] = "brops.something-else.v1"
        doc = {"payload": payload,
               "root_sig": _mac(ROOT_KEY + ROOT_PUBLIC_KEY.encode("ascii"), _canonical(payload))}
        self.assertEqual(self._resolve(doc)[1], ckr.REGISTRY_UNKNOWN)

    def test_key_selection_boundaries(self):
        snapshot, _ = self._resolve(
            _registry_document(keys=[_key_entry(valid_from=100, valid_to=200)]))
        # Inclusive at BOTH ends (§1).
        self.assertIsNotNone(ckr.select_key(snapshot, CHALLENGE_KEY_ID, 100)[0])
        self.assertIsNotNone(ckr.select_key(snapshot, CHALLENGE_KEY_ID, 200)[0])
        self.assertEqual(ckr.select_key(snapshot, CHALLENGE_KEY_ID, 99)[1], ckr.KEY_INVALID)
        self.assertEqual(ckr.select_key(snapshot, CHALLENGE_KEY_ID, 201)[1], ckr.KEY_INVALID)

    def test_revocation_boundary_is_strict(self):
        snapshot, _ = self._resolve(_registry_document(
            keys=[_key_entry(valid_from=100, valid_to=200, revoked=True, revoked_at=150)]))
        self.assertIsNotNone(ckr.select_key(snapshot, CHALLENGE_KEY_ID, 149)[0])
        # `revoked_at_ms > t` is required, so t == revoked_at is already unusable.
        self.assertEqual(ckr.select_key(snapshot, CHALLENGE_KEY_ID, 150)[1], ckr.KEY_INVALID)

    def test_a_verifier_that_raises_is_contained_as_a_refusal(self):
        def boom(message, sig, public_key):
            raise RuntimeError("hostile key material")

        snapshot, reason = ckr.resolve_registry(
            _registry_document(),
            anchor=ckr.RootAnchor(root_key_id=ROOT_KEY_ID, public_key=ROOT_PUBLIC_KEY),
            epoch_floor=0, verify_root_sig=boom,
        )
        self.assertIsNone(snapshot)
        self.assertEqual(reason, ckr.REGISTRY_UNKNOWN)


# ---------------------------------------------------------------------------
# Front door — the sidecar's grant is exactly one protocol wide
# ---------------------------------------------------------------------------


class _Conn:
    def __init__(self, peer_uid, body: bytes = b""):
        self.peer_uid = peer_uid
        self._in = len(body).to_bytes(4, "big") + body
        self._pos = 0
        self.out = b""

    def recv_exactly(self, n):
        chunk = self._in[self._pos:self._pos + n]
        self._pos += n
        return chunk

    def send_all(self, data):
        self.out += data

    def close(self):
        pass

    def reply(self):
        length = int.from_bytes(self.out[:4], "big")
        return json.loads(self.out[4:4 + length].decode("utf-8"))


class FrontDoorTests(_Case):
    def _handle(self, conn, *, sidecar_uid=SIDECAR_UID, broker_uid=BROKER_UID):
        return gss.handle_connection(
            conn, broker_uid, _supervisor_config(), lambda *a: True,
            recompute_request_sha256, lambda: NOW,
            ledger_conn=self.conn,
            open_service=self._service(sidecar_uid=sidecar_uid) if sidecar_uid is not None else None,
        )

    def test_the_sidecar_may_send_governed_turn_open(self):
        body = json.dumps(_request()).encode("utf-8")
        conn = _Conn(SIDECAR_UID, body)
        reply = self._handle(conn)
        self.assertEqual(reply["status"], "opened")

    def test_the_sidecar_may_not_send_any_op(self):
        body = json.dumps({"op": "attest-run", "run_id": "r",
                           "execution_attempt_id": "a"}).encode("utf-8")
        reply = self._handle(_Conn(SIDECAR_UID, body))
        self.assertEqual(reply, {"ok": False, "error": "peer not authorized"})

    def test_an_unknown_uid_is_refused_before_any_frame_is_read(self):
        reply = self._handle(_Conn(999, b"{}"))
        self.assertEqual(reply, {"ok": False, "error": "peer not authorized"})

    def test_the_broker_sending_governed_turn_open_is_peer_denied(self):
        body = json.dumps(_request()).encode("utf-8")
        reply = self._handle(_Conn(BROKER_UID, body))
        self.assertEqual(reply["reason"], gto.REFUSE_PEER_DENIED)

    def test_a_collapsed_sidecar_broker_uid_is_refused_outright(self):
        """§2.6: two principals on one UID is the collapse every ACL here assumes away."""
        body = json.dumps(_request()).encode("utf-8")
        reply = self._handle(_Conn(BROKER_UID, body), sidecar_uid=BROKER_UID)
        self.assertEqual(
            reply, {"ok": False, "error": "principal collapse: sidecar uid equals broker uid"})
        self.assertEqual(self.staging_rows(), [])

    def test_without_an_open_service_the_sidecar_is_not_admitted_at_all(self):
        body = json.dumps(_request()).encode("utf-8")
        reply = self._handle(_Conn(SIDECAR_UID, body), sidecar_uid=None)
        self.assertEqual(reply, {"ok": False, "error": "peer not authorized"})

    def test_the_open_frame_fits_the_existing_8_kib_front_door_bound(self):
        self.assertEqual(gto.MAX_OPEN_FRAME_BYTES, gss.MAX_FRAME_BYTES)


# ---------------------------------------------------------------------------
# Supervisor-side faults are faults, not refusals
# ---------------------------------------------------------------------------


class SupervisorFaultTests(_Case):
    def test_an_off_contract_refusal_reason_is_a_hard_error(self):
        with self.assertRaises(SupervisorError):
            gto.refused("not_a_real_reason")

    def test_a_missing_ledger_connection_is_a_fault_not_a_refusal(self):
        with self.assertRaises(SupervisorError):
            gto.handle_open(
                _request(), peer_uid=SIDECAR_UID, allowed_sidecar_uid=SIDECAR_UID,
                config=_open_config(), conn=None, publish_document=self.store.publish,
                resolve_registry_document=lambda: self.registry_document,
                verify_root_sig=_verify_root_sig, verify_challenge_sig=_verify_challenge_sig,
                clock_ms=lambda: NOW,
            )

    def test_a_non_int_clock_is_a_fault_not_a_refusal(self):
        with self.assertRaises(SupervisorError):
            self.open(now="not-a-clock")


if __name__ == "__main__":
    unittest.main()
