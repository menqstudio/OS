"""The rows of `docs/design/SECURITY_NEGATIVE_TEST_MATRIX.md` whose code exists TODAY.

The matrix declares 242 negative tests. Until this module landed, exactly ONE of those IDs
appeared anywhere in the tree's `.rs`/`.py`/`.ts` sources -- in a docstring saying the control
it names is not implemented. `config/negative-matrix.json` is the mirror that records, per ID,
whether anything establishes it, and `tools/check_negative_matrix.py` refuses a row that claims
`implemented` while naming a test that does not exist or does not carry its ID.

**Rules every test here obeys, taken from the plan itself.**

  * ONE fault per test (the plan's row shape (section 0.1): "the single adversarial mutation -- no compound tests").
  * The ID appears in the function NAME, so it is visible in a runner's output, and as a
    STRING in the body, so the gate can bind it.
  * The assertion is the EXACT outcome the row states -- a named reason, a durable state, a
    refusal type -- never "looks rejected" (the plan's outcome rule (section 0.4)).
  * The the plan's universal invariant (section 0.3) universal invariant is asserted on every row: nothing can render
    `trusted_verified`. At these seams that is concrete rather than decorative --
    `load_attestation_state` returns None (no terminal state ⇒ no §4.9 evidence ⇒ no envelope
    ⇒ no render), or the registry resolver hands back no usable key at all.

**A few rows here are POSITIVE controls and the plan says so** (NM-REG-09, NM-TIME-06,
NM-TIME-09). They exist because the boundaries they sit on point in opposite directions --
the validity window is inclusive, revocation is strict -- and a suite that only ever asserted
refusals would pass just as well against a component that refuses everything.

Everything runs offline: in-memory SQLite, injected clocks, an injected signature seam. No
socket, no key material, no OS trust chain.
"""

import hashlib
import pathlib
import sqlite3
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import brops_protocol as protocol  # noqa: E402
import challenge_key_registry as registry  # noqa: E402
import governed_supervisor_ledger as gsl  # noqa: E402
import isolated_signer as signer  # noqa: E402


def _sign_request():
    """A `brops.sign-request.v1` that `validate_sign_request` accepts, built FROM the field-set
    constants rather than from a hand-written literal.

    Derived on purpose: a hand-listed fixture goes stale the day a field is added, and then the
    NM-FRAME rows below would be refusing for the wrong reason — a missing key rather than the
    fault each one injects. Built this way, adding a field to the signer either keeps these
    tests honest or breaks them loudly.
    """
    evidence = {}
    for field in signer.EVIDENCE_STRING_FIELDS:
        evidence[field] = f"value-for-{field}"
    for field in signer.EVIDENCE_HANDLE_FIELDS + signer.EVIDENCE_DIGEST_FIELDS:
        evidence[field] = hashlib.sha256(field.encode("utf-8")).hexdigest()
    for field in signer.EVIDENCE_TS_FIELDS:
        evidence[field] = 1_700_000_000_000
    for field in signer.EVIDENCE_COUNT_FIELDS:
        evidence[field] = 1
    return {
        "protocol": signer.SIGN_REQUEST_PROTOCOL,
        "attestation": {
            "attestation_protocol": signer.ATTESTATION_PROTOCOL,
            "supervisor_key_id": "sup-key-1",
            "sig": "GOOD-SIG",
        },
        "evidence": evidence,
    }

H_A = "a" * 64
H_B = "b" * 64
H_C = "c" * 64

#: A syntactically valid b64url 32-byte public key. Never used to verify anything here --
#: every signature check in these tests goes through an INJECTED seam, so no key material and
#: no crypto library is involved.
PUB = "A" * 43
ROOT_ANCHOR = registry.RootAnchor(root_key_id="root-1", public_key=PUB)

ACCEPTED_AT = 1_000_000


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _key(**over):
    entry = dict(
        challenge_key_id="ck-1",
        public_key=PUB,
        valid_from_ms=ACCEPTED_AT - 100_000,
        valid_to_ms=ACCEPTED_AT + 100_000,
        key_epoch=1,
        revoked=False,
        revoked_at_ms=None,
    )
    entry.update(over)
    return entry


def _document(keys=None, **over):
    payload = dict(
        artifact_type=registry.REGISTRY_ARTIFACT_TYPE,
        root_key_id="root-1",
        registry_epoch=7,
        registry_issued_at_ms=ACCEPTED_AT - 500_000,
        keys=[_key()] if keys is None else keys,
    )
    payload.update(over)
    return {"payload": payload, "root_sig": "sig-placeholder"}


def _accept_root_sig(_message, _sig, _public_key):
    """The injected Ed25519 seam, standing in for a VALID root signature.

    Every registry test but NM-REG-05 uses this, so that each test injects exactly one fault
    and the signature is never the accidental cause of a refusal it did not mean to test.
    """
    return True


def _resolve(document, epoch_floor=0, verify=_accept_root_sig):
    return registry.resolve_registry(
        document, anchor=ROOT_ANCHOR, epoch_floor=epoch_floor, verify_root_sig=verify)


def _snapshot(keys=None):
    snapshot, reason = _resolve(_document(keys))
    assert snapshot is not None, "fixture registry must resolve, got %r" % (reason,)
    return snapshot


_OPEN = []


def _conn():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    gsl.apply_schema(conn)
    _OPEN.append(conn)
    return conn


def tearDownModule():
    while _OPEN:
        try:
            _OPEN.pop().close()
        except sqlite3.Error:
            pass


def _acceptance(attempt="att-1", **over):
    fields = dict(
        install_id="install-1",
        request_nonce="nonce-%s" % attempt,
        challenge_handle="chal-%s" % attempt,
        run_id="run-1",
        task_id="task-1",
        workspace_id="ws-1",
        execution_attempt_id=attempt,
        challenge_accepted_at_ms=ACCEPTED_AT,
        challenge_registry_handle="reg-h",
        challenge_registry_hash="reg-hash",
        challenge_registry_epoch=7,
        challenge_registry_root_key_id="root-1",
        lease_payload_bytes=b"lease-payload-bytes",
        lease_id="lease-%s" % attempt,
        lease_issued_at_ms=ACCEPTED_AT,
        lease_expires_at_ms=ACCEPTED_AT + gsl.LEASE_DURATION_MS,
        receipt_id="receipt-%s" % attempt,
        supervisor_id="supervisor-1",
        requested_at_ms=ACCEPTED_AT - 1_000,
        request_sha256=H_A,
        system_handle=H_A,
        history_handle=H_B,
        generation_config_handle=H_C,
    )
    fields.update(over)
    return gsl.NewAcceptance(**fields)


def _derived(**over):
    facts = dict(
        record_handle=H_C,
        lease_handle=H_A,
        execution_receipt_handle=H_B,
        evidence_final_event_hash=H_C,
        evidence_event_count=3,
        evidence_last_sequence=3,
        evidence_head_sequence=12,
    )
    facts.update(over)
    return facts


def _produced(**over):
    facts = dict(
        output_handle=H_A,
        containment_evidence_handle=H_B,
        completed_at_ms=ACCEPTED_AT + 50_000,
    )
    facts.update(over)
    return facts


def _lease_ready(conn, attempt="att-1", **over):
    """Drive a fresh attempt to LEASE_READY -- the state the §5 step-8a gate judges."""
    gsl.accept_prepare(conn, _acceptance(attempt, **over), 10)
    gsl.mark_lease_ready(conn, attempt, "lease-h", 20)
    return conn


def _executing(conn, attempt="att-1", **over):
    _lease_ready(conn, attempt, **over)
    gsl.gate_and_start(conn, attempt, ACCEPTED_AT)
    gsl.mark_executing(conn, attempt, process_group_id="pg", cgroup_id="cg",
                       execution_started_marker=None, now_ms=30)
    return conn


class _MatrixCase(unittest.TestCase):
    """Shared assertions for the plan's universal invariant (its section 0.3)."""

    def assert_nothing_renders_trusted_verified(self, conn, run_id="run-1", attempt="att-1"):
        """The plan's universal invariant (section 0.3): a negative row that produced a rendered "Verified" is an automatic fail.

        At the supervisor seam that is not a slogan. `load_attestation_state` is the ONLY way
        to obtain the terminal run state the §4.9 evidence is built from, it returns None for
        any attempt that is not `COMPLETED` with a completion row, and without evidence there
        is no attestation, no signed envelope and nothing a desktop could render. So None here
        IS the invariant, checked rather than asserted in prose.
        """
        self.assertIsNone(
            gsl.load_attestation_state(conn, run_id, attempt),
            "a refused row produced terminal attestation state, so the universal invariant does not hold",
        )

    def assert_no_usable_key(self, key, reason):
        """The universal invariant at the registry seam: a refused resolve/select yields NO key, so nothing
        downstream can bind a challenge signature and no lease is ever issued."""
        self.assertIsNone(key, "a refused registry lookup returned a usable key")
        self.assertIsNotNone(reason, "a refused registry lookup returned no reason")


# ---------------------------------------------------------------------------
# Plan section 3 -- Registry / manifest (NM-REG-*), challenge_key_registry.py
# ---------------------------------------------------------------------------


class NegativeMatrixRegistryTests(_MatrixCase):
    def test_nm_reg_01_registry_epoch_below_the_floor_is_refused(self):
        """NM-REG-01 -- registry rollback (epoch). An older snapshot is exactly how a revoked
        key comes back, so a `registry_epoch` below the stored floor must not resolve."""
        case = "NM-REG-01"
        snapshot, reason = _resolve(_document(registry_epoch=6), epoch_floor=7)
        self.assertIsNone(snapshot, case)
        self.assertEqual(reason, registry.REGISTRY_UNKNOWN)
        self.assert_no_usable_key(snapshot, reason)

    def test_nm_reg_04_unknown_root_key_id_is_refused(self):
        """NM-REG-04 -- a `root_key_id` outside the binary-pinned anchor set is refused BEFORE
        its signature is considered, so a forged registry cannot certify itself."""
        case = "NM-REG-04"
        snapshot, reason = _resolve(_document(root_key_id="root-attacker"))
        self.assertIsNone(snapshot, case)
        self.assertEqual(reason, registry.REGISTRY_UNKNOWN)
        self.assert_no_usable_key(snapshot, reason)

    def test_nm_reg_05_invalid_root_sig_is_refused(self):
        """NM-REG-05 -- `root_sig` not valid over JCS(payload) under the pinned root. The ONLY
        fault: the injected verifier returns False; the document is otherwise the fixture."""
        case = "NM-REG-05"
        snapshot, reason = _resolve(_document(), verify=lambda *_: False)
        self.assertIsNone(snapshot, case)
        self.assertEqual(reason, registry.REGISTRY_UNKNOWN)
        self.assert_no_usable_key(snapshot, reason)

    def test_nm_reg_07_key_revoked_before_acceptance_is_refused(self):
        """NM-REG-07 -- a bound key revoked strictly before `challenge_accepted_at_ms` is not
        usable as of that instant."""
        case = "NM-REG-07"
        snapshot = _snapshot([_key(revoked=True, revoked_at_ms=ACCEPTED_AT - 1)])
        key, reason = registry.select_key(snapshot, "ck-1", ACCEPTED_AT)
        self.assertEqual(reason, registry.KEY_INVALID, case)
        self.assert_no_usable_key(key, reason)

    def test_nm_reg_08_revocation_at_exactly_the_acceptance_instant_is_refused(self):
        """NM-REG-08 -- the revocation boundary. `revoked_at_ms == challenge_accepted_at_ms`
        is ALREADY revoked: revocation is strict (`revoked_at_ms <= t` refuses), the opposite
        direction to the inclusive validity window, and the two must not be guessed to match."""
        case = "NM-REG-08"
        snapshot = _snapshot([_key(revoked=True, revoked_at_ms=ACCEPTED_AT)])
        key, reason = registry.select_key(snapshot, "ck-1", ACCEPTED_AT)
        self.assertEqual(reason, registry.KEY_INVALID, case)
        self.assert_no_usable_key(key, reason)

    def test_nm_reg_09_revocation_after_the_run_leaves_the_past_record_valid(self):
        """NM-REG-09 -- POSITIVE control, and the plan marks it one. A key revoked AFTER the
        instant being judged was valid AS OF the run, so a later revocation must not
        retroactively invalidate a past record. Without this row a component that refused
        every key would pass NM-REG-07 and NM-REG-08."""
        case = "NM-REG-09"
        snapshot = _snapshot([_key(revoked=True, revoked_at_ms=ACCEPTED_AT + 1)])
        key, reason = registry.select_key(snapshot, "ck-1", ACCEPTED_AT)
        self.assertIsNone(reason, case)
        self.assertIsNotNone(key)
        self.assertEqual(key.challenge_key_id, "ck-1")

    def test_nm_reg_10_revoked_true_with_null_revoked_at_ms_is_malformed(self):
        """NM-REG-10 -- `revoked == true` with `revoked_at_ms == null` cannot be compared
        against any instant, so it is a strict-schema reject, never a normalisation."""
        case = "NM-REG-10"
        snapshot, reason = _resolve(_document([_key(revoked=True, revoked_at_ms=None)]))
        self.assertIsNone(snapshot, case)
        self.assertEqual(reason, registry.REGISTRY_UNKNOWN)
        self.assert_no_usable_key(snapshot, reason)

    def test_nm_reg_11_revoked_false_with_a_revoked_at_ms_is_malformed(self):
        """NM-REG-11 -- `revoked == false` carrying a non-null `revoked_at_ms` is a document
        whose two fields disagree about the same fact."""
        case = "NM-REG-11"
        snapshot, reason = _resolve(_document([_key(revoked=False,
                                                    revoked_at_ms=ACCEPTED_AT)]))
        self.assertIsNone(snapshot, case)
        self.assertEqual(reason, registry.REGISTRY_UNKNOWN)
        self.assert_no_usable_key(snapshot, reason)

    def test_nm_reg_12_revoked_at_ms_before_valid_from_ms_is_malformed(self):
        """NM-REG-12 -- a key revoked before it became valid is not a key with a short life,
        it is an inconsistent document."""
        case = "NM-REG-12"
        entry = _key(revoked=True, revoked_at_ms=ACCEPTED_AT - 100_001)
        snapshot, reason = _resolve(_document([entry]))
        self.assertIsNone(snapshot, case)
        self.assertEqual(reason, registry.REGISTRY_UNKNOWN)
        self.assert_no_usable_key(snapshot, reason)

    def test_nm_reg_14_duplicate_challenge_key_ids_are_refused(self):
        """NM-REG-14 -- two entries sharing a `challenge_key_id`. Which one a lookup returns
        would then be an ordering accident, so the document is refused whole."""
        case = "NM-REG-14"
        snapshot, reason = _resolve(_document([_key(), _key(key_epoch=2)]))
        self.assertIsNone(snapshot, case)
        self.assertEqual(reason, registry.REGISTRY_UNKNOWN)
        self.assert_no_usable_key(snapshot, reason)

    def test_nm_reg_16_acceptance_outside_the_key_validity_window_is_refused(self):
        """NM-REG-16 -- `challenge_accepted_at_ms` outside `[valid_from_ms, valid_to_ms]`."""
        case = "NM-REG-16"
        snapshot = _snapshot([_key(valid_to_ms=ACCEPTED_AT - 1)])
        key, reason = registry.select_key(snapshot, "ck-1", ACCEPTED_AT)
        self.assertEqual(reason, registry.KEY_INVALID, case)
        self.assert_no_usable_key(key, reason)

    def test_nm_reg_17_a_present_key_id_is_not_by_itself_validity(self):
        """NM-REG-17 -- presence is not validity. The `challenge_key_id` IS in the snapshot;
        the single fault is that it is not usable at the instant judged, and `select_key` must
        refuse it rather than hand back the entry it found."""
        case = "NM-REG-17"
        snapshot = _snapshot([_key(valid_from_ms=ACCEPTED_AT + 1,
                                   valid_to_ms=ACCEPTED_AT + 100_000)])
        self.assertIsNotNone(snapshot.key("ck-1"), "fixture must actually contain the id")
        key, reason = registry.select_key(snapshot, "ck-1", ACCEPTED_AT)
        self.assertEqual(reason, registry.KEY_INVALID, case)
        self.assert_no_usable_key(key, reason)


# ---------------------------------------------------------------------------
# Plan section 2 -- Time model (NM-TIME-*), the §5 step-8a launch gate
# ---------------------------------------------------------------------------


class NegativeMatrixTimeTests(_MatrixCase):
    def test_nm_time_06_acceptance_at_the_exact_window_hi_is_inclusive(self):
        """NM-TIME-06 -- POSITIVE control, and the plan says any refusal here is a bug.
        §1 fixes windows as `lo_ms <= t <= hi_ms`, so acceptance at exactly `valid_to_ms`
        is INSIDE. This is the row that stops NM-REG-16 from passing against an
        off-by-one that refuses the whole boundary."""
        case = "NM-TIME-06"
        snapshot = _snapshot([_key(valid_to_ms=ACCEPTED_AT)])
        key, reason = registry.select_key(snapshot, "ck-1", ACCEPTED_AT)
        self.assertIsNone(reason, case)
        self.assertIsNotNone(key)

    def test_nm_time_07_an_expired_lease_expires_the_row_and_launches_nothing(self):
        """NM-TIME-07 -- `now_ms > lease_expires_at_ms` at the launch gate: `LEASE_READY`
        becomes `EXPIRED` deterministically, NOT `BLOCKED`, and no launch occurs."""
        case = "NM-TIME-07"
        conn = _lease_ready(_conn())
        expires = ACCEPTED_AT + gsl.LEASE_DURATION_MS
        self.assertEqual(gsl.gate_and_start(conn, "att-1", expires + 5_000), gsl.EXPIRED, case)
        self.assertEqual(gsl._current_state(conn, "att-1"), gsl.EXPIRED)
        self.assertEqual(
            conn.execute("SELECT failure_reason FROM governed_turn_acceptance"
                         " WHERE execution_attempt_id = 'att-1'").fetchone()[0],
            "lease_expired")
        self.assert_nothing_renders_trusted_verified(conn)

    def test_nm_time_08_one_millisecond_under_the_launch_budget_expires(self):
        """NM-TIME-08 -- remaining budget `MIN_LAUNCH_REMAINING_MS - 1` (179999 ms). The lease
        has NOT expired; it simply has too little left to launch into, and the gate refuses."""
        case = "NM-TIME-08"
        conn = _lease_ready(_conn())
        expires = ACCEPTED_AT + gsl.LEASE_DURATION_MS
        now = expires - (gsl.MIN_LAUNCH_REMAINING_MS - 1)
        self.assertEqual(gsl.gate_and_start(conn, "att-1", now), gsl.EXPIRED, case)
        self.assertEqual(
            conn.execute("SELECT failure_reason FROM governed_turn_acceptance"
                         " WHERE execution_attempt_id = 'att-1'").fetchone()[0],
            "insufficient_remaining_budget")
        self.assert_nothing_renders_trusted_verified(conn)

    def test_nm_time_09_exactly_the_launch_budget_proceeds(self):
        """NM-TIME-09 -- POSITIVE control at the same boundary: remaining EXACTLY
        `MIN_LAUNCH_REMAINING_MS` (180000 ms) proceeds to `EXECUTION_STARTING`. Without it,
        NM-TIME-08/10/11 would all pass against a gate that expired every turn."""
        case = "NM-TIME-09"
        conn = _lease_ready(_conn())
        expires = ACCEPTED_AT + gsl.LEASE_DURATION_MS
        now = expires - gsl.MIN_LAUNCH_REMAINING_MS
        self.assertEqual(gsl.gate_and_start(conn, "att-1", now),
                         gsl.EXECUTION_STARTING, case)
        self.assertEqual(gsl._current_state(conn, "att-1"), gsl.EXECUTION_STARTING)

    def test_nm_time_10_now_equal_to_lease_expiry_fails_the_budget_limb(self):
        """NM-TIME-10 -- `now_ms == lease_expires_at_ms` passes limb (i) (not yet past expiry)
        and must fail limb (ii): zero remaining budget is below the launch minimum."""
        case = "NM-TIME-10"
        conn = _lease_ready(_conn())
        expires = ACCEPTED_AT + gsl.LEASE_DURATION_MS
        self.assertEqual(gsl.gate_and_start(conn, "att-1", expires), gsl.EXPIRED, case)
        self.assertEqual(
            conn.execute("SELECT failure_reason FROM governed_turn_acceptance"
                         " WHERE execution_attempt_id = 'att-1'").fetchone()[0],
            "insufficient_remaining_budget")
        self.assert_nothing_renders_trusted_verified(conn)

    def test_nm_time_11_one_millisecond_past_lease_expiry_expires(self):
        """NM-TIME-11 -- `now_ms == lease_expires_at_ms + 1`: the first instant at which limb
        (i) itself fails, so the reason is `lease_expired` and not the budget limb."""
        case = "NM-TIME-11"
        conn = _lease_ready(_conn())
        expires = ACCEPTED_AT + gsl.LEASE_DURATION_MS
        self.assertEqual(gsl.gate_and_start(conn, "att-1", expires + 1), gsl.EXPIRED, case)
        self.assertEqual(
            conn.execute("SELECT failure_reason FROM governed_turn_acceptance"
                         " WHERE execution_attempt_id = 'att-1'").fetchone()[0],
            "lease_expired")
        self.assert_nothing_renders_trusted_verified(conn)


# ---------------------------------------------------------------------------
# Plan sections 1 and 8 -- Replay and acceptance CAS (NM-REPLAY-*, NM-CONC-*)
# ---------------------------------------------------------------------------


    def test_nm_time_16_now_equal_to_lease_issued_at_ms_is_inside_the_window(self):
        """NM-TIME-16 -- the LOWER equality of the §5 step-8a gate.

        §1 fixes every window as `lo <= t <= hi`, so an instant exactly equal to
        `lease_issued_at_ms` is INSIDE the lease and must not read as
        `lease_not_yet_valid`. The gate's refusal is `now_ms < lease_issued_at_ms`,
        strict on purpose; one character makes the boundary exclusive and a lease
        unusable at the instant it becomes valid.

        Both sides are asserted, because a test that only pins the refusal passes
        just as well when the gate refuses everything.
        """
        case = "NM-TIME-16"
        issued, expires = 1_000_000, 1_000_000 + gsl.MIN_LAUNCH_REMAINING_MS
        # one millisecond BEFORE issuance: refused, and by that exact name
        self.assertEqual(
            gsl.lease_launch_gate(issued - 1, issued, expires), "lease_not_yet_valid", case)
        # exactly AT issuance: inside the window, so the lower limb must not fire
        self.assertIsNone(gsl.lease_launch_gate(issued, issued, expires), case)

class NegativeMatrixReplayTests(_MatrixCase):
    def test_nm_replay_05_same_nonce_bound_to_a_different_challenge_is_refused(self):
        """NM-REPLAY-05 -- a new signed challenge reusing an ALREADY-ACCEPTED nonce. The
        `UNIQUE(install_id, request_nonce)` CAS collides and the row is compared field by
        field; a divergent binding is a Conflict and creates no second attempt."""
        case = "NM-REPLAY-05"
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)
        clash = _acceptance("att-2", request_nonce="nonce-att-1")
        with self.assertRaises(gsl.Conflict, msg=case):
            gsl.accept_prepare(conn, clash, 11)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM governed_turn_acceptance").fetchone()[0], 1)
        self.assert_nothing_renders_trusted_verified(conn, attempt="att-2")

    def test_nm_replay_06_same_challenge_handle_under_a_new_nonce_is_refused(self):
        """NM-REPLAY-06 -- the mirror image: an identical `challenge_handle` resubmitted with
        a DIFFERENT nonce. The nonce lookup finds nothing, so the collision was on the
        challenge handle, and that is `challenge_or_attempt_reused`."""
        case = "NM-REPLAY-06"
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)
        clash = _acceptance("att-2", challenge_handle="chal-att-1")
        with self.assertRaises(gsl.Conflict, msg=case):
            gsl.accept_prepare(conn, clash, 11)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM governed_turn_acceptance").fetchone()[0], 1)
        self.assert_nothing_renders_trusted_verified(conn, attempt="att-2")

    def test_nm_replay_08_two_submissions_cannot_reserve_one_execution_attempt_id(self):
        """NM-REPLAY-08 -- `UNIQUE(execution_attempt_id)`: two different turns racing for one
        attempt id yield exactly ONE attempt. The loser gets a refusal, never a second row."""
        case = "NM-REPLAY-08"
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)
        clash = _acceptance("att-1", request_nonce="nonce-other",
                            challenge_handle="chal-other", receipt_id="receipt-other")
        with self.assertRaises(gsl.Conflict, msg=case):
            gsl.accept_prepare(conn, clash, 11)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM governed_turn_acceptance").fetchone()[0], 1)

    def test_nm_conc_02_a_lost_acceptance_cas_is_an_acceptance_conflict(self):
        """NM-CONC-02 -- the `absent -> ACCEPTED_PREPARED` CAS losing to a conflicting existing
        binding.

        The ONE fault is the LEASE PAYLOAD: every identity field is byte-identical to the
        stored row, so the collision is decided by the digest comparison and by nothing else.
        That isolation is deliberate and was found by mutation -- an earlier version of this
        test also varied the attempt id, the challenge handle and the receipt id, so the
        field-by-field `_BOUND_FIELDS` loop refused it first and the digest comparison could
        be deleted with this test still passing. It bound NM-REPLAY-05's control, not its own.
        """
        case = "NM-CONC-02"
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)
        loser = _acceptance("att-1", lease_payload_bytes=b"a-different-lease-payload")
        with self.assertRaises(gsl.Conflict, msg=case) as caught:
            gsl.accept_prepare(conn, loser, 11)
        self.assertIn("nonce_rebound_to_different_turn", str(caught.exception))
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM governed_turn_acceptance").fetchone()[0], 1)
        self.assert_nothing_renders_trusted_verified(conn)

    def test_nm_conc_01_an_identical_resubmission_is_idempotent_not_a_second_attempt(self):
        """NM-CONC-01 -- N simultaneous IDENTICAL submits. Exactly one `ACCEPTED_PREPARED` and
        one attempt; the losers get the idempotent result, never a second execution. Driven
        serially here because the CAS is what decides it -- concurrency only changes who
        arrives first, and the property under test is that arriving second wins nothing."""
        case = "NM-CONC-01"
        conn = _conn()
        acceptance = _acceptance()
        self.assertEqual(gsl.accept_prepare(conn, acceptance, 10), gsl.CREATED, case)
        for tick in (11, 12, 13):
            self.assertEqual(gsl.accept_prepare(conn, acceptance, tick), gsl.IDEMPOTENT)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM governed_turn_acceptance").fetchone()[0], 1)


# ---------------------------------------------------------------------------
# Plan section 10 -- Evidence fork / rollback floor (NM-EVID-*)
# ---------------------------------------------------------------------------


class NegativeMatrixEvidenceFloorTests(_MatrixCase):
    def _complete(self, conn, attempt="att-1", **derived):
        return gsl.record_completion(conn, attempt, _produced(), 40,
                                     derived=_derived(**derived))

    def test_nm_evid_10_the_first_head_on_an_install_bootstraps_the_floor(self):
        """NM-EVID-10 -- bootstrap. With no floor row the validated head is INSERTed and the
        A-branch is not taken. The positive control the other four rows are measured against:
        a floor that refused everything would pass NM-EVID-01/03/04 and be useless."""
        case = "NM-EVID-10"
        conn = _executing(_conn())
        self.assertEqual(self._complete(conn), gsl.CREATED, case)
        row = conn.execute("SELECT highest_head_sequence FROM governed_evidence_head_floor"
                           " WHERE install_id = 'install-1'").fetchone()
        self.assertEqual(row["highest_head_sequence"], 12)
        self.assertIsNotNone(gsl.load_attestation_state(conn, "run-1", "att-1"))

    def test_nm_evid_01_a_head_below_the_durable_floor_is_stale_evidence(self):
        """NM-EVID-01 -- case A. A head below the install-wide floor is a rolled-back or
        truncated chain and refuses the WHOLE completion, so no attestation can ever be built
        over it. The floor is scoped to the INSTALL, not to `(install_id, task_id)`: task_id
        arrives on the wire, and a defence whose scope the attacker chooses is not a defence,
        so the second attempt here uses a fresh task_id deliberately."""
        case = "NM-EVID-01"
        conn = _executing(_conn())
        self._complete(conn)
        _executing(conn, "att-2", run_id="run-2", task_id="task-FRESH")
        with self.assertRaises(gsl.StaleEvidence, msg=case):
            self._complete(conn, "att-2", evidence_head_sequence=3)
        self.assert_nothing_renders_trusted_verified(conn, run_id="run-2", attempt="att-2")

    def test_nm_evid_02_an_equal_head_with_equal_content_is_idempotent(self):
        """NM-EVID-02 -- case B, idempotent limb: an equal `head_sequence` carrying an equal
        content triple must be accepted as a re-sign and must NOT read as a fork.

        Presented from a SECOND attempt on the same `(install_id, task_id)`, because that is
        the only way the floor's idempotent limb is reachable at all. Mutation testing found
        why: `record_completion` calls `_evidence_floor_cas` only `if inserted`, so re-running
        an IDENTICAL completion for the SAME attempt short-circuits on the completion table's
        own primary key and never touches the floor. A version of this test written that way
        passed with the floor's `if identical: return "idempotent"` deleted -- it was
        measuring the completion PK, not case B.
        """
        case = "NM-EVID-02"
        conn = _executing(_conn())
        self.assertEqual(self._complete(conn), gsl.CREATED, case)
        _executing(conn, "att-2", run_id="run-2")
        self.assertEqual(self._complete(conn, "att-2"), gsl.CREATED)
        floor = conn.execute("SELECT * FROM governed_evidence_head_floor").fetchall()
        self.assertEqual(len(floor), 1, "the idempotent limb must not advance or add a row")
        self.assertEqual(floor[0]["highest_head_sequence"], 12)
        self.assertEqual(floor[0]["final_event_hash"], H_C)

    def test_nm_evid_03_an_equal_head_with_divergent_content_is_an_evidence_fork(self):
        """NM-EVID-03 -- case B, fork limb. ONE counter mints `head_sequence`, so the same
        head carrying different content is two chains claiming one position."""
        case = "NM-EVID-03"
        conn = _executing(_conn())
        self._complete(conn)
        _executing(conn, "att-2", run_id="run-2")
        with self.assertRaises(gsl.EvidenceFork, msg=case):
            self._complete(conn, "att-2", evidence_event_count=4, evidence_last_sequence=4)
        self.assert_nothing_renders_trusted_verified(conn, run_id="run-2", attempt="att-2")

    def test_nm_evid_04_same_event_count_with_a_different_final_hash_is_a_fork(self):
        """NM-EVID-04 -- the sharpest limb of case B: counts IDENTICAL, only
        `final_event_hash` differs. A floor comparing lengths alone would accept this, and it
        is precisely a rewritten chain of the same length."""
        case = "NM-EVID-04"
        conn = _executing(_conn())
        self._complete(conn)
        _executing(conn, "att-2", run_id="run-2")
        with self.assertRaises(gsl.EvidenceFork, msg=case):
            self._complete(conn, "att-2", evidence_final_event_hash="d" * 64)
        self.assert_nothing_renders_trusted_verified(conn, run_id="run-2", attempt="att-2")

    def test_nm_evid_11_a_corrupt_stored_floor_row_fails_closed(self):
        """NM-EVID-11 -- startup integrity. A floor row that cannot be a floor (`event_count`
        and `last_sequence` disagreeing) is refused rather than believed. Written directly to
        the table because the fault under test is a CORRUPTED stored row -- no legitimate code
        path produces one, which is the whole reason the guard has to exist."""
        case = "NM-EVID-11"
        conn = _executing(_conn())
        self._complete(conn)
        conn.execute("UPDATE governed_evidence_head_floor SET last_sequence = 99"
                     " WHERE install_id = 'install-1'")
        _executing(conn, "att-2", run_id="run-2")
        with self.assertRaises(gsl.Corrupt, msg=case):
            self._complete(conn, "att-2", evidence_head_sequence=13)
        self.assert_nothing_renders_trusted_verified(conn, run_id="run-2", attempt="att-2")


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Plan section 7.1 / 6.1(14) -- concurrency (NM-CONC-*)
# ---------------------------------------------------------------------------


class NegativeMatrixConcurrencyTests(_MatrixCase):
    def test_nm_conc_05_a_ledger_operation_inside_a_caller_s_transaction_is_refused(self):
        """NM-CONC-05 -- nested-transaction rejection.

        Every ledger write owns its `BEGIN IMMEDIATE`, so the write lock is held
        across the read-then-write of a CAS. A caller that has already opened a
        transaction would have that CAS execute inside a lock it does not own and
        cannot reason about -- the interleaving the lock exists to prevent. `_Tx`
        refuses rather than joining the caller's transaction.

        The refusal is asserted, and so is the state afterwards: nothing was
        written, and no attempt reaches terminal attestation.
        """
        case = "NM-CONC-05"
        conn = _conn()
        conn.execute("BEGIN IMMEDIATE")          # the caller opens its own
        try:
            with self.assertRaises(gsl.LedgerError, msg=case) as caught:
                gsl.accept_prepare(conn, _acceptance(), 10)
            self.assertIn("own its BEGIN IMMEDIATE", str(caught.exception), case)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM governed_turn_acceptance").fetchone()[0],
                0, "%s -- a refused nested operation must write nothing" % case)
        finally:
            conn.execute("ROLLBACK")
        self.assert_nothing_renders_trusted_verified(conn)

    def test_nm_conc_06_a_divergent_duplicate_terminal_write_is_refused(self):
        """NM-CONC-06 -- the terminal write happens EXACTLY ONCE.

        §6(4): the completion row's PRIMARY KEY is the write-once gate. A retry
        carrying byte-identical facts is IDEMPOTENT and buys nothing; a retry whose
        facts DIVERGE is `Conflict("completion_facts_differ")`. Both limbs are
        asserted here, and the row count after each, because a gate that refused
        every second write would satisfy the divergent limb alone while breaking
        the legitimate retry the protocol depends on.
        """
        case = "NM-CONC-06"
        conn = _executing(_conn())
        self.assertEqual(
            gsl.record_completion(conn, "att-1", _produced(), 40, derived=_derived()),
            gsl.CREATED, case)
        # identical retry: idempotent, still one row
        self.assertEqual(
            gsl.record_completion(conn, "att-1", _produced(), 41, derived=_derived()),
            gsl.IDEMPOTENT, case)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM governed_turn_completion").fetchone()[0],
            1, "%s -- an idempotent retry must not add a row" % case)
        # divergent retry: refused by name, and still one row
        divergent = _produced(completed_at_ms=ACCEPTED_AT + 60_000)
        with self.assertRaises(gsl.Conflict, msg=case) as caught:
            gsl.record_completion(conn, "att-1", divergent, 42, derived=_derived())
        self.assertIn("completion_facts_differ", str(caught.exception), case)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM governed_turn_completion").fetchone()[0],
            1, "%s -- a divergent retry must not add a row" % case)

    def test_nm_conc_05_the_same_operation_succeeds_when_it_owns_the_transaction(self):
        """NM-CONC-05, the positive control. Without it the test above passes just
        as well against a ledger that refuses everything."""
        case = "NM-CONC-05"
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM governed_turn_acceptance").fetchone()[0], 1, case)

# ---------------------------------------------------------------------------
# Plan section 5 -- Malformed / oversized frames (NM-FRAME-*), brops_protocol.py
# and isolated_signer.py's strict decode
# ---------------------------------------------------------------------------


class NegativeMatrixFrameTests(_MatrixCase):
    """T-062. Seven of the twenty `NM-FRAME-*` rows, established against the tree.

    Reviewing them found a live defect and it is fixed in the same change: `strict_loads`'s
    own docstring said "strict JSON" and §1.9/§4 say *no NaN/Inf*, but Python's `json.loads`
    accepts `NaN`, `Infinity` and `-Infinity` by default and nothing overrode that.
    `strict_loads(b'{"a": NaN}')` returned `{'a': nan}` — measured on 2026-09-01, before
    `_reject_json_constant` existed. That is what an `unreviewed` row is worth looking at for.

    The other thirteen rows stay `unreviewed`, which is their honest state: nobody has
    established them. Two are worth naming because they were looked at and NOT closed.
    **NM-FRAME-14** (86-char b64url signature) does refuse today, but as
    `attestation_invalid` rather than the matrix's `malformed`: `_validate_attestation`
    accepts any capped string as `sig` and defers the shape to the injected
    `verify_attestation`. Enforcing the shape at the decoder changes an audited perimeter's
    contract and re-fixtures the whole signer suite, which is an Architect-facing change and
    not part of a sweep. **NM-FRAME-15** describes a base `brops.sign-request.v1` presented
    "on the governed path", and the tree has one tag, not two — the row's premise needs
    settling against the design before a test can mean anything.
    """

    # -- 01 / 03: the exact-key-set rule, both directions --------------------

    def test_nm_frame_01_an_unknown_field_is_refused_rather_than_ignored(self):
        """NM-FRAME-01 -- an extra key is `malformed`, never dropped. Dropping it silently is
        how a smuggled field becomes a field the next reader trusts.

        Proven by removing the `keys - allowed` half of `_validate_evidence`'s exact-key rule.
        """
        case = "NM-FRAME-01"
        request = _sign_request()
        request["extra"] = "smuggled"
        with self.assertRaises(signer._Refuse) as caught:
            signer.validate_sign_request(request)
        self.assertEqual(caught.exception.reason, signer.REASON_MALFORMED, case)
        # ... and inside the evidence body, where §4.9 says inline artifact bytes never enter.
        nested = _sign_request()
        nested["evidence"]["output_bytes"] = "aGk="
        with self.assertRaises(signer._Refuse) as caught:
            signer.validate_sign_request(nested)
        self.assertEqual(caught.exception.reason, signer.REASON_MALFORMED, case)
        # The positive control: the same request WITHOUT the extra key parses.
        self.assertIsNotNone(signer.validate_sign_request(_sign_request()), case)

    def test_nm_frame_03_a_missing_required_key_is_refused(self):
        """NM-FRAME-03 -- the key set is exact in BOTH directions. A decoder that only refuses
        extras accepts a frame with a required field missing and reads it as absent.

        Proven by removing the `allowed - set(request.keys())` half in `validate_sign_request`.
        """
        case = "NM-FRAME-03"
        for drop_from, key in (("top", "evidence"),
                               ("attestation", "sig"),
                               ("evidence", signer.EVIDENCE_HANDLE_FIELDS[0])):
            request = _sign_request()
            target = request if drop_from == "top" else request[drop_from]
            del target[key]
            with self.assertRaises(signer._Refuse) as caught:
                signer.validate_sign_request(request)
            self.assertEqual(caught.exception.reason, signer.REASON_MALFORMED,
                             f"{case}: dropping {key} was not refused")

    # -- 02 / 04: what the strict decoder must refuse before anything sees it -

    def test_nm_frame_02_a_duplicate_json_key_is_refused(self):
        """NM-FRAME-02 -- last-one-wins is the default in every JSON parser, and it means the
        bytes that were signed and the object that was read can disagree.

        Proven by replacing `_reject_duplicate_keys`'s raise with `pass`.
        """
        case = "NM-FRAME-02"
        with self.assertRaises(protocol.ProtocolError) as caught:
            protocol.strict_loads(b'{"protocol":"a","protocol":"b"}')
        self.assertIn("duplicate key", str(caught.exception), case)
        self.assertEqual(protocol.strict_loads(b'{"protocol":"a"}'), {"protocol": "a"}, case)

    def test_nm_frame_04_wrong_types_and_the_non_json_constants_are_refused(self):
        """NM-FRAME-04 -- `_ms` as a string, and NaN / Infinity / -Infinity.

        The constants are the half that was NOT true until this row was reviewed. A NaN in a
        declared number field compares FALSE against itself, so an equality check written to
        be fail-closed becomes fail-open; and re-encoding it emits the token `NaN`, which no
        other JSON parser will read back, so a digest over the round trip is a digest of
        nothing shared.

        Proven by removing `parse_constant=_reject_json_constant` from `strict_loads` — the arm
        this row's review ADDED.
        """
        case = "NM-FRAME-04"
        for token in (b'{"a": NaN}', b'{"a": Infinity}', b'{"a": -Infinity}'):
            with self.assertRaises(protocol.ProtocolError) as caught:
                protocol.strict_loads(token)
            self.assertIn("non-JSON constant", str(caught.exception), f"{case}: {token!r}")
        self.assertEqual(protocol.strict_loads(b'{"a": 1}'), {"a": 1},
                         f"{case}: an ordinary number must still decode")

        # A timestamp sent as a string is the same class of fault one layer up.
        request = _sign_request()
        field = signer.EVIDENCE_TS_FIELDS[0]
        request["evidence"][field] = str(request["evidence"][field])
        with self.assertRaises(signer._Refuse) as caught:
            signer.validate_sign_request(request)
        self.assertEqual(caught.exception.reason, signer.REASON_MALFORMED, case)

    # -- 07: the cap, at the number the design names -------------------------

    def test_nm_frame_07_an_oversize_sign_request_is_refused_at_the_cap(self):
        """NM-FRAME-07 -- 256 KiB, asserted on BOTH sides of the number so the bound is the
        bound and not merely "large is refused".

        Proven by disabling the `len(raw) > MAX_FRAME_BYTES` arm.
        """
        case = "NM-FRAME-07"
        self.assertEqual(protocol.MAX_FRAME_BYTES, 256 * 1024, case)
        self.assertEqual(signer.MAX_REQUEST_BYTES, 256 * 1024, case)
        # `{"a":"<pad>"}` — eight bytes of syntax around the padding.
        at_cap = b'{"a":"' + b"x" * (protocol.MAX_FRAME_BYTES - 8) + b'"}'
        self.assertEqual(len(at_cap), protocol.MAX_FRAME_BYTES, "the fixture must sit ON the cap")
        self.assertEqual(len(protocol.strict_loads(at_cap)["a"]), protocol.MAX_FRAME_BYTES - 8,
                         f"{case}: a frame AT the cap must be accepted")
        with self.assertRaises(protocol.ProtocolError) as caught:
            protocol.strict_loads(at_cap[:-1] + b'x"}')
        self.assertIn("over the", str(caught.exception), case)

    # -- 13: handles are lowercase 64-hex, and nothing else ------------------

    def test_nm_frame_13_a_handle_that_is_not_lowercase_64_hex_is_refused(self):
        """NM-FRAME-13 -- `^[0-9a-f]{64}$`. Uppercase is the arm that a case-insensitive
        comparison would let through, and it addresses a different store entry.

        Proven by widening `_is_sha256_hex` to accept uppercase.
        """
        case = "NM-FRAME-13"
        field = signer.EVIDENCE_HANDLE_FIELDS[0]
        good = _sign_request()["evidence"][field]
        self.assertTrue(signer._is_sha256_hex(good), f"{case}: the fixture must be a real handle")
        for bad in (good.upper(), good[:-1], good + "0", good[:-1] + "g", "", 64 * 1, None):
            request = _sign_request()
            request["evidence"][field] = bad
            with self.assertRaises(signer._Refuse) as caught:
                signer.validate_sign_request(request)
            self.assertEqual(caught.exception.reason, signer.REASON_MALFORMED,
                             f"{case}: {bad!r} was not refused")

    # -- 18: nothing large travels inline; the signer reads by handle --------

    def test_nm_frame_18_an_inline_payload_cannot_be_sent_instead_of_a_handle(self):
        """NM-FRAME-18 -- the handle model is the size bound. `_validate_evidence` admits no
        inline artifact bytes AND no caller-supplied `*_sha256` for a handle it derives, so a
        large artifact has no field to travel in and a small lie has no field to travel in
        either.

        Proven by removing the `keys - allowed` half in `_validate_evidence`.
        """
        case = "NM-FRAME-18"
        for handle_field, derived in signer.HANDLE_TO_DERIVED_HASH.items():
            request = _sign_request()
            self.assertIn(handle_field, request["evidence"],
                          f"{case}: the fixture must carry {handle_field}")
            request["evidence"][derived] = "0" * 64
            with self.assertRaises(signer._Refuse) as caught:
                signer.validate_sign_request(request)
            self.assertEqual(caught.exception.reason, signer.REASON_MALFORMED,
                             f"{case}: a caller-supplied {derived} was accepted")
